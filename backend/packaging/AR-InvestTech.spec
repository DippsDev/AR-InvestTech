# -*- mode: python ; coding: utf-8 -*-
"""
Build with (from the backend/ folder, venv active):
    pyinstaller packaging/AR-InvestTech.spec
Output: backend/dist/AR-InvestTech/AR-InvestTech.exe (onedir — see packaging plan for why
onedir over onefile: MT5's native extension + numpy/pandas favor a stable
on-disk layout over onefile's re-extract-to-temp-on-every-launch behavior).
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = this file's directory (packaging/)

# MetaTrader5 has no dedicated community hook (verified — only a single native
# .pyd extension module), so pull its files in explicitly rather than relying
# on PyInstaller's default analysis to find everything.
mt5_datas, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")
# tzdata already has a community hook, but silver_bullet/live_adapter.py builds
# a ZoneInfo("America/New_York") at *import time* — bundle explicitly too as
# insurance, since a missing tz database breaks bot startup outright.
tzdata_datas = collect_data_files("tzdata")

a = Analysis(
    [str(ROOT / "tray.py")],
    pathex=[str(ROOT)],
    binaries=mt5_binaries,
    datas=[
        (str(ROOT / ".env.example"), "."),
    ] + mt5_datas + tzdata_datas,
    hiddenimports=mt5_hidden,
    # Confirmed unused anywhere in the codebase (pywebview) / unreachable from
    # tray.py's live import graph (matplotlib, only used by backtest tooling).
    excludes=["pywebview", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AR-InvestTech",
    icon=str(ROOT / "packaging" / "ar_icon.ico"),
    console=False,  # tray app — no console window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="AR-InvestTech",
)
