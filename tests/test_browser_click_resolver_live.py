"""Phase 2.1 — click resolver against a REAL Chromium + local HTML fixture.

The whole point of this file: the Phase 2 mocked click test patched
`_resolve_click_target` with canned candidates, so the live-DOM behaviour
was never exercised. A single real click against example.com found a real
bug in ~90 seconds. These tests run the actual resolver against a real
headless Chromium loaded with a static HTML fixture — deterministic and
CI-safe (no network, no live-site flakiness), but not mocked at the seam
that let the bug through last time.

Skip gracefully if Chromium isn't installed (fresh CI box without
`playwright install chromium`).
"""
import asyncio
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

# Skip whole module if Playwright itself isn't installed.
playwright_async = pytest.importorskip("playwright.async_api")

FIXTURE = (_project_root / "tests" / "fixtures" / "click_resolver.html").read_text(encoding="utf-8")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _with_page(fn):
    """Spin up a fresh headless Chromium + one page loaded with the
    fixture, run `fn(page)`, tear down. Chromium not being available
    at runtime (`playwright install chromium` skipped) triggers
    pytest.skip so the suite still passes headless."""
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    try:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"chromium not installed: {e}")
        try:
            page = await browser.new_page()
            await page.set_content(FIXTURE)
            return await fn(page)
        finally:
            await browser.close()
    finally:
        await p.stop()


async def _tag(el) -> str:
    return await el.evaluate("e => e.tagName.toLowerCase()")


async def _id(el) -> str:
    return await el.get_attribute("id") or ""


# ── The regression from the live smoke: ellipsis in link text ───────────

def test_more_information_ellipsis_resolves_to_the_anchor():
    """The bug commit 2.1 fixes: `<a>More information...</a>` was returning
    "no element matching" for query 'More information'. Tier 4
    (has_text on role=link) or tier 5 (regex) must catch it now."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "More information")
        assert len(candidates) == 1, f"expected 1 candidate for 'More information', got {len(candidates)} via {method}"
        assert await _tag(candidates[0]) == "a", "should resolve to the <a>, not something else"
        assert await _id(candidates[0]) == "link-more"
        print(f"  [PASS] 'More information' resolves to <a id='link-more'> via {method}")

    _run(_with_page(_test))


# ── Exact must still win when both exact and partial candidates exist ──

def test_exact_match_wins_over_partial():
    """Query 'Home' — fixture has <a>Home</a> AND <a>Home page</a>. Both
    substring-match, only one exact-matches. Tier 2 (exact) must fire
    before tier 3 (substring) so the resolver returns just the exact one."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "Home")
        assert len(candidates) == 1, (
            f"exact match tier must return only the exact hit; got {len(candidates)} via {method}"
        )
        assert await _id(candidates[0]) == "link-home-exact", "should be <a>Home</a>, not <a>Home page</a>"
        assert "exact" in method, f"expected an /exact tier to hit; method={method}"
        print(f"  [PASS] 'Home' resolves to <a id='link-home-exact'> via {method}, ignoring the partial")

    _run(_with_page(_test))


# ── Ambiguity still routes through candidates, never guesses ───────────

def test_ambiguous_query_returns_multiple_candidates():
    """Query 'Sign' — fixture has 'Sign in here' AND 'Sign in there', no
    exact match for 'Sign'. Substring tier hits both. Resolver must
    return both — the tool then blocks with the ambiguous-candidates
    payload, never guessing."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "Sign")
        assert len(candidates) == 2, (
            f"loosened matcher must still detect ambiguity, got {len(candidates)} via {method}. "
            "Never-guess guarantee is what the tool block relies on."
        )
        ids = sorted([await _id(c) for c in candidates])
        assert ids == ["link-sign-a", "link-sign-b"], f"got ids {ids}"
        print(f"  [PASS] 'Sign' returns 2 candidates via {method}; ambiguity preserved")

    _run(_with_page(_test))


# ── Role preference: button beats <p> when both share the exact text ──

def test_actionable_role_preferred_over_generic_text():
    """Query 'Confirm' — fixture has <button>Confirm</button> AND
    <p>Confirm</p>. Tier 2 (exact accessible name on role=button) hits
    the button first; the generic text tier never fires. Resolver
    returns the button, not the paragraph."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "Confirm")
        assert len(candidates) == 1, f"expected 1 (the button), got {len(candidates)} via {method}"
        assert await _tag(candidates[0]) == "button", (
            f"role preference violated — resolved to {await _tag(candidates[0])} instead of button"
        )
        assert await _id(candidates[0]) == "btn-confirm"
        assert "role=button" in method, f"expected role=button tier, got {method}"
        print(f"  [PASS] 'Confirm' resolves to <button>, not <p>, via {method}")

    _run(_with_page(_test))


# ── The already-working tier still works: form label ─────────────────

def test_form_label_still_resolves():
    """Query 'Username' — should hit the <label>-linked <input>. Proves
    the label tier wasn't broken by inserting the new tiers above it."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "Username")
        assert len(candidates) >= 1
        assert await _id(candidates[0]) == "username"
        print(f"  [PASS] 'Username' resolves to the labeled input via {method}")

    _run(_with_page(_test))


# ── No match still returns 0 (fails closed) ───────────────────────────

def test_no_match_returns_empty_not_guess():
    """Query 'this-does-not-exist-anywhere' — every tier fails to find
    anything. Resolver returns 0 candidates, tool blocks. Fails CLOSED,
    never picks a "close enough" partial. This is the safe-failure
    behaviour the live smoke test confirmed on example.com; the fix
    must not weaken it."""
    from backend.core.tools.browser import _resolve_click_target

    async def _test(page):
        candidates, method = await _resolve_click_target(page, "this-does-not-exist-anywhere")
        assert candidates == [], (
            f"expected 0 candidates for non-matching query, got {len(candidates)} via {method}. "
            "The safe-failure guarantee is what stops silent wrong clicks."
        )
        assert method == "none"
        print("  [PASS] non-matching query returns 0 candidates (fails closed)")

    _run(_with_page(_test))


if __name__ == "__main__":
    test_more_information_ellipsis_resolves_to_the_anchor()
    test_exact_match_wins_over_partial()
    test_ambiguous_query_returns_multiple_candidates()
    test_actionable_role_preferred_over_generic_text()
    test_form_label_still_resolves()
    test_no_match_returns_empty_not_guess()
    print("All Phase 2.1 real-DOM click resolver tests passed.")
