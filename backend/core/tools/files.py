"""File ops + dictation tools (Phase 11b)."""
import logging
import subprocess
from pathlib import Path

import pyautogui

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool

log = logging.getLogger(__name__)


def resolve_delete_targets(file: str, limit: int = 10) -> list[Path]:
    """Every file `file` could mean: itself if it is an existing path, else
    each file under SEARCH_ROOTS whose name contains it (up to `limit`).

    Used by delete_file AND by the confirmation step, which binds the call to
    the one full path shown — so what the user approves is what gets deleted.
    The old code deleted the FIRST substring match found anywhere, which the
    user never saw."""
    looks_like_path = any(sep in (file or "") for sep in ("\\", "/")) or ":" in (file or "")
    if looks_like_path:
        p = check_user_path(file)   # raises PathRefused
        return [p] if p.is_file() else []
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


_DRIVE_FIXED = 3
_BITBUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"


def _drive_type(root: str) -> int:
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(root)


def _bitbucket_settings(root: str) -> dict:
    """This volume's Recycle Bin settings: NukeOnDelete, MaxCapacity (MB)."""
    import ctypes
    import winreg

    buf = ctypes.create_unicode_buffer(64)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(root, buf, 64):
        return {}
    guid = buf.value[buf.value.find("{"):buf.value.find("}") + 1]
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_BITBUCKET}\\{guid}") as k:
            for name in ("NukeOnDelete", "MaxCapacity"):
                try:
                    out[name] = int(winreg.QueryValueEx(k, name)[0])
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _total_size(path: Path) -> int:
    """Bytes the Recycle Bin would have to hold: a file's size, or every file
    under a folder (a folder is judged by its total, not its own entry)."""
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def permanent_delete_reason(path: Path) -> str | None:
    """Why deleting this file would NOT be recoverable, or None if it goes to
    the Recycle Bin. The shell's undoable delete silently deletes for good
    when the drive has no bin (removable and network drives), when the bin is
    switched off for that drive, or when the file is bigger than the bin.

    ponytail: predicts from the drive type and this volume's BitBucket
    settings; measured only on fixed drives (this machine has no USB or
    network volume to test on). Ceiling: an exotic volume that reports FIXED
    but has no bin would be predicted recoverable."""
    root = path.anchor
    try:
        if _drive_type(root) != _DRIVE_FIXED:
            return "that drive has no Recycle Bin (removable or network drive)"
        bb = _bitbucket_settings(root)
        if bb.get("NukeOnDelete") == 1:
            return "the Recycle Bin is turned off for that drive"
        cap = bb.get("MaxCapacity")
        if cap and _total_size(path) > cap * 1024 * 1024:
            return "it is larger than the Recycle Bin"
    except Exception as e:  # noqa: BLE001 — when unsure, say so rather than promise undo
        return f"could not confirm a Recycle Bin for that drive ({type(e).__name__})"
    return None


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


def _verify_deleted(args, result):
    path = (result.data or {}).get("path")
    if not path:
        raise ValueError("delete_file recorded no path to check")
    return None if not Path(path).exists() else f"{path} is still there"


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.DESTRUCTIVE, verify=_verify_deleted)  # tier: removes a file; recoverable from the Recycle Bin, but only if the user knows to look
def delete_file(file: str) -> ToolResult:
    """Move a file to the Recycle Bin. `file` is a full path or a substring of
    a file name in your common user folders; if the substring matches more
    than one file, nothing is deleted and the matches are listed so the user
    can pick one. REQUIRES CONFIRMATION, which shows the full path."""
    try:
        targets = resolve_delete_targets(file)
    except PathRefused as e:
        return ToolResult.blocked(str(e))
    if not targets:
        return ToolResult.blocked(f"no file matching {file!r}")
    if len(targets) > 1:
        listing = "; ".join(str(t) for t in targets)
        return ToolResult.blocked(
            f"{file!r} matches {len(targets)} files, so nothing was deleted. "
            f"Say which one: {listing}")
    target = targets[0]
    permanent = permanent_delete_reason(target)
    try:
        _to_recycle_bin(target)   # without a bin this deletes for good
    except Exception as e:
        return ToolResult.error(f"Delete failed: {e}")
    if permanent:
        return ToolResult.success(f"Permanently deleted {target} — {permanent}",
                                  data={"path": str(target), "permanent": True})
    return ToolResult.success(f"Moved {target} to the Recycle Bin", data={"path": str(target)})


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

def _user_folder(name: str) -> Path:
    """The REAL location of a user folder. Windows redirects Desktop,
    Documents and Pictures into OneDrive on many laptops (this dev machine
    included): Path.home()/"Desktop" then still exists but is stale, and every
    search and "open desktop" looked in the wrong place."""
    try:
        from win32com.shell import shell

        fid = getattr(shell, f"FOLDERID_{name}")
        return Path(shell.SHGetKnownFolderPath(fid, 0, None))
    except Exception:
        return Path.home() / name


