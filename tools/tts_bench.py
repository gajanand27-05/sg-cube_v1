"""Measure whether Onyx's SPEECH can actually be understood.

    .venv/Scripts/python.exe tools/tts_bench.py

Input accuracy has a number (tools/stt_bench.py). Output accuracy had none at
all, so "make the voice better" could only ever be answered by taste — and
taste is how a regression ships.

This synthesises each phrase with Piper, transcribes the result with the same
Whisper model the assistant listens with, and scores the round trip. It is a
proxy, not a listening test: Whisper is more tolerant of robotic prosody than
a person and less tolerant of some noise. What it does catch is the failure
that matters most — words that come out WRONG rather than merely flat. A
phrase Whisper cannot recover is one a human will mishear too.

Phrases are chosen to stress the places TTS actually breaks:
  * syllabic consonants (button, bottle, little) -- the voice's phoneme map
    has no U+0329, so espeak emits it and Piper drops it
  * digits, times, units, currency -- normalisation, not pronunciation
  * proper nouns and acronyms the assistant says constantly
  * the assistant's own stock sentences

Compare configurations by editing CONFIGS. Read the notes there first — two
plausible-sounding changes have already been measured and rejected.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import numpy as np

# NOTE: stt_bench rebinds sys.stdout to a UTF-8 wrapper when imported below.
# Wrapping it here too closes the first wrapper as soon as it is collected,
# and every later print raises "I/O operation on closed file". One wrapper.

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from backend.ai_modules.speech.stt_manager import _register_cuda_libs  # noqa: E402

_register_cuda_libs()

import stt_bench as B  # noqa: E402  (normalize / wer / route)

PHRASES = [
    # syllabic consonants — the known phoneme-map gap
    "Press the button to open the bottle.",
    "A little kitten sat on the cotton curtain.",
    "The rhythm of the prism is certain.",
    # numbers, times, units — normalisation rather than pronunciation
    "It is 7:43 PM on Friday, 21 August 2026.",
    "The volume is set to 50 percent.",
    "That costs $1,299.99 including tax.",
    "CPU usage is 12.5 percent across 8 cores.",
    # names and acronyms the assistant says constantly
    "Onyx opened Notepad and Google Chrome.",
    "Jensen Huang is the CEO of NVIDIA.",
    "I could not reach Ollama, so the verifier is unavailable.",
    # the assistant's own stock sentences
    "I need your permission to close app. Should I proceed?",
    "I'm not sure what to do with that, could you say it again?",
    "Mumbai, India: mainly clear, 27 degrees Celsius.",
]

# (label, length_scale, respell). Two things this has already settled:
#
#   * SLOWER IS NOT CLEARER. length_scale 1.15 doubled word error
#     (9.2% -> 18.3%) and rendered "NVIDIA" as 'ee-a-f-f-n-b-e-a'.
#   * A PRONUNCIATION DICTIONARY did not help. Respelling the words the voice
#     mangles ("onyx" -> "on ix", "huang" -> "hwang") made WER worse
#     (10.1% -> 11.0%) and produced 'On Roman 9' and 'Jensen8rank'. Reverted.
#
# Also learned the hard way: this pipeline is NON-DETERMINISTIC. "Notepad"
# came back 'note, add' on one run and 'notepad' on the next from identical
# input, so 13 phrases cannot separate 10% from 11%. Before trusting a
# comparison here, add phrases and repeat each config.
CONFIGS = [
    ("default", 1.0, False),
]


def synth(text: str, length_scale: float, respell: bool = True) -> tuple[np.ndarray, int]:
    from backend.ai_modules.speech import tts_piper

    voice = tts_piper._get_voice()
    try:
        voice.config.length_scale = length_scale
    except Exception:
        pass
    # `respell` exists for testing a pronunciation dictionary. There is none
    # in production: one was tried and reverted, see CONFIGS.
    spoken = text
    chunks = list(voice.synthesize(spoken))
    if not chunks:
        return np.zeros(0, dtype=np.int16), 22050
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    return audio, chunks[0].sample_rate


def resample_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    """Whisper wants 16 kHz; Piper emits 22.05 kHz."""
    if rate == 16000 or audio.size == 0:
        return audio.astype(np.float32) / 32768.0
    n_out = int(round(audio.size * 16000 / rate))
    idx = np.linspace(0, audio.size - 1, n_out)
    return np.interp(idx, np.arange(audio.size), audio).astype(np.float32) / 32768.0


def main() -> int:
    from faster_whisper import WhisperModel
    from backend.ai_modules.speech.stt_whisper import _COMMAND_PROMPT

    model = WhisperModel("medium", device="cuda", compute_type="float16")
    print(f"{len(PHRASES)} phrases, Piper -> Whisper(medium) round trip\n")

    rows = []
    for label, scale, respell in CONFIGS:
        errs = ref_words = exact = 0
        times: list[float] = []
        misses: list[tuple[str, str]] = []

        for text in PHRASES:
            t0 = time.perf_counter()
            audio, rate = synth(text, scale, respell)
            times.append((time.perf_counter() - t0) * 1000)
            if audio.size == 0:
                misses.append((text, "<no audio>"))
                errs += len(B.normalize(text).split())
                ref_words += len(B.normalize(text).split())
                continue

            segs, _ = model.transcribe(
                resample_16k(audio, rate), language="en", beam_size=1,
                vad_filter=False, initial_prompt=_COMMAND_PROMPT)
            heard = " ".join(s.text for s in segs).strip()

            d, n = B.wer(text, heard)
            errs += d
            ref_words += n
            if B.normalize(text) == B.normalize(heard):
                exact += 1
            else:
                misses.append((text, heard))

        n = len(PHRASES)
        rows.append((label, errs / max(ref_words, 1), exact / n,
                     statistics.median(times)))
        print(f"{label:16} WER {errs/max(ref_words,1):5.1%}  "
              f"EXACT {exact/n:5.1%}  synth p50 {statistics.median(times):5.0f}ms")
        for text, heard in misses:
            print(f"      said  {text!r}")
            print(f"      heard {heard!r}")
        print()

    print("— ranked by WER (lower is better) —")
    for label, wer, exact, p50 in sorted(rows, key=lambda r: r[1]):
        print(f"  {label:16} WER {wer:5.1%}  EXACT {exact:5.1%}  p50 {p50:5.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
