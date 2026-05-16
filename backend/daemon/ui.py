import sys
from collections import deque
from datetime import datetime
from pathlib import Path

from pyfiglet import Figlet
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Static

from backend.daemon.ui_events import (
    CommandTranscribed,
    Executed,
    IntentResolved,
    SpokenResponse,
    TriggerError,
    WakeHeard,
)

# Force UTF-8 stdout/stderr — Windows console defaults to cp1252 which can't
# encode block-drawing characters used by the wordmark and panels.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Pop-on-wake: minimize the hosting terminal window between interactions.
try:
    import ctypes
    import win32con
    import win32gui

    def _console_hwnd() -> int | None:
        try:
            return ctypes.windll.kernel32.GetConsoleWindow() or None
        except Exception:
            return None

    def _minimize_console(hwnd: int | None) -> None:
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass

    def _restore_console(hwnd: int | None) -> None:
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

    _HAS_WIN32 = True
except Exception:
    _HAS_WIN32 = False

    def _console_hwnd() -> int | None:
        return None

    def _minimize_console(_hwnd) -> None:
        pass

    def _restore_console(_hwnd) -> None:
        pass


CSS_PATH = Path(__file__).resolve().parents[2] / "assets" / "sgcube.tcss"


def _wordmark() -> str:
    # `ansi_shadow` gives a chunky 3D-shadow look (6 rows tall) — the
    # original Phase 9d default that you liked in the amber preview.
    return Figlet(font="ansi_shadow", width=120).renderText("SG_CUBE").rstrip()


def _bar(percent: float, width: int = 10) -> str:
    filled = int(round(percent / 100 * width))
    return "▰" * filled + "▱" * (width - filled)


