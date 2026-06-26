"""
AR-InvestTech system tray launcher.
Run this instead of python server.py — starts the API server silently
and keeps a tray icon in the system notification area.

Double-click the tray icon  → opens the dashboard
Right-click → Start with Windows / Exit
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
import winreg
from pathlib import Path

import pystray
import uvicorn
from PIL import Image, ImageDraw, ImageFont

# Ensure imports resolve from this file's directory regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)  # bridge/config expect cwd == project root

from server import app as fastapi_app  # noqa: E402  (after path fix)

# ── Constants ──────────────────────────────────────────────────────────────────

DASHBOARD_URL = "https://ar-invest-tech.vercel.app"
APP_NAME      = "AR-InvestTech"
HOST, PORT    = "127.0.0.1", 8000

_REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"

# pythonw.exe runs without a console window — use it for auto-start
_PYTHONW = str(Path(sys.executable).with_name("pythonw.exe"))
_SCRIPT  = str(Path(__file__).resolve())


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _make_icon() -> Image.Image:
    """Draw a 64×64 tray icon: dark circle, green ring, white 'AR' text."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse([0, 0, size - 1, size - 1], fill=(15, 23, 42))          # slate-900
    draw.ellipse([3, 3, size - 4, size - 4], outline=(34, 197, 94), width=3)  # green ring

    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    text = "AR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 1), text, fill="white", font=font)

    return img


# ── Windows auto-start helpers ────────────────────────────────────────────────

def _autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def _set_autostart(enable: bool) -> None:
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _REG_RUN, 0, winreg.KEY_SET_VALUE
    )
    if enable:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                          f'"{_PYTHONW}" "{_SCRIPT}"')
    else:
        try:
            winreg.DeleteValue(key, APP_NAME)
        except OSError:
            pass
    winreg.CloseKey(key)


# ── Tray application ──────────────────────────────────────────────────────────

class TrayApp:
    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None

    # ── Server ────────────────────────────────────────────────────────────────

    def _run_server(self) -> None:
        cfg = uvicorn.Config(
            fastapi_app,
            host=HOST,
            port=PORT,
            log_level="error",
            reload=False,
        )
        self._server = uvicorn.Server(cfg)
        self._server.run()

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _open_dashboard(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(DASHBOARD_URL)

    def _toggle_autostart(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        enable = not _autostart_enabled()
        _set_autostart(enable)
        icon.notify(
            f"AR-InvestTech will {'start automatically with Windows' if enable else 'no longer start automatically'}.",
            APP_NAME,
        )

    def _quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._server:
            self._server.should_exit = True
        icon.stop()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        threading.Thread(target=self._run_server, daemon=True).start()

        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", self._open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_autostart,
                checked=lambda _: _autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._quit),
        )

        icon = pystray.Icon(
            APP_NAME,
            _make_icon(),
            f"{APP_NAME} · running on :{PORT}",
            menu,
        )
        icon.run()


if __name__ == "__main__":
    TrayApp().run()
