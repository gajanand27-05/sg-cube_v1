"""Speech-to-text via Gemini. Drop-in replacement for stt_whisper.

Deliberately exposes the SAME signatures stt_whisper does, so trigger.py and
voice.py change one import line each and the rule engine, the content gate,
the capture archive, and the five agents are untouched.

SYNCHRONOUS on purpose. Whisper's transcribe_array blocked, and trigger.py
calls it without await from inside _handle_wake_async — which itself runs on
the turn worker thread. Making this async would change the call shape at the
one site the whole design is trying not to disturb.

Structured output rather than a prose prompt. Whisper was steered with an
initial_prompt, and when the audio gave it nothing to work with it emitted
that prompt back as a transcript — fluent, confident, and dispatched to the
router as a command. A response_schema makes that failure structurally
impossible: the model fills a boolean and a string, and speech_detected=false
maps to "", which the existing content gate already rejects. This is why
is_prompt_echo() is not ported.
"""
from __future__ import annotations

import json
import logging
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
from google import genai
from google.genai import types

from backend.ai_modules.llm.key_pool import pool
from backend.server.config import settings

log = logging.getLogger(__name__)


class SttUnavailable(RuntimeError):
    """STT could not run at all. `kind` decides what the assistant says.

    Distinct kinds because they must not sound alike. The interrupt bug fixed
    in 59eb62f was exactly this failure: two different situations produced one
    message, so a user who had interrupted was told they had been misheard.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


# Biases recognition toward the command vocabulary — the legitimate version of
# what Whisper's initial_prompt was doing. Safe here in a way it was not there:
# the model answers into a schema, so this text has no field to leak into.
_SYSTEM_INSTRUCTION = (
    "You are a speech-to-text engine for a desktop voice assistant named Onyx. "
    "Transcribe the user's spoken command verbatim in English. "
    "Do not translate, answer, summarise, explain, or add punctuation the "
    "speaker did not imply. Return only what was said.\n"
    "Likely vocabulary: onyx, open, close, notepad, chrome, firefox, vscode, "
    "spotify, whatsapp, discord, telegram, calculator, explorer, command "
    "prompt, lock the screen, volume, brightness, stop, cancel, never mind, "
    "what time is it, weather, news, remind me, translate, summarize, "
    "read the screen, play on youtube, search.\n"
    "If the audio contains no intelligible speech — silence, noise, breathing, "
    "a cough — set speech_detected to false and transcript to an empty string. "
    "Never guess at words that are not there."
)

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING"},
        "speech_detected": {"type": "BOOLEAN"},
    },
    "required": ["transcript", "speech_detected"],
}

_EMPTY: dict = {
    "text": "",
    "language": "en",
    "language_probability": 1.0,
    "duration_sec": 0.0,
}

_clients: dict[int, genai.Client] = {}


# Park reason (key_pool.classify) -> SttUnavailable.kind. Substring match
# because classify() embeds detail: "transient (ConnectionError)".
_PARK_REASON_KINDS: tuple[tuple[str, str], ...] = (
    ("daily quota", "quota"),
    ("rate limit", "quota"),
    ("invalid or unauthorised", "no_key"),
    ("transient", "no_network"),
)


def _kind_from_parks(statuses) -> str:
    """Why the pool is empty, in the vocabulary the assistant speaks in.

    Hardcoding "quota" here was a two-situations-one-sentence bug — the exact
    shape 59eb62f fixed — one layer above the one SttUnavailable.kind exists
    to prevent. With the network down, three offline turns park all three keys
    as `transient`; the fourth turn never reaches the network at all and the
    user was told they had spent a daily quota. Worse for a bad key: the park
    is permanent, so turn 1 said "API key isn't set" and every turn after it
    said "daily limit", forever. The user stops fixing the real problem.

    The pool already knows: report the reason of the key that frees up
    SOONEST, since that key is the one recovery actually hinges on.
    """
    parked = [s for s in statuses if s.configured and s.parked_until is not None]
    if not parked:
        # Unreachable via acquire() — configured and unparked means acquire()
        # would have returned it. Keep the historical answer for a racing read.
        return "quota"
    soonest = min(parked, key=lambda s: s.parked_until)
    reason = (soonest.reason or "").lower()
    for needle, kind in _PARK_REASON_KINDS:
        if needle in reason:
            return kind
    return "no_network"


def _client_for() -> tuple[int, genai.Client]:
    """(slot, client) from the shared pool. Raises SttUnavailable if none."""
    got = pool.acquire()
    if got is None:
        statuses = pool.status()
        if not any(s.configured for s in statuses):
            raise SttUnavailable("no_key", "no Gemini API key is configured")
        kind = _kind_from_parks(statuses)
        reasons = ", ".join(
            f"{s.slot}:{s.reason or 'parked'}" for s in statuses if s.configured)
        raise SttUnavailable(
            kind, f"every Gemini API key is parked ({reasons})")
    slot, key = got
    client = _clients.get(slot)
    if client is None:
        client = genai.Client(api_key=key)
        _clients[slot] = client
    return slot, client


def encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 in [-1, 1] (what trigger.py passes) -> 16-bit mono PCM WAV.

    Clamps before casting. float32 1.0 * 32768 is 32768, which overflows int16
    and WRAPS to -32768 — turning the single loudest sample of a clip into the
    single quietest. numpy does that silently.
    """
    arr = np.asarray(audio)
    if arr.dtype != np.int16:
        arr = np.clip(arr.astype(np.float32) * 32768.0, -32768, 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())
    return buf.getvalue()


