from pathlib import Path
from typing import Callable

import pystray
from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
TRAY_TITLE = "SG_CUBE — say 'sg cube' to wake"


def _generate_default_icon(size: int = 64) -> Image.Image:
    """Pillow-generated fallback when assets/tray.png is missing."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 6
    draw.ellipse((pad, pad, size - pad, size - pad), fill=(30, 144, 255, 255))
    return img


def _load_icon() -> Image.Image:
    path = ASSETS_DIR / "tray.png"
    if path.exists():
        try:
            return Image.open(path)
        except Exception:
            pass
    return _generate_default_icon()


class TrayController:
    """Manages the SG_CUBE system tray icon. Must run on the main thread on Windows."""

    def __init__(self, on_quit: Callable[[], None]):
        self._on_quit = on_quit
        self._image = _load_icon()
        self._icon: pystray.Icon | None = None

    def _quit_clicked(self, icon: pystray.Icon, _item) -> None:
        try:
            self._on_quit()
        finally:
            icon.stop()

    def run(self) -> None:
        """Blocks the calling thread until the user clicks Quit."""
        menu = pystray.Menu(
            pystray.MenuItem("SG_CUBE", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit_clicked),
        )
        self._icon = pystray.Icon("sg_cube", self._image, TRAY_TITLE, menu=menu)
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
