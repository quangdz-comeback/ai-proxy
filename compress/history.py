"""Compress old chat history into a compact focal-point summary.

Summarises old conversation turns while preserving state-bearing messages
and the most recent turns verbatim.  Fails open — on any LLM error the
original message list is returned unchanged.
"""

import logging
import re

from compress.llm import compress_with_llm

logger = logging.getLogger(__name__)

# LLM prompt for history summarization
HISTORY_PROMPT = (
    "Summarize this conversation into focal points. Format:\n"
    "[FILES] list created/modified files with paths\n"
    "[GIT] branch, commits, merge state\n"
    "[LOGIC] core logic changes made (1-2 sentences each)\n"
    "[CHANGELOG] what was added/removed/changed\n"
    "[STATE] what's completed vs pending\n"
    "Max 300 chars. Technical terms exact."
)

# Patterns that indicate state-bearing content
_STATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bcompleted\b", re.IGNORECASE),
    re.compile(r"\bdone\b", re.IGNORECASE),
    re.compile(r"\bfinished\b", re.IGNORECASE),
    re.compile(r"\bremaining\b", re.IGNORECASE),
    re.compile(r"\bTODO\b"),
    re.compile(r"\bpending\b", re.IGNORECASE),
    re.compile(r"\bstill need\b", re.IGNORECASE),
    re.compile(r"\bnext step\b", re.IGNORECASE),
    re.compile(r"\bblocking\b", re.IGNORECASE),
]

# Code fence pattern (triple backtick)
_CODE_FENCE_RE = re.compile(r"^```")

# Maximum characters to feed into the summarization LLM
_MAX_SUMMARY_INPUT = 3000


def compress_history(
    messages: list,
    keep_last_n: int = 4,
    api_key: str = "",
) -> list:
    """Compress old conversation turns into a focal-point summary.

    Args:
        messages: Full list of chat messages (dicts with ``role`` and
            ``content`` keys).
        keep_last_n: Number of recent messages to preserve verbatim.
        api_key: API key (unused here but kept for interface consistency).

    Returns:
        A new message list with old turns summarised and recent turns
        preserved verbatim.  State-bearing messages are kept verbatim
        at the front.
    """
    # Nothing to compress if conversation is short
    if len(messages) <= keep_last_n + 1:
        return messages

    old_messages = messages[:-keep_last_n]
    recent_messages = messages[-keep_last_n:]

    # Extract state-bearing messages (preserve verbatim)
    state_messages, remaining_old = _extract_state_messages(old_messages)

    # Build a text block from remaining old messages for summarization
    summary_input = _build_summary_input(remaining_old)

    if not summary_input.strip():
        # Nothing useful to summarise — just keep everything
        return state_messages + recent_messages

    # Try LLM summarization — fail open
    summary = None
    try:
        summary = compress_with_llm(
            HISTORY_PROMPT,
            summary_input,
            max_tokens=300,
        )
    except Exception:
        logger.warning("LLM history summarization failed; keeping old messages as-is", exc_info=True)
        return messages  # fail open — return original list

    # Build result
    result: list = []

    # 1. State messages (verbatim, so they aren't lost)
    result.extend(state_messages)

    # 2. History summary
    if summary:
        summary_text = summary.strip()
        result.append({
            "role": "system",
            "content": f"[BUDGET_HISTORY] {summary_text}",
        })

    # 3. Recent turns (verbatim)
    result.extend(recent_messages)

    return result


def _extract_state_messages(messages: list) -> tuple[list, list]:
    """Separate state-bearing messages from the rest.

    A message is considered state-bearing if its text content contains
    any of the known state-indicator patterns.

    Args:
        messages: List of message dicts.

    Returns:
        ``(state_messages, remaining_messages)`` — both lists of message
        dicts.
    """
    state_messages: list = []
    remaining: list = []

    for msg in messages:
        text = _message_text(msg)
        if _contains_state_pattern(text):
            state_messages.append(msg)
        else:
            remaining.append(msg)

    return state_messages, remaining


def _contains_state_pattern(text: str) -> bool:
    """Return True if *text* contains any state-indicator pattern."""
    for pat in _STATE_PATTERNS:
        if pat.search(text):
            return True
    return False


def _build_summary_input(messages: list) -> str:
    """Concatenate message text content for summarization.

    - Code blocks longer than 10 lines are replaced with a short note.
    - Total output is capped at ``_MAX_SUMMARY_INPUT`` characters.

    Args:
        messages: List of message dicts.

    Returns:
        Concatenated text ready for the summarization LLM.
    """
    parts: list[str] = []
    total_len = 0

    for msg in messages:
        text = _message_text(msg)
        if not text:
            continue

        processed = _shorten_code_blocks(text)
        chunk = f"[{msg.get('role', '?')}]: {processed}\n"

        if total_len + len(chunk) > _MAX_SUMMARY_INPUT:
            # Truncate to fit
            remaining = _MAX_SUMMARY_INPUT - total_len
            if remaining > 0:
                parts.append(chunk[:remaining])
            break

        parts.append(chunk)
        total_len += len(chunk)

    return "".join(parts)


def _shorten_code_blocks(text: str) -> str:
    """Replace code blocks longer than 10 lines with a brief note."""
    lines = text.splitlines()
    result: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    fence_lang = ""

    for line in lines:
        if _CODE_FENCE_RE.match(line.strip()) and not in_fence:
            # Opening fence
            in_fence = True
            fence_lang = line.strip().lstrip("`").strip()
            fence_lines = []
            continue

        if _CODE_FENCE_RE.match(line.strip()) and in_fence:
            # Closing fence
            in_fence = False
            if len(fence_lines) > 10:
                lang_label = fence_lang or "code"
                result.append(f"[code block: {lang_label} ({len(fence_lines)} lines)]")
            else:
                result.extend(["```" + fence_lang] + fence_lines + ["```"])
            fence_lines = []
            continue

        if in_fence:
            fence_lines.append(line)
        else:
            result.append(line)

    # Unclosed fence — treat remaining as code block
    if in_fence and fence_lines:
        if len(fence_lines) > 10:
            lang_label = fence_lang or "code"
            result.append(f"[code block: {lang_label} ({len(fence_lines)} lines)]")
        else:
            result.extend(["```" + fence_lang] + fence_lines + ["```"])

    return "\n".join(result)


def _message_text(msg: dict) -> str:
    """Extract plain text from a message dict.

    Handles both string content and the list-of-parts format used by
    the OpenAI API.
    """
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content) if content else ""


__all__ = ["compress_history"]
