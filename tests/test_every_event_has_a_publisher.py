"""Every UI event must be constructed somewhere, or be exempted on purpose.

This repo's most-repeated defect is wiring that looks complete and never fires:
a router imported but never include_router'd, a subscriber for an event nothing
publishes, a stale duplicate class shadowing the real one. Grepping the
definition, the wire-map or the subscriber all say "wired" — only the publish
site says "fires".

An audit on 2026-08-13 found four events in ui_events.py that nothing ever
constructed. Two were deleted, one was given its missing publisher, and one is
exempted below with its reason. The point of this test is not the four; it is
that the fifth has to be a decision rather than an accident.

Deliberately a construction check, not a `bus.publish` check: several events are
built and passed to publish() indirectly, and a stricter test would push people
into inlining rather than into wiring.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
UI_EVENTS = ROOT / "backend" / "daemon" / "ui_events.py"

# Events with no publisher, each here because someone decided so — not because
# nobody noticed. Removing a name from this dict means it must now be published.
INTENTIONALLY_UNPUBLISHED: dict[str, str] = {
    # AgentToolCallEvent lived here until 2026-08-13, on the reasoning that
    # publishing it needed the agent name at tool-execution time and
    # runtime.run_tool has none. That was the wrong layer: OperatorAgent knows
    # its own name and every field the event carries, and now publishes it.
    # Left as a reminder that "needs a design change" deserves re-checking
    # before it becomes permanent.
}


def _event_class_names() -> list[str]:
    tree = ast.parse(UI_EVENTS.read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]


def _constructed_names() -> set[str]:
    """Every name called as `Name(...)` anywhere in backend/, excluding
    ui_events.py itself so a dataclass default can't count as a publish."""
    built: set[str] = set()
    for path in (ROOT / "backend").rglob("*.py"):
        if path == UI_EVENTS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                built.add(node.func.id)
    return built


def test_every_event_is_constructed_somewhere():
    unpublished = set(_event_class_names()) - _constructed_names()
    unexplained = sorted(unpublished - set(INTENTIONALLY_UNPUBLISHED))
    assert not unexplained, (
        "these events are defined but nothing ever constructs one, so every "
        "consumer of them waits forever:\n  " + "\n  ".join(unexplained) +
        "\nEither publish them, delete them, or add them to "
        "INTENTIONALLY_UNPUBLISHED with the reason."
    )


def test_the_exemption_list_does_not_go_stale():
    """An exemption for an event that now HAS a publisher is misinformation —
    the next reader trusts it and skips checking."""
    constructed = _constructed_names()
    wrongly_exempt = sorted(n for n in INTENTIONALLY_UNPUBLISHED if n in constructed)
    assert not wrongly_exempt, (
        f"{wrongly_exempt} are listed as unpublished but are constructed now — "
        "drop them from INTENTIONALLY_UNPUBLISHED"
    )


def test_exemptions_still_exist_as_events():
    """Guards the other direction: a deleted event left behind in the list."""
    names = set(_event_class_names())
    stale = sorted(n for n in INTENTIONALLY_UNPUBLISHED if n not in names)
    assert not stale, f"{stale} no longer exist in ui_events.py"


def test_the_audit_can_actually_see_publishers():
    """If the scan silently stopped resolving anything, every event would look
    unpublished and the first assert would fail loudly — but if it stopped
    finding event CLASSES, everything would pass by checking nothing."""
    names = _event_class_names()
    assert len(names) > 30, f"only found {len(names)} event classes; the parse is broken"
    assert "ObstacleEvent" in names
    assert {"ObstacleEvent", "HapticEvent", "SelfHealingEvent"} <= _constructed_names()


