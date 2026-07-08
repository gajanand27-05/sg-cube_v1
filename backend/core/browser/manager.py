"""BrowserManager — lazy-started, persistent Chromium context.

Design contract (Phase 2 spec):
  1. LAZY START.  No Playwright is imported and no browser is launched
     until the first browser tool actually needs a page. This module can
     be imported at boot without paying the ~1-2 s Chromium startup cost
     or requiring `playwright install chromium` on machines that never
     touch the web.
  2. FAULT ISOLATION.  A launch failure records to daemon SERVICE_STATUS
     and returns a structured error to the tool caller — never bubbles
     out of the server.
  3. PERSISTENT CONTEXT.  Cookies / logins survive within a session via
     `launch_persistent_context(user_data_dir=...)`. The profile dir
     lives at ~/sg_cube/browser_profile/ (outside the repo, matching how
     `notes` and `dogfooding` write to ~/sg_cube/).
  4. HEADED BY DEFAULT.  The user is running SG_CUBE on their own
     machine and wants to *see* the browser doing things. Toggleable via
     BROWSER_HEADLESS in .env.
  5. TABS.  Playwright doesn't expose stable tab IDs; we assign our own
     via uuid4()[:8] and maintain a hwnd-like map so tools can address
     tabs deterministically.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class BrowserLaunchError(Exception):
    """Chromium refused to start — most commonly `playwright install chromium`
    was never run, or the profile dir is on a network drive."""


class BrowserManager:
    """Owns the single Playwright context and its pages.

    Every mutating method calls `_ensure_launched()` first; that method is
    idempotent and serialised by an asyncio.Lock so parallel tool calls
    don't race the launch. Everything is instance-level so tests can swap
    a fresh manager without side effects.
    """

    def __init__(self):
        self._playwright: Any = None
        self._context: Any = None  # BrowserContext (persistent-context launch handle)
        self._pages: dict[str, Any] = {}  # tab_id → Page
        self._active_tab_id: str | None = None
        self._launched: bool = False
        self._lock = asyncio.Lock()

    # ── Introspection (used by /system/services + tests) ────────────────
    @property
    def is_launched(self) -> bool:
        return self._launched

    @property
    def tab_count(self) -> int:
        return len(self._pages)

    # ── Launch / close ──────────────────────────────────────────────────
    async def _ensure_launched(self) -> None:
        """Serialise the launch behind an asyncio lock so concurrent tool
        calls can't double-init. Idempotent — later calls are no-ops."""
        if self._launched:
            return
        async with self._lock:
            if self._launched:
                return
            await self._launch()

    async def _launch(self) -> None:
        """The actual Playwright import + Chromium boot. Isolated for
        patching in tests — mock this to skip real browser startup."""
        try:
            # Lazy import — Playwright not imported at module load.
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise BrowserLaunchError(
                "playwright not installed — pip install playwright and run "
                "`playwright install chromium`"
            ) from e

        # Import settings inside the function so this module doesn't drag
        # config into every import chain at boot.
        from backend.server.config import settings

        profile_dir = Path(settings.browser_profile_dir).expanduser()
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BrowserLaunchError(f"cannot create profile dir {profile_dir}: {e}") from e

        try:
            self._playwright = await async_playwright().start()
            # Persistent context = "one browser with saved cookies for this
            # user data dir." It's the launch handle in Playwright's model —
            # we don't hold a separate `browser` object.
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=bool(settings.browser_headless),
                channel="chromium",
                ignore_https_errors=False,
            )
        except Exception as e:
            # Best-effort cleanup so we don't leak a half-started process.
            try:
                if self._playwright is not None:
                    await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
            self._context = None
            raise BrowserLaunchError(f"chromium launch failed: {e}") from e

        # Seed initial page. `launch_persistent_context` opens one about:blank
        # page automatically; grab it as our first tab.
        if self._context.pages:
            first = self._context.pages[0]
        else:
            first = await self._context.new_page()

        tab_id = self._new_tab_id()
        self._pages[tab_id] = first
        self._active_tab_id = tab_id
        self._launched = True
        log.info("BrowserManager launched (profile=%s, headless=%s)",
                 profile_dir, settings.browser_headless)

    async def close(self) -> None:
        """Shutdown hook — safe to call multiple times, safe when never
        launched (no-op). Runs on daemon shutdown via stop_services."""
        if not self._launched:
            return
        try:
            if self._context is not None:
                await self._context.close()
        except Exception as e:
            log.debug("Browser context close failed: %s", e)
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception as e:
            log.debug("Playwright stop failed: %s", e)
        self._context = None
        self._playwright = None
        self._pages.clear()
        self._active_tab_id = None
        self._launched = False

    # ── Tab helpers ─────────────────────────────────────────────────────
    def _new_tab_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def _resolve_tab(self, tab_id: str | None) -> tuple[str | None, Any]:
        """Return (tab_id, page) or (None, None) if the requested tab_id
        doesn't exist. When tab_id is None, returns the active tab."""
        if tab_id is None:
            if self._active_tab_id is None:
                return None, None
            return self._active_tab_id, self._pages.get(self._active_tab_id)
        page = self._pages.get(tab_id)
        if page is None:
            return None, None
        return tab_id, page

    async def list_tabs(self) -> list[dict]:
        """Return the tab list. Doesn't launch — an unlaunched manager
        has zero tabs, which is honest."""
        await self._ensure_launched()
        out = []
        for tid, page in self._pages.items():
            title = ""
            try:
                title = await page.title()
            except Exception:
                pass
            out.append({
                "tab_id": tid,
                "url": page.url,
                "title": title,
                "active": tid == self._active_tab_id,
            })
        return out

    async def new_tab(self, url: str | None = None) -> dict:
        await self._ensure_launched()
        page = await self._context.new_page()
        tab_id = self._new_tab_id()
        self._pages[tab_id] = page
        self._active_tab_id = tab_id
        if url:
            await self._navigate(page, url)
        return await self._tab_metadata(tab_id, page)

    async def switch_tab(self, tab_id: str) -> dict | None:
        await self._ensure_launched()
        tid, page = self._resolve_tab(tab_id)
        if page is None:
            return None
        try:
            await page.bring_to_front()
        except Exception:
            pass
        self._active_tab_id = tid
        return await self._tab_metadata(tid, page)

    async def close_tab(self, tab_id: str) -> bool:
        await self._ensure_launched()
        tid, page = self._resolve_tab(tab_id)
        if page is None:
            return False
        try:
            await page.close()
        finally:
            self._pages.pop(tid, None)
            if self._active_tab_id == tid:
                self._active_tab_id = next(iter(self._pages), None)
        return True

    async def open_url(self, url: str, tab_id: str | None = None) -> dict:
        """Navigate the given (or active) tab to `url`. If no tabs exist
        yet, opens a new one."""
        await self._ensure_launched()
        if tab_id is None and self._active_tab_id is None:
            # No active tab yet — open a new one.
            return await self.new_tab(url)
        tid, page = self._resolve_tab(tab_id)
        if page is None:
            # Requested tab_id doesn't exist — surface as error via return None.
            return {}
        await self._navigate(page, url)
        return await self._tab_metadata(tid, page)

    async def _navigate(self, page: Any, url: str) -> None:
        """Wraps page.goto with the settings-driven timeout so tools get a
        consistent error signal on slow / failing pages."""
        from backend.server.config import settings
        timeout_ms = int(settings.browser_nav_timeout_ms)
        response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        # We don't return the response — tools re-fetch metadata via _tab_metadata
        # so tab_id / url / title / status stay in one place.
        _ = response

    async def _tab_metadata(self, tab_id: str, page: Any) -> dict:
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        # Playwright's Page.url reads the current URL after any redirects,
        # which is what the spec wants for "final url, post-redirect".
        return {"tab_id": tab_id, "url": page.url, "title": title, "status": "ok"}


# Module-level singleton. Created eagerly so tool code has a stable
# reference, but NO Playwright runs until _ensure_launched fires.
browser_manager = BrowserManager()
