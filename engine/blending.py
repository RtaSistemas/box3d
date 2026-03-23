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
from PIL import Image


def alpha_weighted_screen(dst: Image.Image, src: Image.Image) -> Image.Image:
    """
    Screen blend weighted by the source alpha channel.

    For each pixel::

        screen  = 1 − (1 − dst_rgb) × (1 − src_rgb)
        result  = dst_rgb × (1 − src_alpha) + screen × src_alpha

    The alpha channel of *dst* is preserved unchanged (see ADR-004).
    """
    dst_arr = np.array(dst, dtype=np.float32)
    src_arr = np.array(src.convert("RGBA"), dtype=np.float32)

    dst_rgb = dst_arr[:, :, :3] / 255.0
    src_rgb = src_arr[:, :, :3] / 255.0
    src_a   = src_arr[:, :, 3:4] / 255.0

    screen  = 1.0 - (1.0 - dst_rgb) * (1.0 - src_rgb)
    blended = dst_rgb * (1.0 - src_a) + screen * src_a

    # Previne cópia redundante usando empty_like antes da atribuição final
    result = np.empty_like(dst_arr)
    result[:, :, :3] = np.clip(blended * 255.0, 0, 255)
    result[:, :, 3] = dst_arr[:, :, 3]   # ADR-004: alpha do dst preservado

    return Image.fromarray(result.astype(np.uint8), "RGBA")


def dst_in(dst: Image.Image, mask: Image.Image) -> Image.Image:
    """
    DstIn compositing: multiply *dst* alpha by *mask*.
    """
    # copy=True garante o isolamento Zero-Trust antes da mutação in-place
    dst_arr  = np.array(dst, dtype=np.float32, copy=True)
    mask_arr = np.array(mask, dtype=np.float32)
    
    dst_arr[:, :, 3] = np.clip(dst_arr[:, :, 3] * (mask_arr / 255.0), 0, 255)
    return Image.fromarray(dst_arr.astype(np.uint8), "RGBA")


def apply_color_matrix(img: Image.Image, matrix_str: str) -> Image.Image:
    """
    Apply a diagonal RGB multiplier matrix to *img*.
    """
    parts   = matrix_str.split()
    r, g, b = float(parts[0]), float(parts[4]), float(parts[8])

    rgba_img = img.convert("RGBA")
    alpha = rgba_img.getchannel("A")
    
    # Matriz 12-tuple para conversão nativa RGB -> RGB no Pillow
    matrix = (
        r, 0.0, 0.0, 0.0,
        0.0, g, 0.0, 0.0,
        0.0, 0.0, b, 0.0
    )
    
    # Aplica escala nativa em C e remonta a imagem mantendo o Alpha 1.0 original
    rgb_scaled = rgba_img.convert("RGB").convert("RGB", matrix)
    return Image.merge("RGBA", (*rgb_scaled.split(), alpha))


def build_silhouette_mask(*alpha_sources: Image.Image) -> Image.Image:
    """
    Compute the union of the alpha channels of all *alpha_sources*.
    """
    # getchannel("A") carrega apenas a banda Alpha, evitando alocar RGBA completo
    arrays = [
        np.array(src.convert("RGBA").getchannel("A"), dtype=np.float32)
        for src in alpha_sources
    ]
    
    union = arrays[0]
    for a in arrays[1:]:
        union = np.maximum(union, a)
        
    return Image.fromarray(np.clip(union, 0, 255).astype(np.uint8), "L")