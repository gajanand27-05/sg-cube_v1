"""File ops + dictation tools (Phase 11b)."""
import subprocess
from pathlib import Path

import pyautogui

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool


def resolve_delete_targets(file: str, limit: int = 10) -> list[Path]:
    """Every file `file` could mean: itself if it is an existing path, else
    each file under SEARCH_ROOTS whose name contains it (up to `limit`).

    Used by delete_file AND by the confirmation step, which binds the call to
    the one full path shown — so what the user approves is what gets deleted.
    The old code deleted the FIRST substring match found anywhere, which the
    user never saw."""
    p = Path(file).expanduser()
    if p.is_file():
        return [p.resolve()]
    q = (file or "").strip().lower()
    found: list[Path] = []
    if not q:
        return found
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for candidate in root.rglob("*"):
                if candidate.is_file() and q in candidate.name.lower():
                    found.append(candidate.resolve())
                    if len(found) >= limit:
                        return found
        except (PermissionError, OSError):
            continue
    return found


def _to_recycle_bin(path: Path) -> None:
    """Delete via the shell with undo, i.e. into the Recycle Bin. Raises on
    failure. pywin32's SHFileOperation: FOF_ALLOWUNDO is what makes it
    recoverable; the other flags stop the shell from putting up its own UI."""
    from win32com.shell import shell, shellcon

    flags = (shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION
             | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI)
    code, aborted = shell.SHFileOperation(
        (0, shellcon.FO_DELETE, str(path), None, flags, None, None))
    if code != 0 or aborted or path.exists():
        raise OSError(f"shell delete failed (code {code}, aborted={aborted})")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.DESTRUCTIVE)  # tier: removes a file; recoverable from the Recycle Bin, but only if the user knows to look
def delete_file(file: str) -> ToolResult:
    """Move a file to the Recycle Bin. `file` is a full path or a substring of
    a file name in your common user folders; if the substring matches more
    than one file, nothing is deleted and the matches are listed so the user
    can pick one. REQUIRES CONFIRMATION, which shows the full path."""
    targets = resolve_delete_targets(file)
    if not targets:
        return ToolResult.blocked(f"no file matching {file!r}")
    if len(targets) > 1:
        listing = "; ".join(str(t) for t in targets)
        return ToolResult.blocked(
            f"{file!r} matches {len(targets)} files, so nothing was deleted. "
            f"Say which one: {listing}")
    target = targets[0]
    try:
        _to_recycle_bin(target)
    except Exception as e:
        return ToolResult.error(f"Delete failed: {e}")
    return ToolResult.success(f"Moved {target} to the Recycle Bin")


SPECIAL_FOLDERS = {
    "downloads": "Downloads",
    "documents": "Documents",
    "docs": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "photos": "Pictures",
    "videos": "Videos",
    "music": "Music",
}

# Where find_file looks. Bounded to user profile to avoid scanning the OS.
SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
]


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: opens an explorer window, reads nothing, writes nothing
def open_folder(name: str) -> dict:
    """Open a folder in File Explorer. `name` can be a special name
    (downloads, documents, desktop, pictures, videos, music) or a full path."""
    canonical = SPECIAL_FOLDERS.get(name.strip().lower())
    if canonical:
        path = Path.home() / canonical
    else:
        path = Path(name).expanduser()

    if ".." in str(path):
        return {"status": "blocked", "reason": "path traversal rejected"}
    if not path.exists() or not path.is_dir():
        return {"status": "blocked", "reason": f"folder not found: {path}"}

    subprocess.Popen(f'explorer "{path}"')
    return {"status": "success", "message": f"opened {path}"}


@tool(tier=CapabilityTier.READONLY)  # tier: filesystem search, no side effects
def find_file(query: str, max_results: int = 10) -> dict:
    """Search for files whose name contains `query` under your common
    user folders (Desktop, Documents, Downloads, Pictures, Videos, Music).
    Returns up to `max_results` paths."""
    query_low = query.strip().lower()
    if not query_low:
        return {"status": "blocked", "reason": "empty search query"}

    matches: list[str] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if query_low in p.name.lower():
                    matches.append(str(p))
                    if len(matches) >= max_results:
                        break
        except (PermissionError, OSError):
            continue
        if len(matches) >= max_results:
            break

    if not matches:
        return {"status": "blocked", "reason": f"no files matching {query!r}"}
    return {
        "status": "success",
        "message": f"found {len(matches)} matches",
        "args": {"matches": matches},
    }


@tool(tier=CapabilityTier.SYSTEM_WRITE)  # tier: synthesizes keystrokes into focused window, reversible
def type_text(text: str) -> dict:
    """Type `text` into the currently focused window — as if you typed it on
    the keyboard. Use for quick dictation. Does NOT press Enter at the end."""
    if not text:
        return {"status": "blocked", "reason": "empty text"}
    pyautogui.typewrite(text, interval=0.02)
    return {"status": "success", "message": f"typed {len(text)} chars"}
