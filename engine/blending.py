"""
engine/blending.py — Image blending operations
================================================
All blending functions are pure, stateless, and operate on Pillow images
with NumPy arrays.  They have no knowledge of profiles or the pipeline.

Blend operations implemented:
    alpha_weighted_screen  — the primary template blend
    dst_in                 — silhouette clip
    apply_color_matrix     — diagonal RGB scale
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops


def alpha_weighted_screen(dst: Image.Image, src: Image.Image) -> Image.Image:
    """
    Screen blend weighted by the source alpha channel.

    For each pixel::

        screen  = 1 − (1 − dst_rgb) × (1 − src_rgb)
        result  = dst_rgb × (1 − src_alpha) + screen × src_alpha

    The alpha channel of *dst* is preserved unchanged.

    Why this instead of plain Screen
    ---------------------------------
    Plain Screen ignores the source alpha, so near-white pixels in the
    arcade / dvd templates (RGB ≈ 246, alpha ≈ 12) wash the cover to
    almost pure white.  Weighting by alpha limits the effect to ~4.7% in
    those regions while still applying full shading at opaque borders.
    """
    dst_arr = np.array(dst,              dtype=np.float32)
    src_arr = np.array(src.convert("RGBA"), dtype=np.float32)

    dst_rgb = dst_arr[:, :, :3] / 255.0
    src_rgb = src_arr[:, :, :3] / 255.0
    src_a   = src_arr[:, :, 3:4] / 255.0   # shape (H, W, 1) for broadcasting

    screen  = 1.0 - (1.0 - dst_rgb) * (1.0 - src_rgb)
    blended = dst_rgb * (1.0 - src_a) + screen * src_a

    result = dst_arr.copy()
    result[:, :, :3] = np.clip(blended * 255.0, 0, 255)
    # DarkRf 17-03
    result[:, :, 3] = np.maximum(dst_arr[:, :, 3], src_arr[:, :, 3])
    return Image.fromarray(result.astype(np.uint8), "RGBA")


def dst_in(dst: Image.Image, mask: Image.Image) -> Image.Image:
    """
    DstIn compositing: multiply *dst* alpha by *mask*.

    Result:
        ``alpha = dst.alpha × mask / 255``
        ``rgb   = dst.rgb`` (unchanged)

    *mask* must be a single-channel (mode ``"L"``) image the same size
    as *dst*.
    """
    dst_arr  = np.array(dst,  dtype=np.float32)
    mask_arr = np.array(mask, dtype=np.float32)
    dst_arr[:, :, 3] = np.clip(dst_arr[:, :, 3] * (mask_arr / 255.0), 0, 255)
    return Image.fromarray(dst_arr.astype(np.uint8), "RGBA")


def apply_color_matrix(img: Image.Image, matrix_str: str) -> Image.Image:
    """
    Apply a diagonal RGB multiplier matrix to *img*.

    *matrix_str* is the string ``"R 0 0  0 G 0  0 0 B"`` produced by
    :func:`engine.compositor.parse_rgb_str`.  Only the diagonal elements
    (positions 0, 4, 8) are read.
    """
    parts   = matrix_str.split()
    r, g, b = float(parts[0]), float(parts[4]), float(parts[8])

    arr = np.array(img.convert("RGBA"), dtype=np.float32)
    arr[:, :, 0] = np.clip(arr[:, :, 0] * r, 0, 255)
    arr[:, :, 1] = np.clip(arr[:, :, 1] * g, 0, 255)
    arr[:, :, 2] = np.clip(arr[:, :, 2] * b, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def build_silhouette_mask(
    *alpha_sources: Image.Image,
) -> Image.Image:
    """
    Compute the union of the alpha channels of all *alpha_sources*.

    Returns a single-channel (``"L"``) image.  A pixel is included in
    the silhouette if any source has ``alpha > 0`` there.

    Used to build the DstIn mask from the spine warp, cover warp, and
    template alpha so that the box face is visible even where
    ``template.alpha = 0`` (MVS profile).
    """
    arrays = [
        np.array(src.convert("RGBA"), dtype=np.float32)[:, :, 3]
        for src in alpha_sources
    ]
    union = arrays[0]
    for a in arrays[1:]:
        union = np.maximum(union, a)
    return Image.fromarray(np.clip(union, 0, 255).astype(np.uint8), "L")
