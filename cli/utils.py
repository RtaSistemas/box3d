"""
cli/utils.py — Shared CLI utility functions
============================================
Small, pure helpers used by CLI command handlers.
No side effects, no I/O at import time.
"""

from __future__ import annotations

import logging

log = logging.getLogger("box3d.cli")


def parse_rgb_str(rgb_str: str) -> str | None:
    """Convert ``"R,G,B"`` to the diagonal matrix string used by
    :func:`~engine.blending.apply_color_matrix`.
    """
    normalised = rgb_str.replace(";", ",")
    try:
        parts = [float(x.strip()) for x in normalised.split(",")]
        if len(parts) != 3:
            raise ValueError(f"expected 3 values, got {len(parts)}")
        r, g, b = parts
        for label, val in (("R", r), ("G", g), ("B", b)):
            if val < 0:
                raise ValueError(f"channel {label} must be >= 0")
        return f"{r} 0 0  0 {g} 0  0 0 {b}"
    except Exception as exc:
        log.warning("parse_rgb_str: %r — %s — ignored", rgb_str, exc)
        return None
