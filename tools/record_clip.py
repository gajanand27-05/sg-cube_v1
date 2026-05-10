"""Record a short audio clip from a microphone and save as WAV.

Usage:
    python tools/record_clip.py                     # 5s, default mic, default path
    python tools/record_clip.py --duration 8
    python tools/record_clip.py --device 22         # use input device #22
    python tools/record_clip.py --device "Rockerz"  # match by substring
    python tools/record_clip.py --list              # list input devices and exit

Records 16kHz mono int16 PCM (what Whisper wants).
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

DEFAULT_DURATION = 5
DEFAULT_OUT = Path("tools/_recordings/clip.wav")
SAMPLE_RATE = 16000


def list_input_devices() -> None:
    print("=== Input devices ===")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            marker = " <-- DEFAULT" if i == sd.default.device[0] else ""
            print(
                f"  [{i:2d}] {d['name']} "
                f"(in: {d['max_input_channels']}ch, "
                f"sr: {int(d['default_samplerate'])}){marker}"
            )


def resolve_device(spec: str | None) -> int | None:
    if spec is None:
        return None
    if spec.isdigit():
        return int(spec)
    needle = spec.lower()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and needle in d["name"].lower():
            return i
    raise SystemExit(f"No input device matched '{spec}'. Use --list to see options.")


def record(duration: int, out: Path, device: int | None = None) -> Path:
    if device is None:
        device = sd.default.device[0]
    name = sd.query_devices(device)["name"]
    print(f"Using device [{device}]: {name}")

    print("\n>>> GET READY — countdown to recording <<<", flush=True)
    for n in range(5, 0, -1):
        print(f"    {n}...", flush=True)
        time.sleep(1)
    print(f"\n>>> SPEAK NOW — recording for {duration}s <<<\n", flush=True)

    audio: np.ndarray = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=device,
    )
    sd.wait()

    peak = int(np.max(np.abs(audio)))
    if peak < 500:
        print(
            f"  WARNING: peak amplitude {peak}/32767 — recording is essentially silent.\n"
            f"  Check that the right mic is selected and not muted.",
            file=sys.stderr,
        )
    else:
        print(f"  peak amplitude: {peak}/32767 (ok)")

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(audio.tobytes())
    print(f"Saved: {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--device", type=str, default=None,
                    help="Input device index (int) or substring match")
    ap.add_argument("--list", action="store_true", help="List input devices and exit")
    args = ap.parse_args()

    if args.list:
        list_input_devices()
        sys.exit(0)

    record(args.duration, args.out, resolve_device(args.device))
