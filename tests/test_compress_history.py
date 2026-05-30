"""Tests for compress/history.py."""

from unittest.mock import patch

from compress.history import compress_history


def _make_messages(n: int, prefix: str = "msg") -> list:
    """Build n simple alternating user/assistant messages."""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"{prefix}_{i}: some content here"})
    return msgs


class TestCompressHistory:
    """Tests for compress_history()."""

    def test_compress_short_history_unchanged(self):
        """<=5 messages → unchanged."""
        msgs = _make_messages(4)
        result = compress_history(msgs)
        assert result == msgs

    @patch("compress.history.compress_with_llm")
    def test_compress_long_history_summary(self, mock_llm):
        """10 messages, verify old ones summarized."""
        mock_llm.return_value = "Summary: discussed auth and caching"
        msgs = _make_messages(10)
        result = compress_history(msgs, keep_last_n=4)
        # Result should be shorter than input
        assert len(result) < len(msgs)
        # Last 4 messages should be preserved verbatim
        for i in range(4):
            assert result[-(i + 1)] == msgs[-(i + 1)]
        # Should have a summary message
        summary_msgs = [m for m in result if m.get("content", "").startswith("[BUDGET_HISTORY]")]
        assert len(summary_msgs) == 1
        mock_llm.assert_called_once()

    @patch("compress.history.compress_with_llm")
    def test_compress_preserves_state_messages(self, mock_llm):
        """messages with 'completed'/'TODO' preserved verbatim."""
        mock_llm.return_value = "Summary: discussed features"
        msgs = [
            {"role": "assistant", "content": "Setup completed successfully"},
            {"role": "user", "content": "What's left?"},
            {"role": "assistant", "content": "TODO: add tests"},
            {"role": "user", "content": "OK"},
            {"role": "assistant", "content": "msg_4"},
            {"role": "user", "content": "msg_5"},
        ]
        result = compress_history(msgs, keep_last_n=2)
        # State-bearing messages should appear verbatim
        state_contents = [m["content"] for m in result]
        assert "Setup completed successfully" in state_contents
        assert "TODO: add tests" in state_contents

    @patch("compress.history.compress_with_llm")
    def test_compress_llm_failure_fails_open(self, mock_llm):
        """mock LLM to raise, original messages returned."""
        mock_llm.side_effect = RuntimeError("LLM down")
        msgs = _make_messages(10)
        result = compress_history(msgs, keep_last_n=4)
        assert result == msgs

    @patch("compress.history.compress_with_llm")
    def test_compress_injects_budget_history_marker(self, mock_llm):
        """summary has [BUDGET_HISTORY] prefix."""
        mock_llm.return_value = "Discussed X and Y"
        msgs = _make_messages(10)
        result = compress_history(msgs, keep_last_n=4)
        summary_msgs = [m for m in result if "[BUDGET_HISTORY]" in m.get("content", "")]
        assert len(summary_msgs) >= 1
        for sm in summary_msgs:
            assert sm["content"].startswith("[BUDGET_HISTORY]")