class Panel(Container):
    """Bordered container with a titled header and a body identified by `body_id`."""

    def __init__(
        self,
        title: str,
        body: str = "",
        *,
        id: str | None = None,
        body_id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._title = title
        self._body = body
        self._body_id = body_id

    def compose(self) -> ComposeResult:
        yield Static(self._body, id=self._body_id, classes="panel-body")

    def on_mount(self) -> None:
        self.border_title = self._title


class SGCubeApp(App):
    CSS_PATH = str(CSS_PATH)
    BINDINGS = [
        ("f12", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]
    TITLE = "SG_CUBE"

    def __init__(self) -> None:
        super().__init__()
        self._layer_counts: dict[str, int] = {"cache": 0, "rule": 0, "llm": 0}
        self._recent: deque[tuple[str, str, str, int | None]] = deque(maxlen=5)
        self._last_source_layer: str = "—"
        self._last_execution_summary: str = "—"
        self._listener_stop = None  # set by main.py when wiring the listener thread
        self._console_hwnd = _console_hwnd()
        self._idle_minimize_timer = None

    def compose(self) -> ComposeResult:
        yield Container(Static(_wordmark(), id="wordmark"), id="wordmark-box")

        yield Container(
            Static("●  SYSTEM ONLINE", id="status-left"),
            Static("--:--:--", id="status-clock"),
            Static("STATUS · LISTENING", id="status-right"),
            id="status-bar",
        )

        engines_body = "●  vosk    ●  whisper    ●  ollama/phi3    ●  piper    · ALL READY"

        yield Horizontal(
            Vertical(
                Panel("ENGINES", engines_body, id="engines", body_id="engines-body"),
                Panel("ROUTING (session)", self._routing_body(), id="routing", body_id="routing-body"),
                Panel("RECENT", "— no commands yet —", id="recent", body_id="recent-body"),
                id="left-col",
            ),
            Vertical(
                Panel("TRANSCRIPT", "> _", id="transcript", body_id="transcript-body"),
                Panel("INTENT", "—", id="intent", body_id="intent-body"),
                Panel("EXECUTION", "—", id="execution", body_id="execution-body"),
                id="right-col",
            ),
            id="main-row",
        )

        yield Container(
            Static("LIVE MIC", id="mic-label"),
            Static("▏" * 80, id="mic-bars"),
            id="mic-strip",
        )

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_clock)
        self._tick_clock()
        # Pop-on-wake: 2s after startup, minimize the host terminal. Each
        # wake will restore it; 5s after the spoken response it minimizes
        # again.
        self.set_timer(2.0, self._minimize)

    def on_unmount(self) -> None:
        if self._listener_stop is not None:
            try:
                self._listener_stop()
            except Exception:
                pass

    def _tick_clock(self) -> None:
        self.query_one("#status-clock", Static).update(
            datetime.now().strftime("%H:%M:%S")
        )

    def _minimize(self) -> None:
        _minimize_console(self._console_hwnd)

    def _restore(self) -> None:
        _restore_console(self._console_hwnd)

    def _schedule_idle_minimize(self, delay: float = 5.0) -> None:
        if self._idle_minimize_timer is not None:
            try:
                self._idle_minimize_timer.stop()
            except Exception:
                pass
        self._idle_minimize_timer = self.set_timer(delay, self._minimize)

    def _routing_body(self) -> str:
        total = sum(self._layer_counts.values())
        parts = []
        for layer in ("cache", "rule", "llm"):
            count = self._layer_counts[layer]
            pct = (count * 100 // total) if total else 0
            parts.append(f"{layer} {_bar(pct, width=5)} {pct}%")
        return "  ·  ".join(parts)

    def _refresh_routing(self) -> None:
        self.query_one("#routing-body", Static).update(self._routing_body())

    def _refresh_recent(self) -> None:
        if not self._recent:
            self.query_one("#recent-body", Static).update("— no commands yet —")
            return
        lines = []
        for mark, command, layer, lat in self._recent:
            cmd = command if len(command) <= 22 else command[:21] + "…"
            lat_s = f"{lat}ms" if lat is not None else "—"
            lines.append(f"{mark}  {cmd:<22} {layer:<7} {lat_s:>6}")
        self.query_one("#recent-body", Static).update("\n".join(lines))

    # ── Daemon event handler (called from listener worker thread) ───────

    def handle_daemon_event(self, event) -> None:
        if isinstance(event, WakeHeard):
            self._restore()  # pop the terminal into view
            if self._idle_minimize_timer is not None:
                try:
                    self._idle_minimize_timer.stop()
                except Exception:
                    pass
                self._idle_minimize_timer = None
            self.query_one("#status-right", Static).update("STATUS · HEARD")
            self.query_one("#transcript-body", Static).update("> ...")
            self.query_one("#intent-body", Static).update("—")
            self.query_one("#execution-body", Static).update("—")

        elif isinstance(event, CommandTranscribed):
            text = event.text if event.text else "(no speech detected)"
            self.query_one("#transcript-body", Static).update(f"> {text}")

        elif isinstance(event, IntentResolved):
            self._last_source_layer = event.source_layer
            target = event.target or "—"
            self.query_one("#intent-body", Static).update(
                f"{event.action} / {target}  ({event.source_layer})"
            )
            self._layer_counts[event.source_layer] = self._layer_counts.get(event.source_layer, 0) + 1
            self._refresh_routing()

        elif isinstance(event, Executed):
            mark = "✓" if event.status == "success" else "✗"
            detail = event.message or event.reason or event.status
            self._last_execution_summary = f"{mark} {detail}  ·  {event.latency_ms}ms"
            self.query_one("#execution-body", Static).update(self._last_execution_summary)
            self._recent.appendleft(
                (mark, event.command, self._last_source_layer, event.latency_ms)
            )
            self._refresh_recent()

        elif isinstance(event, SpokenResponse):
            # collapse the execution summary into one line with the spoken text
            base = getattr(self, "_last_execution_summary", "—")
            self.query_one("#execution-body", Static).update(
                f"{base}  →  \"{event.text}\""
            )
            self.query_one("#status-right", Static).update("STATUS · LISTENING")
            self._schedule_idle_minimize()

        elif isinstance(event, TriggerError):
            self.query_one("#execution-body", Static).update(
                f"✗ {event.detail}"
            )
            self.query_one("#status-right", Static).update("STATUS · LISTENING")
            self._schedule_idle_minimize()


def main() -> None:
    SGCubeApp().run()


if __name__ == "__main__":
    main()
