import logging
from pathlib import Path

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


@router.get("/list")
def list_files(path: str = Query(".", description="Directory path")):
    try:
        p = Path(path).resolve()
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
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "size": stat.st_size if child.is_file() else 0,
                    "modified": stat.st_mtime,
                })
            except OSError:
                continue

        return {
            "path": str(p),
            "parent": str(p.parent) if str(p) != str(p.parent) else None,
            "entries": entries,
        }
    except Exception as e:
        log.warning(f"File listing failed: {e}")
        return {"error": str(e), "entries": []}
