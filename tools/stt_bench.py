"""Measure STT accuracy and latency per configuration, on YOUR recordings.

    .venv/Scripts/python.exe tools/record_stt_corpus.py    # once
    .venv/Scripts/python.exe tools/stt_bench.py

Reports, per config:
  WER        word error rate over the whole corpus (lower is better)
  EXACT      share of phrases transcribed word-perfect — the metric that
             matters for a command, where one wrong word means the wrong tool
  CMD        share where the ROUTER resolved the same intent as it does from
             the true text. This is the number that actually predicts whether
             the assistant obeys: "open note pad" is a WER miss but routes
             correctly, while "stop" -> "top" routes to a web search.
  p50/p95    per-utterance latency

Why not a public dataset: LibriSpeech tells you how a model reads audiobooks.
It says nothing about whether YOUR microphone, in YOUR room, gets "onyx stop"
through — which is the reported problem.

Two scoring corrections are ON by default (2026-09-13), because without them
this tool reported medium/cuda at CMD 73.3% when the true figure is 93.3%:

  * repeated takes are collapsed — the corpus holds each phrase TWICE, so a
    perfect transcript scored as a doubled error. The collapse count is
    printed so a genuine Whisper repetition loop is still visible.
  * spoken numbers fold to digits — corpus.json says "fifteen", Whisper
    writes "15". That is a correct transcription, not an error.

Disable either with --no-collapse-repeats / --no-fold-numbers. Doing so shows
the raw comparison, which reads roughly 20 points worse than reality.

CAUTION: this corpus is clean read-aloud audio and sits near a ceiling. It
measures the MODEL. It does not measure the capture path — VAD boundaries,
the first-500ms trim, room noise — which is where live mishearing has
historically come from. A good score here does not mean live voice is fine.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CORPUS = ROOT / "tools" / "_stt_corpus"

# Register the pip CUDA DLLs before CTranslate2 loads; see stt_manager for why
# this is PATH and not os.add_dll_directory.
from backend.ai_modules.speech.stt_manager import _register_cuda_libs  # noqa: E402

_register_cuda_libs()

from backend.ai_modules.speech.stt_whisper import _COMMAND_PROMPT  # noqa: E402

CONFIGS = [
    ("small    cpu  int8", "small", "cpu", "int8"),
    ("small    cuda fp16", "small", "cuda", "float16"),
    ("medium   cuda fp16", "medium", "cuda", "float16"),
    ("large-v3 cuda fp16", "large-v3", "cuda", "float16"),
]

_PUNCT = re.compile(r"[^\w\s]")


def pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile. `sorted(v)[int(len(v)*q)-1]` is wrong for small
    samples — at n=2 it returns the MINIMUM, which printed a p95 below p50."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def normalize(s: str) -> str:
    """Compare what was said, not how it was punctuated or capitalised."""
    return " ".join(_PUNCT.sub(" ", s.lower()).split())


def collapse_repeat(s: str) -> str:
    """'be quiet be quiet' -> 'be quiet'.

    The first recorded corpus has each phrase spoken TWICE (confirmed from the
    energy envelope: quiet_1 has speech at 1.62-2.12s and again at 4.64-5.20s)
    while corpus.json stores it once, so a PERFECT transcription scored as an
    error and every model looked far worse than it was.

    ON BY DEFAULT since 2026-09-13. It was opt-in, on the reasoning that
    collapsing by default would hide a real Whisper repetition loop. In
    practice the opposite happened: the default output understated medium/cuda
    by 20 points of CMD (73.3% -> 93.3%) and that understated figure was read
    as "Whisper mishears me" and nearly caused the recogniser to be replaced.
    A misleading default is the worse failure. The repetition-loop concern is
    kept by REPORTING the collapse count per config (see main): 30/30 clips
    collapsing is the corpus, 2/30 is a repetition loop, and both stay visible.
    Pass --no-collapse-repeats for the raw transcripts.

    Only an exact whole-phrase doubling is collapsed, so "very very slow"
    survives untouched.
    """
    w = normalize(s).split()
    if w and len(w) % 2 == 0 and w[: len(w) // 2] == w[len(w) // 2:]:
        return " ".join(w[: len(w) // 2])
    return normalize(s)


# Spoken numbers, as a corpus records them, vs digits, as Whisper writes them.
# corpus.json says "what is fifteen times four"; Whisper returns "What is 15
# times 4?". That is a PERFECT transcription — arguably a better one — and it
# was being counted as two word errors and a routing miss, which is most of
# the gap between "28/30" and the true 30/30. The router already accepts both
# forms (rule_engine matches 'what is 15 times 4'), so the disagreement lived
# only in this scorer.
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100",
}


def fold_numbers(s: str) -> str:
    """Score 'fifteen' and '15' as the same token."""
    return " ".join(_NUMBER_WORDS.get(w, w) for w in s.split())


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(edit distance, reference length) in words — Levenshtein over tokens."""
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return (len(h), 0)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return (prev[-1], len(r))


