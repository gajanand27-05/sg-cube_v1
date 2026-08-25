"""T-proactive-path-never-ran.

    def _run():
        while state_manager.current_state != AssistantState.IDLE:
            time.sleep(1)

`StateMachine` defines `_current_state` and a `current` property. There is no
`current_state` attribute, so this raises AttributeError on the first
iteration — and it sits OUTSIDE the try, so the thread dies before ever
reaching the handler. Every event the Watcher Agent fires is silently
dropped, and nothing in the log says so.

Another wiring-vs-activation case: register_proactive_handler subscribes
correctly, the event publishes correctly, and the subscriber is dead.
"""
import sys
import threading
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import trigger
from backend.daemon.ui_events import ProactiveEvent


def test_state_machine_has_no_current_state_attribute():
    """The guard: name the property that exists, not one that doesn't."""
    assert hasattr(state_manager, "current")
    assert not hasattr(state_manager, "current_state"), (
        "if this ever becomes an alias, the bug this test protects against "
        "stops being detectable — read `current` everywhere instead"
    )


def test_proactive_event_actually_reaches_the_handler(monkeypatch):
    seen: list[str] = []
    ran = threading.Event()

    async def _fake_proactive(query: str):
        seen.append(query)
        ran.set()

    monkeypatch.setattr(trigger, "_handle_proactive_async", _fake_proactive)
    state_manager.transition_to(AssistantState.IDLE)

    trigger.on_proactive_event(ProactiveEvent(query="the kettle has boiled"))

    assert ran.wait(timeout=10), (
        "the proactive thread died before calling the handler"
    )
    assert seen == ["the kettle has boiled"]


def test_proactive_waits_for_idle_then_runs(monkeypatch):
    """It must still defer while a voice turn is in flight."""
    ran = threading.Event()

    async def _fake_proactive(query: str):
        ran.set()

    monkeypatch.setattr(trigger, "_handle_proactive_async", _fake_proactive)
    state_manager.transition_to(AssistantState.SPEAKING)

    trigger.on_proactive_event(ProactiveEvent(query="later please"))
    assert not ran.wait(timeout=1.5), "ran while the assistant was speaking"

    state_manager.transition_to(AssistantState.IDLE)
    assert ran.wait(timeout=10), "never ran once the assistant went idle"


def teardown_function(_fn):
    state_manager.transition_to(AssistantState.IDLE)
