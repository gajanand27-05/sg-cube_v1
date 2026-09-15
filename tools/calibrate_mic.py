"""Measure this room's noise floor and your speech level; print the settings.

    .venv\\Scripts\\python.exe tools\\calibrate_mic.py

Run it ONCE in the room you will demo in, then paste the two lines it prints
into .env. Takes about 90 seconds: it asks you to be quiet, then to talk.

── Why this exists ──────────────────────────────────────────────────────
vad_rms_threshold (50) and capture_min_rms (200) were hardcoded against an
assumed near-silent room. Measured on the dev machine's mic array:

  Realtek enhancements ON : floor p50 0.5 — but speech is gated to rms 1-80,
                            i.e. UNDER both thresholds. Every command dropped.
  Realtek enhancements OFF: speech rms 2568-6742 (healthy) but floor p50 814,
                            p99 6369 — 100% of "silent" frames clear a
                            threshold of 50, so a capture never ends on
                            silence and runs to the 10s cap full of noise.

A live session in that state produced 23 empty transcripts out of 30.

The numbers are properties of a ROOM and a MICROPHONE, not of the software,
and a demo hall is not a bedroom. So measure, do not guess — and re-run this
in the actual room before the actual demo.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLE_RATE = 16000
FRAME = int(SAMPLE_RATE * 0.03)      # 30ms — the granularity the VAD works at
QUIET_SECONDS = 30
SPEECH_SECONDS = 15


def frame_rms(audio: np.ndarray) -> np.ndarray:
    """Per-frame RMS in int16 amplitude units, as the VAD sees it."""
    n = len(audio) - FRAME
    if n <= 0:
        return np.array([0.0])
    return np.array([float(np.sqrt(np.mean(audio[i:i + FRAME] ** 2)))
                     for i in range(0, n, FRAME)])


def record(seconds: float, device: int | None) -> np.ndarray:
    a = sd.rec(int(SAMPLE_RATE * seconds), samplerate=SAMPLE_RATE,
               channels=1, dtype="float32", device=device)
    sd.wait()
    return a.flatten() * 32768


def countdown(message: str, seconds: int = 3) -> None:
    print(f"\n{message}")
    for i in range(seconds, 0, -1):
        print(f"  starting in {i}...", end="\r", flush=True)
        time.sleep(1)
    print("  RECORDING NOW          ")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None,
                    help="mic device index (default: system default)")
    args = ap.parse_args()

    try:
        from backend.server.config import settings
        dev = args.device if args.device is not None else settings.wake_device
        cur_vad, cur_cap = settings.vad_rms_threshold, settings.capture_min_rms
    except Exception:
        dev, cur_vad, cur_cap = args.device, 50.0, 200.0

    name = sd.query_devices(dev)["name"] if dev is not None else "system default"
    print(f"microphone : {name}")
    print(f"current    : VAD_RMS_THRESHOLD={cur_vad:.0f}  CAPTURE_MIN_RMS={cur_cap:.0f}")

    countdown(f"STEP 1 of 2 — stay SILENT for {QUIET_SECONDS}s. "
              f"Don't type, don't move the laptop.")
    floor = frame_rms(record(QUIET_SECONDS, dev))

    countdown(f"STEP 2 of 2 — TALK for {SPEECH_SECONDS}s, normally, at the "
              f"distance you'll use in the demo.\n  Say your real commands: "
              f"\"onyx, what time is it\", \"onyx, stop\", \"onyx, battery status\".")
    speech_all = frame_rms(record(SPEECH_SECONDS, dev))
    # Only the frames where you were actually talking — the gaps between words
    # are floor, and averaging them in would understate your speech level.
    speech = speech_all[speech_all > np.percentile(speech_all, 60)]

    f50, f90, f99 = np.percentile(floor, [50, 90, 99])
    s25, s50 = np.percentile(speech, [25, 50])

    print("\n" + "=" * 68)
    print(f"NOISE FLOOR   p50={f50:8.1f}  p90={f90:8.1f}  p99={f99:8.1f}  max={floor.max():8.1f}")
    print(f"YOUR SPEECH   p25={s25:8.1f}  p50={s50:8.1f}  max={speech.max():8.1f}")
    headroom = s25 / max(f90, 1)
    print(f"HEADROOM      speech p25 / floor p90 = {headroom:.1f}x")

    clipping = 100.0 * float(np.mean(speech >= 32000))
    if clipping > 0.1:
        print(f"\n  WARNING: {clipping:.1f}% of speech frames are CLIPPING. "
              f"Lower Windows input volume — clipped audio hurts recognition.")

    # Sit the frame gate above the floor's p90 but well under quiet speech, and
    # the capture gate under quiet speech too (it is a mean over the whole
    # capture, so silence padding drags it down).
    vad = max(50.0, min(f90 * 1.5, s25 * 0.5))
    cap = max(100.0, min(f99 * 1.2, s25 * 0.6))

    print("\n" + "-" * 68)
    if headroom < 2.0:
        print("VERDICT: NOT USABLE — your voice is not clearly above the room.")
        print("  No threshold can separate them. In order of effectiveness:")
        print("   1. Use a headset or USB mic (closer mic = more signal, less room).")
        print("   2. Toggle Windows 'Audio enhancements' and re-run this — on some")
        print("      Realtek arrays it suppresses speech ~100x; on others it is the")
        print("      only thing making the mic usable. Measure both, keep the winner.")
        print("   3. Reduce room noise (fan, AC, open window).")
        print(f"\n  (For reference the values would be {vad:.0f} / {cap:.0f}, "
              f"but they will not work reliably at {headroom:.1f}x headroom.)")
        return 1

    verdict = "GOOD" if headroom >= 4 else "WORKABLE, but tight"
    print(f"VERDICT: {verdict} ({headroom:.1f}x headroom)")
    # VAD_RMS_THRESHOLD is NOT raised here. It gates which frames reach the
    # Vosk recognizer, and test_barge_in_real_audio.py fails at 100 and every
    # value above — raising it splices loud fragments together until Vosk
    # hallucinates the wake phrase. The end-of-capture decision is a separate
    # setting for exactly this reason; that is the one we tune.
    silence = max(50.0, min(f90 * 1.3, s25 * 0.5))

    print("\nPaste into .env, then RESTART the backend:\n")
    print(f"  VAD_RMS_THRESHOLD=50")
    print(f"  CAPTURE_SILENCE_THRESHOLD={silence:.0f}")
    print(f"  CAPTURE_MIN_RMS={cap:.0f}")
    print(f"\n  (floor p90 {f90:.0f} -> capture gate {silence:.0f} -> speech p25 {s25:.0f})")
    if silence <= f90:
        print("\n  WARNING: the capture gate is not above your noise floor. Captures")
        print("  will not end on silence and every command will run to the 10s cap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
