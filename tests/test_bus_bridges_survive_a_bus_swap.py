"""Both WebSocket bridges must follow the bus, not latch onto one instance.

There are two of them — ws_ui.UIEventManager for the desktop HUD and
remote.RemoteManager for Android devices — and they are parallel
implementations of the same idea. remote.py's own comment says "same fix as
ws_ui.UIEventManager.connect", which is how they drifted: ws_ui was fixed on
2026-08-13 and remote.py was left with the identical defect until this file.

The defect: `init_event_bus()` constructs a NEW AsyncEventBus on every call,
while both bridges recorded "am I subscribed?" as a bool. Once that bool was
set, a subsequent bus swap left the bridge subscribed to a discarded object.
Every publish then succeeded, reached no one, and logged nothing — the HUD and
every connected phone simply went quiet forever.

Same story for the event loop: both cache one, and both silently skip the
broadcast when it is not running, so a replaced loop is permanently fatal and
remote.py even logs "no active loop captured yet" — the opposite of what
happened.

Parametrized over both managers on purpose. One test that names both is what
keeps a fix to either from being a fix to only one.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import events
from backend.core.events import AsyncEventBus, get_bus


def _ws_ui_manager():
    from backend.server.ws_ui import get_manager
    return get_manager()


def _remote_manager():
    from backend.server.routes import remote
    return remote.manager


MANAGERS = [
    pytest.param(_ws_ui_manager, id="ws_ui.UIEventManager"),
    pytest.param(_remote_manager, id="remote.RemoteManager"),
]


@pytest.fixture(autouse=True)
def restore_bus():
    original = events.bus
    yield
    events.bus = original
    # Leave both bridges pointing at the restored bus for the next test.
    for get_mgr in (_ws_ui_manager, _remote_manager):
        mgr = get_mgr()
        mgr._bridged_bus = None
        mgr._setup_event_bridge()


@pytest.mark.parametrize("get_mgr", MANAGERS)
def test_bridge_records_the_bus_instance_not_a_bool(get_mgr):
    """A bool cannot express "which bus", which is the whole bug."""
    mgr = get_mgr()
    mgr._bridged_bus = None
    mgr._setup_event_bridge()
    assert mgr._bridged_bus is get_bus()
    assert not isinstance(mgr._bridged_bus, bool)


@pytest.mark.parametrize("get_mgr", MANAGERS)
def test_bridge_resubscribes_after_the_bus_is_replaced(get_mgr):
    """The production failure: init_event_bus() swaps the global, and a bridge
    that latched on the old one goes silent forever."""
    mgr = get_mgr()
    mgr._bridged_bus = None
    mgr._setup_event_bridge()

    events.bus = AsyncEventBus()          # what init_event_bus() does
    assert mgr._bridged_bus is not events.bus, "precondition: bridge is now stale"

    mgr._setup_event_bridge()
    assert mgr._bridged_bus is events.bus, (
        "bridge did not follow the bus swap — every published event would "
        "reach the discarded instance and no client would ever be told"
    )
    # ...and it is genuinely subscribed on the new bus, not just bookkeeping.
    subscribed = any(mgr._broadcast_event in subs
                     for subs in events.bus._subscribers.values())
    assert subscribed, "bridge recorded the new bus but never subscribed to it"


@pytest.mark.parametrize("get_mgr", MANAGERS)
def test_resubscribing_to_the_same_bus_is_idempotent(get_mgr):
    """connect() calls this on every client, so a duplicate subscription would
    deliver each event twice per reconnect."""
    mgr = get_mgr()
    mgr._bridged_bus = None
    mgr._setup_event_bridge()
    before = sum(subs.count(mgr._broadcast_event)
                 for subs in get_bus()._subscribers.values())

    for _ in range(3):
        mgr._setup_event_bridge()

    after = sum(subs.count(mgr._broadcast_event)
                for subs in get_bus()._subscribers.values())
    assert after == before, f"subscriptions grew {before} -> {after} on repeat setup"
