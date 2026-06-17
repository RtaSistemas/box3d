"""
gui/config.py — Box3D GUI settings persistence
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cli.bootstrap import _DATA

log = logging.getLogger(__name__)

_CONFIG_PATH: Path = _DATA / "gui_config.json"


def load_config() -> dict:
    """Return saved GUI settings, or {} on missing/corrupt file."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    """Write GUI settings to disk; logs but does not raise on failure."""
    try:
        _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Config save failed (%s): %s", _CONFIG_PATH, exc)
