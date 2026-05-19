import json
import queue
from pathlib import Path
from typing import Callable, Optional

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
_VAD_TRAILING_SILENCE_MS = 700  # stop after this much silence post-speech
_VAD_MAX_CAPTURE_S = 8.0  # hard cap so a stuck mic doesn't hang forever
_VAD_INITIAL_WAIT_S = 1.5  # if user never starts speaking, give up


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
        on_wake: Callable[[bytes], None],
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

    def _capture(self) -> bytes:
        """Read mic chunks until VAD says the user stopped speaking.

        Two phases:
          1. Wait up to _VAD_INITIAL_WAIT_S for the first speech chunk.
          2. Once speech started, accumulate chunks and stop once
             _VAD_TRAILING_SILENCE_MS of silence has passed.
        Hard cap at _VAD_MAX_CAPTURE_S total.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_chunks = max(1, int(_VAD_INITIAL_WAIT_S * 2))  # blocksize=8000 -> 0.5s/chunk

        chunks: list[bytes] = []
        total_bytes = 0
        speech_seen = False
        trailing_silence_bytes = 0
        silence_chunks_before_speech = 0

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
                    silence_chunks_before_speech += 1
                    if silence_chunks_before_speech >= initial_wait_chunks:
                        # User never started talking — bail rather than hang.
                        break

        return b"".join(chunks)

    def listen(self) -> None:
        self._running = True
        print(f"[wake] listening for {self.wake_phrase!r}... (Ctrl+C to stop)")
        # Smaller blocksize (250ms vs prior 500ms) gives PartialResult more
        # frequent updates, halving wake-detection latency in practice.
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=4000,
            device=self.device,
            callback=self._cb,
        ):
            while self._running:
                try:
                    data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._capturing:
                    continue

                # Feed audio into Vosk. We check PartialResult on every
                # chunk — it fires the moment the wake phrase appears in
                # the in-progress recognition, NOT only at end-of-utterance.
                # That cuts wake latency from ~1-2s (waiting for the user
                # to finish a phrase) to ~250-400ms.
                self.recognizer.AcceptWaveform(data)
                partial = (json.loads(self.recognizer.PartialResult()).get("partial") or "").lower()
                if self.wake_phrase not in partial:
                    continue
                text = partial

                print(f"[wake] heard: {text!r}")
                self._capturing = True
                # Fire the immediate-feedback callback BEFORE any capture so
                # the UI lights up the moment the wake phrase is recognised.
                if self.on_wake_detected is not None:
                    try:
                        self.on_wake_detected()
                    except Exception as e:
                        print(f"[wake] on_wake_detected raised: {e}")
                try:
                    self._drain()
                    audio = self._capture()
                    self.on_wake(audio)
                except Exception as e:
                    print(f"[wake] on_wake handler raised: {e}")
                finally:
                    self.recognizer.Reset()
                    self._drain()
                    self._capturing = False
                    print(f"[wake] listening for {self.wake_phrase!r}...")

    def stop(self) -> None:
        self._running = False
