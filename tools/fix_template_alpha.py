#!/usr/bin/env python3
"""
tools/fix_template_alpha.py
===========================
Anti-aliases the alpha channel of a Box3D profile template (template.png)
using only Pillow + NumPy — no graphic editor required.

When a template PNG is exported from Photoshop/GIMP/Inkscape/Blender with a
hard 1-bit alpha mask, the box silhouette has stair-step jagged edges.  This
script smooths the 0→255 alpha boundary by:

  1. Thresholding the alpha to a clean binary mask (removes pre-existing
     artifacts and semi-transparent noise from lossy-format re-exports).
  2. Applying a Gaussian blur to create a smooth sub-pixel edge gradient.
  3. Writing the result back (in-place by default, or to --output).

Usage::

    python tools/fix_template_alpha.py profiles/mvs/template.png
    python tools/fix_template_alpha.py profiles/mvs/template.png --radius 2.0
    python tools/fix_template_alpha.py profiles/mvs/template.png --output profiles/mvs/template_aa.png
    python tools/fix_template_alpha.py profiles/*/template.png          # all profiles

The RGB colour data is never modified — only the alpha channel is touched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageFilter
except ImportError:
    print("Requires: pip install Pillow numpy", file=sys.stderr)
    sys.exit(1)


def fix_alpha(
    template_path: Path,
    radius: float = 1.5,
    output_path: Path | None = None,
) -> None:
    """
    Anti-alias the alpha channel of *template_path* and write the result.

    Parameters
    ----------
    template_path:
        Input RGBA PNG (typically ``profiles/<name>/template.png``).
    radius:
        Gaussian blur radius in pixels applied to the alpha boundary.
        1.0–1.5 px is enough for sub-pixel smoothing; 2.0–3.0 px for
        templates rendered at low resolution or with heavy stair-stepping.
    output_path:
        Destination path.  Defaults to overwriting *template_path* in-place.
    """
    out = output_path or template_path

    img = Image.open(template_path).convert("RGBA")
    r, g, b, a = img.split()

    # Threshold → clean binary mask.
    # Any pixel with alpha > 128 is treated as fully opaque; the rest as
    # fully transparent.  This removes JPEG/WebP re-export artifacts and
    # ensures idempotency (running the script twice gives the same result).
    a_arr    = np.array(a, dtype=np.float32)
    a_binary = (a_arr > 128).astype(np.float32) * 255.0
    a_clean  = Image.fromarray(a_binary.astype(np.uint8), "L")

    # Blur the hard edge → smooth 0→255 gradient at the silhouette boundary.
    a_smooth = a_clean.filter(ImageFilter.GaussianBlur(radius=radius))

    result = Image.merge("RGBA", (r, g, b, a_smooth))
    result.save(str(out), "PNG", optimize=False)

    opaque_before = int((a_arr > 0).sum())
    opaque_after  = int((np.array(a_smooth) > 0).sum())
    print(f"✔  {out.name}")
    print(f"   radius={radius}px  |  "
          f"opaque pixels: {opaque_before:,} → {opaque_after:,}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Anti-alias the alpha channel of a Box3D template PNG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("templates", nargs="+", help="Path(s) to template.png")
    p.add_argument(
        "--radius", type=float, default=1.5,
        help="Gaussian blur radius in pixels (default: 1.5)",
    )
    p.add_argument(
        "--output",
        help="Output path — only valid when a single template is given",
    )
    args = p.parse_args()

    if args.output and len(args.templates) > 1:
        print("Error: --output can only be used with a single input file.", file=sys.stderr)
        sys.exit(1)

    output = Path(args.output) if args.output else None
    errors = 0

    for t in args.templates:
        path = Path(t)
        if not path.is_file():
            print(f"✘  Not found: {path}", file=sys.stderr)
            errors += 1
            continue
        try:
            fix_alpha(path, radius=args.radius, output_path=output)
        except Exception as exc:
            print(f"✘  {path.name}: {exc}", file=sys.stderr)
            errors += 1

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
