import json
import queue
import time
from pathlib import Path
from typing import Any, Callable, Optional, Generator

import numpy as np
import sounddevice as sd
import vosk

from backend.core.dogfooding import ledger as dogfooding_ledger
from backend.core.state import AssistantState, manager as state_manager
from backend.server.config import settings

vosk.SetLogLevel(-1)

MODELS_DIR = Path(__file__).resolve().parents[1] / "ai_modules" / "speech" / "vosk_models"
DEFAULT_MODEL = "vosk-model-small-en-us-0.15"

# VAD tuning for command capture. RMS values are int16-amplitude scaled
# (full-scale = 32768). 400 is well above mic noise floor on consumer
# laptops but below normal speech (~1500-3000).
_VAD_RMS_THRESHOLD = 50  # ponytail: lowered from 400 for quieter mics
_VAD_TRAILING_SILENCE_MS = 800  # stop after this much silence post-speech
_VAD_MAX_CAPTURE_S = 10.0  # hard cap so a stuck mic doesn't hang forever
_VAD_INITIAL_WAIT_S = 3.0  # how long to wait for the user to start speaking

_FOLLOWUP_TRIGGER_RMS = 500    # lower = more sensitive to quiet speech
_FOLLOWUP_WINDOW_S = 3.0        # seconds the follow-up window stays open
_FOLLOWUP_MAX_EMPTY = 2



