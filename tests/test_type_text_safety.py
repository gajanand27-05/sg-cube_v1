"""type_text types into whatever window has focus — a terminal included, where
a line break is Enter. Its protection is the confirmation, so first: it must
ask even when Ollama (phi3) is up and approves, on a direct wake command."""
import asyncio

import pytest

import backend.core.tools  # noqa: F401
from backend.core.agent import verifier
from backend.core.state import manager as state_manager


@pytest.fixture
def phi3_approves(monkeypatch):
    async def ok(*a, **k):
        return True
    monkeypatch.setattr(verifier, "_secondary_check", ok)


@pytest.fixture(autouse=True)
def _reset():
    yield
    state_manager._voice_trigger_source = None


@pytest.mark.parametrize("source", [None, "wake", "followup"])
def test_type_text_asks_even_when_phi3_approves(phi3_approves, source):
    state_manager._voice_trigger_source = source
    r = asyncio.run(verifier.verify("type hello", {"name": "type_text",
                                                   "args": {"text": "hello"}, "confidence": 1.0}))
    assert r.is_valid and r.needs_confirmation, (source, r.error)


# ── everything below runs at a seam: a fake foreground window, a recorded
# typewrite, recorded HUD events. No test touches the real desktop or reads
# real window titles.

from backend.core.agent import tool_policy  # noqa: E402
from backend.core.tools import files  # noqa: E402
from backend.core.tools.registry import REGISTRY  # noqa: E402

NOTEPAD = {"hwnd": 101, "pid": 11, "title": "todo.txt - Notepad", "process": "notepad.exe",
           "class": "Notepad"}
BROWSER = {"hwnd": 202, "pid": 22, "title": "SG-CUBE HUD", "process": "chrome.exe",
           "class": "Chrome_WidgetWin_1"}


@pytest.fixture
def desk(monkeypatch):
    """A desktop whose foreground window the test controls. `script` is the
    sequence successive foreground_window() calls return (the last repeats);
    `after_chunk` swaps focus once typing has begun."""
    state = {"script": [NOTEPAD], "typed": [], "events": [], "after_chunk": None, "calls": 0}

    def fg():
        state["calls"] += 1
        return state["script"].pop(0) if len(state["script"]) > 1 else state["script"][0]

    def typewrite(t, interval=0):
        state["typed"].append(t)
        if state["after_chunk"] is not None:
            state["script"] = [state["after_chunk"]]

    def event(state_, title, process, **kw):
        state["events"].append((state_, title, process, kw))

    monkeypatch.setattr(files, "foreground_window", fg)
    monkeypatch.setattr(files.pyautogui, "typewrite", typewrite)
    monkeypatch.setattr(files, "_typing_event", event)
    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    return state


def _prepared(desk, text, window=NOTEPAD):
    desk["script"] = [window]
    prep = tool_policy.prepare_confirmation("type_text", {"text": text})
    assert prep.refusal is None, prep.refusal
    return prep


def test_dictation_with_symbols_is_no_longer_refused(phi3_approves):
    """The metacharacter and blocked-word rules are gone for type_text."""
    for text in [r"save it to C:\Users\me\report.docx", "check https://x.com/?q=a&b=c",
                 "it costs $49.99", "please format the report", "the shutdown meeting is at 4",
                 "a = {1, 2}; b = [3]", "one | two"]:
        r = asyncio.run(verifier.verify("", {"name": "type_text", "args": {"text": text},
                                             "confidence": 1.0}))
        assert r.is_valid and r.needs_confirmation, (text, r.error)


def test_run_command_is_still_checked(phi3_approves):
    r = asyncio.run(verifier.verify("", {"name": "run_command",
                                         "args": {"command": "dir & del x"}, "confidence": 1.0}))
    assert not r.is_valid


def test_the_confirmation_names_the_window_and_shows_line_breaks(desk):
    prep = _prepared(desk, "line one\nline two\r\nthree")
    assert prep.details[0] == "Types into: todo.txt - Notepad (notepad.exe)"
    assert prep.details[1] == "Text: line one\u23celine two\u23cethree"
    assert (prep.args["expect_hwnd"], prep.args["expect_pid"]) == (101, 11)
    assert (prep.args["expect_title"], prep.args["expect_process"]) == ("todo.txt - Notepad", "notepad.exe")


def test_the_window_is_part_of_what_the_user_approves(desk):
    from backend.core.agents.pending_confirmation import calls_digest
    a = _prepared(desk, "hi").args
    b = _prepared(desk, "hi", window=BROWSER).args
    assert calls_digest([{"name": "type_text", "args": a}]) != \
        calls_digest([{"name": "type_text", "args": b}])