_FOLDER_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")

# Where find_file / delete_file / summarize look, and the ONLY places the
# file tools may read or write (check_user_path). Bounded to the user's own
# folders to avoid scanning the OS — and, for writes, to keep the assistant
# out of AppData (the Startup folder there runs whatever lands in it).
SEARCH_ROOTS = list(dict.fromkeys(_user_folder(n) for n in _FOLDER_NAMES))

_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}


class PathRefused(ValueError):
    pass


def _is_network_or_device(raw: str) -> bool:
    return raw.startswith(("\\\\", "//"))


def _own_folders() -> list[Path]:
    """SG-CUBE's own files: install folder / repo checkout, data folder
    (SG_CUBE_HOME), speech models, and the embedding-model caches. Refused
    even when they fall under a user folder or EXTRA_ALLOWED_ROOTS — e.g. a
    checkout under Documents, or D:\\ added as an extra root. Read at call
    time so an SG_CUBE_HOME change is honoured."""
    from backend.core import paths

    own = [paths.APP_ROOT, paths.DATA_DIR, paths.VOSK_DIR, paths.PIPER_DIR]
    try:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
        own.append(ONNXMiniLM_L6_V2.DOWNLOAD_PATH)
    except Exception:  # noqa: BLE001 — a missing optional import must not open a hole
        pass
    try:
        from huggingface_hub import constants
        own.append(Path(constants.HF_HUB_CACHE))
    except Exception:  # noqa: BLE001
        pass
    return own


def allowed_roots() -> list[Path]:
    """SEARCH_ROOTS plus EXTRA_ALLOWED_ROOTS (";"-separated, config/.env only
    — no tool writes settings, so it can never be widened by voice). A UNC,
    device or relative entry is ignored with a warning rather than trusted."""
    from backend.server.config import settings

    roots = list(SEARCH_ROOTS)
    for entry in filter(None, (e.strip() for e in (settings.extra_allowed_roots or "").split(";"))):
        p = Path(entry).expanduser()
        if _is_network_or_device(entry) or not p.is_absolute():
            log.warning("EXTRA_ALLOWED_ROOTS entry ignored (must be a local absolute path): %r", entry)
            continue
        roots.append(p)
    return roots


def check_user_path(path_str: str) -> Path:
    """The path a file tool may touch, resolved — or PathRefused saying why.

    Refuses UNC shares (\\\\server\\share) and device paths (\\\\?\\, \\\\.\\),
    control characters, alternate data streams (file.txt:stream), reserved
    device names (CON, NUL, COM1...), and anything that RESOLVES outside
    allowed_roots() — which catches '..' traversal and junctions or symlinks
    pointing out. A relative path is taken relative to Documents.

    No quote or shell-metacharacter rule: no file tool hands a path to a
    shell (open_folder and open_notes_today were switched to shell-free calls
    on 2026-09-26), and such a rule refused legal names like "Mom's notes.txt".
    """
    raw = (path_str or "").strip()
    if not raw:
        raise PathRefused("empty path")
    if _is_network_or_device(raw):
        raise PathRefused("network (UNC) and device paths are not allowed")
    if any(ord(c) < 32 for c in raw):
        raise PathRefused("path contains control characters")
    if ":" in raw[2:] or (len(raw) > 1 and raw[1] == ":" and not raw[0].isalpha()):
        raise PathRefused("alternate data streams and stray ':' are not allowed")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _user_folder("Documents") / p
    if any(part.split(".")[0].upper() in _RESERVED_NAMES for part in p.parts[1:]):
        raise PathRefused("reserved Windows device names are not allowed")
    resolved = p.resolve()
    for own in _own_folders():
        try:
            if resolved.is_relative_to(own.resolve()):
                raise PathRefused(f"{resolved} is inside SG-CUBE's own files ({own}); "
                                  "the file tools never touch those")
        except OSError:
            continue
    roots = allowed_roots()
    for root in roots:
        try:
            if resolved.is_relative_to(root.resolve()):
                return resolved
        except OSError:
            continue
    raise PathRefused(f"{resolved} is outside your user folders "
                      f"({', '.join(str(r) for r in roots)})")


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: opens an explorer window, reads nothing, writes nothing
def open_folder(name: str) -> dict:
    """Open a folder in File Explorer. `name` can be a special name
    (downloads, documents, desktop, pictures, videos, music) or a full path."""
    canonical = SPECIAL_FOLDERS.get(name.strip().lower())
    if canonical:
        path = _user_folder(canonical)
    else:
        path = Path(name).expanduser()

    if ".." in str(path):
        return {"status": "blocked", "reason": "path traversal rejected"}
    if not path.exists() or not path.is_dir():
        return {"status": "blocked", "reason": f"folder not found: {path}"}

    # Argument list, no shell: the path is one argv entry, never re-parsed
    # out of a command string.
    subprocess.Popen(["explorer", str(path)], shell=False)
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
