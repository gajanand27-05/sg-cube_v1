import json
import queue
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd
import vosk

vosk.SetLogLevel(-1)

MODELS_DIR = Path(__file__).resolve().parents[1] / "ai_modules" / "speech" / "vosk_models"
DEFAULT_MODEL = "vosk-model-small-en-us-0.15"

# VAD tuning for command capture. RMS values are int16-amplitude scaled
# (full-scale = 32768). 400 is well above mic noise floor on consumer
# laptops but below normal speech (~1500-3000).
_VAD_RMS_THRESHOLD = 400
_VAD_TRAILING_SILENCE_MS = 800  # stop after this much silence post-speech
_VAD_MAX_CAPTURE_S = 10.0  # hard cap so a stuck mic doesn't hang forever
_VAD_INITIAL_WAIT_S = 3.0  # how long to wait for the user to start speaking

# Follow-up mode: after a command completes, stay open for this many seconds
# and trigger capture on ANY speech, no wake word required. Lets the user
# chain commands ("open chrome" ... "and the news" ... "lock") without
# saying "sg cube" each time.
#
# A SEPARATE, higher threshold is used for follow-up triggering — the main
# _VAD_RMS_THRESHOLD is for "is this chunk speech vs silence" inside an
# already-triggered capture, where false positives just extend the window.
# Follow-up triggering is upstream: a false positive here STARTS a whole
# capture+STT+TTS round on ambient noise. Worth being conservative.
_FOLLOWUP_TRIGGER_RMS = 1000
_FOLLOWUP_WINDOW_S = 8.0
_FOLLOWUP_MAX_EMPTY = 2  # close follow-up after this many empty captures in a row


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
        wake_phrase: str = "sg cube",
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
        self.capture_seconds = capture_seconds  # unused; kept for arg compat
        self.sample_rate = sample_rate
        self.device = device
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._capturing = False

    def _cb(self, indata, _frames, _time, _status):
        self.queue.put(bytes(indata))

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

    def listen(self) -> None:
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
                initial_audio: list[bytes] = []
                trigger_label = ""

                # Path A: standard wake-word detection via Vosk partial result.
                # PartialResult fires the moment the phrase appears in the
                # in-progress recognition, NOT only at end-of-utterance — so
                # latency drops from ~1-2s to ~125-300ms.
                self.recognizer.AcceptWaveform(data)
                partial = (json.loads(self.recognizer.PartialResult()).get("partial") or "").lower()
                if self.wake_phrase in partial:
                    trigger = True
                    trigger_label = f"wake: {partial!r}"
                    self.recognizer.Reset()
                    empty_in_a_row = 0
                # Path B: follow-up mode — any speech triggers a capture, no
                # wake word required. The chunk that triggered IS the start
                # of the user's command, so we feed it into the capture buffer.
                # Uses a HIGHER threshold than the in-capture VAD so ambient
                # noise / TTS bleed don't start phantom rounds.
                elif in_followup:
                    arr = np.frombuffer(data, dtype=np.int16)
                    if arr.size:
                        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                        if rms > _FOLLOWUP_TRIGGER_RMS:
                            trigger = True
                            trigger_label = f"followup-speech (rms={rms:.0f})"
                            initial_audio = [data]

                if not trigger:
                    continue

                print(f"[wake] heard {trigger_label}")
                self._capturing = True
                # Fire the immediate-feedback callback BEFORE any capture so
                # the UI lights up the moment we triggered.
                if self.on_wake_detected is not None:
                    try:
                        self.on_wake_detected()
                    except Exception as e:
                        print(f"[wake] on_wake_detected raised: {e}")

                command_handled = False
                try:
                    # Do NOT drain — if the user said wake+command in one
                    # breath ("sg cube open notepad"), the command audio is
                    # sitting in the queue. _capture will read it first.
                    audio = self._capture(initial=initial_audio)
                    result = self.on_wake(audio)
                    # on_wake can return True (real command) / False (empty
                    # or error). Old handlers returning None are treated as
                    # successful so wake-only mode behaves as before.
                    command_handled = result is None or bool(result)
                except Exception as e:
                    print(f"[wake] on_wake handler raised: {e}")
                finally:
                    self.recognizer.Reset()
                    self._drain()
                    self._capturing = False
                    # Update follow-up window based on what just happened.
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
                            # Single empty capture — keep the window open but
                            # don't extend it.
                            print(f"[wake] empty capture ({empty_in_a_row}/{_FOLLOWUP_MAX_EMPTY}); follow-up still open")

    def stop(self) -> None:
        self._running = False
