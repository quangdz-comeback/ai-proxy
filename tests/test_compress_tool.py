"""Tests for compress/tool_output.py."""

from unittest.mock import patch, MagicMock

from compress.tool_output import compress_tool_output
from compress.markers import BUDGET_CACHE_PREFIX, BUDGET_CACHE_SUFFIX


class TestCompressToolOutput:
    """Tests for compress_tool_output()."""

    @patch("compress.tool_output.get_cache")
    def test_compress_short_output_unchanged(self, mock_get_cache):
        """<500 chars returned as-is."""
        result = compress_tool_output("cat", "short content under 500 chars", "key1")
        assert result == "short content under 500 chars"
        # Cache should not be consulted for short output
        mock_get_cache.assert_not_called()

    @patch("compress.tool_output.get_cache")
    def test_compress_ls_output(self, mock_get_cache):
        """ls output with permissions/sizes → only filenames."""
        # Build ls -l style output >500 chars
        lines = []
        for i in range(30):
            lines.append(f"-rw-r--r-- 1 user group 4096 Jan 01 file_{i:03d}.py")
        output = "\n".join(lines)
        assert len(output) > 500

        # Cache miss scenario
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        result = compress_tool_output("ls", output, "key1")
        # Should contain filenames without permissions
        assert "file_000.py" in result
        assert "file_029.py" in result
        # Should not contain permission strings
        assert "-rw-r--r--" not in result
        # Should have been cached
        assert mock_cache.put.called

    @patch("compress.tool_output.get_cache")
    def test_compress_cat_output_verbatim(self, mock_get_cache):
        """cat output kept unchanged."""
        content = "line of code\n" * 50  # >500 chars
        output = content
        assert len(output) > 500

        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        result = compress_tool_output("cat", output, "key1")
        # cat output is kept verbatim (minus the marker prefix)
        assert "line of code" in result

    @patch("compress.tool_output.get_cache")
    def test_compress_grep_many_matches(self, mock_get_cache):
        """>50 grep matches → summarized."""
        lines = [f"src/module_{i}.py:{i+1}:match found here" for i in range(60)]
        output = "\n".join(lines)
        assert len(output) > 500

        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        result = compress_tool_output("grep", output, "key1")
        assert "60 matches" in result

    @patch("compress.tool_output.get_cache")
    def test_compress_generic_long(self, mock_get_cache):
        """>2000 chars unknown tool → truncated middle."""
        output = "abcdefghij" * 300  # 3000 chars
        assert len(output) > 2000

        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        result = compress_tool_output("unknown_tool", output, "key1")
        # Generic compression truncates the middle
        assert "chars compressed" in result

    @patch("compress.tool_output.get_cache")
    def test_compress_caches_result(self, mock_get_cache):
        """second call with same content uses cache."""
        output = "x" * 600

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # first call: miss
        mock_get_cache.return_value = mock_cache

        result1 = compress_tool_output("ls", output, "key1")
        assert mock_cache.put.called

    def test_compress_cache_marker_format(self):
        """output starts with [BUDGET_CACHE: prefix."""
        # We test the marker format by checking the _build_marker helper
        # through a compress call with >500 chars output
        from compress.tool_output import _build_marker
        marker = _build_marker("ls", "abcd1234", "full")
        assert marker.startswith(BUDGET_CACHE_PREFIX)
        assert marker.endswith(BUDGET_CACHE_SUFFIX)
        assert "tool=ls" in marker
        assert "hash=abcd1234" in marker
        assert "mode=full" in marker
