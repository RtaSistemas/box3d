"""
engine/compositor.py — Per-cover compositor
============================================
``compose_cover`` is the single public entry point for compositing one
cover image into a finished 3-D box.

Zero I/O: all inputs are pre-loaded PIL Image objects.  No reads, no
writes, no disk access of any kind occur in this module.  All I/O is
concentrated in ``core/pipeline.py``.
"""

from __future__ import annotations

import logging

from PIL import Image

from core.models import Profile, RenderOptions
from engine.blending   import (
    alpha_weighted_screen, apply_color_matrix,
    build_silhouette_mask, dst_in,
)
from engine.perspective import resize_for_fit, warp
from engine.spine_builder import build_spine

log = logging.getLogger("box3d.compositor")


def compose_cover(
    cover_img:    Image.Image,
    profile:      Profile,
    options:      RenderOptions,
    game_logo:    Image.Image | None = None,
    top_logo:     Image.Image | None = None,
    bottom_logo:  Image.Image | None = None,
    template_img: Image.Image | None = None,
) -> Image.Image:
    """
    Compose a complete 3-D box from pre-loaded images.

    Pure function: no disk I/O, no side effects.
    Returns the final composited RGBA image.
    """
    # Contract assertions — validate inputs at the public boundary
    assert cover_img is not None, "cover_img must not be None"
    assert cover_img.mode == "RGBA", \
        f"cover_img must be RGBA mode, got {cover_img.mode!r}"
    assert cover_img.width > 0 and cover_img.height > 0, \
        f"cover_img dimensions must be positive, got {cover_img.size}"
    if template_img is not None:
        assert template_img.mode == "RGBA", \
            f"template_img must be RGBA mode, got {template_img.mode!r}"

    geom   = _effective_geometry(profile, options)
    layout = _effective_layout(profile, options)

    spine_strip = build_spine(
        cover        = cover_img,
        geom         = geom,
        layout       = layout,
        blur_radius  = options.blur_radius,
        darken_alpha = options.darken_alpha,
        game_logo    = game_logo,
        top_logo     = top_logo,
        bottom_logo  = bottom_logo,
    )

    return _composite(
        cover_img    = cover_img,
        spine_img    = spine_strip,
        geom         = geom,
        rgb_matrix   = options.rgb_matrix,
        template_img = template_img,
    )


# ---------------------------------------------------------------------------
# Composite pipeline
# ---------------------------------------------------------------------------

def _composite(
    cover_img:    Image.Image,
    spine_img:    Image.Image,
    geom,
    rgb_matrix:   str | None,
    template_img: Image.Image,
) -> Image.Image:
    """Five-step compositing pipeline (spine → cover → screen → dstin → return)."""
    assert template_img is not None, (
        "template_img is required — engine/ must not perform disk I/O. "
        "Pre-load the template in the pipeline layer."
    )
    template = template_img
    tw, th   = template.size

    colored_template = (
        apply_color_matrix(template, rgb_matrix)
        if rgb_matrix else template
    )

    # Step 1 — Spine warp
    spine_src    = resize_for_fit(spine_img, geom.spine_w, geom.spine_h, "stretch")
    spine_warped = warp(spine_src, tw, th, geom.spine_quad.as_list())
    canvas       = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas       = Image.alpha_composite(canvas, spine_warped)

    # Step 2 — Cover warp
    cover_src    = resize_for_fit(cover_img, geom.cover_w, geom.cover_h, geom.cover_fit)
    cover_warped = warp(cover_src, tw, th, geom.cover_quad.as_list())
    canvas       = Image.alpha_composite(canvas, cover_warped)

    # Step 3 — Alpha-weighted Screen blend of the template
    canvas = alpha_weighted_screen(canvas, colored_template)

    # Step 4 — DstIn: clip to the union silhouette
    mask   = build_silhouette_mask(spine_warped, cover_warped, template)
    canvas = dst_in(canvas, mask)

    return canvas


# ---------------------------------------------------------------------------
# Effective geometry / layout (CLI overrides applied)
# ---------------------------------------------------------------------------

def _effective_geometry(profile: Profile, options: RenderOptions):
    """Return a geometry object with any CLI overrides applied."""
    import dataclasses
    geom = profile.geometry
    overrides = {}
    if options.cover_fit    is not None: overrides["cover_fit"]    = options.cover_fit
    if options.spine_source is not None: overrides["spine_source"] = options.spine_source
    return dataclasses.replace(geom, **overrides) if overrides else geom


def _effective_layout(profile: Profile, options: RenderOptions):
    """Return a layout object with any CLI overrides applied."""
    import dataclasses
    layout = profile.layout
    if options.no_rotate:
        layout = dataclasses.replace(
            layout,
            game   = dataclasses.replace(layout.game,   rotate=0),
            top    = dataclasses.replace(layout.top,     rotate=0),
            bottom = dataclasses.replace(layout.bottom,  rotate=0),
        )
    return layout
