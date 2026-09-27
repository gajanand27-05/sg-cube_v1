"""Turn a contributor's "Onyx" voice note into labelled wake-word clips.

    .venv\\Scripts\\python.exe tools\\import_wake_clips.py NOTE.opus --speaker priya --lang kannada --region karnataka

Accepts whatever a phone sends (WhatsApp .opus/.ogg, .m4a, .mp3, .wav):
PyAV decodes it to 16 kHz mono. The recording is split at its pauses (the
Silero VAD bundled with faster-whisper), and each utterance is saved as a
16-bit WAV in tools/_wake/contrib/<speaker>/ — git-ignored, because these are
other people's voices. See docs/wake-word-recording.md for what they record.

manifest.json lists every clip with its timing, a local Whisper
transcription and a SUGGESTED label (onyx / near_miss / other). Whisper
barely knows the word "Onyx", so check the labels by ear before training or
benchmarking on them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "_wake" / "contrib"
SR = 16000
PAD_S = 0.25
NEAR_MISSES = ("on it", "onion", "annex", "on its way", "only six")


def _label(text: str) -> str:
    t = text.lower()
    if re.search(r"\bon[iy]x\b", t):
        return "onyx"
    if any(n in t for n in NEAR_MISSES):
        return "near_miss"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="voice notes / audio files from one speaker")
    ap.add_argument("--speaker", required=True, help="short name or nickname, used as the folder name")
    ap.add_argument("--lang", default="", help="first language")
    ap.add_argument("--region", default="", help="state or country")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    speaker = re.sub(r"[^a-z0-9_-]+", "_", args.speaker.lower()).strip("_") or "speaker"
    dest = OUT / speaker
    dest.mkdir(parents=True, exist_ok=True)
    model = WhisperModel("small", device="cpu", compute_type="int8")
    manifest = {"speaker": speaker, "lang": args.lang, "region": args.region, "clips": []}
    n = 0
    for src in args.files:
        audio = decode_audio(src, sampling_rate=SR)
        spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500,
                                                        speech_pad_ms=int(PAD_S * 1000)))
        print(f"{Path(src).name}: {len(audio) / SR:.1f}s, {len(spans)} utterances")
        for span in spans:
            clip = audio[span["start"]:span["end"]]
            n += 1
            name = f"{speaker}_{n:03d}.wav"
            with wave.open(str(dest / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())
            segs, _ = model.transcribe(clip, language="en", vad_filter=False,
                                       condition_on_previous_text=False, initial_prompt="Onyx")
            text = " ".join(s.text.strip() for s in segs)
            manifest["clips"].append({"file": name, "source": Path(src).name,
                                      "start_s": round(span["start"] / SR, 2),
                                      "seconds": round(len(clip) / SR, 2),
                                      "transcript_guess": text, "label_guess": _label(text)})
            print(f"  {name}  {len(clip) / SR:4.1f}s  {_label(text):9}  {text}")
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{n} clips in {dest}. Check the label guesses by ear before using them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
