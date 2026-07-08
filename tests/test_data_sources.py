"""Phase 3 — data-source tools return the provenance envelope, cache
correctly, serve stale on provider error, and frame external content
under the Phase 2 untrusted-data flag.

All network calls are mocked at the httpx boundary so the suite runs
offline.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Envelope shape assertions apply to every data tool ─────────────────

def _assert_envelope(data: dict):
    for key in ("source", "fetched_at", "as_of", "stale", "payload"):
        assert key in data, f"envelope missing {key!r}: {data.keys()}"
    assert isinstance(data["source"], str) and data["source"]
    assert isinstance(data["fetched_at"], str) and data["fetched_at"]
    assert isinstance(data["stale"], bool)
    assert isinstance(data["payload"], dict)


def _stub_response(json_body, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


# ── get_stock happy path + cache + rate-limit stale serve ───────────────

def test_get_stock_returns_full_envelope():
    from backend.core.tools import data_sources as ds
    ds._clear_cache_for_tests()

    yahoo_body = {"chart": {"result": [{"meta": {
        "regularMarketPrice": 189.44, "previousClose": 187.10,
        "currency": "USD", "regularMarketTime": 1727100000,
    }}]}}

    with patch.object(ds, "httpx") as hx:
        hx.Client.return_value.__enter__.return_value.get.return_value = _stub_response(yahoo_body)
        hx.HTTPError = Exception
        res = ds.get_stock("AAPL")

    assert res.status.value == "success"
    _assert_envelope(res.data)
    p = res.data["payload"]
    assert p["symbol"] == "AAPL"
    assert p["price"] == 189.44
    assert p["prev_close"] == 187.10
    assert p["change"] == round(189.44 - 187.10, 4)
    assert res.data["source"] == "yahoo-finance"
    assert res.data["stale"] is False
    print("  [PASS] get_stock envelope complete + parsed correctly")


def test_get_stock_cache_hit_within_window():
    """Second identical call within TTL serves cached, no HTTP call."""
    from backend.core.tools import data_sources as ds
    ds._clear_cache_for_tests()

    yahoo_body = {"chart": {"result": [{"meta": {
        "regularMarketPrice": 100.0, "previousClose": 99.0,
        "currency": "USD", "regularMarketTime": 1727100000,
    }}]}}

    with patch.object(ds, "httpx") as hx:
        client = MagicMock()
        client.get.return_value = _stub_response(yahoo_body)
        hx.Client.return_value.__enter__.return_value = client
        hx.HTTPError = Exception

        r1 = ds.get_stock("MSFT")
        r2 = ds.get_stock("MSFT")

    assert r1.status.value == "success" and r2.status.value == "success"
    assert r1.data["stale"] is False and r2.data["stale"] is False
    # Only ONE HTTP call — the second was served from cache.
    assert client.get.call_count == 1, f"expected 1 HTTP call, got {client.get.call_count}"
    print("  [PASS] get_stock caches within TTL — second call served without HTTP")


def test_get_stock_rate_limited_serves_last_good_stale():
    """Provider returns 429; last-good cache is served with stale=True."""
    from backend.core.tools import data_sources as ds
    ds._clear_cache_for_tests()

    ok_body = {"chart": {"result": [{"meta": {
        "regularMarketPrice": 42.0, "previousClose": 40.0,
        "currency": "USD", "regularMarketTime": 1727100000,
    }}]}}

    with patch.object(ds, "httpx") as hx:
        client = MagicMock()
        # First call succeeds → populates cache
        client.get.side_effect = [_stub_response(ok_body), _stub_response({}, status_code=429)]
        hx.Client.return_value.__enter__.return_value = client
        hx.HTTPError = Exception

        first = ds.get_stock("RATE")
        # Force cache to look "expired" so the second call actually re-fetches
        # (we simulated a 15-second-old entry).
        import time
        for k in list(ds._CACHE.keys()):
            _, env = ds._CACHE[k]
            ds._CACHE[k] = (time.monotonic() - 60, env)
        second = ds.get_stock("RATE")

    assert first.status.value == "success" and first.data["stale"] is False
    assert second.status.value == "success", f"stale-serve should still be success, got {second.status.value}"
    assert second.data["stale"] is True
    assert "stale_reason" in second.data and "429" in second.data["stale_reason"]
    print("  [PASS] rate-limited → last-good served with stale=True")


def test_get_stock_error_no_cache_returns_structured_error():
    """No cache, provider fails: structured error, no crash."""
    from backend.core.tools import data_sources as ds
    ds._clear_cache_for_tests()

    with patch.object(ds, "httpx") as hx:
        client = MagicMock()
        client.get.return_value = _stub_response({}, status_code=500)
        hx.Client.return_value.__enter__.return_value = client
        hx.HTTPError = Exception

        res = ds.get_stock("FAIL")

    assert res.status.value == "error"
    assert "500" in (res.reason or "")
    print("  [PASS] no cache + provider error → structured error, no crash")


# ── "not configured" path when a keyed provider is chosen without a key ─

def test_get_stock_not_configured_when_keyed_provider_selected_without_key():
    from backend.core.tools import data_sources as ds
    from backend.server.config import settings

    original = settings.stock_provider
    settings.stock_provider = "finnhub"  # keyed provider, no key configured
    try:
        res = ds.get_stock("AAPL")
        assert res.status.value == "blocked"
        assert "not configured" in (res.reason or "").lower()
        assert "FINNHUB_API_KEY" in (res.reason or "")
        print("  [PASS] keyed provider without key → structured 'not configured'")
    finally:
        settings.stock_provider = original


# ── get_news untrusted-data framing (Phase 2 composition) ──────────────

def test_get_news_data_flags_content_as_external():
    """News text is external web content — Planner's Phase 2 directive
    treats it as data. Envelope must carry is_external_data=True."""
    from backend.core.tools import data_sources as ds
    ds._clear_cache_for_tests()

    fake_feed = MagicMock()
    fake_feed.entries = [
        MagicMock(title="World news headline 1", link="https://x/1", published="Mon 12:00"),
        MagicMock(title="World news headline 2", link="https://x/2", published="Mon 12:30"),
    ]
    with patch("backend.core.tools.data_sources.feedparser.parse", return_value=fake_feed):
        res = ds.get_news_data("world", limit=2)

    assert res.status.value == "success"
    _assert_envelope(res.data)
    assert res.data.get("is_external_data") is True, (
        "get_news_data must set is_external_data=True on envelope — the "
        "Planner's Phase 2 directive keys off this to treat titles as data"
    )
    headlines = res.data["payload"]["headlines"]
    assert len(headlines) == 2
    assert headlines[0]["title"] == "World news headline 1"
    print("  [PASS] get_news_data envelope carries is_external_data=True (Phase 2 composition)")


# ── Healer classifications ─────────────────────────────────────────────

def test_healer_classifies_phase3_signals():
    from backend.core.healing import healer, RecoveryPath

    assert healer.analyze("get_stock", "get_stock: rate limited and no cache") == RecoveryPath.PIVOT
    assert healer.analyze("render_canvas", "canvas schema invalid at 'widgets.0.type': ...") == RecoveryPath.ABORT
    assert healer.analyze("get_stock", "get_stock: FINNHUB_API_KEY not configured") == RecoveryPath.ESCALATE
    print("  [PASS] healer maps Phase 3 signals to PIVOT / ABORT / ESCALATE per spec")


if __name__ == "__main__":
    test_get_stock_returns_full_envelope()
    test_get_stock_cache_hit_within_window()
    test_get_stock_rate_limited_serves_last_good_stale()
    test_get_stock_error_no_cache_returns_structured_error()
    test_get_stock_not_configured_when_keyed_provider_selected_without_key()
    test_get_news_data_flags_content_as_external()
    test_healer_classifies_phase3_signals()
    print("All Phase 3 data-source tests passed.")
