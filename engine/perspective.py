"""
engine/perspective.py — Perspective warp
==========================================
Isolated module for computing perspective transform coefficients and
applying them via pyvips (primary) or PIL.Image.transform (fallback).

All functions are pure and stateless.

pyvips backend
--------------
When pyvips is importable the ``warp()`` function delegates to a pyvips
pipeline that is ~2.3x faster than PIL on cache-hit batches and produces
smoother alpha edges:

* The 8-coefficient homography is cached by ``_solve_cached`` (lru_cache).
* The derived per-output-pixel coordinate map (an ``(H, W, 2)`` float32
  numpy array) is cached in ``_COORD_CACHE`` keyed by
  ``(canvas_w, canvas_h, coeffs)``.  In a typical batch of 1 000 covers
  sharing one profile the 50-60 ms cache-miss cost is paid exactly once per
  unique quad, with subsequent calls costing ~11 ms vs ~75 ms for PIL.
* pyvips.Image.new_from_array wraps the cached numpy array with zero copy,
  so the array must stay alive for the duration of the mapim call — the
  cache guarantees this.
* ``pyvips.Image.mapim`` uses the ``lbb`` (locally bounded bicubic)
  interpolator with ``extend=BACKGROUND`` for transparent out-of-bounds
  regions.  lbb produces a smooth anti-aliased alpha gradient at quad
  boundaries (256 unique alpha values) versus PIL's binary 0/255 edge.
* The default warp kernel can be overridden at process start via the
  ``BOX3D_WARP_BACKEND`` environment variable
  (``lbb`` | ``nohalo`` | ``bicubic`` | ``bilinear``).

Thread safety
-------------
pyvips/libvips uses a GLib thread-pool internally; each ``mapim`` call is
independent.  ``_COORD_CACHE`` is written at most once per key; Python's GIL
serialises the check-and-insert, so no explicit lock is needed.

PyInstaller bundling note
-------------------------
pyvips is a pure-Python CFFI binding.  The runtime dependency is
``libvips.so.42`` (Linux) / ``libvips-42.dll`` (Windows) plus the GLib
stack.  When building a standalone executable, include these shared
libraries alongside the executable.  If libvips is absent at runtime the
module automatically falls back to the PIL path with no code change.

Important: do NOT store pyvips.Image objects in a process-global cache.
Storing them in module-level dicts causes a segfault during Python
interpreter shutdown when the GLib/cffi finalizers run.  Cache the
underlying numpy arrays instead and wrap them into a fresh pyvips.Image
on each call (new_from_array is zero-copy so this is fast).
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional pyvips backend
# ---------------------------------------------------------------------------
try:
    import pyvips as _pyvips  # noqa: F401 — keep reference alive
    _PYVIPS_AVAILABLE = True
    log.info("pyvips %s available — using accelerated mapim warp", _pyvips.__version__)
except Exception:
    _pyvips = None            # type: ignore[assignment]
    _PYVIPS_AVAILABLE = False
    log.info("pyvips not available — falling back to PIL BICUBIC warp")

# Warp kernel used by the pyvips path.
# Supported values: 'lbb' | 'nohalo' | 'bicubic' | 'bilinear'
#   lbb    — locally bounded bicubic; smooth anti-aliased alpha at quad
#             boundaries (256 unique values); fast (default)
#   nohalo — EWA (Elliptical Weighted Average); highest quality for
#             extreme perspective distortions; ~1.7x slower than lbb
#   bicubic — standard bicubic with extend=BACKGROUND; 73 unique alpha
#             values; requires feathering for smooth edges
#   bilinear — bilinear; fastest but lowest quality
# Override via BOX3D_WARP_BACKEND environment variable before process start.
_VALID_VIPS_KERNELS = frozenset({"lbb", "nohalo", "bicubic", "bilinear"})
_VIPS_KERNEL: str = os.environ.get("BOX3D_WARP_BACKEND", "lbb")
if _VIPS_KERNEL not in _VALID_VIPS_KERNELS:
    raise ValueError(
        f"BOX3D_WARP_BACKEND={_VIPS_KERNEL!r} is not a valid pyvips kernel. "
        f"Valid values: {sorted(_VALID_VIPS_KERNELS)}"
    )

# Human-readable backend label for the process-default kernel (env var / diagnostics).
if _PYVIPS_AVAILABLE:
    WARP_BACKEND_LABEL: str = (
        f"pyvips {_pyvips.__version__} — kernel={_VIPS_KERNEL} "  # type: ignore[union-attr]
        "(smooth anti-aliased warp)"
    )
else:
    WARP_BACKEND_LABEL = "PIL BICUBIC fallback — pyvips unavailable (expect jagged edges)"


def get_backend_label(kernel: str) -> str:
    """Return a per-render backend label reflecting the actual *kernel* in use.

    Unlike the module-level ``WARP_BACKEND_LABEL`` constant (which always shows
    the process-default kernel from the env var), this function is called at
    render time so the logged label matches the kernel selected for that run.
    """
    if not _PYVIPS_AVAILABLE:
        return "PIL BICUBIC fallback — pyvips unavailable (expect jagged edges)"
    active = kernel if kernel in _VALID_VIPS_KERNELS else _VIPS_KERNEL
    return (
        f"pyvips {_pyvips.__version__} — kernel={active} "  # type: ignore[union-attr]
        "(smooth anti-aliased warp)"
    )

# LRU cache of float32 coordinate arrays keyed by (canvas_w, canvas_h, coeffs-tuple).
# Capped at _COORD_CACHE_MAX entries (~5.6 MB each for 700×1000 canvas) to bound
# memory growth in long-lived server processes that render multiple profiles.
# Storing numpy arrays (not pyvips Images) avoids a GLib/cffi segfault at shutdown.
_COORD_CACHE_MAX = 16
_COORD_CACHE: OrderedDict[tuple, np.ndarray] = OrderedDict()


# ---------------------------------------------------------------------------
# Homography solver (shared by both backends)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _solve_cached(
    src_pts: tuple[tuple[int, int], ...],
    dst_pts: tuple[tuple[int, int], ...],
) -> tuple[float, ...]:
    """
    Cached core solver. Arguments are immutable tuples so lru_cache can hash
    them. In a typical batch of 1 000 covers sharing the same profile geometry,
    the homography is computed only once per unique (src, dst) pair.

    The returned 8-tuple ``(a0..a7)`` encodes the *inverse* homography
    (output-pixel -> source-pixel) in PIL's convention::

        src_x = (a0*dx + a1*dy + a2) / (a6*dx + a7*dy + 1)
        src_y = (a3*dx + a4*dy + a5) / (a6*dx + a7*dy + 1)

    This is exactly what PIL passes to ``Image.PERSPECTIVE`` and what the
    pyvips ``mapim`` coordinate map evaluates at each output pixel.
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