def route(text: str) -> str:
    """What the assistant would DO with this transcript.

    Rule layer only — no cache, no network, no LLM. A cache hit would make the
    result depend on what was benchmarked first, and the agent path would make
    every run cost money and minutes.
    """
    from backend.core.orchestrator.rule_engine import match
    from backend.core.orchestrator.normalize import normalize_for_rules

    try:
        intent = match(normalize_for_rules(text))
    except Exception:
        return "error"
    if not intent:
        return "agent"
    # args matter as much as target: _set_volume returns target="" and puts the
    # level in args, so comparing action:target alone scored a correct route to
    # "set volume to 50" as a miss. Sorted for a stable comparison.
    args = getattr(intent, "args", None) or {}
    rendered = ",".join(f"{k}={args[k]}" for k in sorted(args))
    return f"{intent.action}:{intent.target}({rendered})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="*", help="substring filter on config labels")
    ap.add_argument("--show-errors", action="store_true",
                    help="print every mismatch, not just the summary")
    # Production decodes greedily (stt_whisper.transcribe_array, beam_size=1).
    # Benching at beam 5 flatters accuracy and inflates latency, so the result
    # would describe a decoder the assistant never runs. Default to the truth;
    # --beam 5 is for answering "would a wider beam be worth the time?"
    ap.add_argument("--beam", type=int, default=1,
                    help="beam size (default 1, matching production)")
    ap.add_argument("--no-collapse-repeats", dest="collapse_repeats",
                    action="store_false", default=True,
                    help="do NOT score 'stop stop' as 'stop'. The corpus holds "
                         "two takes per clip, so this shows raw transcripts and "
                         "will read ~20 points worse than reality")
    ap.add_argument("--no-fold-numbers", dest="fold_numbers",
                    action="store_false", default=True,
                    help="do NOT treat 'fifteen' and '15' as equal")
    args = ap.parse_args()

    corpus_path = CORPUS / "corpus.json"
    if not corpus_path.exists():
        print(f"no corpus at {corpus_path}\n"
              f"record one first:  .venv/Scripts/python.exe tools/record_stt_corpus.py")
        return 1
    corpus: dict[str, str] = json.loads(corpus_path.read_text(encoding="utf-8"))
    items = [(pid, text, CORPUS / f"{pid}.wav")
             for pid, text in corpus.items() if (CORPUS / f"{pid}.wav").exists()]
    if not items:
        print("corpus.json has entries but no .wav files next to it")
        return 1

    print(f"{len(items)} utterances from {CORPUS}  (beam_size={args.beam})\n")

    from faster_whisper import WhisperModel

    rows = []
    for label, size, device, ctype in CONFIGS:
        if args.configs and not any(f.lower() in label.lower() for f in args.configs):
            continue
        try:
            model = WhisperModel(size, device=device, compute_type=ctype)
        except Exception as e:
            print(f"{label:20} UNAVAILABLE: {type(e).__name__}: {str(e)[:90]}")
            continue

        errs = ref_words = exact = cmd_ok = collapsed = 0
        times: list[float] = []
        mistakes: list[tuple[str, str, str]] = []

        for pid, truth, wav in items:
            t0 = time.perf_counter()
            try:
                segs, _ = model.transcribe(
                    str(wav), language="en", beam_size=args.beam, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                    initial_prompt=_COMMAND_PROMPT,
                )
                hyp = " ".join(s.text for s in segs).strip()
            except Exception as e:
                hyp = f"<{type(e).__name__}>"
            times.append((time.perf_counter() - t0) * 1000)

            scored = hyp
            if args.collapse_repeats:
                scored = collapse_repeat(hyp)
                if scored != normalize(hyp):
                    collapsed += 1

            # Scoring-only folding. `scored` keeps its original form for
            # route(), because the router has its own normalizer and the
            # question there is what production would do with the real text.
            ref_cmp, hyp_cmp = normalize(truth), normalize(scored)
            if args.fold_numbers:
                ref_cmp, hyp_cmp = fold_numbers(ref_cmp), fold_numbers(hyp_cmp)

            d, n = wer(ref_cmp, hyp_cmp)
            errs += d
            ref_words += n
            if ref_cmp == hyp_cmp:
                exact += 1
            # A word-perfect transcription IS a correct route, even when
            # route(truth) disagrees. "what is fifteen times four" matches no
            # rule (they expect digits) while Whisper's "what is 15 times 4"
            # routes to `calculate` — comparing the two scored the recogniser
            # down for being more useful than the reference text.
            if ref_cmp == hyp_cmp or route(truth) == route(scored):
                cmd_ok += 1
            else:
                mistakes.append((pid, truth, hyp))

        n = len(items)
        rows.append((label, errs / ref_words if ref_words else 1.0,
                     exact / n, cmd_ok / n,
                     statistics.median(times), pct(times, 0.95)))

        # Collapse count, always shown. This is what keeps the repetition-loop
        # failure mode visible now that collapsing is the default.
        #
        # Reported as a bare count, without a verdict. Only EXACT whole-phrase
        # doublings collapse, so a two-takes corpus does NOT produce n/n —
        # "Play, play lofi bits on youtube" is doubled speech that this cannot
        # match. A threshold guess here said "repetition loop?" at 11/30 on a
        # corpus known to hold two takes of everything. Give the number and
        # the disambiguating question; do not pretend to answer it.
        note = ""
        if args.collapse_repeats and collapsed:
            note = (f"  [collapsed {collapsed}/{n} exact doublings — expected if the "
                    f"corpus holds repeated takes; investigate if it does not]")

        print(f"{label:20} WER {errs/max(ref_words,1):5.1%}  EXACT {exact/n:5.1%}  "
              f"CMD {cmd_ok/n:5.1%}  p50 {statistics.median(times):5.0f}ms  "
              f"p95 {pct(times, 0.95):5.0f}ms{note}")
        if args.show_errors and mistakes:
            for pid, truth, hyp in mistakes:
                print(f"      {pid:16} said {truth!r}\n"
                      f"      {'':16} got  {hyp!r}")
        del model

    if not rows:
        return 1

    print("\n— ranked by CMD (does the assistant do the right thing) —")
    for label, w, e, c, p50, p95 in sorted(rows, key=lambda r: (-r[3], r[4])):
        print(f"  {label:20} CMD {c:5.1%}  EXACT {e:5.1%}  WER {w:5.1%}  p50 {p50:5.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
