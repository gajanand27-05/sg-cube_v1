"""Record wake-word POSITIVES: you saying "Onyx", for tools/wake_bench.py.

    .venv\\Scripts\\python.exe tools\\record_wake_positives.py
    .venv\\Scripts\\python.exe tools\\record_wake_positives.py --device 22   # or "Rockerz"; --list shows mics

Stop SG-CUBE first (Start menu > Stop SG-CUBE): it would hear every "Onyx"
and answer. The script refuses to start while it is running.

29 prompts, one clip each: "Onyx" alone at normal and at quiet volume, then
short commands ("Onyx, what time is it") at both. Press Enter, then speak
while the clip records; r + Enter redoes the last clip, q + Enter stops (what
is recorded so far is kept). 16kHz mono int16 — the listener's format.

Saved to tools/_wake/pos/ (git-ignored: your voice never leaves this laptop),
with manifest.json listing each clip's prompt, volume and loudness.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from record_clip import list_input_devices, resolve_device  # noqa: E402

OUT = ROOT / "tools" / "_wake" / "pos"
SR = 16000
PHRASES = ["Onyx, what time is it", "Onyx, open notepad", "Onyx, what's the weather",
           "Onyx, stop", "Onyx, set a timer for five minutes", "Hey Onyx, are you there"]
PROMPTS = ([("Onyx", "normal", 3.0)] * 14 + [("Onyx", "quiet", 3.0)] * 6
           + [(p, "normal", 4.0) for p in PHRASES] + [(p, "quiet", 4.0) for p in PHRASES[:3]])


def _sg_cube_running() -> bool:
    try:
        import launch
        return launch.running_instance() is not None
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=None, help="input device index or name substring")
    ap.add_argument("--list", action="store_true", help="list input devices and exit")
    args = ap.parse_args()
    if args.list:
        list_input_devices()
        return 0
    if _sg_cube_running():
        print("SG-CUBE is running and would answer every 'Onyx'. Stop it first "
              "(Start menu > Stop SG-CUBE), then run this again.")
        return 1

    device = resolve_device(args.device)
    if device is None:
        from backend.server.config import settings
        device = settings.wake_device if settings.wake_device is not None else sd.default.device[0]
    print(f"Mic [{device}]: {sd.query_devices(device)['name']}")
    print(f"{len(PROMPTS)} clips. Enter = record, r = redo last, q = stop.\n")
    OUT.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    i = 0
    while i < len(PROMPTS):
        text, volume, secs = PROMPTS[i]
        how = "QUIETLY (as if someone is asleep nearby)" if volume == "quiet" else "at your normal voice"
        cmd = input(f"[{i + 1:2d}/{len(PROMPTS)}] Say {text!r} {how} — Enter to start: ").strip().lower()
        if cmd == "q":
            break
        if cmd == "r" and manifest:
            manifest.pop()
            i -= 1
            continue
        audio = sd.rec(int(secs * SR), samplerate=SR, channels=1, dtype="int16", device=device)
        print(f"      recording {secs:.0f}s ... speak now", flush=True)
        sd.wait()
        pcm = audio[:, 0]
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        peak = int(np.max(np.abs(pcm)))
        name = f"pos_{i + 1:02d}_{volume}_{'onyx' if text == 'Onyx' else 'phrase'}.wav"
        with wave.open(str(OUT / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        note = "  (very quiet: check the mic, or press r to redo)" if peak < 500 else ""
        print(f"      saved {name}  peak={peak} rms={rms:.0f}{note}")
        manifest.append({"file": name, "text": text, "volume": volume, "seconds": secs,
                         "peak": peak, "rms": round(rms)})
        i += 1

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone: {len(manifest)} clips in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