# ── option 2: after a HUD yes, wait for the user to click into the window ─

def test_voice_yes_with_focus_already_there_types_at_once(desk):
    args = _prepared(desk, "hello").args
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "success" and desk["typed"] == ["hello"]
    assert "waiting" not in [e[0] for e in desk["events"]]


def test_hud_yes_waits_then_types_when_the_user_clicks_in(desk):
    args = _prepared(desk, "hello").args
    desk["script"] = [BROWSER, BROWSER, BROWSER, NOTEPAD]      # HUD in front, then Notepad
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "success" and desk["typed"] == ["hello"]
    waiting = [e for e in desk["events"] if e[0] == "waiting"][0]
    assert waiting[1:3] == ("todo.txt - Notepad", "notepad.exe")
    assert waiting[3]["timeout_s"] == files.TYPE_TEXT_FOCUS_WAIT_S == 10.0


def test_the_wait_times_out_and_types_nothing(desk, monkeypatch):
    monkeypatch.setattr(files, "TYPE_TEXT_FOCUS_WAIT_S", 0.05)
    args = _prepared(desk, "hello").args
    desk["script"] = [BROWSER]
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "blocked" and "did not get focus" in r["reason"]
    assert "nothing was typed" in r["reason"] and desk["typed"] == []
    assert desk["events"][-1][0] == "cancelled"


def test_another_window_with_the_same_title_is_not_the_target(desk, monkeypatch):
    """Same handle AND process: a different Notepad window does not count."""
    monkeypatch.setattr(files, "TYPE_TEXT_FOCUS_WAIT_S", 0.05)
    args = _prepared(desk, "hello").args
    desk["script"] = [{**NOTEPAD, "hwnd": 999}]
    assert REGISTRY["type_text"].func(**args)["status"] == "blocked"
    assert desk["typed"] == []


def test_focus_leaving_mid_typing_stops_and_reports_how_much(desk):
    text = "a" * 40                                       # chunks of 16, 16, 8
    args = _prepared(desk, text).args
    desk["after_chunk"] = BROWSER                         # user clicks away after chunk 1
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "error"
    assert "after 16 of 40 characters" in r["reason"]
    assert desk["typed"] == ["a" * 16]
    assert desk["events"][-1][0] == "stopped" and desk["events"][-1][3]["typed"] == 16


def test_focus_is_checked_before_every_chunk(desk):
    args = _prepared(desk, "x" * 40).args
    desk["calls"] = 0
    REGISTRY["type_text"].func(**args)
    # 1 wait check + 1 target read + 1 before each of the 3 chunks
    assert desk["calls"] == 5 and len(desk["typed"]) == 3


def test_line_breaks_are_typed_as_their_own_chunks(desk):
    args = _prepared(desk, "one\r\ntwo").args
    REGISTRY["type_text"].func(**args)
    assert desk["typed"] == ["one", "\n", "two"]


# ── line breaks into things that run commands ───────────────────────────

RUNNERS = [
    ("cmd.exe", "ConsoleWindowClass"), ("powershell.exe", "ConsoleWindowClass"),
    ("pwsh.exe", "ConsoleWindowClass"), ("windowsterminal.exe", "CASCADIA_HOSTING_WINDOW_CLASS"),
    ("conhost.exe", "ConsoleWindowClass"), ("mintty.exe", "mintty"),
    ("explorer.exe", "#32770"),                          # the Win+R Run dialog
]


@pytest.mark.parametrize("process,cls", RUNNERS)
def test_a_line_break_where_it_would_run_a_command_is_refused(desk, process, cls):
    window = {**NOTEPAD, "process": process, "class": cls, "title": "x"}
    desk["script"] = [window]
    prep = tool_policy.prepare_confirmation("type_text", {"text": "del important.txt\n"})
    assert prep.refusal and "line break" in prep.refusal
    r = REGISTRY["type_text"].func(text="del important.txt\n")     # and at typing time too
    assert r["status"] == "blocked" and desk["typed"] == []


def test_file_explorer_is_not_the_run_dialog(desk):
    """Only explorer's #32770 dialog runs what you type; a File Explorer
    window (class CabinetWClass) does not."""
    window = {**NOTEPAD, "process": "explorer.exe", "class": "CabinetWClass", "title": "Downloads"}
    assert files.runs_commands(window) is False


def test_a_terminal_without_a_line_break_is_allowed(desk):
    desk["script"] = [{**NOTEPAD, "process": "cmd.exe", "class": "ConsoleWindowClass"}]
    assert tool_policy.prepare_confirmation("type_text", {"text": "dir"}).refusal is None


