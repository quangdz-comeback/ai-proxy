"""Tests for compress/debug_noise.py."""

from unittest.mock import patch, MagicMock

from compress.debug_noise import compress_debug_noise


class TestCompressDebugNoise:
    """Tests for compress_debug_noise()."""

    def test_compress_few_noise_lines_unchanged(self):
        """<3 noise lines → unchanged."""
        text = "Some normal output\nDEBUG: verbose thing\nMore output"
        result = compress_debug_noise(text)
        assert result == text

    def test_compress_all_keep_lines_unchanged(self):
        """only KEEP-classified lines → unchanged."""
        text = "Error: critical failure\nWarning: low disk\nImportant info"
        result = compress_debug_noise(text)
        assert result == text

    @patch("compress.debug_noise.compress_with_llm")
    def test_compress_with_noise_summarized(self, mock_llm):
        """mock LLM, verify NOISE lines replaced with summary."""
        mock_llm.return_value = "3 debug lines: DEBUG messages"
        lines = [
            "Error: something bad",
            "DEBUG: step 1",
            "DEBUG: step 2",
            "DEBUG: step 3",
            "DEBUG: step 4",
            "Important output",
        ]
        text = "\n".join(lines)
        result = compress_debug_noise(text)
        # Should have LLM summary marker
        assert "BUDGET_NOISE_SUMMARY" in result
        assert "Error: something bad" in result
        assert "Important output" in result
        # Individual DEBUG lines should be removed (they become noise)
        # The keep lines + summary should be present
        mock_llm.assert_called_once()

    def test_compress_preserves_code_blocks(self):
        """code fence content untouched."""
        text = "before\n```python\nDEBUG: inside code\nDEBUG: more code\nDEBUG: even more\n```\nafter"
        result = compress_debug_noise(text)
        # Code fence content should be preserved verbatim
        assert "DEBUG: inside code" in result
        assert "```python" in result

    @patch("compress.debug_noise.compress_with_llm")
    def test_compress_llm_failure_fails_open(self, mock_llm):
        """mock LLM to raise, original text returned."""
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        lines = [
            "DEBUG: step 1",
            "DEBUG: step 2",
            "DEBUG: step 3",
            "DEBUG: step 4",
        ]
        text = "\n".join(lines)
        result = compress_debug_noise(text)
        assert result == text
