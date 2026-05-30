"""Budget mode compression/cache pipeline."""

import logging
from budget.trigger import is_budget_mode
from compress.markers import CAVEMAN_PROMPT
from compress.tool_output import compress_tool_output
from compress.debug_noise import compress_debug_noise
from compress.history import compress_history
from compress.dedup import deduplicate_lines

logger = logging.getLogger(__name__)


def transform_payload(payload: dict, api_key: str = "") -> dict:
    """Transform a request payload with budget compression.

    If budget mode is not active, returns payload unchanged (zero overhead).
    If active, applies the full compression pipeline:
    1. Inject caveman system prompt
    2. Compress old history (keep last N turns + focal points)
    3. Compress tool call outputs (pattern-based + LRU cache)
    4. Summarize debug noise in assistant messages
    5. Deduplicate lines (especially errors with migration)
    6. Strip reasoning_effort field (upstream doesn't know "budget")

    Args:
        payload: The request payload dict (must have "messages" key)
        api_key: The API key for cache isolation

    Returns:
        Transformed payload dict (may be same object if not budget mode)
    """
    if not is_budget_mode(payload):
        return payload

    messages = payload.get("messages", [])
    if not messages:
        return payload

    try:
        # 1. Inject caveman system prompt
        messages = _inject_caveman(messages)

        # 2. Compress history (summarize old turns, keep recent)
        messages = compress_history(messages, api_key=api_key)

        # 3. Walk messages and compress per-type
        messages = _compress_messages(messages, api_key)

        # 4. Update payload
        payload["messages"] = messages

    except Exception as e:
        logger.warning("Budget compression failed, using original payload: %s", e)
        # Fail open - never break the request

    # 5. Strip reasoning_effort so upstream doesn't see unknown value
    payload.pop("reasoning_effort", None)

    return payload


def _inject_caveman(messages: list) -> list:
    """Prepend caveman system prompt to messages.

    If a system message already exists, prepend caveman to it.
    If no system message exists, create one.
    """
    if not messages:
        return messages

    if messages[0].get("role") == "system":
        # Prepend caveman to existing system prompt
        messages[0] = {
            **messages[0],
            "content": CAVEMAN_PROMPT + "\n\n" + messages[0].get("content", ""),
        }
    else:
        # Insert new system message
        messages.insert(0, {"role": "system", "content": CAVEMAN_PROMPT})

    return messages


def _compress_messages(messages: list, api_key: str) -> list:
    """Walk messages and apply type-specific compression."""
    compressed = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        # Tool output -> compress with LRU cache
        if role == "tool" and isinstance(content, str):
            tool_name = _extract_tool_name_for(messages, msg)
            try:
                content = compress_tool_output(tool_name, content, api_key)
            except Exception as e:
                logger.debug("Tool output compression failed: %s", e)
            msg = {**msg, "content": content}

        # Assistant message -> debug noise + dedup
        elif role == "assistant" and isinstance(content, str):
            try:
                content = compress_debug_noise(content)
            except Exception as e:
                logger.debug("Debug noise compression failed: %s", e)
            try:
                content = deduplicate_lines(content)
            except Exception as e:
                logger.debug("Dedup failed: %s", e)
            msg = {**msg, "content": content}

        # User message -> dedup
        elif role == "user" and isinstance(content, str):
            try:
                content = deduplicate_lines(content)
            except Exception as e:
                logger.debug("Dedup failed: %s", e)
            msg = {**msg, "content": content}

        compressed.append(msg)

    return compressed


def _extract_tool_name_for(messages: list, tool_msg: dict) -> str:
    """Try to find the tool name that produced this tool output.

    Walks backwards through messages to find the assistant message with
    tool_calls matching this tool_msg's tool_call_id.
    """
    call_id = tool_msg.get("tool_call_id", "")
    if not call_id:
        return ""

    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id") == call_id:
                    return tc.get("function", {}).get("name", "")
    return ""
