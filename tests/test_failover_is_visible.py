"""When the planner model fails and the fallback answers, the HUD metrics and
the turn log both say so.

The HUD kept a "→ fallback" marker latched forever after the first failover,
and the turn log recorded no model at all, so a turn answered by the local
fallback looked like one answered by the planner model. Backends are fakes.
"""
import asyncio

import pytest

from backend.ai_modules.llm import provider as prov
from backend.ai_modules.llm.routing import TaskType
from backend.core import latency
from backend.daemon.ui_events import AIMetricsEvent


class _Backend(prov.LLMBackend):
    def __init__(self, model, fail=False):
        self.model, self.fail = model, fail

    async def generate(self, prompt, **kw):
        return "ok"

    async def chat_stream(self, messages, **kw):
        if self.fail:
            raise ConnectionError("cloud unreachable")
        yield {"token": "hi", "done": False}
        yield {"token": "", "done": True}

    def active_model_name(self):
        return self.model

    def embed(self, text, **kw):
        return []

    async def aembed(self, text, **kw):
        return []


@pytest.fixture
def published(monkeypatch):
    seen = []
    import backend.core.events as events
    monkeypatch.setattr(events, "get_bus", lambda: type("B", (), {"publish": lambda s, e, **k: seen.append(e)})())
    from backend.server.config import settings
    monkeypatch.setattr(settings, "llm_fallback_backend", "fallback")
    return seen


def _provider(primary_fails):
    p = prov.LLMProvider()
    p.register("cloud", _Backend("gemma4:31b", fail=primary_fails))
    p.register("fallback", _Backend("qwen2.5:7b"))
    p.policy.override(TaskType.PLANNING, "cloud")
    return p


async def _turn(p):
    turn = latency.TurnLatency(request_id="t1")
    latency.current_turn.set(turn)
    async for _ in p.chat_stream([{"role": "user", "content": "x"}], task=TaskType.PLANNING):
        pass
    return turn


def test_a_failover_is_named_in_the_hud_and_the_turn_log(published):
    turn = asyncio.run(_turn(_provider(primary_fails=True)))
    (m,) = [e for e in published if isinstance(e, AIMetricsEvent)]
    assert m.active_model == "qwen2.5:7b" and m.failed_over_from == "gemma4:31b"
    assert turn.to_dict()["llm_calls"] == [
        {"task": "planning", "model": "qwen2.5:7b", "failed_over_from": "gemma4:31b"}]


def test_a_normal_turn_names_the_model_and_no_failover(published):
    turn = asyncio.run(_turn(_provider(primary_fails=False)))
    (m,) = [e for e in published if isinstance(e, AIMetricsEvent)]
    assert m.active_model == "gemma4:31b" and m.failed_over_from == ""
    assert turn.to_dict()["llm_calls"] == [{"task": "planning", "model": "gemma4:31b"}]
