"""Sweep every input device, record 2 seconds from each, report peak amplitude.

Use this when audio recording is unexpectedly silent. The device with the
highest peak while you speak is the one to pass via --device <index>.

Usage:
    python tools/diagnose_mic.py
    python tools/diagnose_mic.py --seconds 3
"""
import argparse
import sys
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=2.0,
                    help="Record duration per device (default 2.0)")
    ap.add_argument("--device", type=int, default=None,
                    help="Test only this one device index")
    args = ap.parse_args()

    devices = sd.query_devices()
    if args.device is not None:
        candidates = [(args.device, devices[args.device])]
    else:
        candidates = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    print(f"\nRecording {args.seconds}s from each input device.")
    print("Say something loud during each recording (e.g. 'testing one two three').\n")
    print(f"{'idx':>3}  {'peak':>5}  {'rms':>5}  name")
    print("-" * 70)

    results = []
    for idx, dev in candidates:
        name = dev["name"]
        sys.stdout.write(f"{idx:>3}  ... talk now ... ")
        sys.stdout.flush()
        try:
            audio = sd.rec(
                int(args.seconds * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=idx,
            )
            sd.wait()
            arr = audio.flatten()
            peak = int(np.max(np.abs(arr)))
            rms = int(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            sys.stdout.write("\r")
            print(f"{idx:>3}  {peak:>5}  {rms:>5}  {name}")
            results.append((idx, peak, name))
        except Exception as e:
            sys.stdout.write("\r")
            print(f"{idx:>3}  ERROR  {name}: {e}")
        time.sleep(0.3)

    results.sort(key=lambda r: r[1], reverse=True)
    print("\nLoudest device:")
    for idx, peak, name in results[:3]:
        print(f"  [{idx}] peak={peak}  {name}")
    if results and results[0][1] < 500:
        print("\nALL devices captured near-silence. Check Windows Sound settings,"
              " hardware mute key (F4 on many Lenovos), or driver state.")


if __name__ == "__main__":
    main()
