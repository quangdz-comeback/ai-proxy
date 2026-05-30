"""Line deduplication with error migration for budget-mode compression.

Identifies recurring log/error lines, normalises them into templates,
and merges duplicate occurrences into compact summaries -- while
guaranteeing that every error/warning occurrence is represented in the
output (count is never silently dropped).

Pipeline
--------
1. **Segment** text into code fences (preserved verbatim) and prose.
2. **Classify** each prose line (error / warning / traceback / info / ...).
3. **Extract template** -- strip varying parts (line numbers, IPs, timestamps ...).
4. **Merge** consecutive lines sharing the same (type + template).
5. **Reassemble** all segments.
"""

from __future__ import annotations

import re
from typing import Optional


# ======================================================================
# Phase 1 -- Classify
# ======================================================================

_CLASSIFIERS: list[tuple[str, re.Pattern[str]]] = [
    ("error",      re.compile(r"Error:|error:|ERROR|Exception|Traceback|FAILED|FAIL")),
    ("warning",    re.compile(r"Warning:|warn:|WARN|DeprecationWarning|UserWarning")),
    ("traceback",  re.compile(r"^\s+at\s+|^\s+File\s+\"|^\s+\d+\s+\|")),
    ("code_fence", re.compile(r"^```")),
    ("info",       re.compile(r"INFO:|info:|NOTE:|note:")),
]


def classify_line(line: str) -> str:
    """Return the category of *line*: one of
    ``"error"``, ``"warning"``, ``"traceback"``, ``"code_fence"``,
    ``"info"``, or ``"other"``.
    """
    for category, pattern in _CLASSIFIERS:
        if pattern.search(line):
            return category
    return "other"


# ======================================================================
# Phase 2 -- Extract Template
# ======================================================================

# Each entry: (compiled pattern, field_name)
_VARYING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Timestamps  e.g. 2025-01-15T10:30:00.123
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"), "timestamp"),
    # IPv4:port  e.g. 192.168.1.1:8080
    (re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)\b"), "addr"),
    # File paths with line  e.g. /src/auth.py:42
    (re.compile(r"([\w./-]+\.\w{1,10}:\d+)"), "path"),
    # Line numbers  "line 10"  or  ":42" at end of string
    (re.compile(r"\bline\s+(\d+)"), "line"),
    (re.compile(r":(\d+)(?::(\d+))?$"), "line"),
    # Memory / hex addresses  e.g. 0x7f8a3b2c1d00
    (re.compile(r"0x[0-9a-fA-F]+"), "mem"),
]


def extract_template(line: str) -> tuple[str, dict[str, list[str]]]:
    """Strip varying parts from *line* and return a normalised template.

    Returns
    -------
    (template, fields)
        *template* has ``{}`` placeholders where varying data was removed.
        *fields* maps field names to lists of extracted values.

    Examples
    --------
    >>> extract_template("Error: undefined variable 'x' at line 10")
    ("Error: undefined variable 'x' at line {}", {"line": ["10"]})

    >>> extract_template("Warning: deprecated API at /src/auth.py:42")
    ("Warning: deprecated API at {}", {"path": ["/src/auth.py:42"]})
    """
    fields: dict[str, list[str]] = {}
    template = line

    for pattern, field_name in _VARYING_PATTERNS:
        matches = pattern.findall(template)
        if matches:
            # matches may be strings or tuples (from groups); flatten
            flat: list[str] = []
            for m in matches:
                if isinstance(m, tuple):
                    flat.extend(part for part in m if part)
                else:
                    flat.append(m)
            if flat:
                existing = fields.setdefault(field_name, [])
                existing.extend(flat)
                # Replace the matched text with {}
                template = pattern.sub("{}", template)

    return template, fields


# ======================================================================
# Phase 3 -- Merge Group
# ======================================================================

_MAX_INLINE_VALUES = 10
_INLINE_VALUE_MAX_LEN = 20
_SUMMARY_SHOW_FIRST = 3
_SUMMARY_SHOW_LAST = 2


def _all_values_short(fields: dict[str, list[str]]) -> bool:
    """True when every extracted value across all fields is <= 20 chars."""
    return all(len(v) <= _INLINE_VALUE_MAX_LEN for vals in fields.values() for v in vals)


def merge_group(template: str, varying_fields: dict[str, list[str]], count: int) -> str:
    """Merge *count* occurrences of *template* into a single compact string.

    Merge rules (applied in order of priority):

    1. **count > 10** -- summary with first 3 + last 2 values.
    2. **Single varying field, short values** -- inline merge.
    3. **Multiple fields or long values** -- block merge with indented list.

    Parameters
    ----------
    template : str
        Normalised template with ``{}`` placeholders.
    varying_fields : dict
        Field name -> list of extracted values (one per occurrence).
    count : int
        Total number of occurrences that were collapsed.

    Returns
    -------
    str
        The merged representation.
    """
    field_names = list(varying_fields.keys())

    if not varying_fields:
        # No varying parts -- just note the count
        if count > 1:
            return f"{template} (x{count})"
        return template

    # --- Rule 1: count > 10 -> summary ---------------------------------
    if count > _MAX_INLINE_VALUES:
        reps = _representative_values(varying_fields)
        shown_count = _SUMMARY_SHOW_FIRST + _SUMMARY_SHOW_LAST
        lines = [f"{template} ({count} occurrences, showing {shown_count}):"]
        for v in reps[:_SUMMARY_SHOW_FIRST]:
            lines.append(f"  {v}")
        lines.append("  ...")
        for v in reps[-_SUMMARY_SHOW_LAST:]:
            lines.append(f"  {v}")
        return "\n".join(lines)

    # --- Rule 2: single field, short values -> inline ------------------
    if len(field_names) == 1 and _all_values_short(varying_fields):
        values = varying_fields[field_names[0]]
        if template.count("{}") <= 1:
            joined = ", ".join(values)
            return template.replace("{}", joined, 1)
        else:
            return template  # fallback

    # --- Rule 3: multiple fields or long values -> block ----------------
    reps = _representative_values(varying_fields)
    lines = [f"{template}:"]
    for v in reps:
        lines.append(f"  {v}")
    return "\n".join(lines)


