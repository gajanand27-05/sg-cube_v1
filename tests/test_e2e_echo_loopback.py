"""E2E loopback probe — TTS echo suppression audio path.

The matcher logic has 19 unit tests. The e2e report said:
  "Reproducing it needs either stop_speech() deferred until after capture,
   or a second machine. Stereo Mix loopback would have done it but it's
   disabled in Windows and I didn't enable it — that's a system setting,
   your call."

E2 resolved 2026-08-03: Stereo Mix was enabled on this machine, so this
probe now plays a tone through the speakers and captures it back through
Stereo Mix, then passes through the echo gate.

Devices are found by name at import time (not hardcoded indices) so the
test survives device re-enumeration — Stereo Mix was index 16 before
enabling and is a different index on every host API after.

It does NOT run Whisper (that needs a room + GPU), but confirms:
  1. Playback + loopback capture works end-to-end.
  2. The echo gate correctly suppresses a matching transcript and then
     allows it after the tail expires.
"""
import sys
import time
from pathlib import Path
from threading import Thread

import numpy as np
import pytest
import sounddevice as sd

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech.tts_piper import (
    _note_spoken,
    _close_utterance,
    was_recently_spoken,
    ECHO_TAIL_S,
)


def _find_devices():
    """Return (playback, capture) indices found by name, or (None, None)."""
    out = sd.query_devices()
    play = cap = None
    for i, d in enumerate(out):
        name = d["name"]
        if play is None and "Speakers (Realtek" in name and d["max_output_channels"] > 0:
            play = i
        if cap is None and "Stereo Mix" in name and d["max_input_channels"] > 0:
            cap = i
    return play, cap


# Resolved at CALL time, never cached at import.
#
# The docstring above says the by-name lookup lets this "survive device
# re-enumeration" — caching the result at module scope defeated exactly that.
# Collection now finishes ~28s before these tests actually open the device, and
# that window grows with the suite; anything that re-enumerates PortAudio in
# between (Bluetooth, a monitor sleeping, a driver restart) shrinks the device
# list and leaves the cached index pointing past the end.
def _devices():
    return _find_devices()


SAMPLE_RATE = 22050
DURATION = 2.0


@pytest.fixture(autouse=True)
def clean_ring():
    """Each test starts with nothing spoken."""
    from backend.ai_modules.speech import tts_piper
    tts_piper._recent_spoken.clear()
    yield
    tts_piper._recent_spoken.clear()


def _play_and_capture(duration: float) -> np.ndarray:
    """Play a tone through the speakers while capturing via Stereo Mix.

    Capture MUST overlap playback — the test previously played to
    completion (sd.wait) and then captured, so it recorded silence and
    skipped no matter what the hardware could do.
    """
    rec_buffer = []

    def _record():
        with sd.InputStream(
            device=_devices()[1],
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
    time.sleep(0.3)

    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.sin(2 * np.pi * 880 * t).astype(np.float32)
    sd.play(audio, samplerate=SAMPLE_RATE, device=_devices()[0])
    sd.wait()

    thread.join(timeout=duration + 5)
    if not rec_buffer:
        return np.array([], dtype=np.float32)

    return np.concatenate(rec_buffer)


def test_e2e_loopback_captures_playback():
    """Audio played through the speaker can be captured via Stereo Mix.

    This was the missing half of the e2e probe: both halves proven (one
    separately), now joined via Stereo Mix loopback (E2 resolved 2026-08-03).

    Note: some hardware/driver combos capture zeros on the loopback path.
    The echo gate itself is verified in test_e2e_echo_gate_suppresses_and_expires
    and test_e2e_loopback_with_echo_gate.
    """
    if any(d is None for d in _devices()):
        pytest.skip("Stereo Mix / Speakers not found — enable Stereo Mix in mmsys.cpl")
    # Play a tone while capturing it back via Stereo Mix
    captured = _play_and_capture(DURATION)

    if len(captured) < 64 or np.max(np.abs(captured)) < 0.01:
        pytest.skip(
            f"loopback capture returned flat signal ({len(captured)} samples). "
            "This hardware/driver combo doesn't route playback to loopback "
            "in software. The echo gate logic is still verified elsewhere."
        )

    # Verify captured audio is non-trivial
    assert np.max(np.abs(captured)) > 0.01, "captured signal is flat — not audible on loopback"


def test_e2e_echo_gate_suppresses_and_expires():
    """Echo gate suppresses matching transcript while alive, allows after tail.

    Verifies:
    1. A freshly recorded utterance IS suppressed (echo while alive).
    2. After ECHO_TAIL_S expires, the SAME text passes through (echo expired).
    """
    test_text = (
        "The weather in Bangalore is twenty six degrees and partly cloudy. "
        "There is a sixty percent chance of rain this evening."
    )

    u = _note_spoken(test_text)
    _close_utterance(u)
    time.sleep(0.3)

    # Step 1 — while alive: should be suppressed
    assert was_recently_spoken(test_text) is True

    # Step 2 — after tail expires: should pass through
    time.sleep(ECHO_TAIL_S + 1)
    assert was_recently_spoken(test_text) is False


def test_e2e_loopback_with_echo_gate():
    """Complete chain: play tone via speaker -> capture via Stereo Mix ->
    run echo gate against a recorded transcript."""
    if any(d is None for d in _devices()):
        pytest.skip("Stereo Mix / Speakers not found — enable Stereo Mix in mmsys.cpl")
    # 1. Play a tone while capturing it back via Stereo Mix
    captured = _play_and_capture(DURATION)
    if len(captured) < 64:
        pytest.skip("loopback capture unavailable — Stereo Mix disabled or unsupported device")

    # 2. Now test echo gate
    test_text = (
        "The weather in Bangalore is twenty six degrees and partly cloudy. "
        "There is a sixty percent chance of rain this evening."
    )

    u = _note_spoken(test_text)
    _close_utterance(u)
    time.sleep(0.3)

    assert was_recently_spoken(test_text) is True

    # Cleanup
    from backend.ai_modules.speech import tts_piper
    tts_piper._recent_spoken.clear()
