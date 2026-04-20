"""
engine/perspective.py — Perspective warp
==========================================
Isolated module for computing perspective transform coefficients and
applying them via ``PIL.Image.transform``.

All functions are pure and stateless.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter


@lru_cache(maxsize=64)
def _solve_cached(
    src_pts: tuple[tuple[int, int], ...],
    dst_pts: tuple[tuple[int, int], ...],
) -> tuple[float, ...]:
    """
    Cached core solver. Arguments are immutable tuples so lru_cache can hash
    them. In a typical batch of 1 000 covers sharing the same profile geometry,
    the homography is computed only once per unique (src, dst) pair.
    """
    src = np.array(src_pts, dtype=np.float64)  # (4, 2)
    dst = np.array(dst_pts, dtype=np.float64)  # (4, 2)

    sx, sy = src[:, 0], src[:, 1]
    dx, dy = dst[:, 0], dst[:, 1]

    A = np.zeros((8, 8), dtype=np.float64)
    even = np.arange(0, 8, 2)  # [0, 2, 4, 6]
    odd  = np.arange(1, 8, 2)  # [1, 3, 5, 7]

    A[even, 0] = dx;  A[even, 1] = dy;  A[even, 2] = 1.0
    A[even, 6] = -sx * dx;  A[even, 7] = -sx * dy

    A[odd, 3] = dx;   A[odd, 4] = dy;   A[odd, 5] = 1.0
    A[odd, 6] = -sy * dx;   A[odd, 7] = -sy * dy

    b = np.empty(8, dtype=np.float64)
    b[even] = sx
    b[odd]  = sy

    coeffs = np.linalg.solve(A, b)
    return tuple(float(c) for c in coeffs)


def solve_coefficients(
    src_pts: list[tuple[int, int]],
    dst_pts: list[tuple[int, int]],
) -> tuple[float, ...]:
    """
    Solve the 8-coefficient perspective transform mapping *src_pts* to
    *dst_pts*.

    Converts the mutable lists to hashable tuples before delegating to the
    lru_cache-backed solver, avoiding redundant homography computation across
    covers that share the same profile geometry.
    """
    return _solve_cached(tuple(src_pts), tuple(dst_pts))


def warp(
    src:      Image.Image,
    canvas_w: int,
    canvas_h: int,
    dst_pts:  list[tuple[int, int]],
    feather:  float = 1.2,
) -> Image.Image:
    """
    Perspective-warp *src* onto a transparent canvas.

    *feather* controls the GaussianBlur radius applied to the alpha channel
    after the transform to eliminate the hard binary edge (stair-step aliasing)
    that PIL.Image.transform produces at quad boundaries.  Set to 0 to disable.
    """
    sw, sh  = src.size
    src_pts = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
    coeffs  = solve_coefficients(src_pts, dst_pts)
    warped  = src.transform(
        (canvas_w, canvas_h),
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC,
    ).convert("RGBA")

    if feather > 0:
        r, g, b, a = warped.split()
        a = a.filter(ImageFilter.GaussianBlur(radius=feather))
        warped = Image.merge("RGBA", (r, g, b, a))

    return warped


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
            img = img.resize((target_w, target_h), Image.LANCZOS)
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