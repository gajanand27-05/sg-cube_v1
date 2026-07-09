"""Phase 4C — populate the latency ledger with a real Brain turn.

Skips the mic (mic-dependent stages will be near-zero) but drives the
real LLM + tool path so /diagnostics/latency shows honest numbers for
context_ready, planner_first_token, first_tool_start/end, first_audio_out,
and total.

TTS is patched to no-op so no speaker output happens.
"""
import asyncio
import json
import time
import urllib.request
from unittest.mock import patch


async def _fake_speak_stream(text):
    yield {"status": "started", "text": text}
    yield {"status": "finished", "text": text}


def _fake_stop():
    pass


def _fetch_latency():
    with urllib.request.urlopen("http://127.0.0.1:8001/diagnostics/latency?n=5", timeout=5) as r:
        return json.loads(r.read())


async def drive_turn(command: str, label: str):
    # Deferred imports so the backend is already booted before we import
    # anything that might touch shared modules.
    from backend.core.brain import BrainRequest
    from backend.core.latency import TurnLatency, ledger as latency_ledger
    from backend.daemon.trigger import _run_brain_streaming
    from backend.core.state import manager as state_manager, AssistantState

    print(f"\n=== {label}: {command!r} ===")

    # Ensure state starts at IDLE so the trigger doesn't skip the SPEAKING
    # transition. Not required for the ledger to populate, just cleaner.
    state_manager._current_state = AssistantState.IDLE

    turn = TurnLatency(request_id=f"live-{int(time.time()) % 100000}", mode="voice")
    turn.mark("wake")           # would be VAD onset
    turn.mark("stt_done")       # would be after transcribe_array

    req = BrainRequest(
        user_id="21c19bf1-b73f-4001-80de-789b93c8d703",
        input_text=command,
        input_mode="voice",
    )
    turn.mark("orchestrator_route")

    with patch("backend.ai_modules.speech.tts_queue.speak_stream", side_effect=_fake_speak_stream), \
         patch("backend.ai_modules.speech.tts_queue.stop_speech", side_effect=_fake_stop):
        try:
            resp = await _run_brain_streaming(req, turn=turn)
            print(f"  spoken_text: {resp.spoken_text[:120]!r}")
            print(f"  tool_calls : {[t.name for t in resp.tool_calls]}")
        except Exception as e:
            print(f"  [FAILED] {type(e).__name__}: {e}")

    latency_ledger().record(turn)
    print(f"  stages_ms : {turn.stages}")


async def main():
    await drive_turn("what time is it", "Turn 1 (conversational)")
    await drive_turn("open chrome", "Turn 2 (tool-call)")
    # Give the backend a moment (LLM tasks may still be settling in event loop)
    print("\n--- /diagnostics/latency ---")
    print(json.dumps(_fetch_latency(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
