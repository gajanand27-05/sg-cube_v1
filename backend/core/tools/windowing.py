"""Window management + power tools.

Phase 11b originals: minimize_all / focus_window / close_active_window /
list_open_windows / lock_screen / sleep_pc / shutdown_pc / restart_pc /
cancel_shutdown. Kept, plus their tier/trust flags from Phases 0 – 0.7.

Phase 1 extends this module with:
  - list_windows        — richer schema than list_open_windows (which it replaces)
  - get_monitors        — DPI-aware multi-monitor geometry
  - move_window         — move by hwnd/title/fuzzy/app
  - resize_window       — resize by same
  - move_resize_window  — atomic move+resize
  - arrange_windows     — named grid layouts across monitors

Engine choices:
  - pywin32 is primary. pygetwindow stays for the legacy tools that already
    used it — replacing them is out of scope.
  - DPI awareness: SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2) is set
    at module import so GetWindowRect / EnumDisplayMonitors return real pixel
    coordinates on mixed-scaling setups (a 4K screen at 150% next to a
    1080p external at 100% used to lie without this). Fallback path through
    shcore.SetProcessDpiAwareness(2) for older Windows.
"""
import difflib
import json
import logging
import subprocess
import threading
import time

import pyautogui
import pygetwindow as gw

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool
from backend.core.tools.unsaved_state import confirm_close_focused

log = logging.getLogger(__name__)

# ── DPI awareness — declare at module import ────────────────────────────
# Load-bearing for get_monitors + move_window on multi-monitor setups with
# different scales. If we don't declare, GetWindowRect returns virtualized
# coordinates on the non-primary monitor and everything ends up ~20% off.
# Set once at import; subsequent calls are no-ops on Windows.
def _set_dpi_awareness() -> None:
    try:
        import ctypes
    except ImportError:
        return
    # Per-monitor V2 (DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4)
    # requires Windows 10 1703+. Best precision on modern boxes.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    # Fallback: per-monitor V1 (PROCESS_PER_MONITOR_DPI_AWARE = 2)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    # Ancient fallback: system-DPI-aware. Wrong scale on secondary monitors
    # but at least won't crash on Windows 7 / non-Windows.
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_set_dpi_awareness()


# ── Structured error signaling for the Healer ───────────────────────────
class WindowNotFound(Exception):
    """Requested target didn't resolve to any open window."""


class AccessDenied(Exception):
    """SetWindowPos returned ERROR_ACCESS_DENIED — target is likely elevated."""


class WindowClosed(Exception):
    """Target hwnd disappeared between resolution and SetWindowPos."""


# ── Low-level primitives (patchable in tests) ────────────────────────────

def _enumerate_windows() -> list[dict]:
    """Raw enumeration of visible, titled, non-tool, positive-area top-level
    windows via win32gui.EnumWindows. Returns a list without monitor index —
    that's added by list_windows() using monitor info.

    Field shape (before monitor annotation):
      { "hwnd": int, "title": str, "app": str,
        "rect": [x, y, w, h], "minimized": bool, "maximized": bool,
        "focused": bool }

    Stable ordering by hwnd ascending — makes arrange_windows idempotent
    even when a previous call reshuffled z-order.
    """
    import win32gui
    import win32con
    import win32process
    import win32api

    windows: list[dict] = []
    foreground = 0
    try:
        foreground = win32gui.GetForegroundWindow()
    except Exception:
        pass

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        except Exception:
            return
        # Skip toolbars, taskbar-hidden windows, invisible layered.
        if ex_style & win32con.WS_EX_TOOLWINDOW:
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title.strip():
            return
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return

        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            show_state = placement[1]
        except Exception:
            show_state = win32con.SW_SHOWNORMAL
        minimized = show_state == win32con.SW_SHOWMINIMIZED
        maximized = show_state == win32con.SW_SHOWMAXIMIZED

        app = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) works even without
            # elevation on most processes — better than QUERY_INFO for our needs.
            hproc = win32api.OpenProcess(0x1000, False, pid)
            try:
                exe = win32process.GetModuleFileNameEx(hproc, 0)
                app = exe.rsplit("\\", 1)[-1]
            finally:
                win32api.CloseHandle(hproc)
        except Exception:
            # Elevated / protected process — leave app empty and keep going.
            pass

        windows.append({
            "hwnd": hwnd,
            "title": title,
            "app": app,
            "rect": [left, top, w, h],
            "minimized": minimized,
            "maximized": maximized,
            "focused": hwnd == foreground,
        })

    win32gui.EnumWindows(_cb, None)
    windows.sort(key=lambda w: w["hwnd"])
    return windows


