"""Speech-to-text via Groq whisper-large-v3-turbo. Same contract as stt_gemini.

Why this is now the primary, measured rather than assumed:

  * QUOTA. Gemini STT calls generate_content on settings.gemini_model, which
    is the SAME free-tier budget the planner spends (20/day/key x 3 = 60).
    Measured over this install's own archive: a mean of 49 captures/day and a
    worst day of 123 — 205% of the day's entire budget spent on HEARING,
    before the planner said a word. Groq's free tier is 2,000/day, which
    covers the worst day 16x over.

  * ACCURACY. Benched both Groq models against Gemini's stored transcripts on
    30 real captures:

        model                     WER    EXACT   CMD     p50     p95
        whisper-large-v3         97.6%   13.3%  93.3%   385ms   541ms
        whisper-large-v3-turbo   91.5%   20.0%  93.3%   378ms   516ms

    Those WER figures look terrible because the REFERENCE is Gemini, which is
    itself wrong on these clips — the metric is agreement, not accuracy. The
    qualitative read is the opposite and is what decided it: on a capture
    Gemini heard as 'open whatsapp', v3 answered 'Thank you for watching.' —
    the exact YouTube-outro hallucination the content gate exists to filter —
    while turbo answered 'Can you open WhatsApp?'. Where both Groq models
    agreed with each other against Gemini, they were right.

    And it fixes the failures that started this: on audio Gemini transcribed
    as 'Onyx pull out info about Razor Pay build a ton.' and 'Builder thong,
    which is conducting by reserve pay.', turbo returns 'Onyx, pull out info
    about Razorpay Buildathon' and 'Buildathon which is conducting by
    Razorpay'.

Gemini stays as the fallback on any error, so a Groq outage costs a slower
turn rather than a dead one. See _DEFAULT_PROMPT for why the proper-noun
prompt is off by default despite being the obvious thing to add.
"""
from __future__ import annotations

import io
import logging
import wave

import numpy as np

from backend.ai_modules.speech.stt_gemini import SttUnavailable, _EMPTY
from backend.server.config import settings

log = logging.getLogger(__name__)

_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Whisper's `prompt` biases decoding toward these words. OFF by default, on
# measurement — it was the first thing tried and it does more harm than good:
#
#   * It does not buy the proper nouns. turbo already transcribes "Razorpay
#     Buildathon" from audio Gemini heard as "Razor Pay build a ton" and
#     "reserve pay", WITH OR WITHOUT the prompt. That was the entire reason
#     for adding it.
#   * On quiet, low-information clips it DERAILS, including out of English.
#     Reproduced twice on the same capture:
#         prompt + language=en -> 'Var á ámurinn við í ætarið þeim?'
#         language=en only     -> "What's wrong with you?"
#     A comma-separated proper-noun list is unusual text, and with little
#     acoustic evidence to anchor on the decoder follows it somewhere strange.
#   * Across 20 captures the difference is inside the noise: WER 93.4% vs
#     95.4%, EXACT 10% vs 15%, CMD 100% either way.
#
# Kept as a setting because it did win one real case ("Razorpay" vs "Res...")
# and a noisier room may shift the balance. One flip to test:
#     GROQ_STT_PROMPT="Onyx, Razorpay, KNSIT, WhatsApp, Spotify, YouTube"
_DEFAULT_PROMPT = "Onyx, Razorpay, KNSIT, WhatsApp, Spotify, YouTube, Notepad"


def _wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 [-1, 1] (what trigger.py passes) -> 16-bit mono PCM WAV."""
    arr = np.asarray(audio)
    if arr.dtype != np.int16:
        arr = np.clip(arr * 32768.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(arr.tobytes())
    return buf.getvalue()


def _payload() -> dict:
    """Request fields. `prompt` is omitted entirely when unset — sending an
    empty string is not the same as sending nothing."""
    data = {"model": settings.groq_stt_model, "language": "en",
            "temperature": "0", "response_format": "json"}
    prompt = (settings.groq_stt_prompt or "").strip()
    if prompt:
        data["prompt"] = prompt
    return data


def _kind_for(status: int) -> str:
    """Which SttUnavailable.kind an HTTP failure maps to.

    Only used when the Gemini fallback ALSO fails — the kinds must stay
    distinct because the assistant speaks a different line for each.
    """
    if status == 429:
        return "quota"
    if status in (401, 403):
        return "no_key"
    return "no_network"


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Transcribe a captured command. Falls back to Gemini on any failure."""
    arr = np.asarray(audio)
    if arr.size == 0:
        return dict(_EMPTY)

    if not settings.groq_api_key:
        raise SttUnavailable("no_key", "GROQ_API_KEY is not set")

    import httpx

    try:
        with httpx.Client(timeout=settings.groq_timeout_s) as client:
            r = client.post(
                _URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": ("capture.wav", _wav_bytes(arr, sample_rate), "audio/wav")},
                data=_payload(),
            )
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        text = (r.json().get("text") or "").strip()
    except Exception as e:
        # Gemini is the fallback, not the primary, so a Groq outage costs a
        # slower turn rather than a dead one. Logged at WARNING because a
        # silent demotion to the 60/day budget is exactly the kind of thing
        # that reappears later as "why did it stop answering at lunchtime".
        log.warning("stt_groq failed (%s); falling back to Gemini", e)
        from backend.ai_modules.speech import stt_gemini

        return stt_gemini.transcribe_array(arr, sample_rate)

    if not text:
        log.info("stt_groq: empty transcript")
    return {
        "text": text,
        "language": "en",
        "language_probability": 1.0,
        "duration_sec": round(len(arr) / float(sample_rate), 3),
    }


def transcribe(audio_path) -> dict:
    """Transcribe a WAV file. Same contract as stt_gemini's."""
    import soundfile as sf

    arr, rate = sf.read(str(audio_path), dtype="float32")
    if arr.ndim > 1:
        arr = arr[:, 0]
    return transcribe_array(arr, rate)
