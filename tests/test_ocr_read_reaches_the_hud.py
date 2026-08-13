"""Read mode's output has to arrive at the HUD, over a real socket.

OcrReadEvent was published by DetectionRunner._read_submit and consumed by
nobody: it had no entry in the frontend's UiEventPayloadMap, no crash-guard
entry and no panel, so Read mode's entire output was spoken and otherwise
invisible. Navigate has its obstacle chips and Scan has the health counters;
Read had nothing.

Deliberately a wire-level probe rather than an assertion about TYPE_MAP.
Membership in TYPE_MAP is wiring, not delivery — it is a dict literal, and a
dict literal is exactly the kind of evidence that has passed here while the
feature was dead. This publishes on the real bus, through the real bridge,
into a real WebSocket, and reads the JSON back off it.
"""
import json
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.events import get_bus, init_event_bus
from backend.daemon.ui_events import OcrReadEvent
from backend.server.routes import ui as ui_route

LOOPBACK = ("127.0.0.1", 4000)
RECEIVE_TIMEOUT_S = 5.0

# What the HUD's REQUIRED_FIELDS guard demands of an ocr_read payload. Listed
# here rather than parsed, so this file states the contract it is testing;
# tests/test_event_contract.py is what keeps the two declarations honest.
HUD_REQUIRED = {"text": str, "confidence": float}


@pytest.fixture(scope="module")
def ws_client():
    """A real app with the event bus RUNNING.

    Without the lifespan the bus enqueues and nothing drains it, so a publish
    is silently dropped and every read below blocks forever — the delivery gap
    this file exists to detect, and the reason a fake-bus test cannot stand in
    for it: the other bus tests in this suite assert that publish() was called,
    which stays true when nothing is listening.

    Module-scoped on purpose. init_event_bus() constructs a NEW bus each call,
    while ws_ui's bridge subscribes once and latches `_bridge_setup` — so a
    per-test bus leaves the bridge subscribed to the previous, discarded one
    and every event vanishes. One bus, one bridge, one client for the module;
    each test still opens its own socket.
    """
    @asynccontextmanager
    async def lifespan(_app):
        bus = init_event_bus()
        await bus.start()
        yield
        await bus.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(ui_route.router)
    with TestClient(app, client=LOOPBACK) as client:
        yield client


def _receive(ws, count: int = 1) -> list[dict]:
    """Read exactly `count` frames, failing rather than hanging.

    TestClient's websocket has no receive timeout, so a frame that never
    arrives blocks the entire suite instead of failing the test — which is
    exactly what the first version of this file did. The read runs on a daemon
    thread with a deadline, so a delivery regression reports itself and the
    interpreter can still exit.
    """
    out: queue.Queue = queue.Queue()

    def _read():
        try:
            out.put([json.loads(ws.receive_text()) for _ in range(count)])
        except Exception as exc:  # socket closed under us
            out.put(exc)

    threading.Thread(target=_read, daemon=True).start()
    try:
        result = out.get(timeout=RECEIVE_TIMEOUT_S)
    except queue.Empty:
        pytest.fail(
            f"expected {count} frame(s) on /ws/ui within {RECEIVE_TIMEOUT_S}s; "
            "nothing arrived — the event was published but never delivered"
        )
    if isinstance(result, Exception):
        pytest.fail(f"/ws/ui read failed: {result!r}")
    return result


def test_an_ocr_line_crosses_the_socket_as_ocr_read(ws_client):
    with ws_client.websocket_connect("/ws/ui") as ws:
        get_bus().publish(OcrReadEvent(text="PLATFORM 4", confidence=0.91))
        (message,) = _receive(ws)

    assert message["type"] == "ocr_read", (
        f"OcrReadEvent crossed the wire as {message['type']!r}; the HUD "
        "subscribes to 'ocr_read' and ignores anything else"
    )
    assert message["payload"]["text"] == "PLATFORM 4"
    assert message["payload"]["confidence"] == pytest.approx(0.91)


def test_the_payload_carries_every_field_the_hud_refuses_to_render_without(ws_client):
    """REQUIRED_FIELDS drops the whole event if one field is missing or the
    wrong type — silently, by design. That drop is invisible on both sides, so
    the shape has to be asserted here."""
    with ws_client.websocket_connect("/ws/ui") as ws:
        get_bus().publish(OcrReadEvent(text="EXIT", confidence=0.77))
        (message,) = _receive(ws)

    payload = message["payload"]
    for field, expected in HUD_REQUIRED.items():
        assert field in payload, f"HUD requires {field!r}; payload has {sorted(payload)}"
        assert isinstance(payload[field], expected), (
            f"{field} arrived as {type(payload[field]).__name__}, "
            f"HUD expects {expected.__name__} and drops the event otherwise"
        )


def test_each_line_arrives_separately_and_in_order(ws_client):
    """Read mode publishes one event per recognized line, and the panel renders
    them as a running transcript — so ordering and separation are part of the
    contract, not an implementation detail."""
    with ws_client.websocket_connect("/ws/ui") as ws:
        get_bus().publish(OcrReadEvent(text="FIRST", confidence=0.9))
        get_bus().publish(OcrReadEvent(text="SECOND", confidence=0.9))
        first, second = _receive(ws, 2)

    assert [first["type"], second["type"]] == ["ocr_read", "ocr_read"]
    assert [first["payload"]["text"], second["payload"]["text"]] == ["FIRST", "SECOND"]
