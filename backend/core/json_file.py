"""Read and write the small JSON files SG-CUBE keeps, without losing them.

The failure this exists for: a file that exists but can't be read (half-
written, hand-edited, locked by antivirus) was treated as empty, and the next
save wrote the empty state over everything in it. contacts.json lost every
number that way; dogfooding.json and gate_rejections.json had the same shape.

read() tells "missing" (a genuinely new store) apart from "unreadable" (an
error; do not write over it). write() is temp file + fsync + replace, and
keeps the previous version as <name>.bak.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class Unreadable(RuntimeError):
    """The file exists but could not be read or parsed."""


def read(path: Path) -> Any | None:
    """The parsed file, or None if it doesn't exist. Raises Unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise Unreadable(f"{path}: {type(e).__name__}: {e}") from e


def write(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        os.replace(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)
