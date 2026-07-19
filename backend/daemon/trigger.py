import asyncio
import logging
import tempfile
import threading
import uuid
import wave
from pathlib import Path
from typing import Any, Callable, Optional, AsyncGenerator

import numpy as np
import sounddevice as sd

from backend.ai_modules.speech.stt_whisper import transcribe_array, transcribe_stream
from backend.ai_modules.speech.tts_piper import speak, stop_speech, speak_stream, is_speaking
from backend.ai_modules.speech.tts_queue import get_sentence_queue
from backend.core.agents.commander import commander
from backend.core.brain import brain, BrainRequest, BrainResponse
from backend.core.events import get_bus, Priority
from backend.core.state import AssistantState, manager as state_manager
from backend.core.dogfooding import ledger as dogfooding_ledger
from backend.core.latency import TurnLatency, ledger as latency_ledger
from backend.daemon.ui_events import (
    CommandTranscribed,
    Executed,
    SpeechInterruptedEvent,
    SpokenResponse,
    TriggerError,
    WakeHeard,
)
from backend.daemon.ui_events import STTPartialEvent, TTSChunkEvent

log = logging.getLogger(__name__)

EmitFn = Callable[[Any], None]

# Default daemon user ID — should be overridden per-session in production
DEFAULT_DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"

SAMPLE_RATE = 16000
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


def _play_chime() -> None:
    """Play assets/chime.wav if present; fall back to a generated sine tone."""
    chime = ASSETS_DIR / "chime.wav"
    if chime.exists():
        try:
            with wave.open(str(chime), "rb") as w:
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
            sd.play(audio, samplerate=rate, blocking=True)
            sd.wait()
            return
        except Exception:
            pass
    rate = 44100
    duration = 0.15
    freq = 880
    t = np.linspace(0, duration, int(rate * duration), endpoint=False)
    tone = np.sin(2 * np.pi * freq * t) * 0.30
    fade = int(rate * 0.01)
    tone[:fade] *= np.linspace(0, 1, fade)
    tone[-fade:] *= np.linspace(1, 0, fade)
    tone_i16 = (tone * 32767).astype(np.int16)
    sd.play(tone_i16, samplerate=rate, blocking=True)
    sd.wait()


def _spoken_response(response) -> str:
    """Extract spoken text from BrainResponse."""
    if hasattr(response, 'spoken_text'):
        return response.spoken_text
    # Fallback for legacy format
    if isinstance(response, dict):
        return response.get('spoken_text', response.get('message', 'Done.'))
    return str(response)


def _emit(emit: EmitFn | None, event: Any) -> None:
    if emit is None:
        return
    try:
        emit(event)
    except Exception as e:
        print(f"[ui] emit raised: {e}")


def on_wake_detected(emit: EmitFn | None = None) -> None:
    """Fires the instant the wake phrase is recognised."""
    # Phase C2: Interrupt any in-progress speech immediately
    stop_speech()
    # Phase 4B: drain any queued sentences so they don't resume speaking
    # after the interrupt.
    get_sentence_queue().interrupt()
    commander.interrupt()

    state_manager.transition_to(AssistantState.LISTENING)
    event = WakeHeard(peak=0)
    get_bus().publish(event, priority=Priority.HIGH)
    _emit(emit, event)
    threading.Thread(target=_play_chime, daemon=True).start()


def on_barge_in(rms: float, emit: EmitFn | None = None) -> None:
    """Phase 4A: user spoke while TTS was playing — interrupt and start capturing.

    Same fast-path as on_wake_detected (stop TTS, drain queue, transition
    to LISTENING, chime) plus a distinct SpeechInterruptedEvent so the
    frontend can reflect the "I cut you off" transition, not just a
    neutral wake.
    """
    stop_speech()
    # Phase 4B: drain queued sentences too.
    get_sentence_queue().interrupt()
    commander.interrupt()

    state_manager.transition_to(AssistantState.LISTENING)
    event = SpeechInterruptedEvent(rms=rms)
    get_bus().publish(event, priority=Priority.HIGH)
    _emit(emit, event)
    # Also emit a WakeHeard so the existing "assistant is now listening"
    # UI treatments still fire — barge-in IS a wake, just user-initiated.
    wake_event = WakeHeard(peak=int(rms))
    get_bus().publish(wake_event, priority=Priority.HIGH)
    _emit(emit, wake_event)
    threading.Thread(target=_play_chime, daemon=True).start()