# ---------------------------------------------------------------------------
# pyvips helpers
# ---------------------------------------------------------------------------

def _get_coord_array(
    canvas_w: int,
    canvas_h: int,
    coeffs: tuple[float, ...],
) -> np.ndarray:
    """
    Return a cached float32 array of shape (H, W, 2) encoding the inverse
    warp map: band 0 = source x-coordinate, band 1 = source y-coordinate
    for each output pixel.

    Cache miss: ~50-60 ms for a 1000x1000 canvas (numpy mgrid).
    Cache hit:  O(1) dict lookup, no allocation.
    """
    key = (canvas_w, canvas_h, coeffs)
    if key in _COORD_CACHE:
        _COORD_CACHE.move_to_end(key)   # mark as recently used
        return _COORD_CACHE[key]

    a0, a1, a2, a3, a4, a5, a6, a7 = coeffs
    ys, xs = np.mgrid[0:canvas_h, 0:canvas_w].astype(np.float32)
    denom  = a6 * xs + a7 * ys + 1.0
    src_x  = (a0 * xs + a1 * ys + a2) / denom
    src_y  = (a3 * xs + a4 * ys + a5) / denom
    _COORD_CACHE[key] = np.stack([src_x, src_y], axis=2)  # (H, W, 2) float32

    if len(_COORD_CACHE) > _COORD_CACHE_MAX:
        _COORD_CACHE.popitem(last=False)  # evict least recently used

    return _COORD_CACHE[key]


