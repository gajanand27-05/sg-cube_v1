"""The web-facing content tools must actually answer, not describe answering.

Two regressions, both found by asking the running assistant real questions
rather than by the suite:

1. llm_helper.llm_generate called gemini_client directly. The stack moved off
   Gemini, GEMINI_API_KEY is unset, and so summarize_url / summarize_pdf /
   explain_code / translate all returned "No API key was provided". Nothing
   failed at import, so the suite stayed green with four tools dead.

2. get_news_data returned message="tech: 5 headlines". commander.py's
   Assessment Stage speaks a lone successful tool's `message` verbatim and
   skips the LLM, so asking for the news read back a count while the headlines
   sat unused in `data`.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.tools import data_sources as ds
from backend.core.tools import llm_helper


# ── 1. content tools reach a configured backend ──────────────────────────

def test_llm_generate_targets_the_routed_backend(monkeypatch):
    """Not "does it call Gemini" — does it call whatever the policy picked."""
    from backend.ai_modules.llm.routing import TaskType, build_default_policy

    seen = {}
    monkeypatch.setattr(llm_helper, "generate_sync",
                        lambda prompt, **kw: seen.update(kw) or "ok")

    out = llm_helper.llm_generate("hello", system="sys")
    assert out == "ok"

    expected = build_default_policy().select(TaskType.SUMMARIZATION)
    if expected == "ollama_cloud":
        assert seen["base_url"], "cloud route passed no base_url"
        assert seen["api_key"], "cloud route passed no api key"
    else:
        assert seen["base_url"] is None, "local route should use the default host"


def test_llm_generate_survives_a_dead_backend(monkeypatch):
    """Callers branch on empty string. An exception here crashed the tool
    instead of letting it report 'model returned nothing'."""
    def boom(prompt, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(llm_helper, "generate_sync", boom)
    assert llm_helper.llm_generate("hello") == ""


def test_no_tool_module_still_imports_the_retired_gemini_client():
    """gemini_client is reachable only through its own backend adapter. A
    direct import from a tool is how four tools died silently."""
    import ast

    offenders = []
    for path in (_root / "backend" / "core").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            if any("gemini_client" in n for n in names):
                offenders.append(path.relative_to(_root).as_posix())
                break
    assert not offenders, (
        "these bypass RoutingPolicy and break whenever GEMINI_API_KEY is "
        "unset: " + ", ".join(offenders)
    )


# ── 2. news speaks its headlines ─────────────────────────────────────────

class _FakeEntry:
    def __init__(self, title):
        self.title = title
        self.link = "https://example.com/x"
        self.published = "Thu, 14 Aug 2026 00:00:00 GMT"


class _FakeFeed:
    def __init__(self, titles):
        self.entries = [_FakeEntry(t) for t in titles]


@pytest.fixture(autouse=True)
def _clear_cache():
    ds._clear_cache_for_tests()
    yield
    ds._clear_cache_for_tests()


def test_news_message_carries_the_actual_headlines(monkeypatch):
    titles = ["Mars rover finds ice", "Chip prices fall"]
    monkeypatch.setattr(ds, "fetch_feed", lambda url, **kw: _FakeFeed(titles))

    fn = getattr(ds.get_news_data, "func", ds.get_news_data)
    res = fn(topic="world", limit=5)

    assert res.status.value == "success"
    for t in titles:
        assert t in res.message, (
            f"headline {t!r} never reached the spoken message: {res.message!r}"
        )


def test_cached_news_also_speaks_its_headlines(monkeypatch):
    """The cache branch built its own message string and was missed when the
    live branch was fixed — the same sibling-drift that keeps biting."""
    titles = ["Mars rover finds ice"]
    monkeypatch.setattr(ds, "fetch_feed", lambda url, **kw: _FakeFeed(titles))

    fn = getattr(ds.get_news_data, "func", ds.get_news_data)
    first = fn(topic="world", limit=5)
    second = fn(topic="world", limit=5)

    assert "cached" not in second.message.lower() or titles[0] in second.message
    assert titles[0] in second.message, f"cache path dropped the headlines: {second.message!r}"
    assert first.message == second.message


@pytest.mark.parametrize("spoken,feed", [
    ("artificial intelligence", "tech"),
    ("AI", "tech"),
    ("technology", "tech"),
    ("finance", "business"),
    ("cricket", "sports"),
    ("top stories", "world"),
])
def test_spoken_topics_resolve_to_a_feed(spoken, feed, monkeypatch):
    """A blocked topic costs a full extra agent round trip. Measured at 14.6s
    for 'the latest news about artificial intelligence'."""
    asked = {}
    monkeypatch.setattr(ds, "fetch_feed",
                        lambda url, **kw: asked.update(url=url) or _FakeFeed(["h1"]))

    fn = getattr(ds.get_news_data, "func", ds.get_news_data)
    res = fn(topic=spoken)

    assert res.status.value == "success", f"{spoken!r} was rejected: {res.reason!r}"
    assert asked["url"] == ds._NEWS_FEEDS[feed]


def test_topic_aliases_all_point_at_real_feeds():
    """A typo'd alias sends a legal request down the unknown-topic branch."""
    broken = {k: v for k, v in ds._TOPIC_ALIASES.items() if v not in ds._NEWS_FEEDS}
    assert not broken, f"aliases pointing at no feed: {broken}"


def test_no_module_hands_feedparser_a_url():
    """feedparser.parse(url) fetches with no timeout — the socket default is
    wait-forever. Tools run in a thread pool, so wait_for cancels the await
    while the fetch keeps going: the user got "Execution timed out after
    10.0s" and a leaked worker thread. Only fetch_feed may touch the network.
    """
    import ast

    offenders = []
    for path in (_root / "backend").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "parse"
                    and isinstance(f.value, ast.Name) and f.value.id == "feedparser"):
                continue
            # Passing bytes we already fetched is the safe form; a bare Name
            # holding a URL is not. fetch_feed itself passes r.content.
            arg = node.args[0] if node.args else None
            if not (isinstance(arg, ast.Attribute) and arg.attr == "content"):
                offenders.append(f"{path.relative_to(_root).as_posix()}:{node.lineno}")
    assert not offenders, (
        "feedparser.parse() called with an unbounded URL fetch at: "
        + ", ".join(offenders)
    )


def test_feed_fetch_stays_under_the_data_tool_budget():
    """A feed timeout above the tool's own budget can never be reached — the
    outer cancel wins and the real reason is lost."""
    from backend.server.config import settings

    assert ds._FEED_TIMEOUT_S < settings.tool_timeout_data_fetch_s, (
        f"feed timeout {ds._FEED_TIMEOUT_S}s >= data-fetch budget "
        f"{settings.tool_timeout_data_fetch_s}s"
    )


def test_genuinely_unknown_topic_still_says_so():
    fn = getattr(ds.get_news_data, "func", ds.get_news_data)
    res = fn(topic="underwater basket weaving")
    assert res.status.value == "blocked"
    assert "underwater basket weaving" in res.reason
