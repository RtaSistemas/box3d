"""
gui/fonts.py — Live-scalable font registry
==========================================
All GUI widgets create fonts via F() instead of ctk.CTkFont() directly.
Every font is registered here; set_scale() updates them all in-place,
so CustomTkinter propagates the new size to every widget immediately —
no restart required.

Usage::

    from gui.fonts import F, init_scale, set_scale, get_scale

    # Before building any UI (call once at startup):
    init_scale(config.get("font_scale", 1.0))

    # In widget construction:
    font=F(11)
    font=F(13, "bold")

    # To change scale live:
    set_scale(1.2)   # 120%
"""
from __future__ import annotations

import customtkinter as ctk

from gui.constants import _FONT_MONO

_SCALE_MIN  = 0.8
_SCALE_MAX  = 1.5
_SCALE_STEP = 0.1

_scale: float = 1.0

# (font_object, base_size, weight, family)
_registry: list[tuple[ctk.CTkFont, int, str, str]] = []


def init_scale(scale: float) -> None:
    """Set the initial scale factor before any fonts are created."""
    global _scale
    _scale = max(_SCALE_MIN, min(_SCALE_MAX, float(scale)))


def F(size: int, weight: str = "normal", family: str = _FONT_MONO) -> ctk.CTkFont:
    """Create and register a scalable CTkFont."""
    font = ctk.CTkFont(family=family, size=max(8, int(size * _scale)), weight=weight)
    _registry.append((font, size, weight, family))
    return font


def set_scale(scale: float) -> None:
    """Update every registered font to the new scale factor (live, no restart)."""
    global _scale
    _scale = max(_SCALE_MIN, min(_SCALE_MAX, float(scale)))
    for font, base, weight, family in _registry:
        font.configure(family=family, size=max(8, int(base * _scale)), weight=weight)


def get_scale() -> float:
    return _scale


def scale_pct() -> int:
    """Current scale as integer percentage (e.g. 100 for 1.0)."""
    return round(_scale * 100)


def step_up() -> float:
    """Increment scale by one step; return new scale."""
    return round(min(_SCALE_MAX, _scale + _SCALE_STEP), 1)


def step_down() -> float:
    """Decrement scale by one step; return new scale."""
    return round(max(_SCALE_MIN, _scale - _SCALE_STEP), 1)
