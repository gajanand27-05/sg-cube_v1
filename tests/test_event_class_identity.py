"""Every module must hold the SAME event class object, not one that looks like it.

The bus dispatches on class identity: `bus.subscribe(SomeEvent, cb)` matches a
published object by `type(event)`, and ws_ui's TYPE_MAP is keyed the same way.
So a module holding a different-but-identical-looking class publishes into
silence — the publisher publishes, the subscriber waits, nothing logs anything.

That has now happened three times here:
  * healing.py defined a second SelfHealingEvent (never constructed, so only a
    loaded gun).
  * agents/base.py defined its own InternalAgentEvent and TokenStreamEvent and
    published them on every _emit — twelve call sites across Guardian, Operator
    and Planner, all landing nowhere, for every turn the assistant ever took.

tests/test_every_event_has_a_publisher.py catches the STATIC shape of that: a
duplicate `class` statement. This file catches the shape it cannot see — a
module that imported the right name from the wrong place, or rebound it — by
comparing the actual objects after the app is loaded. Same silence, different
cause, and a duplicate-class scan would pass right over it.
"""
import sys

import pytest

# Importing the app is what populates sys.modules with the real graph — the
# agents, the routes, the daemon wiring. Without it this test would inspect
# whatever happened to be imported by earlier tests, which varies by run order.
import backend.server.main  # noqa: F401
import backend.core.agents.commander  # noqa: F401
import backend.core.agents.operator  # noqa: F401
import backend.core.agents.guardian  # noqa: F401
import backend.core.agents.planner  # noqa: F401
import backend.core.agents.registry  # noqa: F401
from backend.server.ws_ui import TYPE_MAP

CANONICAL = {cls.__name__: cls for cls in TYPE_MAP}


def _backend_modules():
    return [m for name, m in list(sys.modules.items())
            if name.startswith("backend.") and m is not None]


def test_the_scan_actually_loaded_the_app():
    """A scan over an empty module list passes by checking nothing."""
    modules = _backend_modules()
    assert len(modules) > 40, f"only {len(modules)} backend modules loaded"
    assert len(CANONICAL) > 25, f"only {len(CANONICAL)} event classes in TYPE_MAP"


@pytest.mark.parametrize("event_name", sorted(CANONICAL))
def test_no_module_holds_a_look_alike_of(event_name):
    canonical = CANONICAL[event_name]
    impostors = []
    for module in _backend_modules():
        held = getattr(module, event_name, None)
        if held is None or held is canonical:
            continue
        if isinstance(held, type):
            impostors.append(f"{module.__name__} holds {held.__module__}.{held.__qualname__}")
    assert not impostors, (
        f"{event_name}: these modules hold a DIFFERENT class of the same name, so "
        f"anything they publish is invisible to every subscriber:\n  "
        + "\n  ".join(impostors)
    )


def test_emit_publishes_what_ws_ui_bridges():
    """The concrete case that was broken, kept as a named regression."""
    from backend.core.agents.base import InternalAgentEvent
    from backend.daemon.ui_events import InternalAgentEvent as canonical

    assert InternalAgentEvent is canonical
    assert TYPE_MAP[InternalAgentEvent] == "agent_status"


def test_a_deliberate_impostor_is_detected():
    """Proves the check can fail. Without this, a scan that silently stopped
    resolving classes would look identical to a clean codebase."""
    import types

    fake_module = types.ModuleType("backend.fake_shadow_module")
    canonical = CANONICAL["InternalAgentEvent"]
    shadow = type("InternalAgentEvent", (), {})
    setattr(fake_module, "InternalAgentEvent", shadow)
    sys.modules["backend.fake_shadow_module"] = fake_module
    try:
        held = [m for m in _backend_modules()
                if getattr(m, "InternalAgentEvent", None) not in (None, canonical)]
        assert fake_module in held, "the scan would not have noticed a shadow class"
    finally:
        sys.modules.pop("backend.fake_shadow_module", None)
