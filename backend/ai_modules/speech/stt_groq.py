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
import time
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


_network_down_until = 0.0


def _is_network_error(exc: Exception) -> bool:
    """Unreachable network, as opposed to the service saying no.

    The distinction decides whether Gemini is worth trying. A 429 or a 502 is
    Groq's problem and Gemini may well answer; a dead socket means the link is
    down and Gemini will fail the same way, one full timeout later.
    """
    import httpx

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout, httpx.NetworkError)):
        return True
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _note_network_down() -> None:
    """Send the next few commands straight to local.

    Without this, EVERY offline command pays the cloud timeout before local
    even starts. One utterance paying it is a slow answer; every utterance
    paying it is a broken assistant during exactly the outage the local path
    exists for.
    """
    global _network_down_until
    _network_down_until = time.monotonic() + settings.stt_network_down_memo_s
    log.warning("STT: network looks down; routing to local CPU for %.0fs",
                settings.stt_network_down_memo_s)


def _offline() -> bool:
    return time.monotonic() < _network_down_until


def _reachable(host: str = "api.groq.com", port: int = 443,
               timeout: float = 1.5) -> bool:
    """Can we open a socket to the STT host?

    A bare TCP connect — no TLS handshake, no HTTP request, no key, so it
    costs no quota on either provider. That is the point: a probe that spent
    requests to find out whether we can spend requests would be self-defeating
    at 2,880 checks a day.
    """
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def connectivity_loop(interval_s: float = 30.0) -> None:
    """Set the offline memo BEFORE a command needs it.

    Without this the first utterance of an outage discovers the problem the
    expensive way, by waiting out a connect timeout. The probe is cheap and
    runs on its own thread, so by the time someone says "volume up" the route
    to local is already chosen.
    """
    global _network_down_until
    while True:
        try:
            if _reachable():
                if _offline():
                    log.warning("STT: network is back")
                    _network_down_until = 0.0
            else:
                # REFRESH every probe, not only on the transition. The memo
                # and the probe interval are both 30s, so a memo set once
                # would lapse just before the next probe and hand the timeout
                # back to whoever spoke in that gap. Held to twice the
                # interval so a late probe cannot open a hole either.
                was_offline = _offline()
                _network_down_until = time.monotonic() + max(
                    settings.stt_network_down_memo_s, interval_s * 2)
                if not was_offline:
                    log.warning("STT: connectivity probe failed; routing to local")
        except Exception as e:          # a monitor must never kill the daemon
            log.debug("connectivity probe error: %s", e)
        time.sleep(interval_s)


def start_connectivity_monitor() -> None:
    import threading

    threading.Thread(target=connectivity_loop, name="stt-connectivity",
                     daemon=True).start()


def _local(arr: np.ndarray, sample_rate: int) -> dict:
    """Last resort: CPU Whisper. Raises SttUnavailable only if it also fails,
    so "I can't reach the network" is never said over a working transcript."""
    from backend.ai_modules.speech import stt_whisper

    t0 = time.perf_counter()
    out = stt_whisper.transcribe_array_cpu(arr, sample_rate)
    log.warning("STT: answered offline on CPU in %.0fms", (time.perf_counter() - t0) * 1000)
    return out


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Groq -> Gemini -> local CPU, skipping rungs that cannot help.

    The ordering matters more than the rungs. A naive chain makes an offline
    'volume up' wait out BOTH cloud timeouts before the local model starts,
    which is 10-20s of silence in precisely the situation the local model was
    added for.
    """
    global _network_down_until
    arr = np.asarray(audio)
    if arr.size == 0:
        return dict(_EMPTY)

    if _offline():
        return _local(arr, sample_rate)

    if not settings.groq_api_key:
        raise SttUnavailable("no_key", "GROQ_API_KEY is not set")

    import httpx

    try:
        # Split, not one number. CONNECT is the offline case and should give
        # up almost immediately — a dead link cannot be rescued by waiting.
        # READ is the slow-upload / busy-server case, where the request is
        # actually in flight and worth waiting on.
        timeout = httpx.Timeout(
            connect=settings.groq_connect_timeout_s,
            read=settings.groq_timeout_s,
            write=settings.groq_timeout_s,
            pool=settings.groq_timeout_s,
        )
        with httpx.Client(timeout=timeout) as client:
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
        if _is_network_error(e):
            # Skip Gemini entirely — same network, same outcome, one more
            # timeout of silence.
            log.warning("stt_groq: network error (%s); going straight to local", e)
            _note_network_down()
            return _local(arr, sample_rate)

        log.warning("stt_groq failed (%s); falling back to Gemini", e)
        from backend.ai_modules.speech import stt_gemini

        try:
            return stt_gemini.transcribe_array(arr, sample_rate)
        except SttUnavailable:
            raise
        except Exception as ge:
            if _is_network_error(ge):
                _note_network_down()
            log.warning("Gemini fallback also failed (%s); going local", ge)
            return _local(arr, sample_rate)

    # A cloud answer means the link is back; stop short-circuiting to local.
    # The model is NOT released here. It is preloaded at daemon start and kept
    # resident on purpose: dropping it would make the next outage pay the cold
    # load again, which is the whole cost this preload exists to remove.
    if _network_down_until:
        _network_down_until = 0.0

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
