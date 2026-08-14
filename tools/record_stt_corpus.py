"""Record a spoken command corpus, so STT accuracy can be measured not guessed.

Two clips of test audio cannot tell you whether `small` or `large-v3` hears
you better, and synthetic TTS audio tests neither your accent, your mic, nor
your room. This prompts you through the real command vocabulary and saves each
utterance next to its known transcript.

    .venv/Scripts/python.exe tools/record_stt_corpus.py

Press ENTER, say the line, press ENTER again. Anything already recorded is
skipped, so you can stop and resume. Re-record a bad take with --redo.

The corpus lands in tools/_stt_corpus/ (git-ignored, like _recordings and
_scratch) as a .wav per phrase plus corpus.json holding the transcripts. Feed
it to tools/stt_bench.py.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "_stt_corpus"
SR = 16000
MAX_SECONDS = 12

# The vocabulary that actually matters, weighted toward what misfires.
# Single words with no sentence context are where Whisper substitutes a
# commoner word ("stop" -> "top", "onyx" -> "onyx" only if it has heard it),
# which is exactly the failure being reported.
PHRASES: list[tuple[str, str]] = [
    # (id, what to say)
    ("stop_1",            "stop"),
    ("stop_2",            "onyx stop"),
    ("cancel_1",          "cancel"),
    ("nevermind_1",       "never mind"),
    ("quiet_1",           "be quiet"),
    ("wake_1",            "onyx"),
    ("wake_2",            "onyx what time is it"),

    ("open_notepad",      "open notepad"),
    ("open_chrome",       "open chrome"),
    ("open_calculator",   "open calculator"),
    ("open_cmd",          "open command prompt"),
    ("close_notepad",     "close notepad"),

    ("time_1",            "what time is it"),
    ("weather_1",         "what's the weather"),
    ("news_1",            "what is the latest tech news"),
    ("math_1",            "what is fifteen times four"),

    ("read_screen_1",     "read the text on my screen"),
    ("read_screen_2",     "what does my screen say"),
    ("describe_1",        "what am I doing right now"),

    ("search_1",          "who won the twenty twenty four t twenty world cup"),
    ("search_2",          "who is the ceo of nvidia"),
    ("search_3",          "find the official nvidia dgx spark documentation"),
    ("summarize_1",       "summarize this page"),
    ("translate_1",       "translate good morning to hindi"),

    ("volume_1",          "set volume to fifty"),
    ("lock_1",            "lock the screen"),
    ("reminder_1",        "remind me to call mom at six"),
    ("play_1",            "play lofi beats on youtube"),
    ("memory_1",          "what did I ask you earlier"),
    ("followup_1",        "and the one after that"),
]


def record_one(seconds: float = MAX_SECONDS) -> np.ndarray:
    """Record until ENTER, capped at `seconds`."""
    frames: list[np.ndarray] = []

    def cb(indata, n, t, status):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", callback=cb):
        input("      [recording — ENTER to stop] ")
    if not frames:
        return np.zeros(0, dtype="int16")
    return np.concatenate(frames).flatten()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", nargs="*", metavar="ID",
                    help="re-record these ids (or all recorded ones if empty)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    corpus_path = OUT / "corpus.json"
    corpus: dict[str, str] = {}
    if corpus_path.exists():
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    redo = set(args.redo) if args.redo is not None else set()
    redo_all = args.redo is not None and not args.redo

    print(f"device: {sd.query_devices(kind='input')['name']!r}")
    print(f"corpus: {OUT}")
    print("\nSay each line naturally, at the distance and volume you'd really use.\n"
          "ENTER to start, ENTER again to stop. Ctrl+C to quit — progress is kept.\n")

    todo = [
        (pid, text) for pid, text in PHRASES
        if redo_all or pid in redo or not (OUT / f"{pid}.wav").exists()
    ]
    if not todo:
        print(f"all {len(PHRASES)} phrases already recorded. --redo to replace.")
        return 0

    try:
        for i, (pid, text) in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {pid}")
            print(f'      SAY:  "{text}"')
            input("      [ENTER when ready] ")
            audio = record_one()

            if audio.size == 0:
                print("      nothing captured — skipped\n")
                continue
            peak = int(np.abs(audio).max())
            dur = audio.size / SR
            sf.write(OUT / f"{pid}.wav", audio, SR)
            corpus[pid] = text
            corpus_path.write_text(json.dumps(corpus, indent=2), encoding="utf-8")

            warn = ""
            if peak < 2000:
                warn = "  <- very quiet, consider --redo " + pid
            elif peak > 32000:
                warn = "  <- clipping, move back a little"
            print(f"      saved {dur:.1f}s peak={peak}{warn}\n")
    except KeyboardInterrupt:
        print("\nstopped — progress saved.")

    print(f"\n{len(corpus)}/{len(PHRASES)} recorded in {OUT}")
    if len(corpus) == len(PHRASES):
        print("run:  .venv/Scripts/python.exe tools/stt_bench.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
