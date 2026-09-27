"""Recordings (the capture archive) are opt-in and deletable from the HUD.

Everything runs on temp folders: no real recording, .env or log is touched.
"""
import logging
import os
import time
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import capture_archive, env_file
from backend.server import session
from backend.server.config import settings

LOOPBACK = ("127.0.0.1", 50000)


# ── .env writer ──────────────────────────────────────────────────────────

def test_env_file_changes_one_key_and_keeps_everything_else(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# my settings\nAPP_HOST=127.0.0.1\nSTT_ARCHIVE_CAPTURES=true\nGROQ_API_KEY=gsk_x\n", encoding="utf-8")
    env_file.set_value(p, "STT_ARCHIVE_CAPTURES", "false")
    assert p.read_text(encoding="utf-8") == (
        "# my settings\nAPP_HOST=127.0.0.1\nSTT_ARCHIVE_CAPTURES=false\nGROQ_API_KEY=gsk_x\n")
    env_file.set_value(p, "LOG_TRANSCRIPTS", "true")
    assert p.read_text(encoding="utf-8").endswith("LOG_TRANSCRIPTS=true\n")


@pytest.mark.parametrize("key,value", [("lower", "x"), ("A B", "x"), ("OK", "a\nEVIL=1")])
def test_env_file_refuses_odd_keys_and_multiline_values(tmp_path, key, value):
    with pytest.raises(ValueError):
        env_file.set_value(tmp_path / ".env", key, value)


# ── archive: expiry, stats, delete ───────────────────────────────────────

def _wav(path, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(int(16000 * seconds), np.int16).tobytes())
    path.with_suffix(".json").write_text("{}", encoding="utf-8")


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR", tmp_path)
    return tmp_path


def test_commands_now_expire_after_seven_days_too(archive_dir):
    old, new = archive_dir / "20260901-100000-000.wav", archive_dir / "20260927-100000-000.wav"
    _wav(old); _wav(new)
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    capture_archive._prune(archive_dir)
    assert not old.exists() and new.exists()


def test_stats_and_delete_all(archive_dir, monkeypatch):
    monkeypatch.setattr(settings, "stt_archive_captures", True)
    for name in ("20260927-100000-000.wav", "wake-20260927-100001-000.wav", "drop-20260927-100002-000.wav"):
        _wav(archive_dir / name)
    (archive_dir / capture_archive.GATE_REJECTIONS_FILE).write_text("{}", encoding="utf-8")
    s = capture_archive.stats()
    assert s["enabled"] is True and s["recordings"] == 3 and s["bytes"] > 0 and s["retention_days"] == 7
    assert capture_archive.delete_all() == 3
    assert list(archive_dir.iterdir()) == []


# ── HUD API ──────────────────────────────────────────────────────────────

@pytest.fixture
def api(archive_dir, tmp_path, monkeypatch):
    from backend.core import paths
    from backend.server.routes import ui

    env = tmp_path / "user.env"
    env.write_text("APP_HOST=127.0.0.1\n", encoding="utf-8")
    monkeypatch.setattr(paths, "USER_ENV", env)
    monkeypatch.setattr(settings, "stt_archive_captures", False)
    app = FastAPI()
    app.include_router(ui.session_router)
    client = TestClient(app, client=LOOPBACK)
    client.headers.update({"host": f"127.0.0.1:{settings.app_port}"})
    return client, env


def _auth():
    return {"X-SG-Session": session.TOKEN}


def test_recordings_are_off_by_default():
    from backend.server.config import Settings
    assert Settings.model_fields["stt_archive_captures"].default is False


def test_the_hud_turns_recordings_on_and_it_is_saved(api):
    client, env = api
    r = client.post("/api/recordings", json={"enabled": True}, headers=_auth())
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert settings.stt_archive_captures is True
    assert "STT_ARCHIVE_CAPTURES=true" in env.read_text(encoding="utf-8")


def test_delete_all_from_the_hud(api, archive_dir):
    client, _ = api
    _wav(archive_dir / "20260927-100000-000.wav")
    r = client.post("/api/recordings/delete", headers=_auth())
    assert r.json()["deleted"] == 1 and r.json()["recordings"] == 0


@pytest.mark.parametrize("headers", [{}, {"X-SG-Session": "wrong"}])
def test_without_the_session_token_nothing_changes(api, archive_dir, headers):
    client, env = api
    _wav(archive_dir / "20260927-100000-000.wav")
    assert client.post("/api/recordings/delete", headers=headers).status_code == 401
    assert client.post("/api/recordings", json={"enabled": True}, headers=headers).status_code == 401
    assert (archive_dir / "20260927-100000-000.wav").exists()
    assert "STT_ARCHIVE_CAPTURES" not in env.read_text(encoding="utf-8")


def test_another_sites_page_is_refused(api):
    client, _ = api
    r = client.post("/api/recordings/delete", headers={**_auth(), "Origin": "https://evil.example"})
    assert r.status_code == 403
