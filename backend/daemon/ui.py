import sys
from collections import deque
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Static
from textual.reactive import reactive
from backend.core.events import bus
from backend.core.runtime import TaskEvent, TaskStatus
from backend.core.state import AssistantState, StateChangedEvent
from backend.daemon.ui_events import (
    AgentThinkingEvent,
    CommandTranscribed,
    ConfidenceEvent,
    Executed,
    IntentResolved,
    InternalAgentEvent,
    SelfHealingEvent,
    SpokenResponse,
    TokenStreamEvent,
    TriggerError,
    VerificationEvent,
    WakeHeard,
)


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


CSS_PATH = Path(__file__).resolve().parents[2] / "assets" / "sgcube.tcss"


class Panel(Container):
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


class Sidebar(Static):
    def compose(self) -> ComposeResult:
        icons = ["⬢", "", "", "", "", "", "", ""]
        yield Static("\n\n".join(icons), id="sidebar-icons")


class Header(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(" SG_CUBE TERMINAL v2.0", id="header-title")
        yield Static("USER: devuser@sgcube ", id="header-user")


class AnimatedCube(Static):
    CUBE_ART = """\
           +-----------+
          /           /|
         /           / |
        /           /  |
       +-----------+   |
       |           |   +
       |           |  /
       |     SG    | / CUBE
       |           |/
       +-----------+
"""
    def compose(self) -> ComposeResult:
        # Wrap it in a container for clipping
        yield Static(self.CUBE_ART, id="cube-art")

    def on_mount(self) -> None:
        # Animate from below
        cube = self.query_one("#cube-art")
        cube.styles.offset = (0, 30)
        cube.styles.animate("offset", (0, 0), duration=2.5, easing="out_cubic")


class RotatingReactor(Static):
    frames = [" ◴ ", " ◷ ", " ◶ ", " ◵ "]
    frame_idx = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.2, self.tick)

    def tick(self) -> None:
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)

    def render(self) -> str:
        return self.frames[self.frame_idx]


class CustomFooter(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(" SG CUBE v2.0\n BUILD 2024.05.23", id="footer-build")
        yield Static("SYSTEM LOAD\n" + "▃▅▇█▆▄▃", id="footer-load")
        yield RotatingReactor(id="footer-reactor")
        yield Static("TEMP\n58°C", id="footer-temp")
        yield Static("TIME\n--:--:--", id="footer-time")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.tick_time)

    def tick_time(self) -> None:
        time_str = datetime.now().strftime("%H:%M:%S")
        self.query_one("#footer-time", Static).update(f"TIME\n{time_str}")


class SGCubeApp(App):
    CSS_PATH = str(CSS_PATH)
    BINDINGS = [
        ("f12", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]
    TITLE = "SG_CUBE"

    def __init__(self) -> None:
        super().__init__()
        self._listener_stop = None

    def compose(self) -> ComposeResult:
        yield Sidebar(id="app-sidebar")
        
        with Vertical(id="app-main"):
            yield Header(id="app-header")
            
            with Horizontal(id="grid-container"):
                # Left Column
                with Vertical(classes="grid-col"):
                    neofetch_text = "OS: SG Cube OS 2.0\nKernel: 6.6.0-sgcube\nUptime: 2 hours\nShell: bash\nCPU: Intel i7\nMemory: 4GB/32GB"
                    yield Panel("devuser@sgcube:~$ neofetch", neofetch_text, id="neofetch")
                    
                    status_text = "ENVIRONMENT: PRODUCTION\nVERSION: v2.0.0\n\nDatabase    [ OK ]\nAPI Gateway [ OK ]\nStorage     [ OK ]"
                    yield Panel("SG CUBE STATUS", status_text, id="system-status")

                # Center Column
                with Vertical(classes="grid-col", id="center-col"):
                    yield AnimatedCube(id="cube-container")
                    yield Panel("TRANSCRIPT", "> _", id="transcript", body_id="transcript-body")
                    yield Panel("INTENT", "—", id="intent", body_id="intent-body")

                # Right Column
                with Vertical(classes="grid-col"):
                    monitor_text = "CPU USAGE: 42%\nMEMORY: 35%\nDISK: 57%\nNETWORK: OK"
                    yield Panel("SYSTEM MONITOR", monitor_text, id="monitor")
                    
                    services_text = "sgcube-api       [RUNNING]\nsgcube-worker    [RUNNING]\nsgcube-scheduler [RUNNING]\nsgcube-notify    [WARNING]"
                    yield Panel("SG CUBE SERVICES", services_text, id="services")
                    
                    yield Panel("EXECUTION / ACTIVITY", "—", id="execution", body_id="execution-body")

            yield CustomFooter(id="app-footer")

    def on_mount(self) -> None:
        for event_type in [
            WakeHeard, CommandTranscribed, IntentResolved,
            Executed, SpokenResponse, TriggerError, StateChangedEvent,
            VerificationEvent, ConfidenceEvent, SelfHealingEvent,
            InternalAgentEvent, AgentThinkingEvent, TokenStreamEvent,
            TaskEvent
        ]:
            bus.subscribe(event_type, lambda e: self.call_from_thread(self.handle_daemon_event, e))

    def handle_daemon_event(self, event) -> None:
        if isinstance(event, WakeHeard):
            self.query_one("#transcript-body", Static).update("> ...")
            self.query_one("#intent-body", Static).update("—")
            self.query_one("#execution-body", Static).update("—")

        elif isinstance(event, CommandTranscribed):
            text = event.text if event.text else "(no speech detected)"
            self.query_one("#transcript-body", Static).update(f"> {text}")

        elif isinstance(event, TokenStreamEvent):
            self.query_one("#transcript-body", Static).update(f"> {event.full_content} █")

        elif isinstance(event, IntentResolved):
            target = event.target or "—"
            self.query_one("#intent-body", Static).update(
                f"{event.action} / {target} ({event.source_layer})"
            )

        elif isinstance(event, TaskEvent):
            status_icon = "⚡" if event.status == TaskStatus.RUNNING else "✓" if event.status == TaskStatus.COMPLETED else "✗"
            tool_name = event.data.get("tool", "task")
            msg = f"{status_icon} {event.status.upper()} ({tool_name})\n"
            self.query_one("#execution-body", Static).update(msg)

        elif isinstance(event, Executed):
            mark = "✓" if event.status == "success" else "✗"
            msg = f"{mark} {event.status.upper()} ({event.command})\n"
            self.query_one("#execution-body", Static).update(msg)


def main() -> None:
    SGCubeApp().run()


if __name__ == "__main__":
    main()