def _warp_pyvips(
    src:      Image.Image,
    canvas_w: int,
    canvas_h: int,
    coeffs:   tuple[float, ...],
    feather:  float = 0,
    kernel:   str | None = None,
) -> Image.Image:
    """
    pyvips-accelerated perspective warp.

    Uses ``mapim`` with ``extend=BACKGROUND`` so out-of-bounds reads return
    transparent pixels.  ``lbb`` (the default kernel) produces a smooth
    anti-aliased alpha gradient at quad boundaries intrinsically.

    The coordinate array is fetched from ``_COORD_CACHE`` and wrapped
    zero-copy into a pyvips Image.  The source image is also wrapped
    zero-copy (the PIL image buffer stays alive for the call duration).

    *kernel* overrides the module-level ``_VIPS_KERNEL`` for this call only.
    """
    active_kernel = kernel if kernel in _VALID_VIPS_KERNELS else _VIPS_KERNEL

    # Ensure source is RGBA before wrapping (pyvips mapim must return 4 bands)
    src_rgba = src if src.mode == "RGBA" else src.convert("RGBA")
    src_arr  = np.asarray(src_rgba)  # view, no copy; PIL buffer stays alive

    # Wrap source array into pyvips (zero-copy view)
    src_vips = _pyvips.Image.new_from_array(src_arr)

    # Wrap cached coordinate array into pyvips (zero-copy; cache keeps it alive)
    idx_arr  = _get_coord_array(canvas_w, canvas_h, coeffs)
    idx_vips = _pyvips.Image.new_from_array(idx_arr)

    warped_vips = src_vips.mapim(
        idx_vips,
        interpolate=_pyvips.Interpolate.new(active_kernel),
        background=[0, 0, 0, 0],
        extend=_pyvips.Extend.BACKGROUND,
    )

    warped_arr = warped_vips.numpy()
    warped     = Image.fromarray(warped_arr.astype(np.uint8), "RGBA")

    if feather > 0:
        r, g, b, a = warped.split()
        a      = a.filter(ImageFilter.GaussianBlur(radius=feather))
        warped = Image.merge("RGBA", (r, g, b, a))

    return warped


# ---------------------------------------------------------------------------
# Public warp API
# ---------------------------------------------------------------------------

def warp(
    src:      Image.Image,
    canvas_w: int,
    canvas_h: int,
    dst_pts:  list[tuple[int, int]],
    feather:  float = 1.2,
    kernel:   str | None = None,
) -> Image.Image:
    """
    Perspective-warp *src* onto a transparent canvas of size
    (*canvas_w* x *canvas_h*), placing its four corners at *dst_pts*
    (TL, TR, BR, BL order).

    When pyvips is available the warp is performed via ``mapim``, which is
    ~2.3x faster than PIL on cache-hit batches and produces a smooth
    anti-aliased alpha gradient at quad boundaries.

    Falls back to ``PIL.Image.transform(PERSPECTIVE, BICUBIC)`` when pyvips
    is absent.

    *kernel* selects the pyvips interpolator for this call:
      ``lbb`` (default) — smooth anti-aliased, fast
      ``nohalo`` — EWA, highest quality for extreme distortions (~1.7x slower)
      ``bicubic`` | ``bilinear`` — standard alternatives
    If *kernel* is None or invalid the module default (``_VIPS_KERNEL``) is used.

    *feather* controls the GaussianBlur radius on the alpha channel in the
    PIL fallback path only; pyvips ``lbb``/``nohalo`` produce smooth gradients
    intrinsically.
    """
    sw, sh  = src.size
    src_pts = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
    coeffs  = solve_coefficients(src_pts, dst_pts)

    if _PYVIPS_AVAILABLE:
        return _warp_pyvips(src, canvas_w, canvas_h, coeffs, feather, kernel)

    # PIL fallback
    src_rgba = src if src.mode == "RGBA" else src.convert("RGBA")
    warped   = src_rgba.transform(
        (canvas_w, canvas_h),
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC,
    ).convert("RGBA")

    if feather > 0:
        r, g, b, a = warped.split()
        a      = a.filter(ImageFilter.GaussianBlur(radius=feather))
        warped = Image.merge("RGBA", (r, g, b, a))

    return warped


# ---------------------------------------------------------------------------
# Resize helper (unchanged)
# ---------------------------------------------------------------------------

def resize_for_fit(
    img:      Image.Image,
    target_w: int,
    target_h: int,
    mode:     str,
) -> Image.Image:
    """
    Resize *img* to (target_w x target_h) in the requested *mode*,
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
