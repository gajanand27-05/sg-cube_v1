"""Phase 3 — assistant-populated canvas.

Strict schema validation server-side. The assistant emits a list of typed
widget dicts; this module validates against an enumerated set with
`extra="forbid"` at every level, then emits ONE `canvas_update` event that
the frontend maps schema → React component (no dangerouslySetInnerHTML,
default text escaping — grep-tested in tests/test_no_dangerous_inner_html.py).

Load-bearing invariants (both testable):

  1. Only these widget types render:
       "metric" | "list" | "map" | "chart" | "text"
     Anything else fails validation before the WS event fires.
  2. Extra fields at any level fail validation (`extra="forbid"`).
  3. Map embed URLs must match the host allowlist below.
  4. Text fields carry through as data; the frontend renders as plain text.
     There is no path where model output becomes executable markup.

Untrusted-data composition with Phase 2:
  Data tools set `is_external_data=true` on their envelope when the payload
  originated from the open web (get_news_data). The Planner directive treats
  those payloads as data. When the Planner emits render_canvas with an
  untrusted string in a widget field, the widget renders it as plain text
  — no code path elevates it to instructions or markup.
"""
from __future__ import annotations

import logging
import json
from typing import Annotated, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from backend.core.events import get_bus, Priority
from backend.core.tools.registry import CapabilityTier, ToolResult, tool
from backend.daemon.ui_events import CanvasUpdateEvent

log = logging.getLogger(__name__)


# ── Widget schema — strict, discriminated by `type` ─────────────────────

class _StrictBase(BaseModel):
    """Base for every widget model. `extra="forbid"` = unknown fields
    fail validation, which is the load-bearing decision for this whole
    schema. Do NOT relax to "ignore"."""
    model_config = ConfigDict(extra="forbid")


class MetricWidget(_StrictBase):
    type: Literal["metric"]
    id: str
    title: str
    value: float | str
    delta: float | None = None
    delta_pct: float | None = None
    unit: str = ""
    source: str = ""
    fetched_at: str = ""
    stale: bool = False


class ListItem(_StrictBase):
    text: str          # plain text — rendered escaped
    subtitle: str = ""


class ListWidget(_StrictBase):
    type: Literal["list"]
    id: str
    title: str
    items: list[ListItem]
    source: str = ""
    fetched_at: str = ""
    stale: bool = False


class MapWidget(_StrictBase):
    type: Literal["map"]
    id: str
    title: str
    embed_url: str     # validated against host allowlist below
    lat: float | None = None
    lon: float | None = None
    source: str = ""
    fetched_at: str = ""
    stale: bool = False


class ChartPoint(_StrictBase):
    x: str
    y: float


class ChartWidget(_StrictBase):
    type: Literal["chart"]
    id: str
    title: str
    series: list[ChartPoint]
    unit: str = ""
    source: str = ""
    fetched_at: str = ""
    stale: bool = False


class TextWidget(_StrictBase):
    type: Literal["text"]
    id: str
    title: str
    body: str          # plain text — rendered escaped
    source: str = ""
    fetched_at: str = ""
    stale: bool = False


# Discriminated union — pydantic uses `type` to pick the model. An
# unrecognised type value fails validation with a clear error.
Widget = Annotated[
    Union[MetricWidget, ListWidget, MapWidget, ChartWidget, TextWidget],
    Field(discriminator="type"),
]

_WIDGET_LIST_TA = TypeAdapter(list[Widget])


# ── Map embed host allowlist ────────────────────────────────────────────
# Only these hosts may become iframe src on the frontend. An attacker-
# supplied MapWidget.embed_url outside this set is rejected server-side
# BEFORE the WS event is emitted.
_ALLOWED_MAP_HOSTS: set[str] = {
    "www.openstreetmap.org",
    "openstreetmap.org",
}


def _validate_map_embed(url: str) -> str | None:
    """Return an error string if the map embed URL is not on the allowlist,
    else None."""
    try:
        p = urlparse(url)
    except Exception as e:
        return f"could not parse URL: {e}"
    if p.scheme != "https":
        return f"map embed URL must use https, got {p.scheme!r}"
    host = (p.hostname or "").lower()
    if host not in _ALLOWED_MAP_HOSTS:
        return (
            f"map embed host {host!r} not in allowlist "
            f"(allowed: {sorted(_ALLOWED_MAP_HOSTS)})"
        )
    return None


# ── The tool ────────────────────────────────────────────────────────────

@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=False)
def render_canvas(widgets: list) -> ToolResult:
    """Populate the assistant canvas with a layout of widgets.

    `widgets` is a list of widget objects, each with a required `type`
    field ("metric" | "list" | "map" | "chart" | "text") and props
    matching that type's strict schema. Extra fields are rejected.
    Map widgets have their `embed_url` validated against the host
    allowlist. Only when validation passes does a `canvas_update` WS
    event fire.

    Renders as plain text on the frontend. No markup, no scripts, no
    dangerouslySetInnerHTML. This tool never emits UI — it emits data
    the frontend maps to typed React components."""
    if not isinstance(widgets, list):
        # Occasionally the LLM passes a JSON string despite the schema
        # advertising array; be forgiving on that one shape mismatch.
        if isinstance(widgets, str):
            try:
                widgets = json.loads(widgets)
            except json.JSONDecodeError as e:
                return ToolResult.blocked(f"canvas schema invalid: widgets must be a JSON array ({e})")
        else:
            return ToolResult.blocked(
                f"canvas schema invalid: widgets must be a list, got {type(widgets).__name__}"
            )

    if not widgets:
        return ToolResult.blocked("canvas schema invalid: widgets list is empty")

    # ── STRICT validation ─────────────────────────────────────────────
    try:
        validated = _WIDGET_LIST_TA.validate_python(widgets)
    except ValidationError as e:
        # Surface the first error so the Planner can course-correct.
        errs = e.errors()
        first = errs[0] if errs else {"msg": str(e)}
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = first.get("msg", "validation error")
        return ToolResult.blocked(
            f"canvas schema invalid at {loc!r}: {msg}",
            confidence_reason=[
                f"validator rejected {len(errs)} error(s)",
                "no canvas_update event was emitted",
            ],
        )

    # ── Map allowlist enforcement ─────────────────────────────────────
    for w in validated:
        if isinstance(w, MapWidget):
            err = _validate_map_embed(w.embed_url)
            if err:
                return ToolResult.blocked(
                    f"canvas map widget rejected: {err}",
                    confidence_reason=["embed host allowlist", "no canvas_update event was emitted"],
                )

    # ── Emit the WS event ─────────────────────────────────────────────
    payload = [w.model_dump() for w in validated]
    event = CanvasUpdateEvent(widgets=payload)
    get_bus().publish(event, priority=Priority.NORMAL)

    return ToolResult.success(
        message=f"rendered {len(validated)} widget(s) on canvas",
        data={"widget_count": len(validated), "types": [w.type for w in validated]},
        confidence=95.0,
        confidence_reason=[
            "strict schema validated (extra='forbid')",
            "map embed URLs checked against allowlist",
        ],
    )
