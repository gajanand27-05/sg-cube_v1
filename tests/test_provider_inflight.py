"""_inflight must return to zero on every path — it is the UI's queue_depth.

LLMProvider.generate incremented _inflight, then decremented it in `finally`.
The no-fallback error path decremented a *second* time before re-raising, so
every failure with no backup backend drove the counter one further below zero.
AIMetricsEvent.queue_depth reports _inflight straight to the AI Core panel, so
the readout went negative and stayed wrong for the life of the process.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.llm.provider import LLMProvider
from backend.ai_modules.llm.routing import TaskType


class _Backend:
    """Duck-typed backend. Fails if `boom` is set."""

    def __init__(self, name: str, boom: bool = False):
        self._name = name
        self._boom = boom
        self.calls = 0

    def active_model_name(self) -> str:
        return self._name

    async def generate(self, prompt, **kwargs) -> str:
        self.calls += 1
        if self._boom:
            raise RuntimeError(f"{self._name} exploded")
        return f"{self._name} says hi"


def _provider(*backends: _Backend) -> LLMProvider:
    p = LLMProvider()
    for b in backends:
        p.register(b._name, b)
    primary = backends[0]._name
    p.policy.select = lambda task: primary  # type: ignore[method-assign]
    return p


@pytest.fixture
def fallback_backend(monkeypatch):
    """_get_fallback_backend reads settings.llm_fallback_backend — registering a
    second backend is not enough to make one eligible."""
    from backend.server.config import settings

    def _set(name: str):
        monkeypatch.setattr(settings, "llm_fallback_backend", name, raising=False)

    return _set


@pytest.fixture(autouse=True)
def no_ambient_fallback(monkeypatch):
    """Keep the no-fallback tests honest regardless of the developer's .env."""
    from backend.server.config import settings
    monkeypatch.setattr(settings, "llm_fallback_backend", "", raising=False)


@pytest.mark.asyncio
async def test_inflight_returns_to_zero_on_success():
    p = _provider(_Backend("primary"))
    await p.generate("hi", task=TaskType.GENERAL)
    assert p._inflight == 0


@pytest.mark.asyncio
async def test_inflight_returns_to_zero_when_there_is_no_fallback():
    """The regression. One backend, it fails, the error propagates — and the
    counter must land on 0, not -1."""
    p = _provider(_Backend("only", boom=True))

    with pytest.raises(RuntimeError):
        await p.generate("hi", task=TaskType.GENERAL)

    assert p._inflight == 0, f"double-decrement: _inflight is {p._inflight}"


@pytest.mark.asyncio
async def test_repeated_failures_do_not_drive_inflight_negative():
    """queue_depth is read live, so a negative counter poisons every later
    reading for the process lifetime — not just the failing call."""
    p = _provider(_Backend("only", boom=True))

    for _ in range(5):
        with pytest.raises(RuntimeError):
            await p.generate("hi", task=TaskType.GENERAL)

    assert p._inflight == 0, f"_inflight drifted to {p._inflight} over 5 failures"


@pytest.mark.asyncio
async def test_inflight_returns_to_zero_after_a_successful_fallback(fallback_backend):
    primary = _Backend("primary", boom=True)
    backup = _Backend("backup")
    p = _provider(primary, backup)
    fallback_backend("backup")

    result = await p.generate("hi", task=TaskType.GENERAL)

    assert "backup" in result
    assert backup.calls == 1
    assert p._inflight == 0


@pytest.mark.asyncio
async def test_inflight_returns_to_zero_when_the_fallback_also_fails(fallback_backend):
    p = _provider(_Backend("primary", boom=True), _Backend("backup", boom=True))
    fallback_backend("backup")

    with pytest.raises(RuntimeError):
        await p.generate("hi", task=TaskType.GENERAL)

    assert p._inflight == 0
