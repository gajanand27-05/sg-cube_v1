"""The Python->TypeScript event contract, which nothing else type-checks.

Three artifacts have to agree and live in two languages:
  * the backend dataclass in daemon/ui_events.py
  * ws_ui.TYPE_MAP, which names it on the wire
  * the frontend's REQUIRED_FIELDS crash guard in hooks/useUiEvents.ts

REQUIRED_FIELDS is the dangerous one. It DROPS any event missing a declared
field, deliberately, so a renamed backend field can't ship a TypeError into
render. The cost is that the same rename silently blanks a panel with no error
anywhere: the backend logs a successful publish, the socket carries it, and the
HUD discards it on arrival. Nothing in either language catches that.

Two fields crossed this boundary on 2026-08-13 (ObstacleEvent.clipped,
VisionHealthEvent.frame_age_measured), which is what prompted pinning it here.

The parsing is regex over TypeScript, which is fragile by nature — so every
test asserts it still found a plausible amount to check. A contract test that
silently stops parsing passes forever while guarding nothing, the same failure
this file exists to prevent.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WS_UI = ROOT / "backend" / "server" / "ws_ui.py"
UI_EVENTS = ROOT / "backend" / "daemon" / "ui_events.py"
FE_HOOKS = ROOT / "frontend" / "src" / "hooks" / "useUiEvents.ts"
FE_TYPES = ROOT / "frontend" / "src" / "lib" / "uiEvents.ts"

# ws_ui._serialize flattens a nested `metrics` dataclass into metric_<name>
# keys and deletes the original, so ConfidenceEvent legitimately satisfies a
# required "metric_tool_success_rate" it does not declare as a field.
FLATTENED = {"metrics": "metric_"}


def _wire_names() -> dict[str, str]:
    """wire name -> backend class name, from ws_ui.TYPE_MAP."""
    block = re.search(r"TYPE_MAP: dict\[type, str\] = \{(.*?)\n\}",
                      WS_UI.read_text(encoding="utf-8"), re.S)
    assert block, "TYPE_MAP not found — ws_ui.py was restructured"
    return {wire: cls for cls, wire in re.findall(r"(\w+):\s*\"(\w+)\"", block.group(1))}


def _backend_fields() -> dict[str, list[str]]:
    """class name -> annotated field names, across all of backend/."""
    out: dict[str, list[str]] = {}
    for path in (ROOT / "backend").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields = [s.target.id for s in node.body
                          if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
                if fields:
                    out.setdefault(node.name, fields)
    return out


def _required_fields() -> dict[str, list[str]]:
    """wire name -> fields the HUD dereferences and will drop the event over."""
    block = re.search(r"const REQUIRED_FIELDS[^=]*=\s*\{(.*?)\n\};",
                      FE_HOOKS.read_text(encoding="utf-8"), re.S)
    assert block, "REQUIRED_FIELDS not found — useUiEvents.ts was restructured"
    return {m.group(1): re.findall(r"(\w+):\s*\"(?:number|string|boolean)\"", m.group(2))
            for m in re.finditer(r"(\w+):\s*\{([^}]*)\}", block.group(1))}


def _subscribed_wire_names() -> dict[str, set[str]]:
    """wire name -> files subscribing to it, over every subscription hook."""
    hooks = r"useUiEvent|useUiEventEnvelope|useUiEventListener|useUiEventCounter"
    out: dict[str, set[str]] = {}
    for path in (ROOT / "frontend" / "src").rglob("*.ts*"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(rf"\b({hooks})\b\(\s*\"(\w+)\"", text):
            out.setdefault(m.group(2), set()).add(path.name)
    return out


# ── the parsers themselves ───────────────────────────────────────────

def test_every_parser_still_finds_something():
    """Each regex below feeds an assertion. If one stops matching, its test
    passes by checking an empty set — so pin plausible sizes here instead."""
    assert len(_wire_names()) > 25
    assert len(_backend_fields()) > 30
    assert len(_required_fields()) > 15
    assert len(_subscribed_wire_names()) > 10


# ── the contract ─────────────────────────────────────────────────────

def test_no_required_field_is_missing_from_its_backend_event():
    """The silent-drop bug: the HUD refuses any event lacking a declared field,
    so a backend rename blanks the panel with no error on either side."""
    wire_to_class, fields = _wire_names(), _backend_fields()
    problems = []
    for wire, required in sorted(_required_fields().items()):
        cls = wire_to_class.get(wire)
        if cls is None:
            problems.append(f"{wire}: guarded by the HUD but no backend event maps to it")
            continue
        have = set(fields.get(cls, []))
        for nested, prefix in FLATTENED.items():
            if nested in have:
                have |= {f"{prefix}{n}" for n in fields.get("ReliabilityMetrics", [])}
        missing = [f for f in required if f not in have]
        if missing:
            problems.append(f"{wire} ({cls}): HUD requires {missing}, event has {sorted(have)}")
    assert not problems, "\n".join(problems)


def test_every_hud_subscription_has_a_backend_publisher():
    """A panel subscribing to a wire name nothing emits renders empty forever
    and looks like a backend outage."""
    wire = set(_wire_names())
    orphans = {n: sorted(f) for n, f in _subscribed_wire_names().items() if n not in wire}
    assert not orphans, f"HUD subscribes to wire names the backend never sends: {orphans}"


def test_flattening_rule_is_still_real():
    """FLATTENED encodes behaviour in ws_ui._serialize. If that flattening is
    removed, this file would start excusing a genuine mismatch."""
    source = WS_UI.read_text(encoding="utf-8")
    assert 'd[f"metric_{k}"] = v' in source, (
        "ws_ui._serialize no longer flattens `metrics` into metric_* keys — "
        "drop FLATTENED here, and ConfidenceEvent becomes a real mismatch"
    )


@pytest.mark.parametrize("wire, field", [
    # obstacle/distance_m and vision_health/frame_age_ms were the original two;
    # both events were removed with the phone-camera subsystem. Replaced rather
    # than dropped — spot-checks with named values are the only thing here that
    # still bites when the generic check goes vacuous.
    ("vision_update", "description"),
    ("stt_partial", "is_final"),
    ("ai_metrics", "active_model"),
])
def test_known_fields_resolve_end_to_end(wire, field):
    """Spot-checks with named values, so a refactor that makes the generic
    check vacuous still trips on something concrete."""
    cls = _wire_names()[wire]
    assert field in _backend_fields()[cls]
