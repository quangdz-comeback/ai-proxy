"""Summarize noisy debug info lines using LLM.

Classifies each line of assistant/debug text as KEEP or NOISE, then uses
mimo-v2-flash to produce a one-liner summary of the noise.  Fails open —
on any LLM error the original text is returned unchanged.
"""

import logging
import re

from compress.llm import compress_with_llm

logger = logging.getLogger(__name__)

# LLM prompt for summarizing collected noise lines
NOISE_SUMMARY_PROMPT = (
    "Summarize these debug/info lines into 1-2 concise lines. "
    "Keep: error types, warning types, counts. "
    "Drop: verbose details, progress, download bars. "
    'Example output: "3 debug lines: 2x deprecation warnings (old_api), '
    '1x info (server started)".'
)

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Patterns that mark a line as KEEP (errors, warnings, version info, etc.)
_KEEP_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(error|ERROR|Error)\b"),
    re.compile(r"\b(warning|WARNING|Warning|WARN)\b"),
    re.compile(r"\b(version|VERSION)\b", re.IGNORECASE),
    re.compile(r"\bdeprecat", re.IGNORECASE),
    re.compile(r"\b(notice|NOTICE)\b"),
    # ISO-ish timestamp prefix — often useful context
    re.compile(r"^\d{4}-\d{2}-\d{2}[T ]"),
    re.compile(r"^\[\d{4}"),
]

# Patterns that mark a line as NOISE
_NOISE_PATTERNS: list[re.Pattern] = [
    # Explicit level markers
    re.compile(r"\b(DEBUG|TRACE|VERBOSE)\b"),
    # Progress bars / download indicators
    re.compile(r"\[[= ]{4,}\]"),            # [===  ]
    re.compile(r"\bDownloading\b", re.IGNORECASE),
    re.compile(r"[█▓▒░]{3,}"),              # block-char progress bars
    # ANSI escape sequences
    re.compile(r"\x1b\["),
    # Repeated INFO-style log lines
    re.compile(r"^INFO:\s", re.IGNORECASE),
]

# Stack frame detection: "  File "...", line N, in func" or "    at func (file:line:col)"
_STACK_FRAME_RE = re.compile(
    r'^\s+(?:File ".*", line \d+|at \S+ \([^)]*:\d+:\d+\))',
)

# Code fence pattern
_CODE_FENCE_RE = re.compile(r"^```")


def compress_debug_noise(text: str) -> str:
    """Identify and summarize noisy debug lines in *text*.

    Algorithm:
    1. Classify each line as KEEP or NOISE.
    2. If fewer than 3 noise lines, return *text* unchanged.
    3. Call LLM to summarize noise lines into 1-2 concise lines.
    4. Return KEEP lines + ``[BUDGET_NOISE_SUMMARY] {summary}``.

    On any LLM failure the original *text* is returned unchanged (fail open).

    Args:
        text: The raw debug / assistant text to compress.

    Returns:
        Possibly compressed text.
    """
    lines = text.splitlines()
    if not lines:
        return text

    keep_lines: list[str] = []
    noise_lines: list[str] = []
    in_code_fence = False
    stack_frame_count = 0

    for line in lines:
        # Track code fences
        if _CODE_FENCE_RE.match(line.strip()):
            in_code_fence = not in_code_fence
            keep_lines.append(line)
            continue

        # Everything inside a code fence is KEEP
        if in_code_fence:
            keep_lines.append(line)
            continue

        classification = _classify_debug_line(line, stack_frame_count)

        if classification == "NOISE":
            # Track stack frames for depth-based cutoff
            if _STACK_FRAME_RE.match(line):
                stack_frame_count += 1
            noise_lines.append(line)
        else:
            keep_lines.append(line)

    # Not enough noise to bother summarizing
    if len(noise_lines) < 3:
        return text

    # Try LLM summarization — fail open on any error
    try:
        summary = compress_with_llm(
            NOISE_SUMMARY_PROMPT,
            "\n".join(noise_lines),
            max_tokens=150,
        )
    except Exception:
        logger.warning("LLM noise summarization failed; returning original text", exc_info=True)
        return text

    # Reassemble
    result_parts = keep_lines + [f"[BUDGET_NOISE_SUMMARY] {summary.strip()}"]
    return "\n".join(result_parts)


def _classify_debug_line(line: str, stack_frame_count: int) -> str:
    """Classify a single line as ``KEEP`` or ``NOISE``.

    Conservative: when in doubt, KEEP.

    Args:
        line: The text line to classify.
        stack_frame_count: How many stack frames have already been seen
            (for depth-based noise detection).

    Returns:
        ``"KEEP"`` or ``"NOISE"``.
    """
    stripped = line.strip()
    if not stripped:
        return "KEEP"  # blank lines are neutral — keep

    # Check NOISE patterns first (they are more specific)
    for pat in _NOISE_PATTERNS:
        if pat.search(line):
            return "NOISE"

    # Stack frame depth: frames beyond the 5th are noise
    if _STACK_FRAME_RE.match(line):
        if stack_frame_count >= 5:
            return "NOISE"
        # First 5 frames — could be useful context
        return "KEEP"

    # Check KEEP patterns
    for pat in _KEEP_PATTERNS:
        if pat.search(line):
            return "KEEP"

    # Default: conservative keep
    return "KEEP"


__all__ = ["compress_debug_noise"]
