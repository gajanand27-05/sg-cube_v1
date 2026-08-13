"""Embedding calls must fail fast when the backend is not there.

Measured 2026-08-13 with local Ollama stopped: one httpx POST to a refused
127.0.0.1:11434 takes ~2.18s on Windows. Not our retries, not Chroma — a single
TCP connect, which Windows retransmits instead of failing on the first RST.
ContextBuilder.collect() makes two embed calls per turn (LTM + visual), so
every voice turn paid ~4.3s of dead time BEFORE the planner started, and the
only symptom was an assistant that felt broken. Ollama being down is not
hypothetical here: it once ran that way for a day, which is how 32 of 37
long-term memories ended up unsearchable.

After: 2214ms -> 746ms for the first turn, and 26ms for every turn after.

Everything below mocks httpx, so the results do not depend on whether Ollama
happens to be running when the suite is run.
"""
import sys
import time
from pathlib import Path

import httpx
import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.llm import ollama_client as oc


@pytest.fixture(autouse=True)
def clean_breaker():
    oc.reset_embed_breaker()
    yield
    oc.reset_embed_breaker()


class _Client:
    """Stands in for httpx.Client, recording whether a connection was tried."""
    attempts = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _Client.last_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *_a, **_k):
        _Client.attempts += 1
        raise self.error


def _refusing_client(monkeypatch, error=None):
    _Client.attempts = 0
    _Client.error = error or httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "Client", _Client)
    return _Client


def test_a_connect_failure_stops_the_next_call_from_connecting(monkeypatch):
    """The whole point: the second call must not spend 2s learning what the
    first one already found out."""
    client = _refusing_client(monkeypatch)

    with pytest.raises(httpx.ConnectError):
        oc.embed("first")
    assert client.attempts == 1

    with pytest.raises(httpx.ConnectError):
        oc.embed("second")
    assert client.attempts == 1, "the breaker was open but a connection was still attempted"


def test_the_breaker_reopens_after_the_cooldown(monkeypatch):
    """A sticky breaker would keep memory dead long after Ollama came back —
    and it is usually restarted by hand while the assistant is running."""
    client = _refusing_client(monkeypatch)
    with pytest.raises(httpx.ConnectError):
        oc.embed("x")
    assert client.attempts == 1

    monkeypatch.setattr(oc, "_embed_down_until", time.monotonic() - 0.01)
    with pytest.raises(httpx.ConnectError):
        oc.embed("x")
    assert client.attempts == 2, "cooldown expired but the call was still skipped"


def test_an_http_error_does_not_trip_the_breaker(monkeypatch):
    """A 500 means something IS listening. Suppressing calls for 5s over a
    server-side error would turn a recoverable blip into dead memory."""
    client = _refusing_client(
        monkeypatch,
        error=httpx.HTTPStatusError("500", request=None, response=None),
    )
    with pytest.raises(httpx.HTTPStatusError):
        oc.embed("x")
    with pytest.raises(httpx.HTTPStatusError):
        oc.embed("x")
    assert client.attempts == 2, "an HTTP error opened the breaker"


def test_a_success_clears_a_previous_failure(monkeypatch):
    """Otherwise one blip leaves the breaker armed until the cooldown, even
    though the very next call proved the backend is healthy."""
    class _Ok(_Client):
        def post(self, *_a, **_k):
            _Client.attempts += 1
            class R:
                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    # Width is not validated here — ProviderEmbeddingFunction
                    # is what rejects an unusable vector. This only has to be
                    # a successful response.
                    return {"embedding": [0.1] * 768}
            return R()

    oc._note_embed_failure()
    assert oc._embed_breaker_open()

    _Client.attempts = 0
    monkeypatch.setattr(httpx, "Client", _Ok)
    monkeypatch.setattr(oc, "_embed_down_until", 0.0)   # pretend cooldown lapsed
    oc.embed("x")
    assert not oc._embed_breaker_open(), "a successful embed left the breaker armed"


def test_the_connect_timeout_is_actually_applied(monkeypatch):
    """The breaker only helps from the SECOND call. The first still connects,
    so its connect timeout is what caps the cost of a cold start."""
    client = _refusing_client(monkeypatch)
    with pytest.raises(httpx.ConnectError):
        oc.embed("x")

    timeout = client.last_kwargs.get("timeout")
    assert isinstance(timeout, httpx.Timeout), f"got {timeout!r}"
    assert timeout.connect == oc.EMBED_CONNECT_TIMEOUT_S
    assert oc.EMBED_CONNECT_TIMEOUT_S <= 1.0, (
        "a loopback Ollama answers in single-digit ms or is not running; a long "
        "connect timeout puts that wait on every turn's critical path"
    )


# ── the same cost on the OTHER local calls ───────────────────────────────
#
# embed is not the only thing pointed at local Ollama. RoutingPolicy sends
# TaskType.VERIFICATION and INTENT_CLASSIFICATION to "ollama" unconditionally
# (not _cloud_or), and the verifier's secondary check runs on the critical path
# for every SYSTEM_WRITE and DESTRUCTIVE tool call. With Ollama down each of
# those paid the same ~2.18s connect before failing closed. Fixing embed and
# leaving these is the sibling-caller miss that has already bitten this repo.

def test_local_generate_gets_the_short_connect_timeout():
    assert oc._timeout_for("http://127.0.0.1:11434", 30.0).connect == oc.EMBED_CONNECT_TIMEOUT_S
    assert oc._timeout_for("http://localhost:11434", 30.0).connect == oc.EMBED_CONNECT_TIMEOUT_S


def test_the_cloud_keeps_its_full_connect_timeout():
    """The load-bearing half. Applying the loopback figure to the cloud would
    turn a merely slow network into an outage — half a second is an ordinary
    internet handshake."""
    assert oc._timeout_for("https://ollama.com", 30.0).connect == 30.0


def test_read_timeout_is_never_shortened():
    """Only the CONNECT phase is capped. A local model legitimately takes tens
    of seconds to generate, and clipping that would break generation itself."""
    for url in ("http://127.0.0.1:11434", "https://ollama.com"):
        assert oc._timeout_for(url, 60.0).read == 60.0


def test_generate_has_no_breaker_on_purpose():
    """Deliberate asymmetry, recorded so it is not "tidied up" later.

    A suppressed EMBED degrades to an empty memory search, which callers
    already handle. A suppressed VERIFICATION call fails closed and REJECTS a
    tool the user asked for — so a breaker there could wrongly refuse an action
    in the window right after Ollama comes back. The connect timeout is safe
    for both; the breaker is not.
    """
    import inspect
    assert "_embed_breaker_open" not in inspect.getsource(oc.generate)
    assert "_embed_breaker_open" in inspect.getsource(oc.embed)
