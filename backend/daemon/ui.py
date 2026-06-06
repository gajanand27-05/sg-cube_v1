import sys
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Static
from textual.reactive import reactive
from textual.geometry import Offset

from rich.table import Table
from rich.text import Text
from rich.console import Group

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


def build_neofetch():
    t = Table.grid(padding=(0, 2))
    t.add_row("[cyan]OS:[/]", "[white]SG Cube OS 2.0 x86_64[/]")
    t.add_row("[cyan]Host:[/]", "[white]SG-CUBE v2[/]")
    t.add_row("[cyan]Kernel:[/]", "[white]6.6.0-sgcube[/]")
    t.add_row("[cyan]Uptime:[/]", "[white]2 hours, 47 mins[/]")
    t.add_row("[cyan]Packages:[/]", "[white]1542 (sg-pkg)[/]")
    t.add_row("[cyan]Shell:[/]", "[white]bash 5.2.21[/]")
    t.add_row("[cyan]Resolution:[/]", "[white]1920x1080[/]")
    t.add_row("[cyan]DE:[/]", "[white]SGCube Terminal[/]")
    t.add_row("[cyan]CPU:[/]", "[white]Intel i7-12700K (20) @ 5.00GHz[/]")
    t.add_row("[cyan]GPU:[/]", "[white]NVIDIA GeForce RTX 3080[/]")
    t.add_row("[cyan]Memory:[/]", "[white]4.23GiB / 31.32GiB[/]")
    return t

def build_status():
    t1 = Table.grid(padding=(0, 2))
    t1.add_row("[cyan]ENVIRONMENT[/]", "[white]PRODUCTION[/]")
    t1.add_row("[cyan]VERSION[/]", "[white]v2.0.0[/]")
    t1.add_row("[cyan]UPTIME[/]", "[white]2h 47m 13s[/]")
    t1.add_row("[cyan]LAST DEPLOY[/]", "[white]2024-05-23 14:35:10[/]")
    
    t2 = Table.grid(padding=(0, 4))
    t2.add_row("[cyan]Database[/]", "[bold green][ OK ][/]")
    t2.add_row("[cyan]API Gateway[/]", "[bold green][ OK ][/]")
    t2.add_row("[cyan]Auth Service[/]", "[bold green][ OK ][/]")
    t2.add_row("[cyan]Storage[/]", "[bold green][ OK ][/]")
    t2.add_row("[cyan]Cache[/]", "[bold green][ OK ][/]")
    
    return Horizontal(Static(t1), Static(t2))

def build_monitor():
    t = Table.grid(padding=(0, 2))
    t.add_row("[cyan]CPU USAGE[/]", "")
    t.add_row("[bold cyan]42%[/]", "[cyan]▃▅▇█▆▄▃  ▃▅▇█▆▄▃[/]")
    t.add_row("", "")
    t.add_row("[cyan]MEMORY[/]", "[cyan]11.02 GiB / 31.32 GiB[/]")
    t.add_row("[bold cyan]35%[/]", "[cyan]█████░░░░░░░░░░[/]")
    t.add_row("", "")
    t.add_row("[cyan]DISK[/]", "[cyan]178.6 GiB / 314.6 GiB[/]")
    t.add_row("[bold cyan]57%[/]", "[cyan]████████░░░░░░░[/]")
    t.add_row("", "")
    t.add_row("[cyan]NETWORK[/]", "[cyan]↓ 3.42 MB/s  ↑ 1.21 MB/s[/]")
    return t

def build_services():
    t = Table.grid(padding=(0, 4))
    t.add_row("[cyan]SERVICE[/]", "[cyan]STATUS[/]")
    t.add_row("[white]sgcube-api[/]", "[bold green]● RUNNING[/]")
    t.add_row("[white]sgcube-worker[/]", "[bold green]● RUNNING[/]")
    t.add_row("[white]sgcube-scheduler[/]", "[bold green]● RUNNING[/]")
    t.add_row("[white]sgcube-notify[/]", "[bold yellow]● WARNING[/]")
    t.add_row("[white]sgcube-analytics[/]", "[bold green]● RUNNING[/]")
    return t


