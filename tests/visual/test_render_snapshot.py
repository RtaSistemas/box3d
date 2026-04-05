"""
tests/visual/test_render_snapshot.py — Snapshot regression tests
=================================================================
Detects any unintended change to the rendered output by comparing
the current engine output against committed PNG baselines.

Running
-------
    pytest tests/visual/test_render_snapshot.py -v

Generating / updating baselines
--------------------------------
    python tests/visual/generate_baselines.py          # missing only
    python tests/visual/generate_baselines.py --force  # regenerate all

A test is automatically skipped when its baseline does not exist yet.

Failure artefacts
-----------------
On failure, two files are written to ``tests/visual/diff/``:

``<case_id>_actual.png``
    The current engine output (lossless PNG).

``<case_id>_diff.png``
    Amplified difference image (10×) for visual inspection.
    Bright pixels indicate changed areas.

Thresholds (defined in utils.py)
---------------------------------
MSE_THRESHOLD = 5.0  — mean squared error per element
MAX_DIFF      = 20.0 — maximum single-element absolute difference
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.models    import RenderOptions
from core.registry  import ProfileRegistry
from engine.compositor import compose_cover
from tests.visual.cases import CASES, SnapshotCase
from tests.visual.utils import (
    MSE_THRESHOLD, MAX_DIFF,
    image_to_array, load_rgba, compare,
)

ASSETS   = ROOT / "tests" / "assets"
PROFILES = ROOT / "profiles"
EXPECTED = Path(__file__).parent / "expected"
DIFF_DIR = Path(__file__).parent / "diff"
OUTPUT   = Path(__file__).parent / "output"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry():
    return ProfileRegistry(PROFILES).load()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _render(case: SnapshotCase, registry: ProfileRegistry) -> Image.Image:
    profile  = registry.get(case.profile_name)
    cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
    template = Image.open(profile.template_path).convert("RGBA")

    top_logo    = Image.open(ASSETS / "logo_top.png").convert("RGBA")    if case.with_logos else None
    bottom_logo = Image.open(ASSETS / "logo_bottom.png").convert("RGBA") if case.with_logos else None
    game_logo   = Image.open(ASSETS / "marquee.webp").convert("RGBA")    if case.with_logos else None

    opts = RenderOptions(
        blur_radius  = case.blur_radius,
        darken_alpha = case.darken_alpha,
        rgb_matrix   = case.rgb_matrix,
        no_rotate    = case.no_rotate,
        cover_fit    = case.cover_fit,
        spine_source = case.spine_source,
    )

    return compose_cover(
        cover_img    = cover,
        profile      = profile,
        options      = opts,
        game_logo    = game_logo,
        top_logo     = top_logo,
        bottom_logo  = bottom_logo,
        template_img = template,
    )


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_render_matches_baseline(case: SnapshotCase, registry: ProfileRegistry):
    """
    Render the case and compare pixel-by-pixel against the stored baseline.

    Fails if MSE > MSE_THRESHOLD or any single element differs by > MAX_DIFF.
    Diff images are saved to tests/visual/diff/ on failure.
    """
    baseline = EXPECTED / f"{case.id}.png"
    if not baseline.exists():
        pytest.skip(
            f"No baseline for {case.id!r} — "
            f"run: python tests/visual/generate_baselines.py"
        )

    result   = _render(case, registry)
    actual   = image_to_array(result)
    expected = load_rgba(baseline)

    assert actual.shape == expected.shape, (
        f"{case.id}: output shape {actual.shape} "
        f"does not match baseline {expected.shape}"
    )

    diff_path = DIFF_DIR / f"{case.id}_diff.png"
    m, d = compare(actual, expected, diff_path=diff_path)

    # Save the actual output for inspection regardless of pass/fail
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result.save(str(OUTPUT / f"{case.id}.png"), "PNG", optimize=False)

    assert m <= MSE_THRESHOLD, (
        f"{case.id}: MSE {m:.4f} exceeds threshold {MSE_THRESHOLD:.1f} "
        f"(max_diff={d:.1f}). "
        f"Diff image saved to: {diff_path}"
    )
    assert d <= MAX_DIFF, (
        f"{case.id}: max pixel diff {d:.1f} exceeds {MAX_DIFF:.1f} "
        f"(MSE={m:.4f}). "
        f"Diff image saved to: {diff_path}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_render_is_deterministic(case: SnapshotCase, registry: ProfileRegistry):
    """
    Render the same case twice and assert the outputs are bitwise identical.

    Fails if any pixel differs between the two runs — this would indicate
    non-deterministic behaviour in the engine (threading, random, etc.).
    """
    a = image_to_array(_render(case, registry))
    b = image_to_array(_render(case, registry))

    assert a.shape == b.shape
    m = float(__import__("numpy").mean((a - b) ** 2))
    assert m == 0.0, (
        f"{case.id}: render is non-deterministic — "
        f"two runs with identical input produced different output (MSE={m:.6f})"
    )


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_render_output_is_rgba(case: SnapshotCase, registry: ProfileRegistry):
    """Output must be RGBA regardless of profile or options."""
    result = _render(case, registry)
    assert result.mode == "RGBA", f"{case.id}: expected RGBA, got {result.mode}"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_render_output_size_matches_profile(case: SnapshotCase, registry: ProfileRegistry):
    """Output dimensions must match the profile template size exactly."""
    profile = registry.get(case.profile_name)
    result  = _render(case, registry)
    expected_size = (profile.geometry.template_w, profile.geometry.template_h)
    assert result.size == expected_size, (
        f"{case.id}: output size {result.size} "
        f"does not match profile template {expected_size}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_render_output_not_blank(case: SnapshotCase, registry: ProfileRegistry):
    """Output must not be a blank/transparent image."""
    import numpy as np
    result = _render(case, registry)
    arr    = np.array(result)
    assert arr[:, :, 3].max() > 0, f"{case.id}: output is fully transparent"
    assert arr[:, :, :3].std() > 2.0, f"{case.id}: output has no colour variance (blank)"
