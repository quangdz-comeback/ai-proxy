"""Delta diff engine for budget-mode content compression.

Uses ``difflib.unified_diff`` to compute compact deltas between two
text blocks and provides a helper to re-apply them.  A worthwhileness
check ensures we only store deltas that actually save meaningful space.
"""

from __future__ import annotations

import difflib
import re
from typing import Optional


# Fraction of *new_text* length at or above which a delta is considered
# not worth storing (we would rather store the full text).
_DELTA_THRESHOLD = 0.70


def is_delta_worthwhile(new_text_len: int, delta_len: int) -> bool:
    """Return ``True`` if *delta_len* is small enough relative to *new_text_len*.

    A delta is worthwhile when it represents less than 70% of the full
    new text.  Zero-length new text is never worthwhile (nothing to
    compress).
    """
    if new_text_len == 0:
        return False
    return delta_len < new_text_len * _DELTA_THRESHOLD


def compute_delta(old_text: str, new_text: str) -> Optional[str]:
    """Return a unified-diff string encoding the changes from *old_text* to *new_text*.

    Returns ``None`` when:

    * The texts are identical (no diff).
    * The resulting delta is not worthwhile (>= 70% of new_text length).

    Parameters
    ----------
    old_text : str
        The original (base) text.
    new_text : str
        The updated text.

    Returns
    -------
    str | None
        A unified diff string suitable for ``apply_delta``, or ``None``.
    """
    if old_text == new_text:
        return None

    # Split without keepends so each line is a clean string.
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="base",
            tofile="current",
            lineterm="",
        )
    )

    if not diff_lines:
        return None

    delta = "\n".join(diff_lines)

    if not is_delta_worthwhile(len(new_text), len(delta)):
        return None

    return delta


def apply_delta(base_text: str, delta: str) -> Optional[str]:
    """Reconstruct the new text by applying a unified *delta* to *base_text*.

    Returns ``None`` if the delta cannot be applied (malformed diff,
    context mismatch, etc.).

    Parameters
    ----------
    base_text : str
        The original text the delta was computed against.
    delta : str
        A unified diff string previously returned by ``compute_delta``.

    Returns
    -------
    str | None
        The reconstructed text, or ``None`` on failure.
    """
    if not delta:
        return None

    try:
        delta_lines = delta.splitlines()
        base_lines = base_text.splitlines()
        return _apply_unified_diff(base_lines, delta_lines)
    except Exception:
        return None


# ------------------------------------------------------------------
# Internal diff-application helpers
# ------------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _apply_unified_diff(
    base_lines: list[str],
    delta_lines: list[str],
) -> Optional[str]:
    """Apply a parsed unified diff to *base_lines*.

    Returns the reconstructed text as a single string (lines joined with
    ``\\n``), or ``None`` on any parse/apply error.
    """
    result: list[str] = []
    base_idx = 0  # Current position in base_lines

    i = 0
    # Skip header lines (--- / +++) until first @@ hunk header
    while i < len(delta_lines):
        if delta_lines[i].startswith("@@"):
            break
        i += 1

    if i >= len(delta_lines):
        return None  # No hunk found

    while i < len(delta_lines):
        line = delta_lines[i]

        # Parse hunk header
        if line.startswith("@@"):
            hunk_info = _parse_hunk_header(line)
            if hunk_info is None:
                return None
            old_start, _old_count = hunk_info
            # Emit any unchanged base lines between previous hunk end
            # and this hunk's start
            while base_idx < old_start:
                if base_idx < len(base_lines):
                    result.append(base_lines[base_idx])
                base_idx += 1
            i += 1
            continue

        # Hunk body lines
        if line.startswith("-"):
            # Line removed from old -- skip it in base
            if base_idx >= len(base_lines):
                return None
            base_idx += 1
        elif line.startswith("+"):
            # Line added -- emit the content after the prefix
            result.append(line[1:])
        elif line.startswith(" "):
            # Context line -- verify and emit from base
            if base_idx >= len(base_lines):
                return None
            result.append(base_lines[base_idx])
            base_idx += 1
        elif line.startswith("\\"):
            # "\ No newline at end of file" -- skip metadata
            pass
        else:
            # Unexpected line in hunk body
            return None
        i += 1

    # Any remaining base lines after last hunk are kept unchanged
    result.extend(base_lines[base_idx:])

    return "\n".join(result)


def _parse_hunk_header(line: str) -> Optional[tuple[int, int]]:
    """Parse ``@@ -start,count +start,count @@`` and return (old_start_0indexed, old_count).

    Returns ``None`` on parse error.
    """
    m = _HUNK_RE.match(line)
    if not m:
        return None
    old_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) is not None else 1
    # unified_diff uses 1-indexed line numbers; convert to 0-indexed
    return (max(old_start - 1, 0), old_count)