def _enumerate_monitors() -> list[dict]:
    """Enumerate monitors + work area (excludes taskbar) + DPI scale.

    Work area matters more than the full monitor rect: the taskbar takes a
    chunk that arrange_windows must not paint into. Scale is EFFECTIVE
    (renders through per-monitor DPI awareness) so 1.5 means the display
    is at 150% scaling — the assistant can honor it when computing
    layouts if desired.
    """
    import win32api
    import win32con

    monitors: list[dict] = []
    handles = win32api.EnumDisplayMonitors(None, None)
    for i, (hmon, _hdc, _rect) in enumerate(handles):
        try:
            info = win32api.GetMonitorInfo(hmon)
        except Exception:
            continue
        wl, wt, wr, wb = info["Work"]
        w, h = wr - wl, wb - wt
        primary = bool(info["Flags"] & win32con.MONITORINFOF_PRIMARY)

        scale = 1.0
        try:
            import ctypes
            dpi_x = ctypes.c_uint()
            dpi_y = ctypes.c_uint()
            # MDT_EFFECTIVE_DPI = 0
            ctypes.windll.shcore.GetDpiForMonitor(int(hmon), 0,
                                                  ctypes.byref(dpi_x),
                                                  ctypes.byref(dpi_y))
            if dpi_x.value > 0:
                scale = round(dpi_x.value / 96.0, 2)
        except Exception:
            # Older Windows or non-shcore path — leave scale at 1.0.
            pass

        monitors.append({
            "index": i,
            "primary": primary,
            "rect": [wl, wt, w, h],
            "scale": scale,
        })

    return monitors


def _restore_window(hwnd: int) -> None:
    """Restore a minimized window before moving it. No-op on non-minimized."""
    import win32gui
    import win32con
    try:
        placement = win32gui.GetWindowPlacement(hwnd)
    except Exception as e:
        raise WindowClosed(f"hwnd {hwnd} not available") from e
    if placement[1] == win32con.SW_SHOWMINIMIZED:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception as e:
            raise AccessDenied(f"could not restore hwnd {hwnd}") from e


def _set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """Move + resize a window without changing z-order.

    Failure modes translated into structured exceptions the tool layer
    catches:
      - IsWindow(hwnd)==False → WindowClosed
      - SetWindowPos returns ERROR_ACCESS_DENIED (5) → AccessDenied
      - SetWindowPos returns ERROR_INVALID_WINDOW_HANDLE (1400) → WindowClosed
    """
    import win32gui
    import win32con

    if not win32gui.IsWindow(hwnd):
        raise WindowClosed(f"hwnd {hwnd} no longer exists")

    flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
    try:
        win32gui.SetWindowPos(hwnd, 0, x, y, w, h, flags)
    except Exception as e:
        code = getattr(e, "winerror", None) or getattr(e, "errno", None) or 0
        if code == 5:
            raise AccessDenied(
                f"access denied: hwnd {hwnd} may be elevated (running as admin)"
            ) from e
        if code == 1400:
            raise WindowClosed(f"hwnd {hwnd} closed mid-operation") from e
        # Some pywin32 versions raise plain error tuples — retry-guard for
        # the most-likely elevated case using the message.
        msg = str(e).lower()
        if "access" in msg and "denied" in msg:
            raise AccessDenied(f"access denied: hwnd {hwnd} may be elevated") from e
        raise


# ── Resolver: target string → concrete windows ───────────────────────────

def _monitor_of_window(win: dict, monitors: list[dict]) -> int:
    """Return the index of the monitor whose work area contains the window's
    geometric center. Falls back to 0 if no monitor matches (window is
    off-screen or monitors empty)."""
    x, y, w, h = win["rect"]
    cx, cy = x + w // 2, y + h // 2
    for m in monitors:
        mx, my, mw, mh = m["rect"]
        if mx <= cx < mx + mw and my <= cy < my + mh:
            return m["index"]
    return 0