def test_an_unknown_target_window_is_refused(desk):
    desk["script"] = [None]
    assert "which window" in tool_policy.prepare_confirmation("type_text", {"text": "x"}).refusal


# ── deadline and cancel: the typing thread never outlives the call ──────

import threading  # noqa: E402

from backend.core import runtime as rt  # noqa: E402


@pytest.fixture
def clock(monkeypatch, desk):
    """Fake monotonic clock: +1 s per chunk typed."""
    now = {"t": 1000.0}
    monkeypatch.setattr(files.time, "monotonic", lambda: now["t"])
    real_tw = files.pyautogui.typewrite

    def tick(t, interval=0):
        real_tw(t, interval)
        now["t"] += 1.0
    monkeypatch.setattr(files.pyautogui, "typewrite", tick)
    return now


@pytest.fixture
def call_ctx():
    """Stand in for runtime.run_tool's per-call context on this thread."""
    cancel = threading.Event()

    def set_(deadline):
        rt._call_ctx.cancel, rt._call_ctx.deadline = cancel, deadline
    yield cancel, set_
    rt._call_ctx.cancel = rt._call_ctx.deadline = None


def test_the_time_limit_stops_at_a_chunk_boundary_and_reports_it(desk, clock, call_ctx):
    cancel, set_ctx = call_ctx
    args = _prepared(desk, "x" * 1400).args
    set_ctx(clock["t"] + 5.0)          # a 5 s call: typing must stop by t+3 (2 s margin)
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "error"
    assert r["reason"] == "stopped: time limit reached after 48 of 1,400 characters were typed"
    assert sum(map(len, desk["typed"])) == 48 and all(len(c) == 16 for c in desk["typed"])
    assert desk["events"][-1][0] == "stopped"


def test_the_deadline_leaves_the_margin_before_the_runtime_timeout(desk, clock, call_ctx):
    _, set_ctx = call_ctx
    args = _prepared(desk, "x" * 1400).args
    start = clock["t"]
    set_ctx(start + 30.0)              # the default tool timeout
    REGISTRY["type_text"].func(**args)
    assert clock["t"] <= start + 30.0 - files._DEADLINE_MARGIN_S


def test_a_cancel_stops_typing_before_the_next_chunk(desk, clock, call_ctx):
    cancel, set_ctx = call_ctx
    args = _prepared(desk, "y" * 64).args
    set_ctx(clock["t"] + 30.0)
    real_tw = files.pyautogui.typewrite

    def cancel_after_first(t, interval=0):
        real_tw(t, interval)
        cancel.set()
    files.pyautogui.typewrite = cancel_after_first
    r = REGISTRY["type_text"].func(**args)
    assert r["reason"] == "stopped: the request was cancelled after 16 of 64 characters were typed"
    assert sum(map(len, desk["typed"])) == 16


def test_a_cancel_during_the_focus_wait_types_nothing(desk, clock, call_ctx):
    cancel, set_ctx = call_ctx
    args = _prepared(desk, "hello").args
    desk["script"] = [BROWSER]
    set_ctx(clock["t"] + 30.0)
    cancel.set()
    r = REGISTRY["type_text"].func(**args)
    assert r["status"] == "blocked" and "cancelled" in r["reason"] and desk["typed"] == []


def test_the_runtime_sets_the_flag_on_timeout_and_the_thread_exits():
    """End to end through runtime.run_tool with a real (tiny) timeout: the
    sync tool's thread sees the flag and stops instead of running on."""
    import asyncio
    seen = {}
    exited = threading.Event()

    def slow_tool():
        cancel, deadline = rt.current_call()
        seen["ctx"] = (cancel is not None, deadline is not None)
        cancel.wait(5)                       # a tool loop polling the flag
        seen["cancelled"] = cancel.is_set()
        exited.set()
        return {"status": "success", "message": "late"}

    res = asyncio.run(rt.runtime.run_tool("slow_tool", slow_tool, {}, timeout=0.2))
    assert res.status == "error"
    assert "timed out" in (res.message or res.reason or "").lower()
    assert exited.wait(2), "the tool thread kept running after the reported timeout"
    assert seen == {"ctx": (True, True), "cancelled": True}


def test_the_flag_is_set_after_a_normal_finish_too():
    import asyncio
    box = {}

    def quick():
        box["cancel"], _ = rt.current_call()
        return {"status": "success", "message": "ok"}

    asyncio.run(rt.runtime.run_tool("quick", quick, {}, timeout=5))
    assert box["cancel"].is_set()
    assert rt.current_call() == (None, None)
