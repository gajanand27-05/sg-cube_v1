"""Copy the capture archive's recordings into tools/_wake/keep/ before the
archive prunes them.

    .venv\\Scripts\\python.exe tools\\keep_captures.py              # everything still there
    .venv\\Scripts\\python.exe tools\\keep_captures.py --since 2026-09-26

The archive (backend/core/capture_archive.py) keeps only the newest 500
recordings per category, so evaluation clips vanish within a day of normal
use — 2026-09-26's echo recordings did. tools/_wake/keep/ is git-ignored
(your voice) and nothing prunes it. Re-running only adds what is new, and
manifest.json lists every kept clip: date, category, transcript, trigger rms.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KEEP = ROOT / "tools" / "_wake" / "keep"


def _category(name: str) -> str:
    if name.startswith("wake-"):
        return "wake_trigger"
    if name.startswith("drop-"):
        return "speech_gate_dropped"
    return "command"


def main() -> int:
    from backend.core import capture_archive

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="YYYY-MM-DD: only recordings from this date on")
    args = ap.parse_args()
    since = (args.since or "").replace("-", "")

    src = capture_archive._ARCHIVE_DIR
    KEEP.mkdir(parents=True, exist_ok=True)
    manifest_path = KEEP / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    kept = {m["file"] for m in manifest}
    added = 0
    for wav in sorted(src.glob("*.wav")):
        stamp = wav.stem.split("-", 1)[1] if wav.stem[:5] in ("wake-", "drop-") else wav.stem
        if wav.name in kept or (since and stamp[:8] < since):
            continue
        meta_file = wav.with_suffix(".json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            shutil.copy2(wav, KEEP / wav.name)
        except (OSError, ValueError):
            continue  # pruned between the listing and the copy
        if meta_file.exists():
            shutil.copy2(meta_file, KEEP / meta_file.name)
        manifest.append({
            "file": wav.name,
            "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}",
            "time": f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}",
            "category": _category(wav.name),
            "transcript": meta.get("transcript", ""),
            "trigger_rms": meta.get("rms"),
            "trigger_source": meta.get("trigger_source") or meta.get("trigger"),
            "seconds": meta.get("seconds"),
        })
        added += 1
    manifest.sort(key=lambda m: (m["date"], m["time"], m["file"]))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"added {added}; {len(manifest)} clips kept in {KEEP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