class Panel(Container):
    def __init__(
        self,
        title: str,
        renderable,
        *,
        id: str | None = None,
        body_id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._title = title
        self._renderable = renderable
        self._body_id = body_id

    def compose(self) -> ComposeResult:
        # If it's a Textual widget like Horizontal, yield it directly
        if isinstance(self._renderable, (Static, Container, Horizontal, Vertical)):
            yield self._renderable
        else:
            yield Static(self._renderable, id=self._body_id, classes="panel-body")

    def on_mount(self) -> None:
        self.border_title = f"[bold cyan]{self._title}[/]"


class Sidebar(Static):
    def compose(self) -> ComposeResult:
        icons = ["[cyan]◈[/]", "[cyan]💻[/]", "[cyan]📁[/]", "[cyan]🌐[/]", "[cyan]🗄️[/]", "[cyan]⚙[/]", "[cyan]⏻[/]"]
        yield Static("\n\n".join(icons), id="sidebar-icons")


class Header(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup("[bold cyan] SG_CUBE TERMINAL v2.0[/]"), id="header-title")
        yield Static(Text.from_markup("[cyan]USER: devuser@sgcube [/]"), id="header-user")


class AnimatedCube(Static):
    CUBE_ART = """\
[bold cyan]          .-----------.
        .'          .'|
      .'          .'  |
    .'__________.'    |
    |           |     |
    |           |[/] [bold white]CUBE[/][bold cyan]|
    |    [/][bold white]SG[/][bold cyan]     |    .'
    |           |  .'
    |           |.'
    '-----------'[/]"""

    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup(self.CUBE_ART), id="cube-art")

    def on_mount(self) -> None:
        self.cube = self.query_one("#cube-art")
        self.y_offset = 30
        self.cube.styles.offset = Offset(0, self.y_offset)
        self.anim_timer = self.set_interval(0.05, self.tick_anim)

    def tick_anim(self) -> None:
        self.y_offset -= 2
        if self.y_offset <= 0:
            self.cube.styles.offset = Offset(0, 0)
            self.anim_timer.stop()
        else:
            self.cube.styles.offset = Offset(0, self.y_offset)


class RotatingReactor(Static):
    frames = ["[bold cyan] ◴ [/]", "[bold cyan] ◷ [/]", "[bold cyan] ◶ [/]", "[bold cyan] ◵ [/]"]
    frame_idx = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.2, self.tick)

    def tick(self) -> None:
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)

    def render(self) -> str:
        return Text.from_markup(self.frames[self.frame_idx])


class CustomFooter(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup("[bold cyan]SG CUBE v2.0\nBUILD 2024.05.23[/]"), id="footer-build")
        yield Static(Text.from_markup("[cyan]SYSTEM LOAD\n[white]▃▅▇█▆▄▃[/]"), id="footer-load")
        yield RotatingReactor(id="footer-reactor")
        yield Static(Text.from_markup("[cyan]TEMP\n[white]58°C[/]"), id="footer-temp")
        yield Static(Text.from_markup("[cyan]TIME\n[white]--:--:--[/]"), id="footer-time")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.tick_time)

    def tick_time(self) -> None:
        time_str = datetime.now().strftime("%H:%M:%S")
        self.query_one("#footer-time", Static).update(Text.from_markup(f"[cyan]TIME\n[white]{time_str}[/]"))


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
                    yield Panel("devuser@sgcube:~$ neofetch", build_neofetch(), id="neofetch")
                    yield Panel("SG CUBE STATUS", build_status(), id="system-status")

                # Center Column
                with Vertical(classes="grid-col", id="center-col"):
                    yield AnimatedCube(id="cube-container")
                    yield Panel("TRANSCRIPT", Text.from_markup("[white]> _[/]"), id="transcript", body_id="transcript-body")
                    yield Panel("INTENT", Text.from_markup("[cyan]—[/]"), id="intent", body_id="intent-body")

                # Right Column
                with Vertical(classes="grid-col"):
                    yield Panel("SYSTEM MONITOR", build_monitor(), id="monitor")
                    yield Panel("SG CUBE SERVICES", build_services(), id="services")
                    yield Panel("EXECUTION / ACTIVITY", Text.from_markup("[white]—[/]"), id="execution", body_id="execution-body")

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
            self.query_one("#transcript-body", Static).update(Text.from_markup("[white]> ...[/]"))
            self.query_one("#intent-body", Static).update(Text.from_markup("[cyan]—[/]"))
            self.query_one("#execution-body", Static).update(Text.from_markup("[white]—[/]"))

        elif isinstance(event, CommandTranscribed):
            text = event.text if event.text else "(no speech detected)"
            self.query_one("#transcript-body", Static).update(Text.from_markup(f"[white]> {text}[/]"))

        elif isinstance(event, TokenStreamEvent):
            self.query_one("#transcript-body", Static).update(Text.from_markup(f"[white]> {event.full_content} █[/]"))

        elif isinstance(event, IntentResolved):
            target = event.target or "—"
            self.query_one("#intent-body", Static).update(Text.from_markup(f"[cyan]{event.action} / {target} ({event.source_layer})[/]"))

        elif isinstance(event, TaskEvent):
            status_icon = "⚡" if event.status == TaskStatus.RUNNING else "✓" if event.status == TaskStatus.COMPLETED else "✗"
            tool_name = event.data.get("tool", "task")
            msg = f"[bold white]{status_icon} {event.status.upper()} ({tool_name})[/]\n"
            self.query_one("#execution-body", Static).update(Text.from_markup(msg))

        elif isinstance(event, Executed):
            mark = "✓" if event.status == "success" else "✗"
            msg = f"[bold white]{mark} {event.status.upper()} ({event.command})[/]\n"
            self.query_one("#execution-body", Static).update(Text.from_markup(msg))


def main() -> None:
    SGCubeApp().run()


if __name__ == "__main__":
    main()
