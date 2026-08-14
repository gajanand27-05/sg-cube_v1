"""Which Whisper model runs, where, and for how long.

get_model() used to be an @lru_cache(maxsize=1) hardcoded to
device="cpu", compute_type="int8". Three consequences, all measured on this
machine: the GPU was never used though CTranslate2 could see it, accuracy was
capped by int8 quantisation, and the model was pinned for the life of the
process with no way to switch when the power source changed.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import stt_manager as m


@pytest.fixture(autouse=True)
def _reset():
    original = m.settings.stt_profile
    m.release_model()
    yield
    m.settings.stt_profile = original
    m.release_model()


def _pick(monkeypatch, *, cuda: bool, battery: bool, profile="auto"):
    monkeypatch.setattr(m, "cuda_available", lambda: cuda)
    monkeypatch.setattr(m, "on_battery", lambda: battery)
    m.settings.stt_profile = profile
    return m.select_profile()


def test_ac_power_with_a_gpu_gets_the_accurate_model(monkeypatch):
    p = _pick(monkeypatch, cuda=True, battery=False)
    assert (p.device, p.compute_type) == ("cuda", "float16")
    assert p.model == m.settings.whisper_model_gpu


def test_battery_drops_to_the_cheap_model(monkeypatch):
    """A laptop unplugged at a demo should not spend its charge on float16
    attention."""
    p = _pick(monkeypatch, cuda=True, battery=True)
    assert (p.device, p.compute_type) == ("cpu", "int8")
    assert p.model == m.settings.whisper_model_cpu


def test_no_gpu_falls_back_to_cpu_even_on_ac(monkeypatch):
    p = _pick(monkeypatch, cuda=False, battery=False)
    assert p.device == "cpu"


def test_profile_can_be_pinned_against_a_wrong_autodetect(monkeypatch):
    """A demo must be able to force the good model regardless of the cable."""
    p = _pick(monkeypatch, cuda=True, battery=True, profile="accurate")
    assert p.device == "cuda" and p.model == m.settings.whisper_model_gpu

    p = _pick(monkeypatch, cuda=True, battery=False, profile="fast")
    assert p.device == "cpu" and p.model == m.settings.whisper_model_cpu


def test_an_unknown_profile_name_does_not_crash_the_voice_path(monkeypatch):
    p = _pick(monkeypatch, cuda=True, battery=False, profile="turbo-max")
    assert p.device == "cuda", "unknown profile should degrade to auto, not raise"


def test_undetectable_power_state_assumes_plugged_in(monkeypatch):
    """The conservative answer is AC: wrongly assuming battery would silently
    downgrade accuracy on a desktop with no battery sensor."""
    monkeypatch.setattr(m, "psutil", None, raising=False)
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert m.on_battery() is False


def test_cuda_check_does_not_consult_torch(monkeypatch):
    """This venv has a CPU-only torch that reports cuda unavailable while
    CTranslate2 reports a working device. Asking torch would disable the GPU
    permanently."""
    import inspect

    src = inspect.getsource(m.cuda_available)
    assert "torch" not in src.split('"""')[-1], "cuda_available consults torch"


# ── model cache lifetime ────────────────────────────────────────────────

class _FakeModel:
    def __init__(self, name, device=None, compute_type=None):
        self.name, self.device, self.compute_type = name, device, compute_type


@pytest.fixture
def fake_whisper(monkeypatch):
    built = []

    class _FW:
        def __init__(self, name, device=None, compute_type=None):
            built.append((name, device, compute_type))

    monkeypatch.setattr("faster_whisper.WhisperModel", _FW)
    return built


def test_the_model_is_loaded_once_and_reused(fake_whisper, monkeypatch):
    _pick(monkeypatch, cuda=True, battery=False)
    m.get_model()
    m.get_model()
    m.get_model()
    assert len(fake_whisper) == 1, f"reloaded the model {len(fake_whisper)} times"


def test_changing_power_source_reloads_on_the_other_device(fake_whisper, monkeypatch):
    """The old lru_cache could never do this — it returned the CPU model
    forever, whatever the machine was doing."""
    _pick(monkeypatch, cuda=True, battery=False)
    m.get_model()
    _pick(monkeypatch, cuda=True, battery=True)
    m.get_model()

    assert len(fake_whisper) == 2
    assert fake_whisper[0][1] == "cuda" and fake_whisper[1][1] == "cpu"


def test_idle_timeout_releases_the_model(fake_whisper, monkeypatch):
    _pick(monkeypatch, cuda=True, battery=False)
    monkeypatch.setattr(m.settings, "stt_idle_unload_s", 0.2)

    m.get_model()
    assert m.loaded_key() is not None

    deadline = time.monotonic() + 5
    while m.loaded_key() is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert m.loaded_key() is None, "model was never released"


def test_use_during_the_idle_window_keeps_the_model(fake_whisper, monkeypatch):
    """Unloading mid-conversation would pay the load cost on the next
    utterance, which is the whole reason this is a timer and not an
    unload-after-every-call."""
    _pick(monkeypatch, cuda=True, battery=False)
    monkeypatch.setattr(m.settings, "stt_idle_unload_s", 0.6)

    m.get_model()
    for _ in range(4):
        time.sleep(0.2)
        m.get_model()          # keeps pushing the deadline out

    assert m.loaded_key() is not None, "released while still in use"
    assert len(fake_whisper) == 1, "reloaded mid-conversation"


def test_idle_unload_can_be_disabled(fake_whisper, monkeypatch):
    _pick(monkeypatch, cuda=True, battery=False)
    monkeypatch.setattr(m.settings, "stt_idle_unload_s", 0)
    m.get_model()
    time.sleep(0.3)
    assert m.loaded_key() is not None


def test_concurrent_callers_load_one_model(fake_whisper, monkeypatch):
    """The wake listener and the HTTP route both reach this."""
    _pick(monkeypatch, cuda=True, battery=False)
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        m.get_model()

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(fake_whisper) == 1, f"{len(fake_whisper)} models loaded concurrently"


def test_stt_whisper_still_exports_get_model():
    """Callers import get_model from stt_whisper; moving it must not break
    them."""
    from backend.ai_modules.speech import stt_whisper

    assert stt_whisper.get_model is m.get_model