def _resolve_target(target: str, windows: list[dict]) -> tuple[list[dict], str]:
    """Resolve `target` to matching windows.

    Order per spec:
      1. hwnd (int)
      2. exact title (case-insensitive)
      3. fuzzy title (difflib ratio ≥ 0.8)
      4. app substring (case-insensitive on exe basename)

    Returns (candidates, method). Zero candidates → "none". Multiple
    candidates → callers must treat as ambiguous and NOT guess.
    """
    if target is None or target == "":
        return [], "empty"

    # 1. hwnd
    try:
        hwnd = int(target)
        matches = [w for w in windows if w["hwnd"] == hwnd]
        if matches:
            return matches, "hwnd"
    except (TypeError, ValueError):
        pass

    t = str(target).strip().lower()
    if not t:
        return [], "empty"

    # 2. Exact title
    exact = [w for w in windows if w["title"].lower() == t]
    if exact:
        return exact, "exact_title"

    # 3. Fuzzy title (Levenshtein 0.8 via difflib, matches orchestrator cache_layer)
    titles = [w["title"].lower() for w in windows]
    close = difflib.get_close_matches(t, titles, n=5, cutoff=0.8)
    if close:
        close_set = set(close)
        fuzzy = [w for w in windows if w["title"].lower() in close_set]
        return fuzzy, "fuzzy_title"

    # 4. App substring
    app_matches = [w for w in windows if w.get("app") and t in w["app"].lower()]
    if app_matches:
        return app_matches, "app_substring"

    return [], "none"


def _ambiguous(target: str, candidates: list[dict], method: str) -> ToolResult:
    slim = [
        {"hwnd": c["hwnd"], "title": c["title"], "app": c.get("app", "")}
        for c in candidates
    ]
    res = ToolResult.blocked(
        f"{len(candidates)} windows match {target!r} via {method} — pick one by hwnd or exact title"
    )
    res.data = {"candidates": slim, "method": method, "ambiguous": True}
    return res


# ── Layout math ─────────────────────────────────────────────────────────

