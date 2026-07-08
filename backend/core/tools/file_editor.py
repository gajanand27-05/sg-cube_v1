"""File editing tools (Phase T2-2).

Companion to the read-only file tools in `files.py`: read arbitrary
text files, and apply text-anchored edits with explicit user
confirmation. All writers are CAUTION so the guardian confirms each
invocation.
"""
import os
import tempfile
from pathlib import Path

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool

_MAX_BYTES = 5_000_000  # 5MB — read/edit caps to avoid loading massive files blindly.


def _resolve(path_str: str) -> Path | ToolResult:
    p = Path(path_str).expanduser()
    if ".." in p.parts:
        return ToolResult.blocked("path traversal rejected (contains '..')")
    return p


def _atomic_write(p: Path, content: str) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(p.parent), prefix=".sg_", suffix=".tmp", newline=""
    )
    try:
        tmp.write(content)
        tmp.close()
        os.replace(tmp.name, p)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@tool(tier=CapabilityTier.READONLY)  # tier: reads file bytes, no side effects
def read_file(path: str, max_bytes: int = _MAX_BYTES) -> ToolResult:
    """Read a UTF-8 text file and return its contents. `max_bytes` is a soft
    cap (default 5MB) to keep prompts sane."""
    r = _resolve(path)
    if isinstance(r, ToolResult):
        return r
    if not r.is_file():
        return ToolResult.blocked(f"file not found: {r}")
    size = r.stat().st_size
    if size > max_bytes:
        return ToolResult.blocked(f"file too large ({size} bytes > {max_bytes})")
    try:
        text = r.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult.error("file is not UTF-8 text")
    return ToolResult.success(f"read {size} bytes from {r.name}", data={"text": text, "bytes": size})


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.SYSTEM_WRITE)  # tier: mutates file, atomic write, reversible if user has backup
def edit_file(path: str, old_text: str, new_text: str) -> ToolResult:
    """Replace the first occurrence of `old_text` in the file with `new_text`.
    Refuses if `old_text` is missing or ambiguous-friendly (zero matches)."""
    r = _resolve(path)
    if isinstance(r, ToolResult):
        return r
    if not r.is_file():
        return ToolResult.blocked(f"file not found: {r}")
    raw = r.read_text(encoding="utf-8")
    occurrences = raw.count(old_text)
    if occurrences == 0:
        return ToolResult.error(f"old_text not found in {r.name}", confidence_reason=["no match"])
    if occurrences > 1:
        return ToolResult.error(
            f"old_text matches {occurrences} times — make it more specific",
            confidence_reason=["ambiguous match"],
        )
    new_raw = raw.replace(old_text, new_text, 1)
    _atomic_write(r, new_raw)
    return ToolResult.success(f"edited {r.name}")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.SYSTEM_WRITE)  # tier: mutates file, reversible if user has backup
def insert_lines(path: str, line_number: int, text: str) -> ToolResult:
    """Insert `text` BEFORE line `line_number` (1-indexed). Use line_number=0
    or a value larger than the file length to append."""
    r = _resolve(path)
    if isinstance(r, ToolResult):
        return r
    if not r.is_file():
        return ToolResult.blocked(f"file not found: {r}")
    lines = r.read_text(encoding="utf-8").splitlines(keepends=True)
    target = max(0, min(line_number, len(lines)))  # clamp; 0 prepends, >len appends at tail.
    if target == 0:
        idx = 0
    elif target >= len(lines):
        idx = len(lines)
    else:
        # 1-indexed "before line N" lands between lines[N-2] and lines[N-1] — list insert at N-1.
        idx = target - 1
    lines.insert(idx, text if text.endswith("\n") else text + "\n")
    _atomic_write(r, "".join(lines))
    where = (
        "prepended" if idx == 0
        else "appended" if idx >= len(lines) - 1
        else f"at line {idx + 1}"
    )
    return ToolResult.success(f"inserted into {r.name} ({where})")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.SYSTEM_WRITE)  # tier: overwrites file (loses previous content), reversible if user has backup
def write_file(path: str, content: str) -> ToolResult:
    """Overwrite the file with `content`. Creates parent dirs if missing."""
    r = _resolve(path)
    if isinstance(r, ToolResult):
        return r
    r.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(r, content)
    return ToolResult.success(f"wrote {len(content)} bytes to {r.name}")
