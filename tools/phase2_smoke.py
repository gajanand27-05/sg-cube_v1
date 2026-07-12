"""Phase 2 live smoke test — runs the real tools against a real Chromium.

Not for CI. Prints ACTUAL returned values for each of the five checks the
user asked for. Run from repo root:

    python tools/phase2_smoke.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force headed mode for the visible-window requirement in check 1.
import os
os.environ["BROWSER_HEADLESS"] = "false"

# Force-import the tool module so the registry populates.
import backend.core.tools
from backend.core.tools.registry import REGISTRY
from backend.core.browser.manager import browser_manager
from backend.core.healing import healer, RecoveryPath


def _hr(title: str):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _dump(obj, label: str = ""):
    if label:
        print(f"— {label} —")
    # Small helper to print ToolResult data safely, truncating long strings.
    if hasattr(obj, "model_dump"):
        d = obj.model_dump()
    else:
        d = obj
    print(json.dumps(d, indent=2, default=str)[:2000])


async def run():
    # ── Check 1: LAUNCH ──────────────────────────────────────────────
    _hr("Check 1 — LAUNCH: browser_open('https://example.com')")
    print("(A visible Chromium window should now appear.)")
    r1 = await REGISTRY["browser_open"].func("https://example.com")
    print(f"status  : {r1.status.value}")
    print(f"message : {r1.message}")
    print(f"data    : {json.dumps(r1.data, indent=2)}")
    print(f"is_launched (post-call): {browser_manager.is_launched}")

    # Small wait so the user can see the window
    await asyncio.sleep(2)

    # ── Check 2: READ + BOUNDARY ─────────────────────────────────────
    _hr("Check 2 — READ + untrusted-data boundary")
    r2 = await REGISTRY["browser_read"].func()
    print(f"status  : {r2.status.value}")
    print(f"message : {r2.message!r}")
    print(f"data.url             : {r2.data.get('url')}")
    print(f"data.title           : {r2.data.get('title')}")
    print(f"data.is_external_data: {r2.data.get('is_external_data')}")
    print(f"data.content_length  : {r2.data.get('content_length')}")
    pc = r2.data.get("page_content", "")
    print(f"data.page_content (first 400 chars):")
    print(f"    {pc[:400]!r}")
    print(f"data.page_content (last 100 chars):")
    print(f"    ...{pc[-100:]!r}")

    # Explicit boundary assertions
    injection_leak = r2.message and any(
        w in r2.message for w in ("Example Domain", "illustrative examples", "no prior coordination")
    )
    print(f"\nBoundary L1 (page text NOT in .message)     : {'PASS' if not injection_leak else 'FAIL'}")
    print(f"Boundary L2 (sentinel tags present)          : "
          f"{'PASS' if '<UNTRUSTED_PAGE_CONTENT' in pc and '</UNTRUSTED_PAGE_CONTENT>' in pc else 'FAIL'}")
    print(f"Boundary L3 (is_external_data flag == True)  : "
          f"{'PASS' if r2.data.get('is_external_data') is True else 'FAIL'}")

    # ── Check 3: CLICK on a real DOM ────────────────────────────────
    _hr("Check 3 — CLICK on a real DOM (example.com has one link: 'More information...')")

    print("Attempt A: browser_click('More information') — should resolve via role=link")
    r3a = await REGISTRY["browser_click"].func("More information")
    print(f"  status : {r3a.status.value}")
    print(f"  reason : {r3a.reason}")
    print(f"  data   : {json.dumps(r3a.data, indent=2)[:500]}")

    # Wait for any navigation
    await asyncio.sleep(2)

    # Deliberately ambiguous — "the" appears on many pages; on example.com after
    # nav we might land on iana.org which is denser. Let's go back first.
    print("\n(returning to example.com for the ambiguous test)")
    await REGISTRY["browser_open"].func("https://example.com")
    await asyncio.sleep(1)

    print("\nAttempt B: browser_click('example') — deliberately vague (title, body, link)")
    r3b = await REGISTRY["browser_click"].func("example")
    print(f"  status  : {r3b.status.value}")
    print(f"  reason  : {r3b.reason}")
    print(f"  ambiguous flag: {r3b.data.get('ambiguous')}")
    cands = r3b.data.get("candidates") or []
    print(f"  candidates ({len(cands)}):")
    for c in cands[:5]:
        print(f"    - {c}")

    # ── Check 4: TABS ───────────────────────────────────────────────
    _hr("Check 4 — TABS: open 2 tabs, list, switch, close one")

    # Currently 1 tab (example.com). Open a second one.
    r4a = await REGISTRY["browser_new_tab"].func("https://www.iana.org/")
    print(f"new_tab #2: status={r4a.status.value}  data={json.dumps(r4a.data, indent=2)[:300]}")
    await asyncio.sleep(1)

    r4b = await REGISTRY["browser_list_tabs"].func()
    print(f"\nlist_tabs: status={r4b.status.value}  count={r4b.data.get('count')}")
    tabs = r4b.data.get("tabs") or []
    for t in tabs:
        print(f"  {t}")

    if len(tabs) >= 2:
        first_tab_id = tabs[0]["tab_id"]
        second_tab_id = tabs[1]["tab_id"]
        print(f"\nswitch to first tab ({first_tab_id})")
        r4c = await REGISTRY["browser_switch_tab"].func(first_tab_id)
        print(f"  status={r4c.status.value}  active={r4c.data}")

        print(f"\nclose second tab ({second_tab_id})")
        r4d = await REGISTRY["browser_close_tab"].func(second_tab_id)
        print(f"  status={r4d.status.value}  message={r4d.message}")

        # Verify only 1 tab remains
        r4e = await REGISTRY["browser_list_tabs"].func()
        print(f"\nafter close: count={r4e.data.get('count')}")
    else:
        print("only 1 tab present — skipping switch/close verification")

    # ── Check 5: FAILURE PATH ────────────────────────────────────────
    _hr("Check 5 — FAILURE PATH: unreachable domain")

    bad_url = "https://this-does-not-exist-31337.example/"
    print(f"browser_open({bad_url})")
    r5 = await REGISTRY["browser_open"].func(bad_url)
    print(f"status  : {r5.status.value}")
    print(f"reason  : {r5.reason}")

    # Classify via Healer
    if r5.reason:
        p1 = healer.analyze("browser_open", r5.reason, attempt=1)
        p2 = healer.analyze("browser_open", r5.reason, attempt=2)
        print(f"\nHealer.analyze(attempt=1) = {p1.value}")
        print(f"Healer.analyze(attempt=2) = {p2.value}")

    # Prove the server didn't crash — call a normal READONLY tool after the failure.
    print("\nProof server survived: list_tabs after failure:")
    r5b = await REGISTRY["browser_list_tabs"].func()
    print(f"  status={r5b.status.value}  count={r5b.data.get('count')}")


async def main():
    try:
        await run()
    finally:
        # Clean up so the profile lock is released.
        print("\n(cleaning up: closing browser)")
        try:
            await browser_manager.close()
        except Exception as e:
            print(f"  cleanup issue: {e}")


if __name__ == "__main__":
    asyncio.run(main())
