"""
engine/compositor.py — Per-cover compositor
============================================
``render_cover`` is the single entry point called by the pipeline
for each cover image.  It coordinates spine generation, warping,
blending, and file output.

All image inputs (cover, logos, template) are received as pre-loaded
PIL Image objects from the pipeline's Asset Loader layer.  No disk
*read* I/O occurs in this module.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PIL import Image

from core.models import CoverResult, Profile, RenderOptions
from engine.blending   import (
    alpha_weighted_screen, apply_color_matrix,
    build_silhouette_mask, dst_in,
)
from engine.perspective import resize_for_fit, warp
from engine.spine_builder import build_spine

log = logging.getLogger("box3d.compositor")


def render_cover(
    cover_path:   Path,
    cover_img:    Image.Image,
    covers_dir:   Path,
    profile:      Profile,
    options:      RenderOptions,
    output_dir:   Path,
    game_logo:    Image.Image | None = None,
    top_logo:     Image.Image | None = None,
    bottom_logo:  Image.Image | None = None,
    template_img: Image.Image | None = None,
) -> CoverResult:
    """
    Render one cover image and write the result to *output_dir*.

    All image inputs are pre-loaded in-memory PIL Image objects.
    Thread-safe: no shared mutable state is read or written.
    """
    stem = cover_path.stem
    t0   = time.perf_counter()

    rel         = cover_path.relative_to(covers_dir)
    output_path = output_dir / rel.with_suffix(f".{options.output_format}")

    if options.dry_run:
        log.info("[DRY-RUN] %s", rel)
        return CoverResult(stem=stem, status="dry", elapsed=0.0)

    if options.skip_existing and output_path.exists():
        log.info("[SKIP]    %s — already exists", rel)
        return CoverResult(stem=stem, status="skip", elapsed=0.0)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        geom   = _effective_geometry(profile, options)
        layout = _effective_layout(profile, options)

        if game_logo:
            log.debug("%s: marquee provided", rel)

        log.debug("%s: cover %s", rel, cover_img.size)

        # Build the flat 2-D spine strip (kept entirely in memory)
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

        # Composite the final 3-D box
        result = _composite(
            template_path = profile.template_path,
            cover_img     = cover_img,
            spine_img     = spine_strip,
            geom          = geom,
            rgb_matrix    = options.rgb_matrix,
            template_img  = template_img,
        )

        ext = output_path.suffix.lower()
        if ext == ".webp":
            result.save(str(output_path), "WEBP", quality=92, method=4)
        else:
            result.save(str(output_path), "PNG", optimize=False)

        elapsed = time.perf_counter() - t0
        log.info("✔  %-46s (%.2fs)", str(rel), elapsed)
        return CoverResult(stem=stem, status="ok", elapsed=elapsed)

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        msg = str(exc).strip()
        log.error("✘  %s: %s", rel, msg, exc_info=True)
        return CoverResult(stem=stem, status="error", elapsed=elapsed, error=msg)


# ---------------------------------------------------------------------------
# Composite pipeline
# ---------------------------------------------------------------------------

def _composite(
    template_path: Path,
    cover_img:     Image.Image,
    spine_img:     Image.Image,
    geom,
    rgb_matrix:    str | None,
    template_img:  Image.Image | None = None,
) -> Image.Image:
    """Five-step compositing pipeline (spine → cover → screen → dstin → save)."""
    
    if template_img is None:
        raise ValueError(
            "template_img is required — engine/ must not perform disk I/O. "
            "Pre-load the template in the pipeline layer."
        )
    template = template_img
        
    tw, th = template.size

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
