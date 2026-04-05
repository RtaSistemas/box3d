"""
engine/spine_builder.py — 2-D spine strip builder
====================================================
Generates the flat spine strip that is later perspective-warped by the
compositor.  Operates in pure Pillow — no subprocess calls, no disk I/O.

Pipeline:
    1. Sample a colour band from the cover (left / right / center).
    2. Scale to spine dimensions and apply Gaussian blur.
    3. Optional dark overlay.
    4. Composite logos (top → game → bottom) with per-slot rotation.
    5. Return the finished RGBA strip.
"""

from __future__ import annotations

import logging

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
    game_logo:    Image.Image | None,
    top_logo:     Image.Image | None,
    bottom_logo:  Image.Image | None,
) -> Image.Image:
    """
    Build and return the flat 2-D spine strip as an RGBA image of size
    ``(geom.spine_w × geom.spine_h)``.

    All logo arguments are pre-loaded PIL Image objects (or None).
    No disk I/O occurs in this function.

    Args:
        cover:        Front cover already opened as a PIL Image.
        geom:         Profile geometry (spine dimensions + source config).
        layout:       Logo slot positions and opacity.
        blur_radius:  Gaussian blur radius for the background (>= 0).
        darken_alpha: Opacity of the dark overlay (0–255, 0 = disabled).
        game_logo:    Pre-loaded game marquee image, or None.
        top_logo:     Pre-loaded top spine logo image, or None.
        bottom_logo:  Pre-loaded bottom spine logo image, or None.
    """
    sw, sh = geom.spine_w, geom.spine_h
    cw, ch = cover.size

    # ------------------------------------------------------------------
    # Contract assertions — fail fast on invalid engine state
    # ------------------------------------------------------------------
    assert sw > 0 and sh > 0, \
        f"spine dimensions must be positive, got {sw}x{sh}"
    assert cw > 0 and ch > 0, \
        f"cover dimensions must be positive, got {cw}x{ch}"
    assert blur_radius >= 0, \
        f"blur_radius must be >= 0, got {blur_radius}"
    assert 0 <= darken_alpha <= 255, \
        f"darken_alpha must be in [0, 255], got {darken_alpha}"
    assert 0.0 <= layout.logo_alpha <= 1.0, \
        f"logo_alpha must be in [0.0, 1.0], got {layout.logo_alpha}"
    for slot_name, slot in (
        ("top",    layout.top),
        ("game",   layout.game),
        ("bottom", layout.bottom),
    ):
        assert slot.max_w > 0 and slot.max_h > 0, \
            f"Logo slot '{slot_name}' dimensions must be positive: " \
            f"max_w={slot.max_w}, max_h={slot.max_h}"
        assert 0 <= slot.center_y <= sh, \
            f"Logo slot '{slot_name}' center_y={slot.center_y} " \
            f"is outside spine bounds [0, {sh}]"

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
    # 3. Logos: top → game → bottom (per-slot rotation angle)
    # ------------------------------------------------------------------
    alpha = layout.logo_alpha

    canvas = _paste_logo(canvas, top_logo,    sw, sh,
                         layout.top.max_w,    layout.top.max_h,
                         layout.top.center_y, alpha, layout.top.rotate)
    canvas = _paste_logo(canvas, game_logo,   sw, sh,
                         layout.game.max_w,   layout.game.max_h,
                         layout.game.center_y, alpha, layout.game.rotate)
    canvas = _paste_logo(canvas, bottom_logo, sw, sh,
                         layout.bottom.max_w, layout.bottom.max_h,
                         layout.bottom.center_y, alpha, layout.bottom.rotate)
    return canvas


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _paste_logo(
    canvas:       Image.Image,
    logo_img:     Image.Image | None,
    sw:           int,
    sh:           int,
    max_w:        int,
    max_h:        int,
    center_y:     int,
    alpha:        float,
    rotate_angle: int,
) -> Image.Image:
    """
    Optionally rotate, resize and composite one pre-loaded logo onto
    the canvas.  Returns the canvas unchanged if *logo_img* is None.

    No disk I/O — the logo is already an in-memory PIL Image.
    """
    if logo_img is None:
        return canvas

    logo = logo_img.copy().convert("RGBA")

    if rotate_angle != 0:
        logo = logo.rotate(rotate_angle, expand=True)

    # Fit within (max_w × max_h), never upscale
    lw, lh = logo.size
    if lw == 0 or lh == 0 or max_w <= 0 or max_h <= 0:
        log.warning("Invalid logo dimensions — skipped")
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
