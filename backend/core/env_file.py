"""Change one setting in a .env file without touching anything else in it.

For settings the user changes from the HUD (and, in Phase 3, the Setup
screen): the line for KEY is replaced in place, or appended if absent; every
other line and comment is kept as written. Temp file + replace, so a crash
mid-write cannot truncate the user's configuration.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def set_value(path: Path, key: str, value: str) -> None:
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or "\n" in value or "\r" in value:
        raise ValueError(f"refusing to write {key!r}")
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    new, replaced = [], False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                new.append(f"{key}={value}")
                replaced = True
            continue  # a duplicate KEY= line would shadow ours; drop it
        new.append(line)
    if not replaced:
        new.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
    os.replace(tmp, path)
