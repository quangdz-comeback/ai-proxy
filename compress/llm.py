"""LLM-based compression using mimo-v2-flash via upstream API."""

import logging
from upstream.client import call_upstream

logger = logging.getLogger(__name__)

COMPRESS_MODEL = "mimo-v2-flash"


def compress_with_llm(system_prompt: str, content: str, max_tokens: int = 300) -> str:
    """Call upstream mimo-v2-flash to compress content per instruction.

    Args:
        system_prompt: Instruction for how to compress
        content: The text to compress
        max_tokens: Max output tokens

    Returns:
        Compressed text string

    Raises:
        Exception: Propagated from call_upstream on failure (caller should catch)
    """
    payload = {
        "model": COMPRESS_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
    }
    result = call_upstream(payload, stream=False)
    return result["choices"][0]["message"]["content"]
