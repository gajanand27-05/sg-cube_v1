import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from backend.core.auth.deps import get_any_user
from backend.server.config import PROJECT_ROOT

log = logging.getLogger(__name__)

# Previously these routes had no auth and accepted absolute paths, which made
# them an arbitrary filesystem read/write API for anyone who could reach the
# port (including .env). Auth-gated and sandboxed to PROJECT_ROOT now; nothing
# in the frontend consumes them, so the tighter contract breaks no caller.
router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(get_any_user)])


def _resolve_sandboxed(path: str) -> Path:
    """Resolve a client-supplied path inside PROJECT_ROOT or raise 403."""
    candidate = (PROJECT_ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise HTTPException(status_code=403, detail="Path outside the project sandbox")
    return candidate


@router.get("/list")
def list_files(path: str = Query(".", description="Directory path (relative to project root)")):
    try:
        p = _resolve_sandboxed(path)
        if not p.exists():
            return {"error": "Path does not exist", "entries": []}
        if not p.is_dir():
            return {"error": "Path is not a directory", "entries": []}

        entries = []
        for child in sorted(p.iterdir()):
            try:
                stat = child.stat()
                entries.append({
                    "name": child.name,
                    "path": str(child.relative_to(PROJECT_ROOT)),
                    "is_dir": child.is_dir(),
                    "size": stat.st_size if child.is_file() else 0,
                    "modified": stat.st_mtime,
                })
            except OSError:
                continue

        parent = p.parent if p != PROJECT_ROOT else None
        return {
            "path": str(p.relative_to(PROJECT_ROOT)) or ".",
            "parent": str(parent.relative_to(PROJECT_ROOT)) if parent else None,
            "entries": entries,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.warning(f"File listing failed: {e}")
        return {"error": str(e), "entries": []}


@router.post("/upload")
async def upload_file(file: UploadFile, dest: str = Query(".", description="Destination directory (relative to project root)")):
    try:
        dest_path = _resolve_sandboxed(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        # A filename like "..\\..\\x" must not escape the sandbox either.
        save_path = _resolve_sandboxed(str(dest_path / Path(file.filename).name))

        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        return {"status": "ok", "path": str(save_path.relative_to(PROJECT_ROOT)), "size": save_path.stat().st_size}
    except HTTPException:
        raise
    except Exception as e:
        log.warning(f"File upload failed: {e}")
        return {"status": "error", "error": str(e)}
