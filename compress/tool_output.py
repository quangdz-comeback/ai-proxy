"""Rule-based tool output compression with LRU caching.

Compresses tool call outputs using pattern-specific heuristics (no LLM).
Caches compressed results and returns deltas when a previous version is cached.
"""

import hashlib
import logging
import re
import time

from cache.lru_store import get_cache, CacheEntry
from cache.delta import compute_delta, is_delta_worthwhile
from compress.markers import BUDGET_CACHE_PREFIX, BUDGET_CACHE_SUFFIX

logger = logging.getLogger(__name__)


def compress_tool_output(tool_name: str, output: str, api_key: str) -> str:
    """Compress tool output with pattern-based rules and LRU caching.

    Args:
        tool_name: Name of the tool (e.g. "ls", "cat", "pytest")
        output: Raw tool output text
        api_key: API key for cache scoping

    Returns:
        Compressed output string (possibly with cache marker prefix)
    """
    # Not worth compressing short outputs
    if len(output) < 500:
        return output

    # Content hash for cache lookup
    content_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]
    cache_key = f"{api_key}:{tool_name}:{content_hash}"

    cache = get_cache()
    cached = cache.get(cache_key)

    if cached is not None:
        # Cache hit — check if delta is worthwhile
        delta = compute_delta(cached.compressed, output)
        if delta is not None and is_delta_worthwhile(delta, cached.compressed):
            marker = _build_marker(tool_name, content_hash, "delta")
            return f"{marker}\n{delta}"
        # Delta too large or identical — return cached compressed
        marker = _build_marker(tool_name, content_hash, "full")
        return f"{marker}\n{cached.compressed}"

    # Cache miss — compress and store
    compressed = _compress_by_tool(tool_name, output)
    cache.put(
        cache_key,
        CacheEntry(compressed_output=compressed, raw_hash=content_hash, timestamp=time.time()),
    )
    marker = _build_marker(tool_name, content_hash, "full")
    return f"{marker}\n{compressed}"


def _build_marker(tool_name: str, content_hash: str, mode: str) -> str:
    """Build the BUDGET_CACHE marker line."""
    return f"{BUDGET_CACHE_PREFIX}tool={tool_name}:hash={content_hash}:mode={mode}{BUDGET_CACHE_SUFFIX}"


def _compress_by_tool(tool_name: str, output: str) -> str:
    """Apply tool-specific compression rules.

    Args:
        tool_name: Tool name to dispatch to
        output: Raw output text

    Returns:
        Compressed output
    """
    name = tool_name.strip().lower().split("/")[-1]

    # --- File listing tools ---
    if name in ("ls", "find", "tree", "dir"):
        return _compress_listing(output)

    # --- File content tools (keep verbatim) ---
    if name in ("cat", "head", "tail", "type"):
        return output

    # --- Search tools ---
    if name in ("grep", "rg", "findstr"):
        return _compress_grep(output)

    # --- Package installers ---
    if any(
        output.lstrip().startswith(prefix)
        or name in ("npm", "pip", "yarn", "apt")
        for prefix in ("npm install", "pip install", "apt install", "yarn add")
    ) and _is_package_install(output):
        return _compress_install(output)

    # --- Test runners ---
    if name in ("pytest", "jest", "go test", "cargo test"):
        return _compress_test(output)

    # --- Git tools (keep verbatim) ---
    if name in ("git status", "git diff", "git log", "git"):
        return output

    # --- Container orchestration (keep verbatim) ---
    if name in ("docker", "kubectl"):
        return output

    # --- Generic fallback ---
    return _compress_generic(output)


# ---------------------------------------------------------------------------
# Tool-specific compressors
# ---------------------------------------------------------------------------

def _compress_listing(output: str) -> str:
    """Compress ls/find/tree/dir: keep only filenames."""
    lines = output.strip().splitlines()
    entries = []
    for line in lines:
        filename = _extract_filename(line)
        if filename:
            entries.append(filename)

    if not entries:
        # Could not parse — fall back to generic
        return _compress_generic(output)

    if len(entries) > 50:
        first = entries[:30]
        last = entries[-5:]
        summary = "\n".join(first) + f"\n... [{len(entries) - 35} more files]\n" + "\n".join(last)
        return summary

    return "\n".join(entries)