class WakeWordListener:
    """Continuously samples the mic and fires `on_wake(captured_audio_bytes)`
    when `wake_phrase` is recognised.

    Two callbacks:
      - on_wake_detected(): fires the instant the wake phrase is recognised,
        BEFORE any audio is captured. Use it to flash the UI and play a
        chime so the user gets immediate feedback.
      - on_wake(audio_bytes): fires after the command audio has been
        captured (variable length, VAD-controlled).

    Capture length is no longer fixed: we read chunks from the mic, look
    for ~700ms of silence following speech, and stop. Hard caps at 8s.
    """

    def __init__(
        self,
        on_wake: Callable[[bytes], Any],
        on_wake_detected: Optional[Callable[[], None]] = None,
        on_barge_in: Optional[Callable[[float], None]] = None,
        wake_phrase: str = "onyx",
        capture_seconds: float = 2.5,  # legacy arg, ignored by VAD path
        sample_rate: int = 16000,
        device: Optional[int] = None,
        model_name: str = DEFAULT_MODEL,
    ):
        model_path = MODELS_DIR / model_name
        if not model_path.exists():
            raise RuntimeError(
                f"Vosk model not found at {model_path}. "
                f"Run: python tools/download_vosk_model.py"
            )

        self.model = vosk.Model(str(model_path))
        self.recognizer = vosk.KaldiRecognizer(
            self.model, sample_rate, json.dumps([wake_phrase, "[unk]"])
        )
        self.wake_phrase = wake_phrase.lower()
        self.on_wake = on_wake
        self.on_wake_detected = on_wake_detected
        self.on_barge_in = on_barge_in
        self.capture_seconds = capture_seconds  # unused; kept for arg compat
        self.sample_rate = sample_rate
        self.device = device
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._capturing = False
        # Phase 4A: consecutive high-RMS chunks while state == SPEAKING;
        # resets to 0 on any low-RMS chunk. When it reaches
        # settings.barge_in_debounce_frames, we fire barge-in.
        self._barge_in_frames = 0

    def _cb(self, indata, _frames, _time, _status):
        self.queue.put(bytes(indata))

    def _check_barge_in(self, rms: float) -> bool:
        """Phase 4A: return True iff RMS during SPEAKING passes the debounce.

        Kept as a separate method so tests can drive the sequence directly
        without needing a running mic stream. Side effect: mutates
        `self._barge_in_frames`.
        """
        if (
            not settings.enable_barge_in
            or state_manager.current != AssistantState.SPEAKING
        ):
            # Outside SPEAKING or disabled — always reset so partial debounce
            # doesn't leak across a state transition.
            self._barge_in_frames = 0
            return False
        if rms > settings.barge_in_rms_threshold:
            self._barge_in_frames += 1
            if self._barge_in_frames >= settings.barge_in_debounce_frames:
                self._barge_in_frames = 0
                return True
            return False
        # RMS below threshold — reset debounce.
        self._barge_in_frames = 0
        return False

    def _drain(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _capture(self, initial: Optional[list[bytes]] = None) -> bytes:
        """Read mic chunks until VAD says the user stopped speaking.

        Two phases:
          1. Wait up to _VAD_INITIAL_WAIT_S for the first speech chunk.
          2. Once speech started, accumulate chunks and stop once
             _VAD_TRAILING_SILENCE_MS of silence has passed.
        Hard cap at _VAD_MAX_CAPTURE_S total.

        `initial` is any audio already collected by the caller (e.g. the
        chunk that triggered follow-up mode, or audio that arrived during
        wake recognition). It seeds the buffer so we don't lose it.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        for c in chunks:
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _VAD_RMS_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            is_speech = rms > _VAD_RMS_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        # User never started talking — bail rather than hang.
                        break

        return b"".join(chunks)

    def _capture_chunks(self, initial: Optional[list[bytes]] = None) -> Generator[bytes, None, None]:
        """Yield mic chunks until VAD says the user stopped speaking.
        
        Generator version for streaming STT integration.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        for c in chunks:
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _VAD_RMS_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            is_speech = rms > _VAD_RMS_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            yield chunk  # Yield each chunk for streaming STT

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        break

    def listen(self) -> None:
        """Continuously listen for wake word and fire callbacks."""
        self._running = True
        print(f"[wake] listening for {self.wake_phrase!r}... (Ctrl+C to stop)")
        # Smaller blocksize (125ms) gives PartialResult more frequent updates
        # AND lets follow-up RMS triggering react fast. Trade-off: more CPU.
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=2000,
            device=self.device,
            callback=self._cb,
        ):
            followup_until: float = 0.0  # monotonic timestamp; <= now == off
            empty_in_a_row: int = 0  # consecutive empty/error captures in followup

            while self._running:
                try:
                    data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._capturing:
                    continue

                now = time.monotonic()
                in_followup = now < followup_until

                trigger = False
                is_barge_in = False
                initial_audio: list[bytes] = []
                trigger_label = ""

                arr = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

                try:
                    if rms > _VAD_RMS_THRESHOLD:
                        self.recognizer.AcceptWaveform(data)
                        partial_json = json.loads(self.recognizer.PartialResult())
                        partial = (partial_json.get("partial") or "").lower()

                        if self.wake_phrase in partial.split():
                            trigger = True
                            trigger_label = f"wake: {partial!r} (rms={rms:.0f})"
                            self.recognizer.Reset()
                            empty_in_a_row = 0

                    elif in_followup:
                        if rms > _FOLLOWUP_TRIGGER_RMS:
                            trigger = True
                            trigger_label = f"followup-speech (rms={rms:.0f})"
                            initial_audio = [data]
                except Exception:
                    continue

                # Phase 4A: barge-in — if the user speaks WHILE TTS is playing,
                # interrupt playback and treat the utterance as a new command.
                # RMS + debounce is a coarse mitigation for TTS-bleeding-into-
                # mic false-fires; a loud speaker close to the mic will still
                # false-fire (out of scope — future AEC work).
                if not trigger and self._check_barge_in(rms):
                    trigger = True
                    is_barge_in = True
                    trigger_label = f"barge-in (rms={rms:.0f})"
                    initial_audio = [data]

                if not trigger:
                    continue

                print(f"[wake] heard {trigger_label}")
                self._capturing = True
                # Route the pre-capture callback: barge-in gets its own hook
                # (so the trigger can also publish SpeechInterruptedEvent),
                # falling back to on_wake_detected for the normal wake path.
                if is_barge_in and self.on_barge_in is not None:
                    try:
                        self.on_barge_in(rms)
                    except Exception as e:
                        print(f"[wake] on_barge_in raised: {e}")
                elif self.on_wake_detected is not None:
                    try:
                        self.on_wake_detected()
                    except Exception as e:
                        print(f"[wake] on_wake_detected raised: {e}")

                command_handled = False
                try:
                    audio = self._capture(initial=initial_audio)
                    result = self.on_wake(audio)
                    command_handled = result is None or bool(result)
                except Exception as e:
                    print(f"[wake] on_wake handler raised: {e}")
                finally:
                    try:
                        self.recognizer.Reset()
                    except Exception:
                        pass
                    self._drain()
                    self._capturing = False
                    # ponytail: one-line dogfooding hook — survived wake=True/False
                    try:
                        dogfooding_ledger.record_wake(command_handled)
                    except Exception:
                        pass
                    if command_handled:
                        empty_in_a_row = 0
                        followup_until = time.monotonic() + _FOLLOWUP_WINDOW_S
                        print(f"[wake] follow-up window open for {_FOLLOWUP_WINDOW_S:.0f}s")
                    else:
                        empty_in_a_row += 1
                        if empty_in_a_row >= _FOLLOWUP_MAX_EMPTY:
                            followup_until = 0.0
                            empty_in_a_row = 0
                            print(f"[wake] follow-up closed after {_FOLLOWUP_MAX_EMPTY} empty captures; say {self.wake_phrase!r} again")
                        else:
                            print(f"[wake] empty capture ({empty_in_a_row}/{_FOLLOWUP_MAX_EMPTY}); follow-up still open")

    def stop(self) -> None:
        self._running = False
