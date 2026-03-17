"""
engine/spine_builder.py — 2-D spine strip builder
====================================================
Generates the flat spine strip that is later perspective-warped by the
compositor.  Operates in pure Pillow — no subprocess calls.

Pipeline:
    1. Sample a colour band from the cover (left / right / center).
    2. Scale to spine dimensions and apply Gaussian blur.
    3. Optional dark overlay.
    4. Composite logos (top → game → bottom) with optional 90° CW rotation.
    5. Return the finished RGBA strip.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from core.models import ProfileGeometry, SpineLayout

log = logging.getLogger("box3d.spine")


def build_spine(
    cover:        Image.Image,
    geom:         ProfileGeometry,
    layout:       SpineLayout,
    blur_radius:  int,
    darken_alpha: int,
    game_logo:    Path | None,
    top_logo:     Path | None,
    bottom_logo:  Path | None,
) -> Image.Image:
    """
    Build and return the flat 2-D spine strip as an RGBA image of size
    ``(geom.spine_w × geom.spine_h)``.

    Args:
        cover:        Front cover already opened as a PIL Image.
        geom:         Profile geometry (spine dimensions + source config).
        layout:       Logo slot positions and opacity.
        blur_radius:  Gaussian blur radius for the background (>= 0).
        darken_alpha: Opacity of the dark overlay (0–255, 0 = disabled).
        game_logo:    Path to the game marquee, or None.
        top_logo:     Path to the top spine logo, or None.
        bottom_logo:  Path to the bottom spine logo, or None.
    """
    sw, sh = geom.spine_w, geom.spine_h
    cw, ch = cover.size

    # ------------------------------------------------------------------
    # 1. Sample background strip from the cover
    # ------------------------------------------------------------------
    src_w  = max(10, int(cw * geom.spine_source_frac))
    source = geom.spine_source

    if source == "left":
        region = (0, 0, src_w, ch)
    elif source == "right":
        region = (cw - src_w, 0, cw, ch)
    else:  # "center"
        cx   = cw // 2
        half = src_w // 2
        x0   = max(0, cx - half)
        x1   = min(cw, cx + half)
        region = (x0, 0, x1 if x1 > x0 else cw, ch)

    strip   = cover.crop(region)
    scaled  = strip.resize((sw, sh), Image.LANCZOS)
    blurred = scaled.filter(ImageFilter.GaussianBlur(radius=max(0, blur_radius)))
    canvas  = blurred.convert("RGBA")

    # ------------------------------------------------------------------
    # 2. Dark overlay (optional)
    # ------------------------------------------------------------------
    if darken_alpha > 0:
        overlay = Image.new("RGBA", (sw, sh),
                            (0, 0, 0, max(0, min(255, darken_alpha))))
        canvas  = Image.alpha_composite(canvas, overlay)

    # ------------------------------------------------------------------
    # 3. Logos: top → game → bottom
    # ------------------------------------------------------------------
    rotate = layout.rotate_logos
    alpha  = layout.logo_alpha

    canvas = _paste_logo(canvas, top_logo,    sw, sh,
                         layout.top.max_w,    layout.top.max_h,
                         layout.top.center_y, alpha, rotate)
    canvas = _paste_logo(canvas, game_logo,   sw, sh,
                         layout.game.max_w,   layout.game.max_h,
                         layout.game.center_y, alpha, rotate)
    canvas = _paste_logo(canvas, bottom_logo, sw, sh,
                         layout.bottom.max_w, layout.bottom.max_h,
                         layout.bottom.center_y, alpha, rotate)
    return canvas


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _paste_logo(
    canvas:   Image.Image,
    path:     Path | None,
    sw:       int,
    sh:       int,
    max_w:    int,
    max_h:    int,
    center_y: int,
    alpha:    float,
    rotate:   bool,
) -> Image.Image:
    """
    Open, optionally rotate, resize and composite one logo onto the canvas.
    Returns the canvas unchanged on any error (logged as warning).
    """
    if path is None:
        return canvas

    try:
        logo = Image.open(path).convert("RGBA")
    except Exception as exc:
        log.warning("Cannot open logo '%s': %s", path, exc)
        return canvas

    if rotate:
        logo = logo.rotate(-90, expand=True)

    # Fit within (max_w × max_h), never upscale
    lw, lh = logo.size
    if lw == 0 or lh == 0 or max_w <= 0 or max_h <= 0:
        log.warning("Invalid logo dimensions for '%s' — skipped", path)
        return canvas

    scale = min(max_w / lw, max_h / lh, 1.0)
    nw    = max(1, int(lw * scale))
    nh    = max(1, int(lh * scale))
    if (nw, nh) != (lw, lh):
        logo = logo.resize((nw, nh), Image.LANCZOS)
    lw, lh = logo.size

    # Apply opacity
    arr = np.array(logo, dtype=np.float32)
    arr[:, :, 3] = np.clip(arr[:, :, 3] * alpha, 0, 255)
    logo = Image.fromarray(arr.astype(np.uint8), "RGBA")

    # Position
    x = (sw - lw) // 2
    y = max(2, min(center_y - lh // 2, sh - lh - 2))

    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    layer.paste(logo, (x, y))
    return Image.alpha_composite(canvas, layer)
