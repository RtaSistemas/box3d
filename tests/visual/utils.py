"""
tests/visual/utils.py — Image comparison utilities for snapshot testing
========================================================================
All functions operate on NumPy float32 RGBA arrays for consistent
arithmetic across platforms.

Thresholds
----------
MSE_THRESHOLD   Mean squared error per element.  5.0 tolerates ±2-pixel
                cross-platform differences from floating-point divergence
                in Gaussian blur and BICUBIC warp resampling while still
                catching any meaningful regression.

MAX_DIFF        Maximum single-element absolute difference.  20 (~8% of
                full range) flags gross per-pixel corruption that low MSE
                might not catch if errors are spatially isolated.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

MSE_THRESHOLD: float = 5.0
MAX_DIFF:      float = 20.0


def load_rgba(path: Path) -> np.ndarray:
    """Load a PNG as a float32 (H, W, 4) RGBA array."""
    return np.array(Image.open(path).convert("RGBA"), dtype=np.float32)


def image_to_array(img: Image.Image) -> np.ndarray:
    """Convert a PIL RGBA Image to float32 array."""
    return np.array(img.convert("RGBA"), dtype=np.float32)


def mse(a: np.ndarray, b: np.ndarray) -> float:
    """Mean squared error across all elements of two same-shape arrays."""
    return float(np.mean((a - b) ** 2))


def max_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Maximum absolute difference across all elements."""
    return float(np.abs(a - b).max())


def save_diff(actual: np.ndarray, expected: np.ndarray, path: Path) -> None:
    """
    Write an amplified RGB difference image to *path* for visual inspection.

    The alpha channel is excluded (usually uninteresting for composition
    regressions).  Differences are amplified 10× so single-bit changes
    are easily visible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    diff_rgb = np.abs(actual[:, :, :3] - expected[:, :, :3])
    amplified = np.clip(diff_rgb * 10, 0, 255).astype(np.uint8)
    Image.fromarray(amplified, "RGB").save(str(path))


def compare(
    actual:    np.ndarray,
    expected:  np.ndarray,
    diff_path: Path | None = None,
) -> tuple[float, float]:
    """
    Compare *actual* against *expected*.  Returns ``(mse_value, max_diff)``.

    If the comparison fails the thresholds AND *diff_path* is provided,
    a diff image is written there for inspection.
    """
    m = mse(actual, expected)
    d = max_abs_diff(actual, expected)

    if diff_path and (m > MSE_THRESHOLD or d > MAX_DIFF):
        save_diff(actual, expected, diff_path)

    return m, d