def test_no_event_class_is_defined_twice():
    """A second class with the same name is silent death, not a style problem.

    The bus keys subscribers — and ws_ui's TYPE_MAP keys wire names — on the
    class OBJECT. A shadow definition is a different object, so publishers on
    one side and subscribers on the other never meet, and nothing anywhere logs
    it. This has now happened twice:

      * healing.py's SelfHealingEvent (6720ca3) — never constructed, so it was
        only a loaded gun.
      * agents/base.py's InternalAgentEvent and TokenStreamEvent — actively
        published by BaseInternalAgent._emit, so all twelve _emit call sites
        across Guardian, Operator and Planner went nowhere: no "agent_status"
        on the wire, /agents/status permanently empty.

    The earlier version of this test named SelfHealingEvent specifically, which
    is exactly why the second pair survived it. Checks every event class now.
    """
    # Only classes the bus actually DISPATCHES on. Nested payload types
    # (DetectedObject, MemoryHit, ReliabilityMetrics) travel inside another
    # event's fields, are never subscribed to, and so are harmless to define
    # twice — DetectedObject legitimately exists in both context/types.py and
    # ui_events.py for two unrelated purposes. Flagging those would be noise,
    # and a noisy guard gets muted.
    from backend.server.ws_ui import TYPE_MAP
    event_names = {cls.__name__ for cls in TYPE_MAP}
    definitions: dict[str, list[str]] = {}
    for path in (ROOT / "backend").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in event_names:
                definitions.setdefault(node.name, []).append(path.relative_to(ROOT).as_posix())

    duplicated = {n: sorted(p) for n, p in definitions.items() if len(p) > 1}
    assert not duplicated, (
        "these event classes are defined in more than one place; publishers and "
        "subscribers holding different ones will never meet:\n  "
        + "\n  ".join(f"{n}: {paths}" for n, paths in sorted(duplicated.items()))
    )


def test_emitting_agents_publish_the_bridged_event_class():
    """The specific consequence, pinned end to end: BaseInternalAgent._emit
    must publish the class ws_ui actually bridges, not a look-alike."""
    from backend.core.agents.base import InternalAgentEvent as emitted
    from backend.daemon.ui_events import InternalAgentEvent as bridged
    from backend.server.ws_ui import TYPE_MAP

    assert emitted is bridged, "_emit publishes a shadow class the HUD never sees"
    assert TYPE_MAP[emitted] == "agent_status"


def test_every_apirouter_is_actually_mounted():
    """Same defect family, one layer out: commit 354b250 imported the
    phone_stream router and never include_router'd it, so the WS endpoint did
    not exist while the commit message claimed "registered router". The import
    line reads as wiring; only the include_router call is."""
    trees = {}
    for p in (ROOT / "backend").rglob("*.py"):
        try:
            trees[p] = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

    # Collect real include_router(module.attr) CALLS, not text mentions. A
    # substring search over the sources passes on a commented-out mount and on
    # the import line itself — verified: it did, which is this family's whole
    # point. Only the call node is evidence.
    mounted: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "include_router"
                    and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                    mounted.add(f"{arg.value.id}.{arg.attr}")
                elif isinstance(arg, ast.Name):
                    mounted.add(arg.id)

    unmounted = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            func = node.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "APIRouter":
                continue
            for target in node.targets:
                # Accept mounting on the app OR into a parent router, so a
                # legitimately nested router isn't reported as dead.
                if isinstance(target, ast.Name) and \
                        f"{path.stem}.{target.id}" not in mounted and \
                        target.id not in mounted:
                    unmounted.append(f"{path.relative_to(ROOT).as_posix()}::{target.id}")
    assert not unmounted, (
        "these routers are defined but never include_router'd, so none of their "
        "endpoints exist at runtime:\n  " + "\n  ".join(unmounted)
    )


@pytest.mark.parametrize("event_name", ["SelfHealingEvent"])
def test_ws_ui_maps_the_events_it_forwards(event_name):
    """An event with a publisher but no TYPE_MAP entry crosses the wire under
    its class name instead of its agreed wire name — the same class of silent
    mismatch, one layer out."""
    from backend.server import ws_ui
    names = {cls.__name__ for cls in ws_ui.TYPE_MAP}
    assert event_name in names, f"{event_name} is published but absent from ws_ui.TYPE_MAP"
