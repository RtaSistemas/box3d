"""
engine/blending.py — Image blending operations
================================================
All blending functions are pure, stateless, and operate on Pillow images
with NumPy arrays.  They have no knowledge of profiles or the pipeline.

Blend operations implemented:
    alpha_weighted_screen   — Screen blend in linear light (primary template blend)
    linear_alpha_composite  — Porter-Duff 'over' in linear light
    dst_in                  — silhouette clip (alpha-only; no gamma correction needed)
    apply_color_matrix      — diagonal RGB scale (sRGB space, by convention)
    build_silhouette_mask   — union of alpha channels

Colour science — why linear light?
-----------------------------------
Digital images are stored in sRGB (IEC 61966-2-1), which applies a gamma
transfer function to compress luminance.  Arithmetic operations (addition,
multiplication, Screen blend) performed directly on sRGB values produce
physically incorrect results because equal numeric steps do not correspond
to equal perceptual or luminance steps.

The canonical example: blending two 50 %-gray pixels should give 50 % gray,
but sRGB-space blending gives 73 % gray (because sRGB(128) represents only
~21 % of peak luminance).  For Screen blend specifically, operating in sRGB
overstates the screen effect — the result is brighter than physically correct.

The fix is to linearise the sRGB values before any arithmetic, perform the
operation in linear-light space, then re-encode back to sRGB:

    sRGB  →  linear   (× (v+0.055/1.055)^2.4 or v/12.92 for small values)
             blend / composite
    linear  →  sRGB   (× 1.055·v^(1/2.4) − 0.055 or v·12.92)

Alpha channels are NOT gamma-corrected — they represent geometric coverage
fractions (already linear by convention).

Performance
-----------
The sRGB→linear direction uses a 256-entry float32 LUT (``_SRGB_TO_LINEAR``)
indexed by the uint8 pixel value.  NumPy array indexing is an O(1)-per-element
C operation, avoiding the power-function call entirely in the hot path.

The linear→sRGB direction uses a vectorised ``np.where`` with ``np.power``,
which numpy evaluates in C across the entire array in a single pass.  For a
typical 700 × 1 000 pixel image this adds ≈ 3–5 ms — negligible compared to
the I/O and warp costs.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# sRGB ↔ linear-light conversion  (IEC 61966-2-1)
# ---------------------------------------------------------------------------

# 256-entry LUT: uint8 sRGB index  →  float32 linear in [0, 1].
# Computed once at import time.  Indexing with a uint8 numpy array is a
# zero-overhead C table lookup — no per-pixel power() call needed.
_SRGB_TO_LINEAR: np.ndarray = np.array(
    [
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        for v in (i / 255.0 for i in range(256))
    ],
    dtype=np.float32,
)


def _to_linear(srgb_u8: np.ndarray) -> np.ndarray:
    """Look up linear-light values for a uint8 sRGB array via the module LUT."""
    return _SRGB_TO_LINEAR[srgb_u8]


def _to_srgb_f32(lin: np.ndarray) -> np.ndarray:
    """Convert a linear float32 [0, 1] array to sRGB float32 [0, 1]."""
    safe = np.clip(lin, 0.0, 1.0)
    return np.where(
        safe <= 0.0031308,
        safe * 12.92,
        1.055 * np.power(safe, 1.0 / 2.4) - 0.055,
    )


# ---------------------------------------------------------------------------
# Public blend operations
# ---------------------------------------------------------------------------

def alpha_weighted_screen(dst: Image.Image, src: Image.Image) -> Image.Image:
    """
    Screen blend weighted by the source alpha channel, computed in linear light.

    For each pixel (all arithmetic in linear-light space)::

        screen  = 1 − (1 − dst_lin) × (1 − src_lin)
        result  = dst_lin × (1 − src_alpha) + screen × src_alpha

    The result is converted back to sRGB before returning.

    The output alpha is max(dst_alpha, src_alpha) — a union of both
    silhouettes.  This is intentional: the template image has opaque pixels
    outside the spine/cover warp area, and those pixels must survive the
    subsequent dst_in clip or the template overlay disappears entirely.
    See ADR-004 for the full rationale.
    """
    assert dst.mode == "RGBA", f"dst must be RGBA, got {dst.mode!r}"
    dst_arr = np.array(dst, dtype=np.uint8)
    src_arr = np.array(src.convert("RGBA"), dtype=np.uint8)

    # Convert RGB to linear light via LUT (alpha is NOT converted)
    dst_lin = _to_linear(dst_arr[:, :, :3])             # (H, W, 3) float32
    src_lin = _to_linear(src_arr[:, :, :3])             # (H, W, 3) float32
    src_a   = src_arr[:, :, 3:4].astype(np.float32) / 255.0  # (H, W, 1)

    # Screen blend in linear light: 1 − (1−A)(1−B)
    screen_lin  = 1.0 - (1.0 - dst_lin) * (1.0 - src_lin)
    blended_lin = dst_lin * (1.0 - src_a) + screen_lin * src_a

    # Convert result back to sRGB
    blended_srgb = _to_srgb_f32(blended_lin)

    result = np.empty_like(dst_arr)
    result[:, :, :3] = np.clip(np.round(blended_srgb * 255.0), 0, 255).astype(np.uint8)
    # Alpha: union of dst and src so the template silhouette survives dst_in.
    result[:, :, 3]  = np.maximum(dst_arr[:, :, 3], src_arr[:, :, 3])

    return Image.fromarray(result, "RGBA")


def linear_alpha_composite(dst: Image.Image, src: Image.Image) -> Image.Image:
    """
    Porter-Duff 'over' compositing in linear-light space.

    Equivalent to ``PIL.Image.alpha_composite`` but performs the alpha blend
    in linear light, preventing the systematic darkening that occurs when
    partial-alpha pixels are blended in gamma-encoded sRGB.

    Use this instead of ``PIL.Image.alpha_composite`` whenever the source
    has fractional alpha (e.g. feathered warp boundaries, anti-aliased logos).
    For a fully-transparent destination the result is mathematically identical
    to the source, so ``PIL.Image.alpha_composite`` is an equivalent and
    faster choice in that degenerate case.

    Porter-Duff 'over' in linear space::

        out_a   = src_a + dst_a × (1 − src_a)
        out_lin = (src_lin × src_a + dst_lin × dst_a × (1 − src_a)) / out_a
    """
    assert dst.mode == "RGBA", f"dst must be RGBA, got {dst.mode!r}"
    dst_arr = np.array(dst, dtype=np.uint8)
    src_arr = np.array(src.convert("RGBA"), dtype=np.uint8)

    dst_lin = _to_linear(dst_arr[:, :, :3])
    src_lin = _to_linear(src_arr[:, :, :3])
    dst_a   = dst_arr[:, :, 3:4].astype(np.float32) / 255.0
    src_a   = src_arr[:, :, 3:4].astype(np.float32) / 255.0

    out_a = src_a + dst_a * (1.0 - src_a)

    # Guard against division by zero for fully-transparent output pixels
    safe_out_a  = np.where(out_a > 0.0, out_a, 1.0)
    out_lin     = (src_lin * src_a + dst_lin * dst_a * (1.0 - src_a)) / safe_out_a
    out_srgb    = _to_srgb_f32(out_lin)

    result = np.empty_like(dst_arr)
    result[:, :, :3] = np.clip(np.round(out_srgb * 255.0), 0, 255).astype(np.uint8)
    result[:, :, 3]  = np.clip(np.round(out_a[:, :, 0] * 255.0), 0, 255).astype(np.uint8)

    return Image.fromarray(result, "RGBA")


def dst_in(dst: Image.Image, mask: Image.Image) -> Image.Image:
    """
    DstIn compositing: multiply *dst* alpha by *mask*.

    Alpha is a geometric coverage fraction (already linear) — no gamma
    correction is applied here.
    """
    dst_arr  = np.array(dst, dtype=np.float32, copy=True)
    mask_arr = np.array(mask, dtype=np.float32)

    dst_arr[:, :, 3] = np.clip(dst_arr[:, :, 3] * (mask_arr / 255.0), 0, 255)
    return Image.fromarray(dst_arr.astype(np.uint8), "RGBA")


def apply_color_matrix(img: Image.Image, matrix_str: str) -> Image.Image:
    """
    Apply a diagonal RGB multiplier matrix to *img*.

    Operates in sRGB space by convention — the matrix coefficients are
    typically authored relative to sRGB channel values (e.g. ``--rgb 0.9,0.9,1.1``
    means "reduce red/green by 10 %, boost blue by 10 %").
    """
    parts   = matrix_str.split()
    r, g, b = float(parts[0]), float(parts[4]), float(parts[8])

    rgba_img = img.convert("RGBA")
    alpha    = rgba_img.getchannel("A")

    matrix = (
        r, 0.0, 0.0, 0.0,
        0.0, g, 0.0, 0.0,
        0.0, 0.0, b, 0.0,
    )

    rgb_scaled = rgba_img.convert("RGB").convert("RGB", matrix)
    return Image.merge("RGBA", (*rgb_scaled.split(), alpha))


def build_silhouette_mask(*alpha_sources: Image.Image) -> Image.Image:
    """
    Compute the union of the alpha channels of all *alpha_sources*.
    """
    assert all(src.mode == "RGBA" for src in alpha_sources), \
        "build_silhouette_mask: all sources must be RGBA"
    arrays = [
        np.array(src.getchannel("A"), dtype=np.float32)
        for src in alpha_sources
    ]

    union = arrays[0]
    for a in arrays[1:]:
        union = np.maximum(union, a)

    return Image.fromarray(np.clip(union, 0, 255).astype(np.uint8), "L")
