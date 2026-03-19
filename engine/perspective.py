"""
engine/perspective.py — Perspective warp
==========================================
Isolated module for computing perspective transform coefficients and
applying them via ``PIL.Image.transform``.

All functions are pure and stateless.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def solve_coefficients(
    src_pts: list[tuple[int, int]],
    dst_pts: list[tuple[int, int]],
) -> tuple[float, ...]:
    """
    Solve the 8-coefficient perspective transform mapping *src_pts* to
    *dst_pts*.
    """
    matrix: list[list[float]] = []
    for (dx, dy), (sx, sy) in zip(dst_pts, src_pts):
        matrix.append([dx, dy, 1, 0,  0,  0, -sx * dx, -sx * dy])
        matrix.append([0,  0,  0, dx, dy, 1, -sy * dx, -sy * dy])

    A = np.array(matrix, dtype=np.float64)
    b: list[float] = []
    for _, (sx, sy) in zip(dst_pts, src_pts):
        b.extend([sx, sy])

    coeffs = np.linalg.solve(A, np.array(b, dtype=np.float64))
    return tuple(float(c) for c in coeffs)


def warp(
    src:      Image.Image,
    canvas_w: int,
    canvas_h: int,
    dst_pts:  list[tuple[int, int]],
) -> Image.Image:
    """
    Perspective-warp *src* onto a transparent canvas.
    """
    sw, sh  = src.size
    src_pts = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
    coeffs  = solve_coefficients(src_pts, dst_pts)
    return src.transform(
        (canvas_w, canvas_h),
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC,
    ).convert("RGBA")


def resize_for_fit(
    img:      Image.Image,
    target_w: int,
    target_h: int,
    mode:     str,
) -> Image.Image:
    """
    Resize *img* to (target_w × target_h) in the requested *mode*,
    always returning RGBA.
    """
    # --- OOM Hardening: Clamp estrutural da geometria de destino ---
    # Se os parâmetros alvo excederem 8192px, aplicamos um scale down
    # proporcional para proteger a alocação de memória subsequente,
    # mantendo a integridade matemática da proporção original.
    max_dim = max(target_w, target_h)
    if max_dim > 8192:
        scale_factor = 8192.0 / max_dim
        target_w = max(1, int(target_w * scale_factor))
        target_h = max(1, int(target_h * scale_factor))
    # ---------------------------------------------------------------

    img = img.convert("RGBA")

    # --- OOM Hardening: Downscale preventivo da fonte ---
    if img.width > 8192 or img.height > 8192:
        img.thumbnail((8192, 8192), Image.BICUBIC)
    # ----------------------------------------------------

    if mode == "stretch":
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.BICUBIC)
        return img

    iw, ih = img.size

    if mode == "fit":
        scale = min(target_w / iw, target_h / ih)
        nw    = max(1, int(iw * scale))
        nh    = max(1, int(ih * scale))
        img   = img.resize((nw, nh), Image.LANCZOS)
        out   = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        out.paste(img, ((target_w - nw) // 2, (target_h - nh) // 2), img)
        return out

    # "crop"
    scale = max(target_w / iw, target_h / ih)
    nw    = max(1, int(iw * scale))
    nh    = max(1, int(ih * scale))
    img   = img.resize((nw, nh), Image.LANCZOS)
    ox    = (nw - target_w) // 2
    oy    = (nh - target_h) // 2
    return img.crop((ox, oy, ox + target_w, oy + target_h))