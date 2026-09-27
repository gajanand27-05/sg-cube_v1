"""remember / set_preference say so when the memory store refused.

LongTermMemory.store returns False when it cannot store (the embedding model
is unavailable, or the write failed); remember_fact dropped that and the
tool said "I'll remember that". The store is faked here.
"""
import pytest

from backend.core.memory.manager import memory as manager
from backend.core.tools.registry import REGISTRY


@pytest.fixture
def store(monkeypatch):
    state = {"ok": True, "stored": []}

    def fake_store(entry):
        if state["ok"]:
            state["stored"].append(entry.content)
        return state["ok"]
    monkeypatch.setattr(manager.ltm, "store", fake_store)
    return state


@pytest.mark.parametrize("tool", ["remember", "set_preference"])
def test_a_refused_write_is_an_error(store, tool):
    store["ok"] = False
    res = REGISTRY[tool].func("my cat is named Luna")
    assert res["status"] == "error"
    assert "couldn't save" in res["reason"]
    assert store["stored"] == []


@pytest.mark.parametrize("tool", ["remember", "set_preference"])
def test_a_stored_write_is_success(store, tool):
    res = REGISTRY[tool].func("my cat is named Luna")
    assert res["status"] == "success"
    assert store["stored"] == ["my cat is named Luna"]


def test_the_manager_passes_the_result_through(store):
    store["ok"] = False
    assert manager.remember_fact("x") is False
    assert manager.remember_preference("x") is False
    store["ok"] = True
    assert manager.remember_fact("x") is True
