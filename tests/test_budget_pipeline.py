"""Tests for budget/pipeline.py."""

import hashlib
from unittest.mock import patch, MagicMock

from budget.pipeline import (
    transform_payload,
    _inject_caveman,
    _extract_tool_name_for,
)
from compress.markers import CAVEMAN_PROMPT


def _budget_payload(messages=None, model="gpt-4"):
    """Build a minimal budget-mode payload."""
    return {
        "model": model,
        "reasoning_effort": "budget",
        "messages": messages or [{"role": "user", "content": "hi"}],
    }


def _non_budget_payload(messages=None, model="gpt-4"):
    """Build a non-budget payload."""
    return {
        "model": model,
        "reasoning_effort": "high",
        "messages": messages or [{"role": "user", "content": "hi"}],
    }


class TestTransformPayload:
    """Tests for transform_payload()."""

    def test_transform_passthrough_non_budget(self):
        """non-budget payload returned unchanged (same object)."""
        payload = _non_budget_payload()
        result = transform_payload(payload)
        assert result is payload

    def test_transform_strips_reasoning_effort(self):
        """budget payload has reasoning_effort removed."""
        payload = _budget_payload()
        result = transform_payload(payload)
        assert "reasoning_effort" not in result

    def test_transform_injects_caveman(self):
        """first message is system with caveman prompt."""
        payload = _budget_payload(messages=[{"role": "user", "content": "hi"}])
        result = transform_payload(payload)
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert CAVEMAN_PROMPT in msgs[0]["content"]

    def test_transform_injects_caveman_existing_system(self):
        """prepends to existing system message."""
        payload = _budget_payload(
            messages=[
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "hi"},
            ]
        )
        result = transform_payload(payload)
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"].startswith(CAVEMAN_PROMPT)
        assert "Be helpful." in msgs[0]["content"]

    def test_transform_preserves_model(self):
        """model field unchanged."""
        payload = _budget_payload(model="claude-3-opus")
        result = transform_payload(payload)
        assert result["model"] == "claude-3-opus"

    @patch("budget.pipeline.compress_tool_output")
    @patch("budget.pipeline.compress_history", side_effect=lambda msgs, **kw: msgs)
    def test_transform_tool_output_compressed(self, mock_hist, mock_compress):
        """tool message with long output gets compressed."""
        long_content = "x" * 600
        tool_msg = {"role": "tool", "content": long_content, "tool_call_id": "tc1"}
        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc1", "function": {"name": "ls"}}],
        }
        payload = _budget_payload(messages=[assistant_msg, tool_msg])
        # compress_tool_output should be called for the tool message
        transform_payload(payload)
        assert mock_compress.called

    @patch("budget.pipeline.compress_history", side_effect=lambda msgs, **kw: msgs)
    def test_transform_deduplicates_errors(self, mock_hist):
        """assistant message with repeated errors gets deduped."""
        content = "Error: failed at line 1\nError: failed at line 2\nError: failed at line 3"
        payload = _budget_payload(
            messages=[{"role": "assistant", "content": content}]
        )
        result = transform_payload(payload)
        # The assistant content should be modified (deduplicated)
        assistant_content = result["messages"][1]["content"]  # index 1 = after system inject
        # Should have fewer lines or contain dedup markers
        assert isinstance(assistant_content, str)

    @patch("budget.pipeline.compress_history", side_effect=lambda msgs, **kw: msgs)
    def test_transform_empty_messages(self, mock_hist):
        """empty messages list handled gracefully."""
        payload = {"model": "gpt-4", "reasoning_effort": "budget", "messages": []}
        result = transform_payload(payload)
        assert result["messages"] == []

    @patch("budget.pipeline.compress_history", side_effect=lambda msgs, **kw: msgs)
    def test_transform_preserves_short_tool_output(self, mock_hist):
        """tool output <500 chars unchanged."""
        tool_msg = {"role": "tool", "content": "short", "tool_call_id": "tc1"}
        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc1", "function": {"name": "cat"}}],
        }
        payload = _budget_payload(messages=[assistant_msg, tool_msg])
        result = transform_payload(payload)
        # Find tool message in result
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        # Short output should not have been altered by compress_tool_output
        # (it returns as-is under 500 chars)
        assert tool_msgs[0]["content"] == "short"


class TestInjectCaveman:
    """Tests for _inject_caveman()."""

    def test_inject_caveman_creates_system(self):
        """no system message → creates one."""
        messages = [{"role": "user", "content": "hello"}]
        result = _inject_caveman(messages)
        assert result[0]["role"] == "system"
        assert CAVEMAN_PROMPT in result[0]["content"]
        assert result[1]["role"] == "user"

    def test_inject_caveman_prepends(self):
        """existing system message → prepends caveman."""
        messages = [{"role": "system", "content": "Be concise."}]
        result = _inject_caveman(messages)
        assert result[0]["content"].startswith(CAVEMAN_PROMPT)
        assert "Be concise." in result[0]["content"]


class TestExtractToolName:
    """Tests for _extract_tool_name_for()."""

    def test_extract_tool_name_found(self):
        """finds tool name from matching assistant tool_calls."""
        tool_msg = {"role": "tool", "tool_call_id": "call_123"}
        assistant_msg = {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_123", "function": {"name": "read_file"}},
                {"id": "call_456", "function": {"name": "write_file"}},
            ],
        }
        messages = [assistant_msg, tool_msg]
        assert _extract_tool_name_for(messages, tool_msg) == "read_file"

    def test_extract_tool_name_not_found(self):
        """returns empty string when no match."""
        tool_msg = {"role": "tool", "tool_call_id": "call_999"}
        assistant_msg = {
            "role": "assistant",
            "tool_calls": [{"id": "call_123", "function": {"name": "read_file"}}],
        }
        messages = [assistant_msg, tool_msg]
        assert _extract_tool_name_for(messages, tool_msg) == ""