async def _speak_selective(text: str, device_id: Optional[str] = None):
    """Speak locally (streaming) or push audio to a remote device."""
    if device_id:
        from backend.ai_modules.speech.tts_piper import generate_audio
        from backend.server.routes.remote import manager as remote_manager

        audio_bytes, rate = generate_audio(text)
        if audio_bytes:
            await remote_manager.broadcast_bytes_to_device(device_id, audio_bytes)
    else:
        # Use streaming TTS for local playback
        async for _ in speak_stream(text):
            pass


def handle_wake(audio_bytes: bytes, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    """Synchronous entry point for the wake word listener."""
    return asyncio.run(_handle_wake_async(audio_bytes, emit, device_id))


async def _process_and_execute(command: str, peak: int, t0: float, emit: EmitFn | None = None, device_id: Optional[str] = None, turn: Optional[TurnLatency] = None) -> bool:
    request_id = str(uuid.uuid4())[:8]
    if turn is None:
        # Called without a pre-created TurnLatency (proactive, text path) —
        # start one now so /diagnostics/latency has something to show for
        # every turn regardless of entry point.
        turn = TurnLatency(request_id=request_id, mode="voice")
    event = CommandTranscribed(text=command, peak=peak)
    get_bus().publish(event, priority=Priority.HIGH)
    _emit(emit, event)

    if not command:
        state_manager.transition_to(AssistantState.IDLE)
        latency_ledger().record(turn)
        return False

    # Use Brain for unified pipeline
    brain_request = BrainRequest(
        user_id=DEFAULT_DAEMON_USER_ID,
        input_text=command,
        input_mode="voice",
        session_id=None,
        metadata={"peak": peak, "device_id": device_id},
    )
    turn.mark("orchestrator_route")

    # Phase 4B: for local playback, drain sentences via the queue as
    # brain.run_stream produces them — cuts perceived time-to-first-audio.
    # For remote (device_id set) we keep the old collect-then-broadcast
    # path since streaming audio bytes to a remote device would require
    # a different transport protocol than what's currently wired.
    try:
        if device_id:
            response = await brain.run(brain_request)
        else:
            response = await _run_brain_streaming(brain_request, turn=turn)
    except Exception as e:
        try:
            dogfooding_ledger.record_crash()
        except Exception:
            pass
        state_manager.transition_to(AssistantState.ERROR)
        err_event = TriggerError(detail=f"Brain error: {e}")
        get_bus().publish(err_event, priority=Priority.NORMAL)
        _emit(emit, err_event)
        reply = "Sorry, I encountered an error"
        print(f"[ai] Brain error: {e}")
        print(f"[ai] → {reply}")

        state_manager.transition_to(AssistantState.SPEAKING)
        await _speak_selective(reply, device_id)
        spoken_event = SpokenResponse(text=reply)
        get_bus().publish(spoken_event, priority=Priority.NORMAL)
        _emit(emit, spoken_event)
        state_manager.transition_to(AssistantState.IDLE)
        latency_ledger().record(turn)
        return False

    print(f"[ai] response: {response.spoken_text} (latency: {response.latency_ms}ms, tools: {len(response.tool_calls)})")
    
    # Publish execution events for each tool call. `response.tool_calls`
    # is a list[ToolCall] (dataclass, see brain.py) — attribute access,
    # not dict.get. Prefer the ToolResult's own .message string, fall back
    # to str(result) or "ok" when neither is present.
    for tool_call in response.tool_calls:
        res = tool_call.result
        msg = (getattr(res, "message", None) or str(res)) if res is not None else "ok"
        # ToolResult carries a .reason field on blocked/error outcomes;
        # Executed requires the field (no default), so surface it through
        # or fall back to None for successful runs.
        reason = getattr(res, "reason", None) if res is not None else None
        exec_event = Executed(
            command=command,
            status=getattr(tool_call, "status", "success"),
            message=msg,
            reason=reason,
            latency_ms=response.latency_ms,
            confidence=100.0,
            confidence_reason=[]
        )
        get_bus().publish(exec_event, priority=Priority.NORMAL)
        _emit(emit, exec_event)

    reply = response.spoken_text

    # For remote device or non-streaming paths, still call _speak_selective.
    # For local streaming, run_brain_streaming already dispatched the reply
    # sentence-by-sentence — but if the response never yielded any tts_ready
    # chunks (short text, no sentence boundary, tool-call-only turn), we
    # still need to speak the reply here as a fallback.
    if device_id:
        state_manager.transition_to(AssistantState.SPEAKING)
        await _speak_selective(reply, device_id)
    else:
        # If streaming already spoke everything, skip. Otherwise fall back.
        if not get_sentence_queue().spoke_anything and reply.strip():
            state_manager.transition_to(AssistantState.SPEAKING)
            await _speak_selective(reply, device_id)

    spoken_event = SpokenResponse(text=reply)
    get_bus().publish(spoken_event, priority=Priority.NORMAL)
    _emit(emit, spoken_event)

    state_manager.transition_to(AssistantState.IDLE)
    latency_ledger().record(turn)
    return True


async def _run_brain_streaming(brain_request: BrainRequest, turn: Optional[TurnLatency] = None) -> BrainResponse:
    """Phase 4B: drain brain.run_stream() into per-sentence TTS as chunks
    arrive. Returns the final BrainResponse when the stream completes.

    * `tts_ready` → enqueue sentence for TTS immediately.
    * `final`     → capture the BrainResponse to return.
    * Anything else (token/tool_start/tool_end/context_ready) is ignored
      here — token stream is separate WS traffic handled elsewhere.
    """
    sq = get_sentence_queue()
    await sq.start()
    response: Optional[BrainResponse] = None

    try:
        async for chunk in brain.run_stream(brain_request):
            if chunk.type == "tts_ready":
                if turn is not None:
                    turn.mark("first_audio_out")
                # Transition to SPEAKING at first sentence — not eagerly at
                # stream start, since context_ready may fire before any
                # spoken tokens (e.g. for tool-call turns).
                if state_manager.current != AssistantState.SPEAKING:
                    state_manager.transition_to(AssistantState.SPEAKING)
                await sq.enqueue(chunk.content)
            elif chunk.type == "final":
                response = chunk.content
            elif chunk.type == "context_ready" and turn is not None:
                turn.mark("context_ready")
            elif chunk.type == "token" and turn is not None:
                turn.mark("planner_first_token")
            elif chunk.type == "tool_start" and turn is not None:
                turn.mark("first_tool_start")
            elif chunk.type == "tool_end" and turn is not None:
                turn.mark("first_tool_end")
    finally:
        await sq.finish()

    if response is None:
        # Stream ended without a final chunk — synthesize an empty response
        # so callers don't hit an attribute error. Matches Brain.run()'s
        # fallback shape.
        response = BrainResponse(
            spoken_text="",
            intent={},
            tool_calls=[],
            execution_trace=[],
            latency_ms=0,
        )
    return response


# Whisper emits these verbatim on silence, music, or room tone. They are not
# commands and must never reach the router.
_STT_HALLUCINATIONS = frozenset({
    "you", "thank you", "thanks for watching", "thank you for watching",
    "bye", "bye.", ".", "..", "...", "[blank_audio]", "[silence]",
    "subtitles by the amara.org community", "please subscribe",
    "music", "[music]", "applause", "[applause]",
})


def _is_dispatchable(command: str) -> bool:
    """Whether an STT transcript is plausibly a spoken command.

    Deliberately conservative: this only rejects transcripts that are
    self-evidently not commands. It is a floor, not a classifier — a
    determined mis-transcription of real speech still gets through, and the
    real fix for TTS-bleed is acoustic echo cancellation (see the note in
    wake_word.listen).
    """
    if not command:
        return False
    normalized = command.strip().lower().rstrip(".!?")
    if not normalized:
        return False
    if normalized in _STT_HALLUCINATIONS:
        return False
    # Single stray character is noise, never an utterance worth executing.
    if len(normalized) < 2:
        return False
    return True


async def _handle_wake_async(audio_bytes: bytes, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    """Main daemon orchestration via async events.

    Phase C1: Uses `transcribe_stream` for streaming STT with partial results.
    Phase C2: TTS is non-blocking — returns to IDLE immediately after dispatching speech.
    Phase 4C: creates a TurnLatency at wake-onset that threads through the
              pipeline so /diagnostics/latency reports a per-stage breakdown.
    """
    t0 = asyncio.get_event_loop().time()
    outcome = False  # ponytail: captured into dogfooding ledger via finally

    # Phase 4C: t=0 is here (wake VAD onset — the earliest observable
    # moment). Mark `wake` and thread the record through the pipeline.
    turn = TurnLatency(request_id=str(uuid.uuid4())[:8], mode="voice")
    turn.mark("wake")

    try:
        state_manager.transition_to(AssistantState.THINKING)
        arr = np.frombuffer(audio_bytes, dtype=np.int16)
        peak = int(np.max(np.abs(arr))) if arr.size else 0
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

        if rms < 200:
            print(f"[trigger] skipping whisper: capture too quiet (rms={rms:.0f})")
            state_manager.transition_to(AssistantState.IDLE)
            latency_ledger().record(turn)
            return False

        # Normalize int16 → float32 for Whisper
        audio_float = arr.astype(np.float32) / 32768.0

        try:
            # Use streaming STT - audio_float is already the full captured audio
            # For true streaming, we'd need to refactor wake_word to yield chunks
            stt = transcribe_array(audio_float, SAMPLE_RATE)
            turn.mark("stt_done")
            command = (stt.get("text") or "").strip()
            print(f"[command] {command!r}")

            # Content gate. The only prior check is an RMS floor, which
            # measures loudness, not speech — so Whisper hallucinating on
            # room noise or on the assistant's own TTS bleeding back into the
            # mic produced a transcript that was dispatched to the router and
            # EXECUTED. That is how ambient audio ended up launching apps.
            #
            # Loudness alone is not consent to run a command.
            if not _is_dispatchable(command):
                print(f"[trigger] dropping non-command transcript {command!r}")
                log.info("dropped non-command transcript: %r", command)
                state_manager.transition_to(AssistantState.IDLE)
                latency_ledger().record(turn)
                return False

            # Emit partial for UI feedback (simulated since we don't have true streaming yet)
            from backend.daemon.ui_events import STTPartialEvent
            bus = get_bus()
            bus.publish(STTPartialEvent(text=command, is_final=True), priority=Priority.HIGH)

            outcome = await _process_and_execute(command, peak, t0, emit, device_id, turn=turn)
            return outcome
        except Exception as e:
            state_manager.transition_to(AssistantState.ERROR)
            log.exception(f"trigger crash: {e}")
            state_manager.transition_to(AssistantState.IDLE)
            try:
                dogfooding_ledger.record_crash()
            except Exception:
                pass
            return False
    finally:
        latency_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
        try:
            dogfooding_ledger.record_command(outcome, latency_ms)
        except Exception:
            pass


from backend.daemon.ui_events import ProactiveEvent
import time

def on_proactive_event(event: ProactiveEvent):
    """Handle events fired by the Watcher Agent in the background."""
    def _run():
        while state_manager.current_state != AssistantState.IDLE:
            time.sleep(1)

        try:
            asyncio.run(_handle_proactive_async(event.query))
        except Exception as e:
            log.error(f"Proactive trigger failed: {e}")

    threading.Thread(target=_run, daemon=True, name="proactive-trigger").start()


async def _handle_proactive_async(query: str):
    t0 = asyncio.get_event_loop().time()
    state_manager.transition_to(AssistantState.THINKING)
    print(f"[proactive] {query!r}")

    command = f"[Proactive] {query}"
    await _process_and_execute(command, peak=0, t0=t0, emit=None, device_id=None)


def register_proactive_handler() -> None:
    """Register the proactive event handler. Call after event bus is initialized."""
    get_bus().subscribe(ProactiveEvent, on_proactive_event)
