"""POST /voice/process was broken twice over, and nothing covered it.

The handler called TWO coroutine functions without awaiting: process_input (the
orchestrator) and safe_executor.execute. Either alone 500s the route — the
first attribute access on the coroutine raises AttributeError. So the flagship
end-to-end voice endpoint had never worked, with the suite green throughout.

STT and TTS are stubbed (they need a model and a sound card); the orchestrator
and the executor run for real, because those are the two calls that were
broken. "what time is it" resolves on the rule layer, so no LLM is involved.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.server.routes import voice as voice_route

LOOPBACK = ("127.0.0.1", 4000)


def _client(monkeypatch, transcript="what time is it") -> tuple[TestClient, list]:
    spoken: list[str] = []
    monkeypatch.setattr(voice_route, "transcribe", lambda path: {"text": transcript})
    monkeypatch.setattr(voice_route, "speak", lambda text: spoken.append(text))
    app = FastAPI()
    app.include_router(voice_route.router)
    return TestClient(app, client=LOOPBACK), spoken


def test_voice_process_runs_the_whole_loop(monkeypatch):
    client, spoken = _client(monkeypatch)
    r = client.post("/voice/process", files={"audio": ("clip.wav", b"RIFFfake", "audio/wav")})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "what time is it"
    # Both previously-unawaited calls have to have produced real results:
    assert body["intent"]["action"] == "get_time"        # process_input
    assert body["execution"]["status"] == "success"      # safe_executor.execute
    assert body["source_layer"] == "rule"
    assert spoken and body["spoken_text"] == spoken[0]


def test_voice_process_reports_real_stage_timings(monkeypatch):
    """timings are computed around the two awaits; with the coroutines dropped
    they were the duration of building an object, not of doing the work."""
    client, _ = _client(monkeypatch)
    timings = client.post(
        "/voice/process", files={"audio": ("clip.wav", b"RIFFfake", "audio/wav")}
    ).json()["timings"]

    assert set(timings) >= {"stt_ms", "orchestrate_ms", "execute_ms", "tts_ms", "total_ms"}
    assert timings["total_ms"] == sum(
        timings[k] for k in ("stt_ms", "orchestrate_ms", "execute_ms", "tts_ms")
    )


def test_empty_transcript_short_circuits_without_touching_the_executor(monkeypatch):
    client, spoken = _client(monkeypatch, transcript="   ")
    body = client.post(
        "/voice/process", files={"audio": ("clip.wav", b"RIFFfake", "audio/wav")}
    ).json()

    assert body["transcript"] == ""
    assert body["intent"] is None and body["execution"] is None
    assert spoken == ["Sorry, I did not hear anything"]


def test_unsupported_extension_is_refused(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/voice/process", files={"audio": ("clip.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert ".exe" in r.json()["detail"]
