"""
engine/compositor.py — Per-cover compositor
============================================
``render_cover`` is the single entry point called by the pipeline
for each cover image.  It coordinates spine generation, warping,
blending, and file I/O.

All image maths lives in ``engine.blending`` and ``engine.perspective``;
all domain types come from ``core.models``.
"""

from __future__ import annotations

import hashlib
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

VALID_EXT: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")


def render_cover(
    cover_path:   Path,
    covers_dir:   Path,
    profile:      Profile,
    options:      RenderOptions,
    output_dir:   Path,
    temp_dir:     Path,
    logo_paths:   dict[str, Path | None],
    marquees_dir: Path,
) -> CoverResult:
    """
    Render one cover image and write the result to *output_dir*.

    Returns a :class:`~core.models.CoverResult` describing the outcome.
    Thread-safe: no shared mutable state is read or written.
    """
    stem = cover_path.stem
    t0   = time.perf_counter()

    rel         = cover_path.relative_to(covers_dir)
    output_path = output_dir / rel.with_suffix(f".{options.output_format}")

    # Unique temp filename to prevent collisions between concurrent workers
    rel_hash  = hashlib.md5(str(rel).encode()).hexdigest()[:8]
    spine_tmp = temp_dir / f"_spine_{rel_hash}_{stem}.png"

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

        # Resolve game marquee (matched by stem, any supported extension)
        game_logo = _find_asset(marquees_dir, stem)
        if game_logo:
            log.debug("%s: marquee → %s", rel, game_logo.name)

        # Build the flat 2-D spine strip
        cover_img = Image.open(cover_path).convert("RGBA")
        log.debug("%s: cover %s", rel, cover_img.size)

        spine_strip = build_spine(
            cover        = cover_img,
            geom         = geom,
            layout       = layout,
            blur_radius  = options.blur_radius,
            darken_alpha = options.darken_alpha,
            game_logo    = game_logo,
            top_logo     = logo_paths.get("top"),
            bottom_logo  = logo_paths.get("bottom"),
        )
        spine_strip.save(str(spine_tmp), "PNG")

        # Composite the final 3-D box
        result = _composite(
            template_path = profile.template_path,
            cover_path    = cover_path,
            spine_path    = spine_tmp,
            geom          = geom,
            rgb_matrix    = options.rgb_matrix,
        )

        # Save
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

    finally:
        spine_tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Composite pipeline
# ---------------------------------------------------------------------------

def _composite(
    template_path: Path,
    cover_path:    Path,
    spine_path:    Path,
    geom,
    rgb_matrix:    str | None,
) -> Image.Image:
    """Five-step compositing pipeline (spine → cover → screen → dstin → save)."""
    template = Image.open(template_path).convert("RGBA")
    tw, th   = template.size

    colored_template = (
        apply_color_matrix(template, rgb_matrix)
        if rgb_matrix else template
    )

    # Step 1 — Spine warp
    spine_src    = resize_for_fit(Image.open(spine_path).convert("RGBA"),
                                  geom.spine_w, geom.spine_h, "stretch")
    spine_warped = warp(spine_src, tw, th, geom.spine_quad.as_list())
    canvas       = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas       = Image.alpha_composite(canvas, spine_warped)

    # Step 2 — Cover warp
    cover_src    = resize_for_fit(Image.open(cover_path).convert("RGBA"),
                                  geom.cover_w, geom.cover_h, geom.cover_fit)
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
    if options.rotate_logos is not None:
        layout = dataclasses.replace(layout, rotate_logos=options.rotate_logos)
    return layout


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------

def _find_asset(directory: Path, stem: str) -> Path | None:
    """Find the first file with *stem* in any supported extension."""
    if not directory.is_dir():
        return None
    stem_l = stem.lower()
    exts   = {e.lower() for e in VALID_EXT}
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.stem.lower() == stem_l and f.suffix.lower() in exts:
            return f
    return None


def parse_rgb_str(rgb_str: str) -> str | None:
    """
    Convert ``"R,G,B"`` to the diagonal matrix string used by
    :func:`~engine.blending.apply_color_matrix`.

    Returns None on error (negative values, wrong count, etc.).
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
