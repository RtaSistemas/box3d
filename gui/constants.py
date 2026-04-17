"""gui/constants.py — Shared visual constants for the Box3D desktop GUI."""
from __future__ import annotations

import platform

_VERSION   = "2.1.0"

# ── Colour palette (mirrors web Control Center) ───────────────────────────────
_BG      = "#0b0e14"
_PANEL   = "#12161e"
_PANEL2  = "#181d28"
_BORDER  = "#1e2535"
_ACCENT  = "#00eaff"
_ACCENT2 = "#ff2bd6"
_WARN    = "#ffb347"
_OK      = "#39ff7a"
_ERROR   = "#ff4757"
_TEXT    = "#c8d0e0"
_DIM     = "#5a6480"

_FONT_MONO = "Courier New" if platform.system() == "Windows" else "monospace"

# ── Designer canvas object colours ────────────────────────────────────────────
# Tkinter Canvas has no native alpha, so we use dark solid fills.
_DSN_COLORS: dict[str, dict[str, str]] = {
    "spine":   {"fill": "#2a2000", "stroke": "#ffd32a"},
    "cover":   {"fill": "#0a2010", "stroke": "#2ed573"},
    "logo":    {"fill": "#2a0a0a", "stroke": "#ff4757"},
    "marquee": {"fill": "#002025", "stroke": "#00eaff"},
}

_DSN_SWATCH: dict[str, str] = {
    "spine": "#ffd32a",
    "cover": "#2ed573",
    "logo":  "#ff4757",
    "marquee": "#00eaff",
}

_HANDLE_SIZE = 8   # px (canvas space)
_MIN_DIM     = 10  # minimum object dimension in template px