def _classify_transport(exc: Exception) -> str:
    """Which SttUnavailable.kind a failed call maps to."""
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429 or "resource_exhausted" in text or "429" in text:
        return "quota"
    if code in (400, 401, 403) or "api key not valid" in text:
        return "no_key"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return "no_network"
    for needle in ("getaddrinfo", "name resolution", "connection", "unreachable",
                   "timed out", "timeout", "ssl"):
        if needle in text:
            return "no_network"
    return "no_network"


def _parse(raw: str | None) -> str:
    """Schema payload -> transcript. Anything unparseable becomes "".

    Empty is the safe value: the content gate already rejects it, whereas a
    half-parsed body could reach the router as a command.
    """
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("stt_gemini: unparseable response body %r", raw[:200])
        return ""
    if not isinstance(data, dict) or not data.get("speech_detected"):
        return ""
    transcript = data.get("transcript")
    return transcript.strip() if isinstance(transcript, str) else ""


def transcribe_array(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """Transcribe a captured command. Same contract as stt_whisper's."""
    arr = np.asarray(audio)
    if arr.size == 0:
        return dict(_EMPTY)
    duration = round(len(arr) / float(sample_rate), 3)

    wav_bytes = encode_wav(arr, sample_rate)

    # One attempt per key. report_failure parks the spent slot, so the next
    # _client_for() hands back a different one and the loop rotates; when all
    # are parked _client_for raises SttUnavailable with the real reason.
    # Bounded by the pool size — three keys, three tries, no retry of a key
    # that just failed.
    #
    # This used to acquire once and give up, so a 429 on key 1 ended the turn
    # while keys 2 and 3 sat healthy. GeminiBackend re-acquires on every retry
    # attempt; this path did not, and STT_BACKEND=gemini puts it on every turn.
    for _ in range(3):
        slot, client = _client_for()
        try:
            resp = client.models.generate_content(
                model=settings.gemini_model,
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    temperature=0.0,
                ),
            )
            break
        except Exception as e:
            pool.report_failure(slot, e)
            kind = _classify_transport(e)
            log.warning("stt_gemini: %s on key %d: %s", kind, slot, e)
            last_error, last_kind = e, kind
    else:
        raise SttUnavailable(last_kind, str(last_error)) from last_error

    pool.report_success(slot)
    return {
        "text": _parse(getattr(resp, "text", None)),
        "language": "en",
        "language_probability": 1.0,
        "duration_sec": duration,
    }


def transcribe(audio_path: str | Path) -> dict:
    """Transcribe a WAV file. Same contract as stt_whisper's."""
    with wave.open(str(audio_path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return transcribe_array(arr, rate)
