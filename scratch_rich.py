from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel

console = Console()

# Neofetch
neofetch = Table.grid(padding=(0, 2))
neofetch.add_row("[bold cyan]OS:[/]", "[white]SG Cube OS 2.0 x86_64[/]")
neofetch.add_row("[bold cyan]Host:[/]", "[white]SG-CUBE v2[/]")
neofetch.add_row("[bold cyan]Kernel:[/]", "[white]6.6.0-sgcube[/]")
neofetch.add_row("[bold cyan]Uptime:[/]", "[white]2 hours, 47 mins[/]")
neofetch.add_row("[bold cyan]Shell:[/]", "[white]bash 5.2.21[/]")
console.print(Panel(neofetch, title="devuser@sgcube:~$ neofetch", border_style="cyan"))

# Services
services = Table.grid(padding=(0, 4))
services.add_row("[white]sgcube-api[/]", "[bold green]● RUNNING[/]")
services.add_row("[white]sgcube-worker[/]", "[bold green]● RUNNING[/]")
services.add_row("[white]sgcube-scheduler[/]", "[bold green]● RUNNING[/]")
services.add_row("[white]sgcube-notify[/]", "[bold yellow]● WARNING[/]")
console.print(Panel(services, title="SG CUBE SERVICES", border_style="cyan"))

# Cube
cube = """[bold cyan]          .-----------.
        .'          .'|
      .'          .'  |
    .'__________.'    |
    |           |     |
    |           |[/] [bold white]CUBE[/][bold cyan]|
    |    [/][bold white]SG[/][bold cyan]     |    .'
    |           |  .'
    |           |.'
    '-----------'[/]"""
console.print(Panel(Text.from_markup(cube), title="CUBE", border_style="cyan"))
