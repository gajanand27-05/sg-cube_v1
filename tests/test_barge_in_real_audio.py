"""Barge-in end-to-end through the real listen() loop and the real Vosk
recognizer — no mic, no mocked gate.

The unit tests in test_barge_in.py drive `_check_barge_in` directly, so they
prove the decision rule and nothing about the loop that feeds it. The whole
fix hinges on loop-level state: `partial` deliberately persists across
frames, and `self._partial_tokens` is updated in exactly one place per
frame. A stale or per-frame-reset baseline still passes every unit test
while making every loud frame after a quiet one look like fresh speech.
So this drives the actual loop and asserts on what the callbacks saw.

Audio in: a synthetic click train + broadband noise at ~3000 RMS (louder
than the 2854 RMS room transients that were self-interrupting playback),
then a real recorded speech clip.
"""
import json
import sys
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

BLOCK_FRAMES = 2000
BLOCK_BYTES = BLOCK_FRAMES * 2
_RECORDINGS = _project_root / "tools" / "_recordings"


def _noise_blocks(n=12, peak=9000) -> list[bytes]:
    """Loud, impulsive, and not speech. ~3000 RMS."""
    rng = np.random.default_rng(0)
    out = []
    for _ in range(n):
        block = rng.normal(0, peak / 3, BLOCK_FRAMES)
        block[::250] += peak  # click train
        out.append(np.clip(block, -32000, 32000).astype(np.int16).tobytes())
    return out


def _blocks_of(wav: Path) -> list[bytes] | None:
    with wave.open(str(wav), "rb") as w:
        if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (1, 16000, 2):
            return None
        pcm = w.readframes(w.getnframes())
    return [pcm[i:i + BLOCK_BYTES] for i in range(0, len(pcm) - BLOCK_BYTES, BLOCK_BYTES)]


def _says_wake_word(blocks: list[bytes]) -> bool:
    import vosk
    from backend.daemon import wake_word as ww
    rec = vosk.KaldiRecognizer(
        vosk.Model(str(ww.MODELS_DIR / ww.DEFAULT_MODEL)),
        16000,
        json.dumps(["onyx", "[unk]"]),
    )
    for b in blocks:
        rec.AcceptWaveform(b)
        if "onyx" in (json.loads(rec.PartialResult()).get("partial") or "").split():
            return True
    return "onyx" in (json.loads(rec.FinalResult()).get("text") or "").split()


def _speech_blocks() -> list[bytes]:
    """A recorded clip that does NOT contain the wake phrase.

    The wake branch is checked before barge-in and legitimately wins, so a
    clip containing "onyx" tests the wake path instead of this one — which
    is how the first version of this test failed.
    """
    for wav in sorted(_RECORDINGS.glob("*.wav")):
        blocks = _blocks_of(wav)
        if blocks and not _says_wake_word(blocks):
            return blocks
    pytest.skip(f"no wake-word-free 16k mono clip in {_RECORDINGS}")


class _NullStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_loop(blocks, require_speech=True):
    """Feed `blocks` through the real listen() loop. Returns the trigger
    sources observed, in order."""
    vosk = pytest.importorskip("vosk")
    from unittest.mock import patch
    from backend.core.state import AssistantState, manager
    from backend.daemon import wake_word as ww
    from backend.server.config import settings

    if not (ww.MODELS_DIR / ww.DEFAULT_MODEL).exists():
        pytest.skip("Vosk model not downloaded")

    seen: list[str] = []

    def on_wake(audio):
        seen.append(manager._voice_trigger_source)
        return True

    listener = ww.WakeWordListener(on_wake=on_wake, on_barge_in=lambda rms: None)
    # Capture would sit waiting on an empty queue for _VAD_INITIAL_WAIT_S;
    # the trigger decision is what is under test, not the capture.
    listener._capture = lambda initial=None: b""
    for b in blocks:
        listener.queue.put(b)

    saved = {
        k: getattr(settings, k)
        for k in ("enable_barge_in", "barge_in_rms_threshold",
                  "barge_in_debounce_frames", "barge_in_require_speech")
    }
    prev_state = manager.current
    # The loop sets _voice_trigger_source and trigger.py's finally clears it.
    # We stub out that half, so restore it here or it leaks: verifier.py only
    # honours a tool's `trusted` flag when the source is None/"wake", and a
    # stray "barge_in" silently un-trusts every SYSTEM_WRITE tool in every
    # test that runs after this one.
    prev_source = manager._voice_trigger_source
    try:
        settings.enable_barge_in = True
        settings.barge_in_rms_threshold = 800
        settings.barge_in_debounce_frames = 2
        settings.barge_in_require_speech = require_speech
        manager._current_state = AssistantState.SPEAKING

        with patch.object(ww.sd, "RawInputStream", lambda **kw: _NullStream()):
            t = threading.Thread(target=listener.listen, daemon=True)
            t.start()
            # Loop drains the queue, then blocks on get(timeout=0.5).
            deadline = 15.0
            step = 0.25
            waited = 0.0
            while waited < deadline and not listener.queue.empty():
                t.join(step)
                waited += step
            t.join(1.0)  # let the last frames flush
            listener._running = False
            t.join(2.0)
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)
        manager._current_state = prev_state
        manager._voice_trigger_source = prev_source
    return seen


def test_loud_noise_does_not_barge_in_through_the_real_loop():
    assert _run_loop(_noise_blocks(n=12)) == []


def test_the_same_noise_fires_under_the_old_loudness_only_rule():
    """Non-vacuity guard. barge_in_require_speech=False is the pre-fix
    behaviour; if this ever stops firing, the test above is passing because
    the fixture is too quiet, not because the gate works."""
    assert _run_loop(_noise_blocks(n=12), require_speech=False) == ["barge_in"]


def test_speech_does_barge_in_through_the_real_loop():
    seen = _run_loop(_speech_blocks())
    assert "barge_in" in seen, f"expected a barge_in trigger, got {seen}"


def test_noise_before_speech_still_barges_in_on_the_speech():
    """The baseline-staleness case: quiet/undecoded frames precede speech.
    Noise must not fire, and must not desensitise the loop to what follows."""
    seen = _run_loop(_noise_blocks(n=12) + _speech_blocks())
    assert "barge_in" in seen, f"expected a barge_in trigger, got {seen}"
    # And the noise must not have fired one of its own beforehand.
    assert seen[0] == "barge_in", f"noise triggered first: {seen}"


if __name__ == "__main__":
    test_loud_noise_does_not_barge_in_through_the_real_loop()
    print("  [PASS] loud non-speech does not barge in (real loop, real Vosk)")
    test_the_same_noise_fires_under_the_old_loudness_only_rule()
    print("  [PASS] the same noise DID fire under the old loudness-only rule")
    test_speech_does_barge_in_through_the_real_loop()
    print("  [PASS] speech does barge in (real loop, real Vosk)")
    test_noise_before_speech_still_barges_in_on_the_speech()
    print("  [PASS] noise before speech does not desensitise the loop")
