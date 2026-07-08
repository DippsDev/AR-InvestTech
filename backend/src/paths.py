"""Filesystem paths that work both running from source and as a PyInstaller build.

When frozen, writable data (`.env`, `.license`, logs) lives in the per-user
`%LOCALAPPDATA%\\AR-InvestTech\\` directory rather than next to the executable,
since the executable is normally installed under Program Files, which a
standard user cannot write to at runtime.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_data_dir() -> Path:
    """Writable directory for `.env`, `.license`, and logs."""
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        d = Path(base) / "AR-InvestTech"
    else:
        d = Path(__file__).resolve().parent.parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle_dir() -> Path:
    """Read-only directory containing files PyInstaller packaged alongside the app."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def ensure_env_file() -> Path:
    """Return the path to the live `.env`, seeding it from `.env.example` on first run."""
    env_path = app_data_dir() / ".env"
    if not env_path.exists():
        example = bundle_dir() / ".env.example"
        if example.exists():
            shutil.copy(example, env_path)
        else:
            env_path.touch()
    return env_path


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Rewrite only the given keys in `env_path`.

    Preserves comments, blank lines, and existing ordering; appends any key
    that isn't already present. Shared by `bridge.py`'s settings save and by
    first-run config seeding (e.g. the generated API token) so there is one
    rewrite mechanism, not two that could drift apart.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