def _layout_slots(layout: str, work_rect: tuple[int, int, int, int]) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Return [(slot_name, (x, y, w, h)), ...] for the named layout.

    Widths / heights use `w - w // 2` on the right/bottom slot so odd sizes
    tile exactly with no gaps (100px width → 50 + 50, 101px width → 50 + 51).
    """
    x, y, w, h = work_rect
    layouts = {
        "left-half":       lambda: [("left",  (x, y, w // 2, h))],
        "right-half":      lambda: [("right", (x + w // 2, y, w - w // 2, h))],
        "top-half":        lambda: [("top",    (x, y, w, h // 2))],
        "bottom-half":     lambda: [("bottom", (x, y + h // 2, w, h - h // 2))],
        "left-two-thirds": lambda: [("left",   (x, y, 2 * w // 3, h))],
        "right-third":     lambda: [("right",  (x + 2 * w // 3, y, w - 2 * w // 3, h))],
        "2-col":           lambda: [
            ("left",  (x, y, w // 2, h)),
            ("right", (x + w // 2, y, w - w // 2, h)),
        ],
        "3-col":           lambda: [
            ("left",   (x, y, w // 3, h)),
            ("center", (x + w // 3, y, w // 3, h)),
            ("right",  (x + 2 * (w // 3), y, w - 2 * (w // 3), h)),
        ],
        "2x2":             lambda: [
            ("top-left",     (x, y, w // 2, h // 2)),
            ("top-right",    (x + w // 2, y, w - w // 2, h // 2)),
            ("bottom-left",  (x, y + h // 2, w // 2, h - h // 2)),
            ("bottom-right", (x + w // 2, y + h // 2, w - w // 2, h - h // 2)),
        ],
        "quad":            lambda: [  # alias for 2x2
            ("top-left",     (x, y, w // 2, h // 2)),
            ("top-right",    (x + w // 2, y, w - w // 2, h // 2)),
            ("bottom-left",  (x, y + h // 2, w // 2, h - h // 2)),
            ("bottom-right", (x + w // 2, y + h // 2, w - w // 2, h - h // 2)),
        ],
        "maximize":        lambda: [("full",   (x, y, w, h))],
        "center":          lambda: [("center", (x + w // 4, y + h // 4, w // 2, h // 2))],
    }
    if layout not in layouts:
        raise ValueError(f"unknown layout {layout!r}")
    return layouts[layout]()


def _assign_to_slots(
    slots: list[tuple[str, tuple[int, int, int, int]]],
    windows: list[dict],
    assn_map: dict[str, str],
) -> list[tuple[int, str, tuple[int, int, int, int]]]:
    """Compute (hwnd, slot_name, rect) triples.

    Explicit assignments come first (by app/title substring match). Remaining
    slots fill with the not-yet-placed windows in hwnd-ascending order — the
    stable ordering is what makes arrange_windows idempotent across calls.
    """
    placements: list[tuple[int, str, tuple[int, int, int, int]]] = []
    used_hwnds: set[int] = set()
    used_slots: set[str] = set()

    for app_key, slot_name in assn_map.items():
        slot = next((s for s in slots if s[0] == slot_name), None)
        if slot is None or slot_name in used_slots:
            continue
        key = app_key.lower()
        candidates = [
            w for w in windows
            if w["hwnd"] not in used_hwnds and (
                (w.get("app") and key in w["app"].lower()) or
                key in w["title"].lower()
            )
        ]
        if not candidates:
            continue
        target = min(candidates, key=lambda w: w["hwnd"])
        placements.append((target["hwnd"], slot[0], slot[1]))
        used_hwnds.add(target["hwnd"])
        used_slots.add(slot[0])

    remaining_slots = [s for s in slots if s[0] not in used_slots]
    remaining_windows = sorted(
        (w for w in windows if w["hwnd"] not in used_hwnds),
        key=lambda w: w["hwnd"],
    )
    for slot, win in zip(remaining_slots, remaining_windows):
        placements.append((win["hwnd"], slot[0], slot[1]))

    return placements


# ── READONLY tools ───────────────────────────────────────────────────────

@tool(tier=CapabilityTier.READONLY)  # tier: enumerates windows, no side effects
def list_windows() -> ToolResult:
    """List every visible top-level window with rich metadata. Each entry:
    hwnd, title, app, monitor (index), rect [x,y,w,h], minimized, maximized,
    focused. Excludes tool windows, zero-area windows, and untitled shell
    surfaces. Ordering is stable (by hwnd)."""
    try:
        raw = _enumerate_windows()
        monitors = _enumerate_monitors()
    except Exception as e:
        log.exception("list_windows failed")
        return ToolResult.error(f"could not enumerate windows: {e}")
    for w in raw:
        w["monitor"] = _monitor_of_window(w, monitors)
    return ToolResult.success(
        message=f"{len(raw)} windows open",
        data={"windows": raw, "count": len(raw)},
        confidence=95.0,
        confidence_reason=["EnumWindows returned cleanly", f"{len(monitors)} monitors resolved"],
    )


@tool(tier=CapabilityTier.READONLY)  # tier: reads monitor geometry, no side effects
def get_monitors() -> ToolResult:
    """List each display: index, primary flag, work-area rect [x,y,w,h] (which
    excludes the taskbar), and DPI scale (1.0 = 100%, 1.5 = 150%, etc). Work
    area is the safe target for arrange_windows."""
    try:
        monitors = _enumerate_monitors()
    except Exception as e:
        log.exception("get_monitors failed")
        return ToolResult.error(f"could not enumerate monitors: {e}")
    return ToolResult.success(
        message=f"{len(monitors)} monitor(s)",
        data={"monitors": monitors, "count": len(monitors)},
        confidence=98.0,
        confidence_reason=[
            "EnumDisplayMonitors returned cleanly",
            "Per-monitor DPI awareness declared",
        ],
    )


# ── SYSTEM_WRITE mutating tools (untrusted for now) ──────────────────────

def _apply_position(target: str, x: int | None, y: int | None,
                    w: int | None, h: int | None) -> ToolResult:
    """Shared implementation for move_window / resize_window / move_resize.
    Resolves the target, restores if minimized, then SetWindowPos. Any None
    coordinate is taken from the current rect (so move preserves size, resize
    preserves position)."""
    try:
        windows = _enumerate_windows()
    except Exception as e:
        log.exception("window enumeration failed during move/resize")
        return ToolResult.error(f"could not enumerate windows: {e}")

    candidates, method = _resolve_target(target, windows)
    if not candidates:
        return ToolResult.blocked(
            f"no window matching {target!r} (tried hwnd, exact title, fuzzy title, app substring)"
        )
    if len(candidates) > 1:
        return _ambiguous(target, candidates, method)

    win = candidates[0]
    cur_x, cur_y, cur_w, cur_h = win["rect"]
    nx = cur_x if x is None else int(x)
    ny = cur_y if y is None else int(y)
    nw = cur_w if w is None else int(w)
    nh = cur_h if h is None else int(h)

    # Restore minimized targets so SetWindowPos has something to move.
    try:
        _restore_window(win["hwnd"])
    except WindowClosed as e:
        return ToolResult.error(f"window closed mid-operation: {e}")
    except AccessDenied as e:
        return ToolResult.error(f"access denied restoring window: {e}")

    try:
        _set_window_pos(win["hwnd"], nx, ny, nw, nh)
    except WindowClosed as e:
        return ToolResult.error(f"window closed mid-operation: {e}")
    except AccessDenied as e:
        return ToolResult.error(f"access denied: {e}")
    except Exception as e:
        return ToolResult.error(f"SetWindowPos failed: {e}")

    return ToolResult.success(
        message=f"placed {win['title']!r} at ({nx}, {ny}) size ({nw}x{nh})",
        data={
            "hwnd": win["hwnd"], "title": win["title"], "app": win.get("app", ""),
            "rect": [nx, ny, nw, nh], "resolved_by": method,
        },
        confidence=90.0,
        confidence_reason=[f"resolved via {method}", "SetWindowPos returned cleanly"],
    )


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: window position, reversible by moving it back
def move_window(target: str, x: int, y: int) -> ToolResult:
    """Move the window matching `target` to screen coordinate (x, y),
    preserving its current size. `target` resolves as hwnd (int) → exact
    title → fuzzy title (≥0.8) → app substring. Ambiguous matches return
    a candidates list instead of guessing."""
    return _apply_position(target, x, y, None, None)


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: window size, reversible
def resize_window(target: str, w: int, h: int) -> ToolResult:
    """Resize the window matching `target` to (w, h), preserving its current
    position. Same target resolution as move_window."""
    return _apply_position(target, None, None, w, h)


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: window geometry, reversible
def move_resize_window(target: str, x: int, y: int, w: int, h: int) -> ToolResult:
    """Atomically move and resize the window matching `target` to a rect."""
    return _apply_position(target, x, y, w, h)


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: rearranges windows, reversible; loses no data
def arrange_windows(layout: str, assignments: str = "", monitor: int = -1) -> ToolResult:
    """Tile foreground windows into a named grid on a monitor's work area.

    Layouts: left-half, right-half, top-half, bottom-half, left-two-thirds,
    right-third, 2-col, 3-col, 2x2 / quad, maximize, center.

    `assignments` is an optional JSON string mapping app/title-substring to a
    slot name, e.g. '{"chrome": "left", "vscode": "right"}'. Unassigned slots
    fill with the remaining foreground windows in stable order (by hwnd, so
    calling twice produces the same layout).

    `monitor` is a monitor index; -1 (default) picks the monitor of the
    focused window, falling back to primary."""
    try:
        monitors = _enumerate_monitors()
        windows = _enumerate_windows()
    except Exception as e:
        log.exception("arrange_windows: enumeration failed")
        return ToolResult.error(f"could not enumerate windows/monitors: {e}")

    if not monitors:
        return ToolResult.blocked("no monitors detected")
    for w in windows:
        w["monitor"] = _monitor_of_window(w, monitors)

    # Pick the target monitor.
    if monitor == -1:
        focused = next((w for w in windows if w["focused"]), None)
        if focused is not None:
            monitor = focused["monitor"]
        else:
            primary = next((m for m in monitors if m["primary"]), monitors[0])
            monitor = primary["index"]

    target_mon = next((m for m in monitors if m["index"] == monitor), None)
    if target_mon is None:
        return ToolResult.blocked(f"monitor index {monitor} not found (have {len(monitors)})")

    try:
        slots = _layout_slots(layout, tuple(target_mon["rect"]))
    except ValueError as e:
        return ToolResult.blocked(str(e))

    # Parse assignments if provided.
    assn_map: dict[str, str] = {}
    if assignments:
        try:
            parsed = json.loads(assignments)
            if not isinstance(parsed, dict):
                return ToolResult.blocked("assignments must be a JSON object mapping app→slot")
            assn_map = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError as e:
            return ToolResult.blocked(f"assignments not valid JSON: {e}")

    # Only arrange windows currently on the target monitor unless assigned
    # explicitly. Keeps "arrange left half" from stealing windows from your
    # other screen unexpectedly.
    on_monitor = [w for w in windows if w["monitor"] == monitor and not w["minimized"]]
    placements = _assign_to_slots(slots, on_monitor, assn_map)

    if not placements:
        return ToolResult.blocked(f"no windows to arrange on monitor {monitor}")

    placed = []
    failures = []
    for hwnd, slot_name, (px, py, pw, ph) in placements:
        try:
            _restore_window(hwnd)
            _set_window_pos(hwnd, px, py, pw, ph)
            placed.append({"hwnd": hwnd, "slot": slot_name, "rect": [px, py, pw, ph]})
        except AccessDenied as e:
            failures.append({"hwnd": hwnd, "slot": slot_name, "error": f"access denied: {e}"})
        except WindowClosed as e:
            failures.append({"hwnd": hwnd, "slot": slot_name, "error": f"window closed: {e}"})
        except Exception as e:
            failures.append({"hwnd": hwnd, "slot": slot_name, "error": str(e)})

    msg = f"arranged {len(placed)} window(s) into {layout}"
    if failures:
        msg += f" ({len(failures)} skipped: access denied or closed)"
    return ToolResult.success(
        message=msg,
        data={"layout": layout, "monitor": monitor, "placed": placed, "failures": failures},
        confidence=85.0 if not failures else 65.0,
        confidence_reason=[
            f"{len(placed)}/{len(placements)} placements succeeded",
            f"layout={layout} on monitor {monitor}",
        ],
    )


# ── Existing tools kept unchanged ────────────────────────────────────────

@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: reversible by restoring
def minimize_all() -> ToolResult:
    """Minimize every window and show the desktop (Win+D)."""
    pyautogui.hotkey("win", "d")
    return ToolResult.success("showed desktop")


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # tier: window focus, reversible; trusted: benign UX affordance
def focus_window(app: str) -> ToolResult:
    """Bring a window to the front by matching its title against `app`.
    Match is case-insensitive substring (e.g. "chrome" matches "Google Chrome").
    """
    needle = app.strip().lower()
    if not needle:
        return ToolResult.blocked("empty app name")

    matches = [w for w in gw.getAllWindows() if w.title and needle in w.title.lower()]
    if not matches:
        return ToolResult.blocked(f"no window matching {app!r}")

    target = matches[0]
    try:
        if target.isMinimized:
            target.restore()
        target.activate()
    except Exception as e:
        return ToolResult.error(str(e))
    return ToolResult.success(f"focused {target.title!r}")


@tool(
    tier=CapabilityTier.SYSTEM_WRITE,
    trusted=True,
    confirm_if=lambda args: confirm_close_focused(),
)  # trusted like close_app, and guarded the same way — the difference is that
# the target is whatever happens to be focused, so the guard has to look it up
def close_active_window(expect_hwnd: int | None = None, expect_pid: int | None = None,
                        expect_title: str = "", expect_process: str = "") -> ToolResult:
    """Close the currently focused window. Leave the expect_* arguments
    empty: the confirmation step fills them with the window the user
    approved."""
    # Alt+F4 went to whatever had focus when it RAN — after a HUD "yes" that
    # can be the HUD — and "closed" was said even when a "Save changes?"
    # prompt kept the window open. Now: the window pinned when the guard
    # looked (or the foreground now, with no confirmation in between), a
    # polite WM_CLOSE to exactly that window, and a check that it went.
    if expect_hwnd is None:
        from backend.core.tools.files import foreground_window

        fg = foreground_window()
        if fg is None:
            return ToolResult.blocked("can't tell which window is focused")
        expect_hwnd, expect_pid, expect_title = fg["hwnd"], fg["pid"], fg["title"]
    label = expect_title or expect_process or "the window"
    if not _window_alive(expect_hwnd) or (expect_pid and _window_pid(expect_hwnd) != expect_pid):
        return ToolResult.blocked(f"{label} is no longer open — nothing was closed")
    if not _post_close(expect_hwnd):
        return ToolResult.error(f"Windows wouldn't send the close request to {label}")
    deadline = time.monotonic() + _CLOSE_WAIT_S
    while time.monotonic() < deadline:
        if not _window_alive(expect_hwnd):
            return ToolResult.success(f"closed {label}")
        time.sleep(0.1)
    if _has_modal_popup(expect_hwnd):
        return ToolResult.blocked(f"a save prompt is open in {label} — it is still open")
    return ToolResult.error(f"{label} didn't close")


_CLOSE_WAIT_S = 2.0


def _window_alive(hwnd: int) -> bool:
    import win32gui

    return bool(win32gui.IsWindow(hwnd)) and bool(win32gui.IsWindowVisible(hwnd))


def _window_pid(hwnd: int) -> int:
    import win32process

    return int(win32process.GetWindowThreadProcessId(hwnd)[1])


def _post_close(hwnd: int) -> bool:
    import win32con
    import win32gui

    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True
    except Exception as e:  # noqa: BLE001 — pywintypes.error on a dead/elevated window
        log.debug("WM_CLOSE to %s failed: %s", hwnd, e)
        return False


def _has_modal_popup(hwnd: int) -> bool:
    """A dialog the window is waiting on ("Save changes?"): it disables its
    owner, and GW_ENABLEDPOPUP names it."""
    import win32con
    import win32gui

    popup = win32gui.GetWindow(hwnd, win32con.GW_ENABLEDPOPUP)
    return (bool(popup) and popup != hwnd) or not win32gui.IsWindowEnabled(hwnd)


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: locking is the SAFE direction, and reversible by unlocking
def lock_screen() -> ToolResult:
    """Lock the workstation (Win+L)."""
    # Called directly: rundll32 swallowed the result, so a lock refused by
    # policy (DisableLockWorkstation) still said "screen locked" while the
    # machine stayed open. Nonzero means Windows accepted the request; the
    # lock itself follows a moment later.
    import ctypes

    if not ctypes.windll.user32.LockWorkStation():
        return ToolResult.error(
            f"Windows refused to lock the screen (error {ctypes.GetLastError()}) — "
            "locking may be disabled by a policy on this PC")
    return ToolResult.success("screen locked")


# ── power ─────────────────────────────────────────────────────────────────
# Each result comes from Windows, never from having asked. shutdown.exe was
# started with Popen and its exit code thrown away, so "shutting down in 10s"
# was said even when Windows refused. Decisions go by exit code, never by the
# English text of an error, which a localized Windows doesn't print.
_ERROR_SHUTDOWN_IS_SCHEDULED = 1190
_ERROR_NO_SHUTDOWN_IN_PROGRESS = 1116

_sleep_lock = threading.Lock()
_sleep_timer: threading.Timer | None = None


def _suspend() -> tuple[bool, int]:
    """Sleep now: SetSuspendState(Hibernate=FALSE, ...). Called directly —
    `rundll32 powrprof.dll,SetSuspendState 0,1,0` hands the function junk
    arguments and hibernates instead when hibernation is on. (ok, winerror)."""
    import ctypes

    ok = bool(ctypes.windll.powrprof.SetSuspendState(False, True, False))
    return ok, (0 if ok else ctypes.GetLastError())


def _sleep_allowed() -> bool:
    import ctypes

    return bool(ctypes.windll.powrprof.IsPwrSuspendAllowed())


def _fire_sleep() -> None:
    global _sleep_timer
    with _sleep_lock:
        _sleep_timer = None
    ok, err = _suspend()
    if not ok:
        log.error("sleep_pc: Windows refused to sleep (error %s)", err)


def _shutdown_exe(*args: str) -> subprocess.CompletedProcess:
    # shutdown.exe returns as soon as the request is registered, so waiting
    # for it costs nothing and gives us Windows' answer.
    return subprocess.run(["shutdown", *args], capture_output=True, text=True, timeout=15)


def _schedule(flag: str, seconds: int, doing: str) -> ToolResult:
    try:
        r = _shutdown_exe(flag, "/t", str(seconds))
    except (OSError, subprocess.SubprocessError) as e:
        return ToolResult.error(f"couldn't ask Windows to {doing}: {e}")
    if r.returncode == 0:
        return ToolResult.success(f"{doing} in {seconds}s — say cancel shutdown to abort")
    if r.returncode == _ERROR_SHUTDOWN_IS_SCHEDULED:
        return ToolResult.blocked("a shutdown or restart is already scheduled — "
                                  "say cancel shutdown first")
    detail = (r.stderr or r.stdout or "").strip()
    return ToolResult.error(f"Windows refused to {doing} (code {r.returncode}){': ' + detail if detail else ''}")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: sleeps machine, disrupts running work
def sleep_pc(seconds: int = 5) -> ToolResult:
    """Put the PC to sleep after a `seconds` countdown (default 5).
    Use cancel_shutdown to abort within the countdown window."""
    global _sleep_timer
    seconds = max(0, int(seconds))
    if not _sleep_allowed():
        return ToolResult.blocked("this PC doesn't allow sleep (its power settings or hardware)")
    if seconds == 0:
        ok, err = _suspend()
        if not ok:
            return ToolResult.error(f"Windows refused to sleep (error {err})")
        return ToolResult.success("slept")  # returns after the PC wakes up again
    with _sleep_lock:
        if _sleep_timer is not None:
            return ToolResult.blocked("sleep is already scheduled — say cancel shutdown to stop it")
        timer = _sleep_timer = threading.Timer(seconds, _fire_sleep)
        timer.daemon = True
    timer.start()  # outside the lock: _fire_sleep takes it
    return ToolResult.success(f"sleeping in {seconds}s — say cancel shutdown to abort")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: power state, unsaved work is lost
def shutdown_pc(seconds: int = 10) -> ToolResult:
    """Shut down the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    return _schedule("/s", max(0, int(seconds)), "shutting down")


