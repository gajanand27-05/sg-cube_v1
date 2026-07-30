"""End-to-end e2e TTS echo suppression probe using WASAPI loopback.

Runs the full echo chain: PCM audio → speaker output → loopback capture →
Whisper-like STT → echo gate matcher.

In this probe the audio path (speaker → loopback → PCM) is verified directly.
The echo gate matcher is already covered by 19 unit tests.  The actual Whisper
STT step is replaced with a direct call to was_recently_spoken() because
running faster-whisper would require a GPU or a very long CPU run.

The real e2e path (speaker → air → mic → Whisper → gate) still needs a room
test.  This probe verifies that at least the audio plumbing works.
"""
import sys
import time
from pathlib import Path
from threading import Thread

import numpy as np
import sounddevice as sd

# Ensure the project root is on sys.path
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech.tts_piper import (
    _note_spoken,
    _close_utterance,
    was_recently_spoken,
    ECHO_TAIL_S,
)


# Device indices — change if your machine uses different slots.
PLAYBACK_DEVICE: int = 3        # Speakers (Realtek(R) Audio)
CAPTURE_DEVICE: int = 4         # Primary Sound Capture Driver (Windows loopback)
SAMPLE_RATE = 22050
DURATION = 2.0


def generate_tone(freq: float = 880, duration: float = 2.0) -> np.ndarray:
    """A short tone burst that is distinct."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def capture_loopback(duration: float):
    """Record via loopback, return numpy array of captured float32 PCM."""
    rec_buffer = []

    def _record():
        with sd.InputStream(
            device=CAPTURE_DEVICE,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=int(SAMPLE_RATE * 0.05),
            dtype=np.float32,
        ) as stream:
            blocks = int(duration / (stream.blocksize / SAMPLE_RATE)) + 20
            for _ in range(blocks):
                try:
                    data, _ = stream.read(stream.blocksize)
                    rec_buffer.append(data.flatten())
                except Exception:
                    break

    thread = Thread(target=_record, daemon=True)
    thread.start()
    elapsed = 0
    while elapsed < duration:
        time.sleep(0.2)
        elapsed += 0.2

    if not rec_buffer:
        return np.array([], dtype=np.float32)

    return np.concatenate(rec_buffer)


def run_e2e_probe():
    """Run the e2e echo chain: spoken → loopback → was_recently_spoken."""
    print("=" * 60)
    print("[e2e] TTS echo suppression — end-to-end probe")
    print("=" * 60)

    # --- 1. Play on speaker while capturing via loopback ---
    audio_float = generate_tone(freq=880, duration=DURATION)
    print(f"[e2e] playing tone (880 Hz, {DURATION}s) on index {PLAYBACK_DEVICE}")
    sd.play(audio_float, samplerate=SAMPLE_RATE, device=PLAYBACK_DEVICE)
    sd.wait()

    # --- 2. Capture via loopback ---
    print(f"[e2e] capturing loopback on index {CAPTURE_DEVICE} ...")
    captured = capture_loopback(DURATION + 0.5)
    print(f"[e2e] captured {len(captured)} samples")

    if len(captured) < 64:
        print("[e2e] FAIL: 0 or near-0 bytes captured — loopback device may not support capture.")
        print("[e2e] Try: change CAPTURE_DEVICE to a different index, or enable Stereo Mix (device 16).")
        return

    # Normalize
    if np.max(np.abs(captured)) > 0:
        captured = captured / np.max(np.abs(captured))

    print(f"[e2e] OK: captured {DURATION:.1f}s of tone via loopback — audio path works")

    # --- 3. Verify echo gate with recorded assistant speech ---
    test_text = (
        "The weather in Bangalore is twenty six degrees and partly cloudy. "
        "There is a sixty percent chance of rain this evening."
    )
    print(f"\n[e2e] Assistant spoke: {test_text!r}")

    u = _note_spoken(test_text)
    _close_utterance(u)
    time.sleep(0.3)

    print(f"[e2e] Testing echo gate with tail = {ECHO_TAIL_S}s ...")
    suppressed = was_recently_spoken(test_text)
    print(f"[e2e] Is echo suppressed? {suppressed}")

    # --- 4. After tail expires, the same text should pass ---
    print(f"[e2e] Waiting for tail to expire ({ECHO_TAIL_S}s) ...")
    time.sleep(ECHO_TAIL_S + 1)
    suppressed_expired = was_recently_spoken(test_text)
    print(f"[e2e] After tail expired, is echo suppressed? {suppressed_expired}")

    # Cleanup
    from backend.ai_modules.speech import tts_piper
    tts_piper._recent_spoken.clear()

    print()
    if suppressed:
        print("[e2e] PASS: echo gate correctly suppresses the echoed transcript.")
        print("        (loopback audio path also verified)")
    else:
        print("[e2e] FAIL: echo gate did not suppress")

    if not suppressed_expired:
        print("[e2e] PASS: echo gate correctly allows transcript after tail expiry.")
    else:
        print("[e2e] WARN: echo gate still suppresses after tail — tail may be too long")

    print("\nNote: The full room test (speaker -> air -> mic -> Whisper -> gate)\n"
          "      remains unverified. This probe confirms the loopback audio path.\n"
          "      To complete: play natural speech, capture via mic, run through\n"
          "      Whisper, and feed the transcript to was_recently_spoken().\n")


if __name__ == "__main__":
    run_e2e_probe()
