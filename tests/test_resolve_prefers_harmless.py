"""An ambiguous tool name must resolve to the least side-effecting candidate.

LLMs drop suffixes — "search" instead of "search_and_answer". `_resolve_name`
fuzzy-matches those, and when several tools fit the given args equally the
only tiebreaker was NAME LENGTH.

A bare "search" matches `search_web`, `web_search` and `search_and_answer`.
All three take `query`, so length decided it, and it landed on `search_web` —
whose docstring begins "Open a browser window showing a web search". The
read-only siblings answer the same question without touching the browser.

That is how a latency probe of "what time is it", run twelve times, left seven
Google tabs open on the user's actual desktop. The model being vague is not a
reason to pick the option with a side effect.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import backend.core.tools  # noqa: F401 — populates REGISTRY
from backend.core.tools.registry import REGISTRY, CapabilityTier, _resolve_name


def test_bare_search_does_not_open_a_browser():
    """The exact case that produced the tabs."""
    resolved = _resolve_name("search", {"query": "what time is it"})
    assert resolved is not None
    assert REGISTRY[resolved].tier == CapabilityTier.READONLY, (
        f"{resolved!r} has tier {REGISTRY[resolved].tier}; an ambiguous name "
        "resolved to a tool with a side effect"
    )
    assert resolved != "search_web"


def test_the_ambiguity_is_real_and_not_assumed():
    """Guard the premise. If these ever stop colliding the test above starts
    passing for the wrong reason."""
    candidates = [n for n in REGISTRY if "search" in n.lower()]
    assert len(candidates) > 1, candidates
    assert "search_web" in candidates
    assert REGISTRY["search_web"].tier != CapabilityTier.READONLY, (
        "search_web opens a browser window; if that changed, this test's "
        "reason for existing changed too"
    )


def test_arg_fit_still_beats_harmlessness():
    """Safety is a TIEBREAKER, not an override. A read-only tool that does not
    accept the given args must not win over one that does — that would trade
    a stray browser tab for dispatching to the wrong tool entirely."""
    resolved = _resolve_name("summarize", {"url": "https://example.com"})
    assert resolved is not None
    params = REGISTRY[resolved].schema["parameters"]
    assert "url" in params.get("properties", {}), (
        f"{resolved!r} does not take a url, so arg fit was ignored"
    )


def test_exact_names_are_never_rewritten():
    """Fuzzy matching must not touch a name that exists. Silently redirecting
    an explicit search_web to something read-only would break the one case
    where the user DID ask for a browser window."""
    for name in ("search_web", "web_search", "search_and_answer", "get_time"):
        assert _resolve_name(name, {"query": "x"}) == name


def test_unknown_names_still_fail_closed():
    assert _resolve_name("definitely_not_a_tool_xyz", {}) is None
    assert _resolve_name("", {}) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
