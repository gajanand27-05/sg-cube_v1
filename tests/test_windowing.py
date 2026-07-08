"""Phase 1 — windowing tools.

Everything patches the low-level primitives (_enumerate_windows,
_enumerate_monitors, _set_window_pos, _restore_window) so the suite runs
headless on any box — real HWNDs and monitors aren't required. The one
place we can't easily mock is DPI awareness init at module import; if
that path fails it's silent (per the module docstring), so import
doesn't crash.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)


# ── Fixture data ────────────────────────────────────────────────────────

def _sample_windows():
    """Four windows on a single monitor. Kept small and predictable."""
    return [
        {"hwnd": 101, "title": "Google Chrome — Home",       "app": "chrome.exe",
         "rect": [0, 0, 800, 600], "minimized": False, "maximized": False, "focused": True},
        {"hwnd": 202, "title": "Visual Studio Code",          "app": "Code.exe",
         "rect": [100, 100, 900, 700], "minimized": False, "maximized": False, "focused": False},
        {"hwnd": 303, "title": "Notepad",                     "app": "notepad.exe",
         "rect": [200, 200, 400, 300], "minimized": False, "maximized": False, "focused": False},
        {"hwnd": 404, "title": "Slack | general | Acme",       "app": "slack.exe",
         "rect": [300, 50, 800, 600], "minimized": False, "maximized": False, "focused": False},
    ]


def _sample_monitors():
    """One 1920×1080 primary monitor with a 40-pixel taskbar."""
    return [{"index": 0, "primary": True, "rect": [0, 0, 1920, 1040], "scale": 1.0}]


# ── list_windows ────────────────────────────────────────────────────────

def test_list_windows_schema():
    """Every entry must have the full schema per spec §1."""
    from backend.core.tools import windowing as w

    with patch.object(w, "_enumerate_windows", return_value=_sample_windows()), \
         patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()):
        result = w.list_windows()

    assert result.status.value == "success"
    windows = result.data["windows"]
    assert len(windows) == 4
    for entry in windows:
        for key in ("hwnd", "title", "app", "monitor", "rect",
                    "minimized", "maximized", "focused"):
            assert key in entry, f"missing key {key!r}: {entry}"
        assert isinstance(entry["hwnd"], int)
        assert isinstance(entry["rect"], list) and len(entry["rect"]) == 4
        assert entry["monitor"] == 0  # all four sit on our single monitor
    # Stable order → hwnd ascending
    hwnds = [w["hwnd"] for w in windows]
    assert hwnds == sorted(hwnds), f"expected stable hwnd order, got {hwnds}"
    print(f"  [PASS] list_windows: 4 entries, full schema, stable order")


# ── get_monitors ────────────────────────────────────────────────────────

def test_get_monitors_schema():
    """Reports ≥1 monitor with plausible work area + a scale value."""
    from backend.core.tools import windowing as w

    with patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()):
        result = w.get_monitors()

    assert result.status.value == "success"
    monitors = result.data["monitors"]
    assert len(monitors) >= 1
    m = monitors[0]
    for key in ("index", "primary", "rect", "scale"):
        assert key in m, f"missing key {key!r}: {m}"
    x, y, mw, mh = m["rect"]
    assert mw > 0 and mh > 0, f"work-area rect must be positive: {m['rect']}"
    assert m["scale"] > 0, f"scale must be > 0: {m['scale']}"
    print(f"  [PASS] get_monitors: {len(monitors)} monitor(s) with valid schema")


# ── Target resolver — hwnd / exact title / fuzzy / app / ambiguous / missing ─

def _install_move_stubs(w, capture: dict):
    """Patch _enumerate_windows + _set_window_pos + _restore_window on the
    windowing module. `capture["calls"]` records each SetWindowPos call."""
    def _cap(hwnd, x, y, ww, hh):
        capture["calls"].append((hwnd, x, y, ww, hh))
    patches = [
        patch.object(w, "_enumerate_windows", return_value=_sample_windows()),
        patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()),
        patch.object(w, "_set_window_pos", side_effect=_cap),
        patch.object(w, "_restore_window", return_value=None),
    ]
    for p in patches:
        p.start()
    return lambda: [p.stop() for p in patches]


def test_move_window_by_hwnd():
    from backend.core.tools import windowing as w
    capture = {"calls": []}
    stop = _install_move_stubs(w, capture)
    try:
        result = w.move_window("101", 50, 60)
        assert result.status.value == "success"
        assert result.data["resolved_by"] == "hwnd"
        assert capture["calls"] == [(101, 50, 60, 800, 600)]  # size preserved
        print("  [PASS] move_window resolved by hwnd; size preserved")
    finally:
        stop()


def test_move_window_by_exact_title():
    from backend.core.tools import windowing as w
    capture = {"calls": []}
    stop = _install_move_stubs(w, capture)
    try:
        result = w.move_window("notepad", 10, 20)
        assert result.status.value == "success"
        assert result.data["resolved_by"] == "exact_title"
        assert capture["calls"] == [(303, 10, 20, 400, 300)]
        print("  [PASS] move_window resolved by exact title (case-insensitive)")
    finally:
        stop()


def test_move_window_by_fuzzy_title():
    from backend.core.tools import windowing as w
    capture = {"calls": []}
    stop = _install_move_stubs(w, capture)
    try:
        # difflib.get_close_matches("visual studio code", [...], cutoff=0.8)
        # matches "visual studio code" — fuzzy pass since our real title
        # has trailing whitespace differences that pass 0.8.
        result = w.move_window("visual studio code", 300, 300)
        assert result.status.value == "success"
        assert result.data["resolved_by"] in ("exact_title", "fuzzy_title")
        assert capture["calls"] == [(202, 300, 300, 900, 700)]
        print("  [PASS] move_window resolved by title match (fuzzy or exact)")
    finally:
        stop()


def test_move_window_by_app_substring():
    from backend.core.tools import windowing as w
    capture = {"calls": []}
    stop = _install_move_stubs(w, capture)
    try:
        # "chrome" doesn't match "Google Chrome — Home" fuzzily (ratio < 0.8),
        # but does substring-match app "chrome.exe".
        result = w.move_window("chrome", 0, 0)
        assert result.status.value == "success"
        assert result.data["resolved_by"] == "app_substring"
        assert capture["calls"] == [(101, 0, 0, 800, 600)]
        print("  [PASS] move_window resolved by app substring")
    finally:
        stop()


def test_move_window_ambiguous_returns_candidates_not_guess():
    """Two windows with the same fuzzy match → blocked + candidates data."""
    from backend.core.tools import windowing as w

    # Two Chrome windows: substring-match on app is ambiguous.
    two_chromes = [
        {"hwnd": 501, "title": "Google Chrome — Gmail",  "app": "chrome.exe",
         "rect": [0, 0, 800, 600], "minimized": False, "maximized": False, "focused": False},
        {"hwnd": 502, "title": "Google Chrome — GitHub", "app": "chrome.exe",
         "rect": [50, 50, 800, 600], "minimized": False, "maximized": False, "focused": False},
    ]
    capture = {"calls": []}
    patches = [
        patch.object(w, "_enumerate_windows", return_value=two_chromes),
        patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()),
        patch.object(w, "_set_window_pos", side_effect=lambda *a: capture["calls"].append(a)),
        patch.object(w, "_restore_window", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        result = w.move_window("chrome", 100, 100)
        # Ambiguous → BLOCKED, not SUCCESS, and includes candidates.
        assert result.status.value == "blocked", f"expected blocked, got {result.status.value}"
        assert result.data.get("ambiguous") is True, "must flag ambiguity for the Planner"
        cands = result.data.get("candidates") or []
        assert len(cands) == 2
        assert {c["hwnd"] for c in cands} == {501, 502}
        assert capture["calls"] == [], "must NOT guess and move one"
        print("  [PASS] ambiguous match returns candidates, does not guess")
    finally:
        for p in patches:
            p.stop()


def test_move_window_not_found_returns_structured_error():
    from backend.core.tools import windowing as w
    capture = {"calls": []}
    stop = _install_move_stubs(w, capture)
    try:
        result = w.move_window("definitely-not-a-window", 0, 0)
        # Structured error, no exception.
        assert result.status.value == "blocked"
        assert "no window matching" in (result.reason or "").lower()
        assert capture["calls"] == []
        print("  [PASS] not-found → structured 'blocked' with clear reason")
    finally:
        stop()


def test_move_window_access_denied_returns_structured_error():
    """Elevated window: SetWindowPos raises AccessDenied → tool returns
    error status the Healer can classify (not an uncaught exception)."""
    from backend.core.tools import windowing as w

    def _raise_access_denied(*_args, **_kw):
        raise w.AccessDenied("hwnd 101 may be elevated (running as admin)")

    patches = [
        patch.object(w, "_enumerate_windows", return_value=_sample_windows()),
        patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()),
        patch.object(w, "_set_window_pos", side_effect=_raise_access_denied),
        patch.object(w, "_restore_window", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        result = w.move_window("101", 0, 0)
        assert result.status.value == "error"
        assert "access denied" in (result.reason or "").lower()
        print("  [PASS] access denied → structured error (no uncaught exception)")
    finally:
        for p in patches:
            p.stop()


# ── arrange_windows ─────────────────────────────────────────────────────

def _rects_overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _rects_tile_area(rects: list, area: tuple[int, int, int, int]) -> bool:
    """Every pixel of the work area covered by exactly one rect."""
    total = sum(r[2] * r[3] for r in rects)
    ax, ay, aw, ah = area
    return total == aw * ah


def test_arrange_2x2_tiles_work_area():
    """Four windows on the primary monitor → 4 non-overlapping rects that
    together tile the entire work area exactly."""
    from backend.core.tools import windowing as w

    capture = {"calls": []}
    def _cap(hwnd, x, y, ww, hh):
        capture["calls"].append((hwnd, x, y, ww, hh))

    patches = [
        patch.object(w, "_enumerate_windows", return_value=_sample_windows()),
        patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()),
        patch.object(w, "_set_window_pos", side_effect=_cap),
        patch.object(w, "_restore_window", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        result = w.arrange_windows("2x2")
        assert result.status.value == "success"
        placed = result.data["placed"]
        assert len(placed) == 4, f"expected 4 placements, got {len(placed)}"

        rects = [tuple(p["rect"]) for p in placed]
        # No pairwise overlap
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j]), (
                    f"rects {rects[i]} and {rects[j]} overlap"
                )
        # Tile the work area exactly
        work = tuple(_sample_monitors()[0]["rect"])
        assert _rects_tile_area(rects, work), (
            f"total area {sum(r[2] * r[3] for r in rects)} != work area "
            f"{work[2] * work[3]}"
        )
        # And SetWindowPos was called for each
        assert len(capture["calls"]) == 4
        print("  [PASS] arrange_windows('2x2'): 4 non-overlapping rects, tile work area exactly")
    finally:
        for p in patches:
            p.stop()


def test_arrange_windows_idempotent():
    """Calling twice with identical inputs must yield identical placements —
    stable ordering by hwnd is what buys us that."""
    from backend.core.tools import windowing as w

    patches = [
        patch.object(w, "_enumerate_windows", return_value=_sample_windows()),
        patch.object(w, "_enumerate_monitors", return_value=_sample_monitors()),
        patch.object(w, "_set_window_pos", return_value=None),
        patch.object(w, "_restore_window", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        r1 = w.arrange_windows("2x2")
        r2 = w.arrange_windows("2x2")
        # Compare (hwnd, slot, rect) tuples
        p1 = sorted((x["hwnd"], x["slot"], tuple(x["rect"])) for x in r1.data["placed"])
        p2 = sorted((x["hwnd"], x["slot"], tuple(x["rect"])) for x in r2.data["placed"])
        assert p1 == p2, f"non-idempotent placements:\n  {p1}\n  {p2}"
        print("  [PASS] arrange_windows is idempotent across successive calls")
    finally:
        for p in patches:
            p.stop()


# ── Healer integration — exercises the new mappings ─────────────────────

def test_healer_maps_windowing_errors():
    """Phase 1's new failure signals must route to the recovery paths spec'd."""
    from backend.core.healing import healer, RecoveryPath

    # window-not-found → PIVOT (re-list, try again)
    assert healer.analyze("move_window", "no window matching 'chrome'") == RecoveryPath.PIVOT

    # access-denied on elevated → ESCALATE (user has to act)
    assert healer.analyze("move_window", "access denied: hwnd 42 may be elevated") == RecoveryPath.ESCALATE

    # window-closed-mid-op → RETRY once, then ABORT
    assert healer.analyze("move_window", "window closed mid-operation", attempt=1) == RecoveryPath.RETRY
    assert healer.analyze("move_window", "window closed mid-operation", attempt=2) == RecoveryPath.ABORT

    print("  [PASS] healer maps windowing signals to spec'd recovery paths")


if __name__ == "__main__":
    test_list_windows_schema()
    test_get_monitors_schema()
    test_move_window_by_hwnd()
    test_move_window_by_exact_title()
    test_move_window_by_fuzzy_title()
    test_move_window_by_app_substring()
    test_move_window_ambiguous_returns_candidates_not_guess()
    test_move_window_not_found_returns_structured_error()
    test_move_window_access_denied_returns_structured_error()
    test_arrange_2x2_tiles_work_area()
    test_arrange_windows_idempotent()
    test_healer_maps_windowing_errors()
    print("All Phase 1 windowing tests passed.")