@tool(security=SecurityLevel.CRITICAL, tier=CapabilityTier.DESTRUCTIVE)  # tier: power state, unsaved work is lost
def restart_pc(seconds: int = 10) -> ToolResult:
    """Restart the PC after a `seconds` countdown (default 10).
    Run cancel_shutdown to abort within the countdown."""
    return _schedule("/r", max(0, int(seconds)), "restarting")


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: aborts a pending shutdown — prompting to CANCEL a destructive event is backwards
def cancel_shutdown() -> ToolResult:
    """Cancel a pending shutdown, restart or sleep."""
    global _sleep_timer
    with _sleep_lock:
        timer, _sleep_timer = _sleep_timer, None
    if timer is not None:
        timer.cancel()
    try:
        r = _shutdown_exe("/a")
    except (OSError, subprocess.SubprocessError) as e:
        return ToolResult.error(f"couldn't ask Windows to cancel: {e}")
    if r.returncode == 0:
        return ToolResult.success("shutdown cancelled" + (" and sleep cancelled" if timer else ""))
    if r.returncode == _ERROR_NO_SHUTDOWN_IN_PROGRESS:
        if timer is not None:
            return ToolResult.success("sleep cancelled")
        return ToolResult.blocked("nothing was scheduled — no shutdown, restart or sleep")
    detail = (r.stderr or r.stdout or "").strip()
    return ToolResult.error(f"Windows refused to cancel (code {r.returncode}){': ' + detail if detail else ''}"
                            + (" — sleep was cancelled" if timer else ""))
