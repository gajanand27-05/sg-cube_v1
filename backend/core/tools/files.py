"""File ops + dictation tools (Phase 11b)."""
import os
import subprocess
from pathlib import Path

import pyautogui

from backend.core.tools.registry import SecurityLevel, ToolResult, tool

# ... (rest of imports)

@tool(security=SecurityLevel.CAUTION)
def delete_file(file: str) -> ToolResult:
    """Delete a file. `file` is a full path or a substring of a file name in
    your common user folders. REQUIRES CONFIRMATION."""
    # This logic matches summarize.py's _resolve_file
    p = Path(file).expanduser()
    resolved = None
    if p.exists() and p.is_file():
        resolved = p
    else:
        q = file.strip().lower()
        if q:
            for root in SEARCH_ROOTS:
                if not root.exists(): continue
                try:
                    for candidate in root.rglob("*"):
                        if candidate.is_file() and q in candidate.name.lower():
                            resolved = candidate
                            break
                    if resolved: break
                except (PermissionError, OSError): continue

    if not resolved:
        return {"status": "blocked", "reason": f"no file matching {file!r}"}
    
    try:
        os.remove(resolved)
        return {"status": "success", "message": f"Deleted {resolved.name}"}
    except Exception as e:
        return {"status": "error", "reason": f"Delete failed: {e}"}

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


@tool
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


@tool
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


@tool
def type_text(text: str) -> dict:
    """Type `text` into the currently focused window — as if you typed it on
    the keyboard. Use for quick dictation. Does NOT press Enter at the end."""
    if not text:
        return {"status": "blocked", "reason": "empty text"}
    pyautogui.typewrite(text, interval=0.02)
    return {"status": "success", "message": f"typed {len(text)} chars"}
