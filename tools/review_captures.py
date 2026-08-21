"""Turn archived live captures into a corpus of what you ACTUALLY said.

    STT_ARCHIVE_CAPTURES=true          # then use Onyx normally for a while
    .venv/Scripts/python.exe tools/review_captures.py

An archived capture stores what Whisper THOUGHT you said, which is exactly
the thing under test — it cannot be its own ground truth. This plays each
one back and asks. Confirming a correct one is a single keypress; the
failures are the ones worth typing out.

The result lands in tools/_stt_corpus/ alongside the read-aloud corpus, in
the same format, so tools/stt_bench.py scores real speech and read speech
together. That matters: the read corpus scores CMD 93.3% while live sessions
produce 'Next voice is cuo of nvd.', so every tuning decision so far has been
measured on the wrong distribution.

Keys per capture:
    ENTER   the transcript is right      -> keep as ground truth
    r       replay
    t       type what you really said
    s       skip (unusable, someone else talking, silence)
    q       stop; everything decided so far is saved
"""
from __future__ import annotations

import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "backend" / "database" / "captures"
CORPUS = ROOT / "tools" / "_stt_corpus"
REVIEWED = CAPTURES / "reviewed.json"
SR = 16000


def _load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def main() -> int:
    if not CAPTURES.exists():
        print(f"no captures at {CAPTURES}\n"
              f"set STT_ARCHIVE_CAPTURES=true in .env, use Onyx for a while, "
              f"then run this again.")
        return 1

    reviewed: dict[str, str] = {}
    if REVIEWED.exists():
        reviewed = json.loads(REVIEWED.read_text(encoding="utf-8"))

    wavs = sorted(CAPTURES.glob("*.wav"))
    todo = [w for w in wavs if w.stem not in reviewed]
    print(f"{len(wavs)} captures, {len(todo)} not yet reviewed\n")
    if not todo:
        print("nothing left to review.")
        return 0

    CORPUS.mkdir(parents=True, exist_ok=True)
    corpus_path = CORPUS / "corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8")) \
        if corpus_path.exists() else {}

    import soundfile as sf

    try:
        for i, wav in enumerate(todo, 1):
            meta_path = wav.with_suffix(".json")
            meta = json.loads(meta_path.read_text(encoding="utf-8")) \
                if meta_path.exists() else {}
            heard = meta.get("transcript", "")
            audio = _load_wav(wav)

            print(f"[{i}/{len(todo)}] {wav.stem}  ({meta.get('seconds', '?')}s, "
                  f"trigger={meta.get('trigger') or '?'})")
            print(f"      WHISPER HEARD: {heard!r}")
            sd.play(audio, SR)
            sd.wait()

            while True:
                choice = input("      [ENTER]=correct  r=replay  t=type  "
                               "s=skip  q=quit > ").strip().lower()
                if choice == "r":
                    sd.play(audio, SR)
                    sd.wait()
                    continue
                if choice == "q":
                    raise KeyboardInterrupt
                if choice == "s":
                    reviewed[wav.stem] = "__skipped__"
                    break
                if choice == "t":
                    truth = input("      what you actually said: ").strip()
                    if not truth:
                        continue
                elif choice == "":
                    if not heard:
                        print("      (nothing was transcribed — use t or s)")
                        continue
                    truth = heard
                else:
                    continue

                pid = f"live_{wav.stem}"
                sf.write(CORPUS / f"{pid}.wav", audio, SR)
                corpus[pid] = truth
                corpus_path.write_text(json.dumps(corpus, indent=2),
                                       encoding="utf-8")
                reviewed[wav.stem] = truth
                mark = "kept" if truth == heard else "CORRECTED"
                print(f"      {mark}: {truth!r}\n")
                break

            REVIEWED.write_text(json.dumps(reviewed, indent=2), encoding="utf-8")
    except KeyboardInterrupt:
        print("\nstopped — progress saved.")

    REVIEWED.write_text(json.dumps(reviewed, indent=2), encoding="utf-8")
    live = [k for k in corpus if k.startswith("live_")]
    wrong = sum(1 for k, v in reviewed.items()
                if v not in ("__skipped__",) and v != "")
    print(f"\ncorpus now holds {len(corpus)} utterances ({len(live)} from live use)")
    print(f"run:  .venv/Scripts/python.exe tools/stt_bench.py --collapse-repeats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
