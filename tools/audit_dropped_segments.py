"""How many REAL commands did the segment quality gate silently delete?

The gate in stt_whisper._collect_segments dropped any segment with
no_speech_prob > 0.6, independent of how confident Whisper was about the
words. On the read-aloud corpus that cost exactly one command — "stop" — but
that corpus is clean audio near a ceiling. The archived captures are the real
thing: your voice, your room, your microphone, mid-session.

This replays each archived capture through Whisper with the SAME decode
parameters production uses, and reports every segment where the old gate and
the new one disagree — i.e. a real transcript the assistant threw away.

    .venv\\Scripts\\python.exe tools\\audit_dropped_segments.py
    .venv\\Scripts\\python.exe tools\\audit_dropped_segments.py --limit 40

Captures live in backend/database/captures/ (git-ignored) and are written when
STT_ARCHIVE_CAPTURES=true.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# reconfigure(), not `sys.stdout = TextIOWrapper(sys.stdout.buffer, ...)`.
# Replacing the stream object made this script exit 127 with no output
# whenever stdout was a pipe or a file redirect — it only ran when attached
# to a terminal, which is the worst possible failure mode for a tool whose
# output you want to save.
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import logging
logging.disable(logging.WARNING)

from backend.ai_modules.speech.stt_manager import _register_cuda_libs, select_profile  # noqa: E402

_register_cuda_libs()

from backend.ai_modules.speech import stt_whisper as sw  # noqa: E402

CAPTURES = ROOT / "backend" / "database" / "captures"

# The thresholds as they were before 2026-09-13, so the audit measures the real
# historical behaviour rather than whatever the constants say today.
OLD_NO_SPEECH = 0.6
OLD_LOGPROB = -1.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the N newest captures")
    ap.add_argument("--show-all", action="store_true",
                    help="print every capture, not just the disagreements")
    args = ap.parse_args()

    if not CAPTURES.exists():
        print(f"no captures at {CAPTURES}")
        return 1
    wavs = sorted(CAPTURES.glob("*.wav"))
    if args.limit:
        wavs = wavs[-args.limit:]
    if not wavs:
        print(f"no .wav files in {CAPTURES}")
        return 1

    from faster_whisper import WhisperModel

    prof = select_profile()
    print(f"{len(wavs)} captures  |  {prof}\n")
    model = WhisperModel(prof.model, device=prof.device, compute_type=prof.compute_type)

    kw = dict(language="en", beam_size=1, vad_filter=True,
              vad_parameters={"min_silence_duration_ms": 300},
              initial_prompt=sw._COMMAND_PROMPT)

    total_segs = 0
    rescued: list[tuple[str, str, float, float, str]] = []
    still_dropped = 0
    empty_before = empty_after = 0

    for wav in wavs:
        try:
            segs, info = model.transcribe(str(wav), **kw)
            segs = list(segs)
        except Exception as e:
            print(f"  {wav.name}: {type(e).__name__}: {str(e)[:70]}")
            continue

        # What the archive recorded at the time, if anything.
        sidecar = wav.with_suffix(".json")
        logged = ""
        if sidecar.exists():
            try:
                logged = (json.loads(sidecar.read_text(encoding="utf-8"))
                          .get("text") or "").strip()
            except Exception:
                pass

        total_segs += len(segs)

        # Both sides go through the REAL _collect_segments, so the "thank
        # you."/"bye." hallucination list and the prompt-echo drop apply to
        # each equally. An earlier version of this script reimplemented only
        # the threshold comparison and duly "recovered" a 'Thank you.'
        # hallucination that production would have filtered anyway — the
        # audit has to model the whole pipeline or it invents wins.
        #
        # Anything the OLD gate kept, the NEW gate also keeps (old keeps only
        # when no_speech <= 0.6 and logprob >= -1.5, which fails both new
        # drop clauses), so pre-filtering with the old rule and re-running the
        # real collector reproduces the old end-to-end behaviour exactly.
        survived_old = [s for s in segs
                        if not (s.no_speech_prob > OLD_NO_SPEECH
                                or s.avg_logprob < OLD_LOGPROB)]
        old_text = sw._collect_segments(survived_old, info)["text"].strip()
        new_text = sw._collect_segments(segs, info)["text"].strip()

        if new_text != old_text:
            worst = max((s for s in segs if s not in survived_old),
                        key=lambda s: s.no_speech_prob, default=None)
            rescued.append((wav.name, new_text, old_text,
                            worst.no_speech_prob if worst else float("nan"),
                            worst.avg_logprob if worst else float("nan"), logged))
        else:
            still_dropped += len(segs) - len(survived_old)

        empty_before += not old_text
        empty_after += not new_text

        if args.show_all:
            print(f"  {wav.name}  old={old_text[:40]!r}  new={new_text[:40]!r}")

    print("=" * 78)
    print(f"captures scanned            : {len(wavs)}")
    print(f"segments decoded            : {total_segs}")
    print(f"segments the OLD gate ate   : {len(rescued) + still_dropped}")
    print(f"  ...that were real speech  : {len(rescued)}   <- silently lost commands")
    print(f"  ...correctly dropped      : {still_dropped}")
    print(f"captures that went EMPTY    : {empty_before} before  ->  {empty_after} after")

    if rescued:
        print(f"\n{'-' * 78}\nRecovered — heard correctly, then discarded:\n")
        for name, new_text, old_text, ns, lp, logged in rescued:
            print(f"  {name}")
            print(f"      was      : {old_text[:66]!r}")
            print(f"      now      : {new_text[:66]!r}")
            print(f"      logged at the time : {logged[:56]!r}")
            print(f"      no_speech={ns:.3f}  avg_logprob={lp:+.3f}")
    else:
        print("\nNo real speech was lost to the old gate in this set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
