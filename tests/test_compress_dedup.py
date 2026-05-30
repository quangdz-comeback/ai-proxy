"""Tests for compress/dedup.py."""

from compress.dedup import (
    classify_line,
    extract_template,
    merge_group,
    deduplicate_lines,
)


class TestClassifyLine:
    """Tests for classify_line()."""

    def test_classify_line_error(self):
        """various error patterns."""
        assert classify_line("Error: something went wrong") == "error"
        assert classify_line("error: file not found") == "error"
        assert classify_line("ERROR critical failure") == "error"
        assert classify_line("Exception: ValueError") == "error"
        assert classify_line("Traceback (most recent call last):") == "error"
        assert classify_line("FAILED test_foo") == "error"
        assert classify_line("FAIL: bad output") == "error"

    def test_classify_line_warning(self):
        """various warning patterns."""
        assert classify_line("Warning: deprecated") == "warning"
        assert classify_line("warn: low memory") == "warning"
        assert classify_line("WARN threshold exceeded") == "warning"
        assert classify_line("DeprecationWarning: old_api") == "warning"
        assert classify_line("UserWarning: something") == "warning"

    def test_classify_line_traceback(self):
        """stack frame patterns."""
        assert classify_line('  File "app.py", line 42') == "traceback"
        assert classify_line('    at main (app.py:10:5)') == "traceback"
        assert classify_line('    42 | x = foo()') == "traceback"

    def test_classify_line_info(self):
        """info patterns."""
        assert classify_line("INFO: server started") == "info"
        assert classify_line("info: connection established") == "info"
        assert classify_line("NOTE: see docs") == "info"
        assert classify_line("note: important") == "info"

    def test_classify_line_other(self):
        """plain text."""
        assert classify_line("just some regular text") == "other"
        assert classify_line("hello world") == "other"
        assert classify_line("") == "other"


class TestExtractTemplate:
    """Tests for extract_template()."""

    def test_extract_template_line_number(self):
        """'Error at line 10' → template + line field."""
        template, fields = extract_template("Error at line 10")
        assert "{}" in template
        assert "10" in fields.get("line", [])

    def test_extract_template_ip_port(self):
        """'Connection refused 192.168.1.1:8080' → template + addr field."""
        template, fields = extract_template("Connection refused 192.168.1.1:8080")
        assert "{}" in template or "192.168.1.1:8080" not in template
        assert any("192.168.1.1:8080" in v for v in fields.get("addr", []))

    def test_extract_template_no_varying(self):
        """plain text → template unchanged, empty fields."""
        template, fields = extract_template("plain text with no varying parts")
        assert template == "plain text with no varying parts"
        assert not fields


class TestMergeGroup:
    """Tests for merge_group()."""

    def test_merge_group_single_occurrence(self):
        """count=1 returns template as-is."""
        result = merge_group("Error: failed", {}, 1)
        assert result == "Error: failed"

    def test_merge_group_inline(self):
        """single field, short values → inline merge."""
        result = merge_group(
            "Error at line {}",
            {"line": ["1", "2", "3"]},
            3,
        )
        assert "1, 2, 3" in result
        assert "Error at line" in result

    def test_merge_group_block(self):
        """multiple fields → block merge."""
        result = merge_group(
            "Error at {}:{}",
            {"addr": ["10.0.0.1:80"], "line": ["42"]},
            1,
        )
        # Block merge produces indented values
        assert "Error at" in result

    def test_merge_group_large_count(self):
        """count > 10 → summary with first/last values."""
        values = [str(i) for i in range(15)]
        result = merge_group(
            "Error at line {}",
            {"line": values},
            15,
        )
        assert "15 occurrences" in result
        assert "0" in result  # first value
        assert "14" in result  # last value
        assert "..." in result


class TestDeduplicateLines:
    """Tests for deduplicate_lines()."""

    def test_deduplicate_empty(self):
        """empty string returns ''."""
        assert deduplicate_lines("") == ""

    def test_deduplicate_no_duplicates(self):
        """all unique lines → unchanged."""
        text = "line1\nline2\nline3"
        result = deduplicate_lines(text)
        assert result == text

    def test_deduplicate_error_migration(self):
        """3 identical errors with different line numbers → merged into 1 line."""
        text = (
            "Error: undefined variable at line 1\n"
            "Error: undefined variable at line 2\n"
            "Error: undefined variable at line 3"
        )
        result = deduplicate_lines(text)
        # Should be collapsed into fewer lines
        assert result.count("Error: undefined variable") < 3
        # Line numbers should be preserved somewhere
        assert "1" in result and "2" in result and "3" in result

    def test_deduplicate_preserves_code_blocks(self):
        """code fences untouched."""
        text = "before\n```python\nprint('hello')\nprint('hello')\n```\nafter"
        result = deduplicate_lines(text)
        assert "```python" in result
        assert "print('hello')" in result

    def test_deduplicate_info_dedup(self):
        """repeated INFO lines → removed with BUDGET_DEDUP trailer."""
        text = "INFO: starting\nINFO: starting\nINFO: starting"
        result = deduplicate_lines(text)
        # Duplicates should be removed
        assert result.count("INFO: starting") == 1
        assert "BUDGET_DEDUP" in result

    def test_deduplicate_traceback_merge(self):
        """traceback frames merged, unique frames kept."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "a.py", line 1\n'
            '  File "b.py", line 2\n'
            '  File "a.py", line 1\n'  # duplicate frame
            '  File "c.py", line 3'
        )
        result = deduplicate_lines(text)
        # Should keep unique frames
        assert 'a.py' in result
        assert 'b.py' in result
        assert 'c.py' in result
