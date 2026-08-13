"""POST /execute returned 500 on every request.

safe_executor.execute() is a coroutine function; the route handler was sync
and called it without awaiting, so `.model_dump()` landed on a coroutine
object and raised AttributeError. Nothing covered the route, so the endpoint
was dead in production while the whole suite stayed green.

These drive the real route through TestClient — a unit test on
safe_executor.execute() would have passed with the bug present, because the
bug lives in the handler, not the executor.
"""
import inspect

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.safe_executor.command_whitelist import HANDLERS
from backend.server.routes import execute as execute_route

LOOPBACK = ("127.0.0.1", 4000)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(execute_route.router)
    # get_any_user falls back to localhost auto-auth when no bearer token is
    # sent, and that fallback checks request.client.host.
    return TestClient(app, client=LOOPBACK)


def test_execute_returns_a_result_not_a_coroutine():
    r = _client().post("/execute", json={"action": "get_time", "target": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["intent"]["action"] == "get_time"
    assert isinstance(body["latency_ms"], int)


def test_execute_blocks_a_dangerous_target_without_erroring():
    """The blocked path returns an ExecutionResult too — it must survive the
    same await, not just the happy path."""
    r = _client().post("/execute", json={"action": "open_app", "target": "rm -rf /"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "blocked"


def test_every_handler_takes_a_parameter_named_intent():
    """executor.execute() dispatches via runtime.run_tool(..., {"intent": ...}),
    which calls func(**args) — so the parameter NAME is the contract. Spelling
    it `_intent` (the usual "unused arg" convention) raises TypeError and the
    action silently degrades to status="error"; get_time and unknown were both
    dead that way, and neither had a test."""
    for action, handler in HANDLERS.items():
        params = list(inspect.signature(handler).parameters)
        assert params == ["intent"], f"{action} -> {handler.__name__}{tuple(params)}"