def _extract_filename(line: str) -> str:
    """Extract filename from a ls-style line.

    Handles formats like:
        -rw-r--r-- 1 user group 4096 Jan 01 file.py
        file.py
        ./path/to/file.py
    """
    stripped = line.strip()
    if not stripped:
        return ""

    # ls -l style: permission string starts with -, d, l, c, b, s, p
    # e.g. -rw-r--r-- 1 user group 4096 Jan 01 file.py
    parts = stripped.split()
    if parts and re.match(r'^[d\-lcbpsrwx]{7,10}$', parts[0]):
        # Last column is the filename (handle " -> " symlinks)
        name = parts[-1]
        if name == "->":
            return ""
        return name

    # tree style: ├── file.py  or └── dir/
    tree_match = re.search(r'[├└│─\s]+(.+)$', stripped)
    if tree_match:
        return tree_match.group(1).strip()

    # find style: ./path/to/file
    if stripped.startswith("./") or stripped.startswith("/"):
        return stripped

    # Bare filename
    return stripped


def _compress_grep(output: str) -> str:
    """Compress grep/rg output: keep matches, summarize if too many."""
    lines = output.strip().splitlines()
    # Filter empty lines
    matches = [line for line in lines if line.strip()]

    if len(matches) > 50:
        # Summarize: "N matches in M files: [file list]"
        files = set()
        for m in matches:
            # grep format: file:line:content  or  file:content
            parts = m.split(":", 1)
            if parts[0]:
                files.add(parts[0])
        file_list = ", ".join(sorted(files)[:20])
        if len(files) > 20:
            file_list += f", ... (+{len(files) - 20} more)"
        return f"{len(matches)} matches in {len(files)} files: [{file_list}]"

    return "\n".join(matches)


def _is_package_install(output: str) -> bool:
    """Detect if output looks like a package install."""
    indicators = ("added", "packages", "Successfully installed", "installed",
                   "Installed", "added packages", "Done in")
    lower = output.lower()
    return any(ind.lower() in lower for ind in indicators)


def _compress_install(output: str) -> str:
    """Compress npm/pip/apt install: keep only summary line."""
    lines = output.strip().splitlines()
    # Look for summary lines
    summary_patterns = [
        r"added \d+ packages",        # npm/yarn
        r"Successfully installed",     # pip
        r"Installed \d+ packages",     # pip
        r"\d+ packages? .*installed",  # apt
        r"Done in \d+",                # yarn
    ]
    for line in reversed(lines):
        for pat in summary_patterns:
            if re.search(pat, line, re.IGNORECASE):
                return line.strip()

    # No summary found — return generic compressed
    return _compress_generic(output)


def _compress_test(output: str) -> str:
    """Compress test runner output: keep pass/fail summary only."""
    lines = output.strip().splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        # Always keep FAILED / ERROR lines
        if re.search(r"(FAILED|ERROR|FAIL)", stripped, re.IGNORECASE):
            kept.append(stripped)
            continue
        # Keep summary lines (e.g. "5 passed, 2 failed in 3.2s")
        if re.search(r"\d+ passed", stripped, re.IGNORECASE) or re.search(
            r"\d+ (tests?|examples?).*\d+ (passed|failed)", stripped, re.IGNORECASE
        ):
            kept.append(stripped)
            continue
        # Keep test result status lines (e.g. "test_foo PASSED", "test_bar FAILED")
        if re.search(r"(PASSED|FAILED|SKIPPED|ERROR)\s*$", stripped):
            kept.append(stripped)
            continue
        # Drop dot progress lines and empty noise
        if re.match(r'^[.sSFE*]+$', stripped):
            continue
        # Drop other noise (timestamps, setup output, etc.)
        if re.match(r'^={3,}', stripped) or re.match(r'^-{3,}', stripped):
            continue
        # Keep anything else that looks like a result
        if stripped:
            # Conservative: keep if it looks like a test-related line
            if re.search(r"(test|spec|assert|error|warn)", stripped, re.IGNORECASE):
                kept.append(stripped)

    if not kept:
        return _compress_generic(output)

    return "\n".join(kept)


def _compress_generic(output: str) -> str:
    """Generic fallback: truncate middle of long output."""
    if len(output) <= 2000:
        return output

    first = output[:500]
    last = output[-500:]
    return f"{first}\n... [{len(output) - 1000} chars compressed]\n{last}"


__all__ = ["compress_tool_output"]
