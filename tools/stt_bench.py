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
    return f"{intent.action}:{intent.target}" if intent else "agent"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="*", help="substring filter on config labels")
    ap.add_argument("--show-errors", action="store_true",
                    help="print every mismatch, not just the summary")
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

    print(f"{len(items)} utterances from {CORPUS}\n")

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

        errs = ref_words = exact = cmd_ok = 0
        times: list[float] = []
        mistakes: list[tuple[str, str, str]] = []

        for pid, truth, wav in items:
            t0 = time.perf_counter()
            try:
                segs, _ = model.transcribe(
                    str(wav), language="en", beam_size=5, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                    initial_prompt=_COMMAND_PROMPT,
                )
                hyp = " ".join(s.text for s in segs).strip()
            except Exception as e:
                hyp = f"<{type(e).__name__}>"
            times.append((time.perf_counter() - t0) * 1000)

            d, n = wer(truth, hyp)
            errs += d
            ref_words += n
            if normalize(truth) == normalize(hyp):
                exact += 1
            if route(truth) == route(hyp):
                cmd_ok += 1
            else:
                mistakes.append((pid, truth, hyp))

        n = len(items)
        rows.append((label, errs / ref_words if ref_words else 1.0,
                     exact / n, cmd_ok / n,
                     statistics.median(times), pct(times, 0.95)))

        print(f"{label:20} WER {errs/max(ref_words,1):5.1%}  EXACT {exact/n:5.1%}  "
              f"CMD {cmd_ok/n:5.1%}  p50 {statistics.median(times):5.0f}ms  "
              f"p95 {pct(times, 0.95):5.0f}ms")
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
