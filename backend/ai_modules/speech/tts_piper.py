"""Streaming TTS with proper chunked playback and interrupt support."""
import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Tuple

import numpy as np
import sounddevice as sd
from piper import PiperVoice

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import TTSChunkEvent, TTSStartEvent, TTSEndEvent

VOICE_DIR = Path(__file__).parent / "piper_voices"
VOICE_NAME = "en_US-ryan-high"

_voice: PiperVoice | None = None
_playback_task: asyncio.Task | None = None
_audio_queue: asyncio.Queue | None = None
_stop_event: asyncio.Event | None = None


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        model_path = VOICE_DIR / f"{VOICE_NAME}.onnx"
        config_path = VOICE_DIR / f"{VOICE_NAME}.onnx.json"
        if not model_path.exists() or not config_path.exists():
            raise RuntimeError(
                f"Piper voice files missing in {VOICE_DIR}. "
                f"Expected {VOICE_NAME}.onnx + .onnx.json"
            )
        _voice = PiperVoice.load(str(model_path), config_path=str(config_path))
    return _voice


def generate_audio(text: str) -> Tuple[bytes, int]:
    """Synthesize `text` and return raw PCM bytes (16kHz) and sample rate.
    
    Kept for backward compatibility with tests and legacy callers.
    """
    voice = _get_voice()
    chunks = list(voice.synthesize(text))
    if not chunks:
        return b"", 0
    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    return audio.tobytes(), rate


async def _audio_player() -> None:
    """Background task that plays audio chunks from queue."""
    global _audio_queue, _stop_event
    
    if _audio_queue is None or _stop_event is None:
        return
    
    stream = None
    try:
        # Get first chunk to determine sample rate
        first_chunk = await _audio_queue.get()
        if first_chunk is None:
            return
        
        rate = first_chunk.get("rate", 22050)
        audio_data = first_chunk.get("audio", np.array([], dtype=np.int16))
        
        if audio_data.size > 0:
            stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16")
            stream.start()
            stream.write(audio_data)
        
        # Play remaining chunks
        while not _stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(_audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            
            if chunk is None:  # End signal
                break
            
            audio_data = chunk.get("audio", np.array([], dtype=np.int16))
            if audio_data.size > 0 and stream:
                stream.write(audio_data)
    
    except Exception as e:
        print(f"[TTS] Audio player error: {e}")
    finally:
        if stream:
            stream.stop()
            stream.close()
        # Drain queue
        while not _audio_queue.empty():
            try:
                _audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


async def speak_stream(text: str) -> AsyncGenerator[dict, None]:
    """True streaming TTS — plays chunks as they're synthesized.
    
    Yields progress dicts: {"status": "started|playing|finished", "text": str, "progress": float}
    """
    global _playback_task, _audio_queue, _stop_event
    
    voice = _get_voice()
    
    # Initialize streaming infrastructure
    _audio_queue = asyncio.Queue(maxsize=10)
    _stop_event = asyncio.Event()
    _stop_event.clear()
    
    # Start audio player task
    _playback_task = asyncio.create_task(_audio_player())
    
    # Emit start event
    bus = get_bus()
    bus.publish(TTSStartEvent(text=text), priority=Priority.HIGH)
    
    yield {"status": "started", "text": text, "progress": 0.0}
    
    try:
        iterator = voice.synthesize(text)
        chunk_count = 0
        
        for chunk in iterator:
            if _stop_event.is_set():
                break
            
            audio_array = chunk.audio_int16_array
            rate = chunk.sample_rate
            
            # Queue chunk for playback
            await _audio_queue.put({"audio": audio_array, "rate": rate})
            
            chunk_count += 1
            yield {"status": "playing", "text": text, "progress": chunk_count * 0.1}
            
            # Small delay to let audio player start
            await asyncio.sleep(0.01)
        
        # Signal end
        await _audio_queue.put(None)
        
        if _playback_task:
            await _playback_task
        
        bus.publish(TTSEndEvent(text=text), priority=Priority.HIGH)
        yield {"status": "finished", "text": text, "progress": 1.0}
        
    except Exception as e:
        print(f"[TTS] Streaming error: {e}")
        _stop_event.set()
        yield {"status": "error", "text": text, "error": str(e)}
    finally:
        # Cleanup
        _audio_queue = None
        _stop_event = None
        _playback_task = None


def speak(text: str) -> dict:
    """Synthesize and play text (blocking synthesis, non-blocking playback)."""
    # Use streaming internally but wait for completion
    async def _run():
        async for _ in speak_stream(text):
            pass
    
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # If already in async context, create task
        task = loop.create_task(_run())
        # Don't await - non-blocking
        return {"status": "started", "text": text}
    except RuntimeError:
        # No running loop, run in new loop
        asyncio.run(_run())
        return {"status": "finished", "text": text}


def stop_speech() -> None:
    """Immediately stop any in-progress speech playback."""
    global _stop_event, _audio_queue, _playback_task
    
    if _stop_event:
        _stop_event.set()
    
    # Clear queue
    if _audio_queue:
        while not _audio_queue.empty():
            try:
                _audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    
    # Also stop sounddevice directly
    sd.stop()
    
    print("[TTS] Speech interrupted")


def is_speaking() -> bool:
    """Check if TTS is currently playing."""
    return _playback_task is not None and not _playback_task.done()