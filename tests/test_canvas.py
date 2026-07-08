"""Phase 3 — canvas schema validation + WS event emission.

The strict validator is the whole security posture:
  - unknown widget type → rejected, no event
  - extra field at any level → rejected, no event
  - missing required prop → rejected, no event
  - map embed URL outside the host allowlist → rejected, no event

Only a fully validated payload emits ONE `canvas_update` event.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event, priority=None):
        self.published.append(event)


def _capture_bus():
    bus = _FakeBus()
    return bus, patch("backend.core.tools.canvas.get_bus", return_value=bus)


def _widget(**kw):
    """Minimal metric widget with all required fields."""
    base = {"type": "metric", "id": "m1", "title": "AAPL", "value": 189.44}
    base.update(kw)
    return base


# ── Valid layouts ──────────────────────────────────────────────────────

def test_render_canvas_valid_payload_emits_one_event():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        res = canvas.render_canvas([
            _widget(),
            {"type": "text", "id": "t1", "title": "Note", "body": "Hello"},
        ])
    assert res.status.value == "success"
    assert res.data["widget_count"] == 2
    assert len(bus.published) == 1, f"expected exactly one event, got {len(bus.published)}"
    from backend.daemon.ui_events import CanvasUpdateEvent
    assert isinstance(bus.published[0], CanvasUpdateEvent)
    assert len(bus.published[0].widgets) == 2
    print("  [PASS] valid payload → one canvas_update event")


# ── STRICT validation: unknown type ────────────────────────────────────

def test_render_canvas_rejects_unknown_widget_type():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        res = canvas.render_canvas([{"type": "iframe", "id": "x", "title": "T", "src": "https://a"}])
    assert res.status.value == "blocked", "unknown type must be rejected"
    assert "canvas schema invalid" in (res.reason or "").lower()
    assert len(bus.published) == 0, "no event may fire on invalid payload"
    print("  [PASS] unknown widget type rejected, no event emitted")


# ── STRICT validation: extra field ─────────────────────────────────────

def test_render_canvas_rejects_extra_field():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        payload = _widget(malicious_field="<script>alert(1)</script>")
        res = canvas.render_canvas([payload])
    assert res.status.value == "blocked", "extra field must be rejected (extra='forbid')"
    assert "canvas schema invalid" in (res.reason or "").lower()
    assert len(bus.published) == 0
    print("  [PASS] extra field rejected — extra='forbid' is enforced")


# ── STRICT validation: missing required prop ───────────────────────────

def test_render_canvas_rejects_missing_required_prop():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        # `value` is required on metric
        res = canvas.render_canvas([{"type": "metric", "id": "m", "title": "T"}])
    assert res.status.value == "blocked"
    assert "canvas schema invalid" in (res.reason or "").lower()
    assert len(bus.published) == 0
    print("  [PASS] missing required prop rejected")


# ── STRICT validation: wrong prop type ─────────────────────────────────

def test_render_canvas_rejects_wrong_prop_type():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        # `y` on chart point must be a number
        payload = {
            "type": "chart", "id": "c1", "title": "Series",
            "series": [{"x": "9am", "y": "not-a-number"}],
        }
        res = canvas.render_canvas([payload])
    assert res.status.value == "blocked"
    assert "canvas schema invalid" in (res.reason or "").lower()
    assert len(bus.published) == 0
    print("  [PASS] wrong prop type rejected")


# ── Map embed host allowlist ───────────────────────────────────────────

def test_render_canvas_map_embed_allowlist_enforced():
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()

    # Rejected: not on the allowlist
    with patcher:
        bad = {"type": "map", "id": "m", "title": "T", "embed_url": "https://evil.example.com/embed"}
        res = canvas.render_canvas([bad])
        assert res.status.value == "blocked"
        assert "not in allowlist" in (res.reason or "").lower()
        assert len(bus.published) == 0

    # Rejected: http:// (must be https)
    bus2, patcher2 = _capture_bus()
    with patcher2:
        http_url = {"type": "map", "id": "m", "title": "T", "embed_url": "http://www.openstreetmap.org/embed"}
        res = canvas.render_canvas([http_url])
        assert res.status.value == "blocked"
        assert "https" in (res.reason or "").lower()
        assert len(bus2.published) == 0

    # Accepted: allowlisted host + https
    bus3, patcher3 = _capture_bus()
    with patcher3:
        good = {"type": "map", "id": "m", "title": "T",
                "embed_url": "https://www.openstreetmap.org/export/embed.html?bbox=1,2,3,4"}
        res = canvas.render_canvas([good])
        assert res.status.value == "success"
        assert len(bus3.published) == 1

    print("  [PASS] map embed URLs: non-allowlisted + http rejected, https+allowlisted passes")


# ── The XSS defence — render_canvas holds a payload with attacker HTML ─

def test_render_canvas_html_in_text_field_passes_schema_frontend_escapes():
    """Text fields accept the string as-is — the defence is the frontend's
    default React text rendering (no dangerouslySetInnerHTML). The
    backend-level tests here verify the schema accepts the string but does
    NOT elevate it. The frontend grep test
    (test_no_dangerous_inner_html.py) verifies the render path can't turn
    it into markup."""
    from backend.core.tools import canvas
    bus, patcher = _capture_bus()
    with patcher:
        attack = {"type": "text", "id": "t", "title": "Note",
                  "body": "<script>alert('xss')</script>"}
        res = canvas.render_canvas([attack])
    assert res.status.value == "success", "text widget accepts strings; XSS defence is at render"
    assert len(bus.published) == 1
    payload = bus.published[0].widgets[0]
    # The payload carries the raw string — that's fine because the frontend
    # renders it as plain text ({body} in JSX, no innerHTML).
    assert payload["body"] == "<script>alert('xss')</script>"
    print("  [PASS] HTML string carries through as data — frontend renders as text (grep test verifies)")


if __name__ == "__main__":
    test_render_canvas_valid_payload_emits_one_event()
    test_render_canvas_rejects_unknown_widget_type()
    test_render_canvas_rejects_extra_field()
    test_render_canvas_rejects_missing_required_prop()
    test_render_canvas_rejects_wrong_prop_type()
    test_render_canvas_map_embed_allowlist_enforced()
    test_render_canvas_html_in_text_field_passes_schema_frontend_escapes()
    print("All Phase 3 canvas tests passed.")
