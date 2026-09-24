"""The hardware probe decides defaults for settings the user did not set.

The laptop floor is 8 GB RAM, no GPU, no Ollama. Defaults tuned on the dev
box (6 GB NVIDIA card, Ollama resident) must not be what such a machine runs.
"""
import pytest

from backend.core import hardware
from backend.server.config import Settings


def _hw(**kw):
    base = dict(ram_gb=8.0, nvidia_gpu=False, cuda_usable=False, on_battery=False,
                ollama_up=False, ollama_models=())
    base.update(kw)
    return hardware.Hardware(**base)


def _settings(monkeypatch, **env):
    for k in ("ENABLE_VISION", "VISION_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_model_lookup_accepts_the_implicit_latest_tag():
    hw = _hw(ollama_up=True, ollama_models=("qwen2.5vl:3b", "phi3:latest"))
    assert hw.has_ollama_model("qwen2.5vl:3b")
    assert hw.has_ollama_model("phi3")
    assert not hw.has_ollama_model("gemma4:31b")


def test_no_ollama_turns_passive_vision_off(monkeypatch):
    s = _settings(monkeypatch)
    applied = hardware.apply(s, _hw())
    assert s.enable_vision is False
    assert [a.field for a in applied] == ["enable_vision"]
    assert "qwen2.5vl:3b" in applied[0].reason


def test_ollama_without_the_vision_model_also_turns_it_off(monkeypatch):
    s = _settings(monkeypatch)
    hardware.apply(s, _hw(ollama_up=True, ollama_models=("phi3:latest",)))
    assert s.enable_vision is False


def test_a_machine_that_has_the_model_keeps_vision(monkeypatch):
    s = _settings(monkeypatch)
    applied = hardware.apply(s, _hw(ollama_up=True, ollama_models=("qwen2.5vl:3b",)))
    assert s.enable_vision is True and applied == []


def test_an_explicit_setting_is_never_overridden(monkeypatch):
    """.env wins. The probe may only fill in what the user left unset —
    but it says so, because an explicit setting the machine cannot honour is
    worth a warning."""
    s = _settings(monkeypatch, ENABLE_VISION="true")
    applied = hardware.apply(s, _hw())
    assert s.enable_vision is True
    assert applied == []
    conflicts = hardware.conflicts(s, _hw())
    assert [c.field for c in conflicts] == ["enable_vision"]


def test_probe_survives_a_dead_ollama(monkeypatch):
    """No Ollama is the laptop floor, not an error."""
    hw = hardware.probe("http://127.0.0.1:1", timeout=0.3)
    assert hw.ollama_up is False and hw.ollama_models == ()
    assert hw.ram_gb > 0


def test_summary_is_json_safe():
    import json

    json.dumps(_hw(ollama_up=True, ollama_models=("a",)).summary())
