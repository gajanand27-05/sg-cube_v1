"""open_url / search_web / play_youtube open web pages without a shell.

They went through `start "" "{url}"` with shell=True, so a quote in the URL
closed the string and the rest ran as a command: `x.com" & calc & "` started
calc. Now: webbrowser.open (no shell), http/https only, and a False return is
a failure rather than "opened". Nothing is launched here — webbrowser.open
and subprocess.Popen are replaced.
"""
import pytest

from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw


@pytest.fixture
def browser(monkeypatch):
    opened = []

    def fake_open(url):
        opened.append(url)
        return True

    def no_shell(*a, **k):
        raise AssertionError(f"a process was started: {a!r}")

    monkeypatch.setattr(cw.webbrowser, "open", fake_open)
    monkeypatch.setattr(cw.subprocess, "Popen", no_shell)
    return opened


def _open(target):
    return cw.handle_open_url(Intent(action="open_url", target=target))


def test_the_injection_from_the_audit_starts_nothing(browser):
    res = _open('x.com" & calc & "')
    assert res["status"] == "blocked"
    assert browser == []


def test_a_quoted_url_without_spaces_is_only_ever_a_url(browser):
    """No shell, so a quote is just a character in a URL the browser gets."""
    url = 'https://x.com"&calc&"'
    _open(url)
    assert browser in ([], [url])  # opened as a URL, or refused; never run


@pytest.mark.parametrize("target", [
    "file:///C:/Users/Public/page.html",
    "ms-settings:display",
    "search-ms:query=secret",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "mailto:someone@example.com",
    "steam://run/10",
    "vscode://file/C:/x",
    "ms-msdt:/id PCWDiagnostic",
    "ftp://example.com/file",
])
def test_non_web_schemes_are_refused(browser, target):
    res = _open(target)
    assert res["status"] == "blocked", res
    assert "http or https" in res["reason"]
    assert browser == []


@pytest.mark.parametrize("target,url", [
    ("github.com", "https://github.com"),
    ("https://news.ycombinator.com", "https://news.ycombinator.com"),
    ("http://example.com/a?b=c", "http://example.com/a?b=c"),
    ("localhost:3000", "https://localhost:3000"),   # a port, not a scheme
])
def test_web_addresses_open(browser, target, url):
    assert _open(target) == {"status": "success", "message": url}
    assert browser == [url]


def test_no_browser_is_a_failure_not_opened(browser, monkeypatch):
    monkeypatch.setattr(cw.webbrowser, "open", lambda url: False)
    res = _open("github.com")
    assert res["status"] == "error"


def test_search_web_encodes_the_query_and_uses_no_shell(browser):
    res = cw.handle_search_google(Intent(action="search_google", target='cats" & calc & "'))
    assert res["status"] == "success"
    (url,) = browser
    assert url.startswith("https://www.google.com/search?q=")
    assert '"' not in url and "&calc" not in url and " " not in url


def test_youtube_search_uses_no_shell(browser):
    res = cw.handle_search_youtube(Intent(action="search_youtube", target="lofi"))
    assert res["status"] == "success"
    assert browser == ["https://www.youtube.com/results?search_query=lofi"]


# ── queries are URL-encoded ──────────────────────────────────────────────

QUERIES = ['rock & roll', 'c# tutorial', 'why? because', 'say "hi"', "it's", 'a+b=c%',
           'हिंदी गाने', 'ಕನ್ನಡ ಹಾಡುಗಳು']


def _query_of(url: str, key: str) -> str:
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(url).query)[key][0]


@pytest.mark.parametrize("query", QUERIES)
def test_google_search_carries_the_query_intact(browser, query):
    cw.handle_search_google(Intent(action="search_google", target=query))
    (url,) = browser
    assert _query_of(url, "q") == query            # decodes back to exactly what was asked
    assert not any(c in url.split("?", 1)[1] for c in ' "#')


@pytest.mark.parametrize("query", QUERIES)
def test_youtube_search_carries_the_query_intact(browser, query):
    cw.handle_search_youtube(Intent(action="search_youtube", target=query))
    (url,) = browser
    assert _query_of(url, "search_query") == query


class _FakeYDL:
    result = {}

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, q, download=False):
        return self.result


@pytest.fixture
def ytdlp(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_FakeYDL))
    return _FakeYDL


@pytest.mark.parametrize("query", QUERIES)
def test_play_youtube_fallback_carries_the_query_intact(browser, ytdlp, query):
    ytdlp.result = {"entries": []}
    cw.handle_play_youtube(Intent(action="play_youtube", target=query))
    (url,) = browser
    assert _query_of(url, "search_query") == query


def test_play_youtube_encodes_the_video_id(browser, ytdlp):
    ytdlp.result = {"entries": [{"id": 'abc" & calc & "', "title": "x"}]}
    cw.handle_play_youtube(Intent(action="play_youtube", target="song"))
    (url,) = browser
    assert _query_of(url, "v") == 'abc" & calc & "'
    assert " " not in url and '"' not in url