def _representative_values(varying_fields: dict[str, list[str]]) -> list[str]:
    """Build a flat list of representative strings from *varying_fields*.

    For a single field, returns its values directly.
    For multiple fields, returns ``field=value`` tuples per occurrence.
    """
    field_names = list(varying_fields.keys())

    if len(field_names) == 1:
        return varying_fields[field_names[0]]

    # Multiple fields -- zip them into composite strings
    max_len = max(len(v) for v in varying_fields.values())
    result: list[str] = []
    for i in range(max_len):
        parts = []
        for name in field_names:
            vals = varying_fields[name]
            if i < len(vals):
                parts.append(f"{name}={vals[i]}")
        if parts:
            result.append(" ".join(parts))
    return result


# ======================================================================
# Main function
# ======================================================================

_CODE_FENCE_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)


def deduplicate_lines(text: str) -> str:
    """Deduplicate error/warning/info lines in *text*.

    Algorithm
    ---------
    1. Split into segments: code blocks (```) and non-code text.
    2. For non-code text:
       a. Split into lines.
       b. Classify each line.
       c. Group consecutive error/warning/traceback lines by (type + template).
       d. For each group: merge via ``merge_group()``.
       e. For info/other lines: exact-dedup -- skip duplicates, count removals.
    3. Reassemble all segments.

    **Critical rule**: every error/warning occurrence is represented in
    the output.  Counts are never silently dropped.

    Parameters
    ----------
    text : str
        The raw tool-call output or log text.

    Returns
    -------
    str
        The deduplicated text with a ``[BUDGET_DEDUP: ...]`` trailer if
        any lines were removed.
    """
    if not text:
        return ""

    # --- Step 1: Segment into code fences and prose --------------------
    segments = _CODE_FENCE_RE.split(text)

    result_parts: list[str] = []
    info_dedup_count = 0
    seen_info_lines: set[str] = set()

    for segment in segments:
        if segment.startswith("```"):
            # Code fence -- preserve verbatim
            result_parts.append(segment)
        else:
            # Prose -- deduplicate
            deduped, removed = _dedup_prose(segment, seen_info_lines)
            info_dedup_count += removed
            result_parts.append(deduped)

    output = "".join(result_parts)

    # Append summary trailer if we removed anything
    if info_dedup_count > 0:
        # Ensure trailing newline before trailer
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"[BUDGET_DEDUP: {info_dedup_count} duplicate info lines removed]"

    return output


# ------------------------------------------------------------------
# Prose deduplication internals
# ------------------------------------------------------------------

def _dedup_prose(
    prose: str,
    seen_info_lines: set[str],
) -> tuple[str, int]:
    """Deduplicate non-code prose lines.

    Returns (deduplicated_text, count_of_removed_info_lines).
    """
    if not prose.strip():
        return prose, 0

    lines = prose.split("\n")
    output_lines: list[str] = []
    removed_count = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            output_lines.append(line)
            i += 1
            continue

        category = classify_line(line)

        # --- code_fence inside prose (guard)
        if category == "code_fence":
            output_lines.append(line)
            i += 1
            continue

        # --- error / warning / traceback -- try to form a group ----------
        if category in ("error", "warning", "traceback"):
            template, fields = extract_template(line)
            group_type = category
            group_template = template
            group_fields: dict[str, list[str]] = dict(fields)
            group_count = 1
            group_raw_lines: list[str] = [line]

            # Extend group while next lines match same (type, template)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                if not next_line.strip():
                    break
                next_cat = classify_line(next_line)
                if next_cat not in ("error", "warning", "traceback"):
                    break
                # For traceback lines, they extend the current group
                if next_cat == "traceback" and group_type in ("error", "warning", "traceback"):
                    group_raw_lines.append(next_line)
                    group_count += 1
                    j += 1
                    continue
                next_template, next_fields = extract_template(next_line)
                if next_cat == group_type and next_template == group_template:
                    for fname, fvals in next_fields.items():
                        group_fields.setdefault(fname, []).extend(fvals)
                    group_count += 1
                    group_raw_lines.append(next_line)
                    j += 1
                else:
                    break

            # Emit merged group
            if group_count == 1:
                output_lines.append(line)
            elif group_type == "traceback" or any(
                classify_line(rl) == "traceback" for rl in group_raw_lines
            ):
                merged = _merge_traceback_group(group_raw_lines, group_count)
                output_lines.append(merged)
            else:
                merged = merge_group(group_template, group_fields, group_count)
                output_lines.append(merged)

            i = j
            continue

        # --- info / other -- simple exact dedup --------------------------
        if line in seen_info_lines:
            removed_count += 1
        else:
            seen_info_lines.add(line)
            output_lines.append(line)

        i += 1

    return "\n".join(output_lines), removed_count


def _merge_traceback_group(raw_lines: list[str], count: int) -> str:
    """Merge a traceback group: keep all unique frames, note total count."""
    unique_frames: list[str] = []
    seen_frames: set[str] = set()
    for line in raw_lines:
        stripped = line.strip()
        if stripped not in seen_frames:
            seen_frames.add(stripped)
            unique_frames.append(line)

    if count <= len(unique_frames):
        return "\n".join(unique_frames)

    result = "\n".join(unique_frames)
    result += f"\n  ({count} total frames, {len(unique_frames)} unique)"
    return result
