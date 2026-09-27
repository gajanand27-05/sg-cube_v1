"""Copy the capture archive's recordings into tools/_wake/keep/ before the
archive prunes them.

    .venv\\Scripts\\python.exe tools\\keep_captures.py              # everything still there
    .venv\\Scripts\\python.exe tools\\keep_captures.py --since 2026-09-26

The archive (backend/core/capture_archive.py) keeps only the newest 500
recordings per category, so evaluation clips vanish within a day of normal
use — 2026-09-26's echo recordings did. tools/_wake/keep/ is git-ignored
(your voice) and nothing prunes it. Re-running only adds what is new, and
manifest.json lists every kept clip: date, category, transcript, trigger rms,
and from sg_cube.log what Onyx was doing when a wake fired and when it began
speaking during a capture (what the real-recording tests select by).
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import shutil
import sys
from datetime import datetime
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


_STATE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*State: AssistantState\.\w+ -> AssistantState\.(\w+)")


def _stamp_s(name: str) -> float | None:
    """Epoch seconds from an archive name (…YYYYMMDD-HHMMSS-mmm.wav), local time."""
    m = re.search(r"(\d{8})-(\d{6})-(\d{3})", name)
    if not m:
        return None
    t = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return t.timestamp() + int(m.group(3)) / 1000


def _state_changes(logs: list[Path]) -> list[tuple[float, str]]:
    out = []
    for log in logs:
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _STATE.match(line)
                if m:
                    t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()
                    out.append((t, m.group(2)))
        except OSError:
            continue
    return sorted(out)


def annotate(manifest: list[dict], changes: list[tuple[float, str]]) -> None:
    """Add what the tests need, from SG-CUBE's own log:
    - wake clips: `assistant_state`, what Onyx was doing when the wake fired;
    - command captures started by a wake: `playback_started_after_trigger_s`,
      when Onyx began speaking during the recording (absent if it didn't).
    The wake clip is archived at the trigger; the capture starts there."""
    if not changes:
        return
    times = [t for t, _ in changes]
    wakes = sorted((_stamp_s(m["file"]), m) for m in manifest if m["category"] == "wake_trigger")
    for m in manifest:
        t = _stamp_s(m["file"])
        if t is None:
            continue
        if m["category"] == "wake_trigger":
            i = bisect.bisect_left(times, t) - 1
            m["assistant_state"] = changes[i][1] if i >= 0 else None
        elif m["category"] == "command" and m.get("trigger_source") == "wake" and m.get("seconds"):
            trig = max((w for w, _ in wakes if w is not None and 0 < t - w < 20), default=None)
            if trig is None:
                continue
            end = trig + m["seconds"] - _PREROLL_S
            spoke = next((ct for ct, st in changes if trig < ct < end and st == "SPEAKING"), None)
            m["trigger_at"] = trig
            if spoke is not None:
                m["playback_started_after_trigger_s"] = round(spoke - trig, 3)


_PREROLL_S = 13 * 0.125  # the wake pre-roll the capture begins with


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
    from backend.core import paths
    annotate(manifest, _state_changes(sorted(paths.LOG_DIR.glob("sg_cube.log*"))))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"added {added}; {len(manifest)} clips kept in {KEEP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
