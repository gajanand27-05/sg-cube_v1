"""Measure STT accuracy and latency per configuration, on YOUR recordings.

    .venv/Scripts/python.exe tools/record_stt_corpus.py    # once
    .venv/Scripts/python.exe tools/stt_bench.py
    .venv/Scripts/python.exe tools/stt_bench.py --configs groq --show-errors
    .venv/Scripts/python.exe tools/stt_bench.py --no-groq   # offline, no quota

Benches local faster-whisper (small/medium/large-v3) AND the cloud rung,
Groq whisper-large-v3-turbo and whisper-large-v3, on the same clips through
the same scorer. Two things to hold in mind when reading the cloud rows:

  * their p50 includes a round trip, so it moves with your network and is
    not comparable IN KIND to a local GPU number — but it IS what a turn
    actually pays, which is the figure that matters.
  * they spend API quota: one request per clip per model.

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

LOCAL_CONFIGS = [
    ("small    cpu  int8", "small", "cpu", "int8"),
    ("small    cuda fp16", "small", "cuda", "float16"),
    ("medium   cuda fp16", "medium", "cuda", "float16"),
    ("large-v3 cuda fp16", "large-v3", "cuda", "float16"),
]

# The cloud rung. Named separately from LOCAL_CONFIGS because they are not
# the same kind of measurement: a local p50 is compute, a Groq p50 is compute
# plus a round trip, and only the second one moves when your wifi does.
GROQ_MODELS = [
    ("groq     turbo", "whisper-large-v3-turbo"),
    ("groq     v3   ", "whisper-large-v3"),
]

_PUNCT = re.compile(r"[^\w\s]")


# ── engines ──────────────────────────────────────────────────────────────
#
# Each engine is `load() -> transcribe(wav) -> str -> close()`. The scoring
# loop below does not know which kind it is holding, so local and cloud are
# scored by identical code on identical audio — which is the only way the
# comparison means anything.


class LocalWhisper:
    """faster-whisper, decoding exactly as production does."""

    def __init__(self, label: str, size: str, device: str, ctype: str, beam: int):
        self.label = label
        self.size, self.device, self.ctype, self.beam = size, device, ctype, beam
        self.model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(self.size, device=self.device,
                                  compute_type=self.ctype)

    def transcribe(self, wav: Path) -> str:
        segs, _ = self.model.transcribe(
            str(wav), language="en", beam_size=self.beam, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=_COMMAND_PROMPT,
        )
        return " ".join(s.text for s in segs).strip()

    def close(self) -> None:
        self.model = None


class GroqWhisper:
    """One direct POST per clip.

    Deliberately NOT stt_groq.transcribe(). That function is a FALLBACK CHAIN
    — Groq, then Gemini, then local CPU Whisper — so a rate-limited run would
    quietly return Gemini's transcripts and this bench would print them under
    Groq's name and call it a measurement. The whole point here is to learn
    what ONE model does, so failures must surface as failures.

    The corpus is already 16 kHz mono PCM_16, the same shape stt_groq._wav_bytes
    produces, so the file bytes go up untouched.
    """

    def __init__(self, label: str, model: str, prompt: str):
        self.label = label
        self.model = model
        self.prompt = prompt
        self.failures = 0
        # Seconds spent asleep waiting out a 429 during the last transcribe.
        # The caller subtracts it: a rate-limit wait is the BENCH's cost, not
        # the model's, and leaving it in put a 3.7s p95 on a model whose p50
        # is under half a second. A latency figure nobody can trust is worse
        # than no latency figure, because this one gets quoted later.
        self.last_wait_s = 0.0
        self._client = None

    def load(self) -> None:
        import httpx

        from backend.server.config import settings

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self._key = settings.groq_api_key
        # Far longer than production's ~3s read timeout, on purpose. In
        # production a slow response SHOULD give up and let Gemini answer; in
        # a bench, giving up would score a timeout as a wrong transcript and
        # understate the model's accuracy. We wait, and report the latency —
        # p95 is where a response too slow for production shows up.
        self._client = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=60.0,
                                                          write=60.0, pool=60.0))

    def transcribe(self, wav: Path) -> str:
        data = {"model": self.model, "language": "en",
                "temperature": "0", "response_format": "json"}
        if self.prompt:
            data["prompt"] = self.prompt

        # Retry ONLY on 429. A rate limit is the one failure that is both
        # likely (30 clips back-to-back) and silently score-destroying, since
        # a refused request is indistinguishable from a bad transcript once
        # it lands in the WER column.
        self.last_wait_s = 0.0
        for attempt in range(4):
            r = self._client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (wav.name, wav.read_bytes(), "audio/wav")},
                data=data,
            )
            if r.status_code == 429 and attempt < 3:
                wait = min(float(r.headers.get("retry-after") or 2 ** attempt), 30.0)
                print(f"      rate limited, waiting {wait:.0f}s…", flush=True)
                time.sleep(wait)
                self.last_wait_s += wait
                continue
            break

        if r.status_code != 200:
            self.failures += 1
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        return (r.json().get("text") or "").strip()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def build_engines(args) -> list:
    """Every engine the run asks for, unfiltered ones dropped by label."""
    engines: list = [LocalWhisper(label, size, device, ctype, args.beam)
                     for label, size, device, ctype in LOCAL_CONFIGS]
    if not args.no_groq:
        engines += [GroqWhisper(label, model, args.groq_prompt)
                    for label, model in GROQ_MODELS]
    if args.configs:
        engines = [e for e in engines
                   if any(f.lower() in e.label.lower() for f in args.configs)]
    return engines


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
    ap.add_argument("--no-groq", action="store_true",
                    help="local models only — no network, no API quota spent")
    # stt_groq ships with GROQ_STT_PROMPT empty, on measurement: the proper-noun
    # list derailed quiet clips, once out of English entirely. Its docstring
    # names the flip worth retrying in a noisier room; this is that flip.
    ap.add_argument("--groq-prompt", default="",
                    help="bias Groq decoding toward these words, e.g. "
                         "'Onyx, Razorpay, KNSIT, WhatsApp'. Off by default, "
                         "matching production")
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

    rows = []
    for engine in build_engines(args):
        label = engine.label
        try:
            engine.load()
        except Exception as e:
            print(f"{label:20} UNAVAILABLE: {type(e).__name__}: {str(e)[:90]}")
            continue

        errs = ref_words = exact = cmd_ok = collapsed = 0
        times: list[float] = []
        mistakes: list[tuple[str, str, str]] = []

        for pid, truth, wav in items:
            t0 = time.perf_counter()
            try:
                hyp = engine.transcribe(wav)
            except Exception as e:
                hyp = f"<{type(e).__name__}: {str(e)[:60]}>"
            elapsed = time.perf_counter() - t0 - getattr(engine, "last_wait_s", 0.0)
            times.append(elapsed * 1000)

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
        # A refused request lands in the WER column looking exactly like a bad
        # transcript, so say plainly that the number is not an accuracy figure.
        failed = getattr(engine, "failures", 0)
        if failed:
            print(f"      ⚠ {failed}/{n} requests FAILED — these scored as errors. "
                  f"This row is not a measurement of accuracy.")
        if args.show_errors and mistakes:
            for pid, truth, hyp in mistakes:
                print(f"      {pid:16} said {truth!r}\n"
                      f"      {'':16} got  {hyp!r}")
        engine.close()

    if not rows:
        return 1

    print("\n— ranked by CMD (does the assistant do the right thing) —")
    for label, w, e, c, p50, p95 in sorted(rows, key=lambda r: (-r[3], r[4])):
        print(f"  {label:20} CMD {c:5.1%}  EXACT {e:5.1%}  WER {w:5.1%}  p50 {p50:5.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
