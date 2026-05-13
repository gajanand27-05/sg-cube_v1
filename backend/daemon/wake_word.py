import json
import queue
from pathlib import Path
from typing import Callable, Optional

import sounddevice as sd
import vosk

vosk.SetLogLevel(-1)

MODELS_DIR = Path(__file__).resolve().parents[1] / "ai_modules" / "speech" / "vosk_models"
DEFAULT_MODEL = "vosk-model-small-en-us-0.15"


class WakeWordListener:
    """Continuously samples the mic and fires `on_wake(captured_audio_bytes)`
    when `wake_phrase` is recognised. After firing, it collects the next
    `capture_seconds` of audio from the same stream and hands it to the
    callback as int16 mono PCM bytes (16kHz). Listening pauses while
    on_wake runs, then resumes.
    """

    def __init__(
        self,
        on_wake: Callable[[bytes], None],
        wake_phrase: str = "sg cube",
        capture_seconds: int = 5,
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
        self.capture_seconds = capture_seconds
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
        target = self.capture_seconds * self.sample_rate * 2
        chunks: list[bytes] = []
        got = 0
        while got < target:
            try:
                chunk = self.queue.get(timeout=10.0)
            except queue.Empty:
                break
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)[:target]

    def listen(self) -> None:
        self._running = True
        print(f"[wake] listening for {self.wake_phrase!r}... (Ctrl+C to stop)")
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=8000,
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
                if not self.recognizer.AcceptWaveform(data):
                    continue
                text = (json.loads(self.recognizer.Result()).get("text") or "").lower()
                if self.wake_phrase not in text:
                    continue

                print(f"[wake] heard: {text!r}")
                self._capturing = True
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
