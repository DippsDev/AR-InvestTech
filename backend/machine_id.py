"""Stable machine identifier for license activation tracking.

The ID is generated once per machine and stored in the app-data directory. It
survives app restarts and re-installs as long as the data directory is preserved.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from src import paths


_MACHINE_ID_FILE = paths.app_data_dir() / "machine-id"


def _generate_id() -> str:
    """Generate a new random machine ID."""
    return uuid.uuid4().hex


def get_machine_id() -> str:
    """Return the stable machine ID for this device, creating it if needed."""
    id_path: Path = _MACHINE_ID_FILE
    if id_path.exists():
        machine_id = id_path.read_text(encoding="utf-8").strip()
        if machine_id:
            return machine_id

    machine_id = _generate_id()
    id_path.write_text(machine_id, encoding="utf-8")
    return machine_id


def reset_machine_id() -> str:
    """Generate a new machine ID. Useful for testing or re-activation."""
    machine_id = _generate_id()
    _MACHINE_ID_FILE.write_text(machine_id, encoding="utf-8")
    return machine_id
