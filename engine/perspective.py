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

    PIL uses an **inverse** mapping (destination → source), so the linear
    system is built with destination as input and source as output.

    Reference: https://stackoverflow.com/a/14178717

    Raises:
        numpy.linalg.LinAlgError — if the system is singular (degenerate
        quadrilateral, e.g. all points collinear).
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
    Perspective-warp *src* onto a transparent canvas of
    (canvas_w × canvas_h), placing the four corners of *src* at *dst_pts*.

    *dst_pts* must be four points in clockwise order: TL, TR, BR, BL.

    Returns an RGBA image.
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

    Modes:
        ``"stretch"`` — force exact dimensions (may alter aspect ratio).
        ``"fit"``     — preserve aspect ratio, pad with transparency.
        ``"crop"``    — preserve aspect ratio, crop to centre.
    """
    img = img.convert("RGBA")

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
