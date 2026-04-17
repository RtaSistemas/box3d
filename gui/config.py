"""
gui/config.py — Box3D GUI settings persistence
"""
from __future__ import annotations

import json
from pathlib import Path

from cli.bootstrap import _DATA

_CONFIG_PATH: Path = _DATA / "gui_config.json"


def load_config() -> dict:
    """Return saved GUI settings, or {} on missing/corrupt file."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    """Write GUI settings to disk; silently ignores all errors."""
    try:
        _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
