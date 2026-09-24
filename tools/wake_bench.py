"""Wake-word false-fire rate and miss rate, measured offline.

Two controlled tests, because waiting for real use gives you one noisy
afternoon and no control group:

  FALSE FIRES  replay room audio that contains NO wake word; count triggers.
               Reported per hour, so corpora of different lengths compare.

  MISSES       replay clips that each DO contain a spoken wake word; count
               the ones that fail to trigger.

Both replay through the SAME functions the live listener uses
(feed_wake_chunk / wake_phrase_present / WAKE_BLOCKSIZE / the RMS floor), so
this measures production rather than a re-implementation of it. That matters
more than usual here: the whole point is a before/after comparison, and a
bench that drifts from production compares two things that are not the
alternatives being considered.

    .venv/Scripts/python.exe tools/wake_bench.py --false-fires path/to/room/
    .venv/Scripts/python.exe tools/wake_bench.py --misses path/to/onyx_clips/
    .venv/Scripts/python.exe tools/wake_bench.py --false-fires room.wav --engine vosk

Recording the corpora:
  room audio  - an hour of normal life near the mic (YouTube, music, talking)
                with nobody ever saying the wake word. One long wav is fine.
  onyx clips  - 20-30 short wavs, one spoken "Onyx" each, deliberately varied:
                close / across the room / turned away / over background audio.
                tools/record_clip.py writes the right format.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import logging
logging.disable(logging.WARNING)

import numpy as np
import soundfile as sf

from backend.daemon import wake_word as ww

SAMPLE_RATE = 16000


# ── engines ──────────────────────────────────────────────────────────────

class VoskEngine:
    """Exactly what ships today: grammar [wake_phrase, "[unk]"], token match,
    no confidence check, RMS floor in front."""

    name = "vosk"

    def __init__(self, wake_phrase: str = "onyx"):
        from vosk import Model, KaldiRecognizer, SetLogLevel

        SetLogLevel(-1)
        model_dir = ROOT / "backend" / "ai_modules" / "speech" / "vosk_models"
        picks = sorted(model_dir.glob("vosk-model-*"))
        if not picks:
            raise SystemExit(f"no vosk model under {model_dir}")
        self._model = Model(str(picks[0]))
        self._KaldiRecognizer = KaldiRecognizer
        self.wake_phrase = wake_phrase
        self.detail = picks[0].name
        self.reset()

    def reset(self) -> None:
        self._rec = self._KaldiRecognizer(
            self._model, SAMPLE_RATE, json.dumps([self.wake_phrase, "[unk]"]))

    def feed(self, chunk: np.ndarray) -> bool:
        """One 125ms chunk. True == the live listener would have woken."""
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) if chunk.size else 0.0
        if rms <= ww._VAD_RMS_THRESHOLD:
            return False
        partial = ww.feed_wake_chunk(self._rec, chunk.tobytes())
        if ww.wake_phrase_present(partial, self.wake_phrase):
            self._rec.Reset()      # production resets on a wake
            return True
        return False


class OpenWakeWordEngine:
    """openWakeWord, if a model for this phrase exists on disk."""

    name = "openwakeword"

    def __init__(self, wake_phrase: str = "onyx", model_path: str | None = None):
        try:
            from openwakeword.model import Model
        except ImportError as e:
            raise SystemExit(
                "openwakeword is not installed.\n"
                "  uv sync --group bench\n"
                "and supply --oww-model with a trained 'onyx' model — the "
                "shipped pretrained set does not include it."
            ) from e
        # Accepts a PRETRAINED NAME ("hey_jarvis") or a path to a trained
        # model. There is no pretrained "onyx", so a like-for-like comparison
        # needs training; a pretrained name still measures the ENGINE's
        # false-accept behaviour on the same audio, which is the half that
        # does not need recorded positives.
        if not model_path:
            raise SystemExit(
                "--oww-model is required: a pretrained name (hey_jarvis, "
                "alexa, hey_mycroft, hey_rhasspy) or a path to a trained model.")
        if not os.path.exists(model_path):
            # A pretrained NAME. Its files are release assets, not part of the
            # wheel, so a fresh venv has none of them; this fetches only what
            # is missing (plus the shared melspectrogram/embedding models).
            from openwakeword.utils import download_models

            download_models(model_names=[model_path])
        self._m = Model(wakeword_models=[model_path], inference_framework="onnx")
        self.wake_phrase = wake_phrase
        self.detail = os.path.basename(model_path)
        self._threshold = float(os.environ.get("OWW_THRESHOLD", "0.5"))

    def reset(self) -> None:
        try:
            self._m.reset()
        except Exception:
            pass

    def feed(self, chunk: np.ndarray) -> bool:
        scores = self._m.predict(chunk)
        hit = any(v >= self._threshold for v in scores.values())
        if hit:
            self.reset()
        return hit


def build_engine(name: str, wake_phrase: str, oww_model: str | None):
    if name == "vosk":
        return VoskEngine(wake_phrase)
    if name == "openwakeword":
        return OpenWakeWordEngine(wake_phrase, oww_model)
    raise SystemExit(f"unknown engine {name!r}")


# ── replay ───────────────────────────────────────────────────────────────

def _wavs(target: str) -> list[Path]:
    p = Path(target)
    if p.is_dir():
        return sorted(p.glob("*.wav"))
    if p.is_file():
        return [p]
    hits = sorted(Path(x) for x in glob.glob(target))
    if not hits:
        raise SystemExit(f"no wav files at {target!r}")
    return hits


def _chunks(wav: Path):
    x, sr = sf.read(str(wav), dtype="int16")
    if x.ndim > 1:
        x = x[:, 0]
    if sr != SAMPLE_RATE:
        raise SystemExit(f"{wav.name}: expected {SAMPLE_RATE}Hz, got {sr}")
    n = ww.WAKE_BLOCKSIZE
    for i in range(0, len(x) - n + 1, n):
        yield x[i:i + n]
    return


def replay(engine, wav: Path) -> tuple[int, float]:
    """(fires, seconds). Engine state is reset per file."""
    engine.reset()
    fires = 0
    samples = 0
    for chunk in _chunks(wav):
        samples += len(chunk)
        if engine.feed(chunk):
            fires += 1
    return fires, samples / SAMPLE_RATE


def run_false_fires(engine, target: str) -> None:
    wavs = _wavs(target)
    total_fires = 0
    total_s = 0.0
    worst: list[tuple[str, int, float]] = []
    for wav in wavs:
        fires, secs = replay(engine, wav)
        total_fires += fires
        total_s += secs
        if fires:
            worst.append((wav.name, fires, secs))

    hours = total_s / 3600
    print(f"\n── FALSE FIRES · {engine.name} ({engine.detail})")
    print(f"  corpus          : {len(wavs)} files, {total_s/60:.1f} min")
    print(f"  false fires     : {total_fires}")
    print(f"  per hour        : {total_fires / hours:.1f}" if hours else "  per hour: n/a")
    if worst:
        print(f"  files that fired: {len(worst)}/{len(wavs)}")
        for name, f, s in sorted(worst, key=lambda r: -r[1])[:10]:
            print(f"      {name:34} {f} fire(s) in {s:.1f}s")


def run_misses(engine, target: str) -> None:
    wavs = _wavs(target)
    missed = []
    hit = 0
    for wav in wavs:
        fires, secs = replay(engine, wav)
        if fires:
            hit += 1
        else:
            missed.append(wav.name)
    n = len(wavs)
    print(f"\n── MISSES · {engine.name} ({engine.detail})")
    print(f"  clips           : {n}")
    print(f"  detected        : {hit}")
    print(f"  missed          : {len(missed)}  ({len(missed)/n*100:.1f}% miss rate)" if n else "")
    for name in missed[:15]:
        print(f"      MISS {name}")
    if len(missed) > 15:
        print(f"      ... +{len(missed)-15} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--false-fires", metavar="PATH",
                    help="wav/dir of room audio containing NO wake word")
    ap.add_argument("--misses", metavar="PATH",
                    help="dir of clips that each DO contain the wake word")
    ap.add_argument("--engine", default="vosk", choices=["vosk", "openwakeword"])
    ap.add_argument("--wake-phrase", default=None,
                    help="default: whatever .env configures")
    ap.add_argument("--oww-model", help="path to a trained openWakeWord model")
    args = ap.parse_args()

    if not args.false_fires and not args.misses:
        ap.error("give --false-fires and/or --misses")

    from backend.server.config import settings
    phrase = (args.wake_phrase or getattr(settings, "wake_phrase", "onyx")).lower()

    engine = build_engine(args.engine, phrase, args.oww_model)
    print(f"engine={engine.name} ({engine.detail})  phrase={phrase!r}  "
          f"rms_floor={ww._VAD_RMS_THRESHOLD}  chunk={ww.WAKE_BLOCKSIZE} samples")

    if args.false_fires:
        run_false_fires(engine, args.false_fires)
    if args.misses:
        run_misses(engine, args.misses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
