#!/usr/bin/env python3
"""
tests/visual/generate_baselines.py — Baseline generator for snapshot tests
===========================================================================
Renders each case in CASES and saves lossless PNG baselines to
``tests/visual/expected/``.

Usage::

    # Generate missing baselines only (safe default):
    python tests/visual/generate_baselines.py

    # Regenerate ALL baselines (use after intentional engine change):
    python tests/visual/generate_baselines.py --force

    # Regenerate specific cases:
    python tests/visual/generate_baselines.py --cases mvs_default arcade_default

Baselines are lossless PNG files and must be committed to the repository.
Regenerate them whenever the render output intentionally changes (e.g. after
a profile update or algorithm improvement), verify them visually, then commit.

⚠️  Never regenerate baselines from a branch with unreviewed engine changes.
    The baseline represents the *known-good* output.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from core.models    import RenderOptions
from core.registry  import ProfileRegistry
from engine.compositor import compose_cover
from tests.visual.cases import CASES, SnapshotCase

ASSETS   = ROOT / "tests" / "assets"
PROFILES = ROOT / "profiles"
EXPECTED = Path(__file__).parent / "expected"


def render_case(case: SnapshotCase, registry: ProfileRegistry) -> Image.Image:
    """Render one snapshot case to an in-memory RGBA Image."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate snapshot baselines")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing baselines",
    )
    parser.add_argument(
        "--cases", nargs="+", default=None,
        metavar="CASE_ID",
        help="Generate only these case IDs (default: all)",
    )
    args = parser.parse_args()

    EXPECTED.mkdir(parents=True, exist_ok=True)
    registry = ProfileRegistry(PROFILES).load()

    cases = [c for c in CASES if args.cases is None or c.id in args.cases]
    if not cases:
        print(f"No matching cases for: {args.cases}")
        sys.exit(1)

    print(f"\nGenerating baselines → {EXPECTED}")
    print("=" * 54)

    generated = skipped = errors = 0
    for case in cases:
        dest = EXPECTED / f"{case.id}.png"
        if dest.exists() and not args.force:
            print(f"  SKIP  {case.id:<30} (already exists — use --force to overwrite)")
            skipped += 1
            continue

        t0 = time.perf_counter()
        try:
            img = render_case(case, registry)
            img.save(str(dest), "PNG", optimize=False)
            elapsed = time.perf_counter() - t0
            size_kb = dest.stat().st_size / 1024
            print(f"  OK    {case.id:<30} {img.size[0]}x{img.size[1]}  "
                  f"{elapsed:.2f}s  {size_kb:.0f} KB")
            generated += 1
        except Exception as exc:
            print(f"  ERROR {case.id:<30} {exc}")
            errors += 1

    print("=" * 54)
    print(f"  Generated : {generated}")
    print(f"  Skipped   : {skipped}")
    print(f"  Errors    : {errors}")
    print()

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
