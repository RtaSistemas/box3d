"""
cli/main.py — Command-line interface
======================================
Entry point for all box3d CLI commands (render, profiles, designer).

Path resolution and first-run bootstrap are handled by :mod:`cli.bootstrap`.
Shared utilities live in :mod:`cli.utils`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

from cli.bootstrap import (
    _BUNDLE, _DATA, _PROFILES,
    _bootstrap_data_dir, _bootstrap_instructions,
)
from cli.utils import parse_rgb_str
from core.models   import CoverResult, RenderOptions, RenderSummary
from core.registry import ProfileRegistry, ProfileError

log = logging.getLogger("box3d.cli")


# ---------------------------------------------------------------------------
# CLI Parsers
# ---------------------------------------------------------------------------

def _workers_type(value: str) -> int:
    """argparse type for --workers: accepts a positive integer or 'auto'."""
    if value == "auto":
        return os.cpu_count() or 1
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid workers value: '{value}'")
    if n < 1:
        raise argparse.ArgumentTypeError("--workers must be >= 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="box3d",
        description="box3d — Arcade game 3D box art generator (v2.0.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  box3d render -p mvs
  box3d render -p arcade -w 8 --rgb 1.1,1.0,0.9
  box3d --profiles-dir ~/my-profiles render -p ps2
  box3d profiles list
  box3d designer
"""
    )

    parser.add_argument(
        "--profiles-dir", default=str(_PROFILES),
        help="Path to profiles directory (default: profiles/ next to the executable)",
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Path to write log file (pass '' for default location)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Render ---
    render_p = subparsers.add_parser("render", help="Render covers using a profile")
    render_p.add_argument("--profile", "-p", required=True,
                          help="Profile name (e.g. mvs, arcade, dvd)")
    render_p.add_argument("--input", "-i", type=str,
                          help="Input directory containing covers (default: <data>/inputs/covers)")
    render_p.add_argument("--output", "-o", type=str,
                          help="Output directory (default: <data>/output/converted)")
    render_p.add_argument("--temp", type=str, help="(Legacy) Temp directory path")
    render_p.add_argument("--blur-radius", "-b", type=int, default=20,
                          help="Spine background blur radius (>= 0)")
    render_p.add_argument("--darken", "-d", type=int, default=180,
                          help="Spine dark overlay alpha (0-255)")
    render_p.add_argument("--rgb", "-R", type=str,
                          help="RGB multiplier matrix, e.g. '1.1,1.0,0.9'")
    render_p.add_argument("--spine-source", choices=["left", "right", "center"],
                          help="Spine background source edge")
    render_p.add_argument("--cover-fit", "-c", choices=["stretch", "fit", "crop"],
                          help="Cover fit mode")
    render_p.add_argument("--no-rotate", "-r", action="store_true",
                          help="Force all logo rotations to 0 degrees")
    render_p.add_argument("--no-logos", "-l", action="store_true",
                          help="Disable all logo overlays")
    render_p.add_argument("--top-logo",    type=str,
                          help="Path to top spine logo override")
    render_p.add_argument("--bottom-logo", type=str,
                          help="Path to bottom spine logo override")
    render_p.add_argument("--marquees-dir", type=str,
                          help="Directory containing game marquees (default: <data>/inputs/marquees)")
    render_p.add_argument("--output-format", "-f", choices=["webp", "png"],
                          default="webp", help="Output format")
    render_p.add_argument("--skip-existing", "-s", action="store_true",
                          help="Skip already rendered covers")
    render_p.add_argument("--workers", "-w", type=_workers_type, default=4,
                          help="Number of parallel workers, or 'auto' to use os.cpu_count()")
    render_p.add_argument("--dry-run", action="store_true",
                          help="Simulate pipeline without rendering")

    # --- Profiles ---
    prof_p = subparsers.add_parser("profiles", help="Manage profiles")
    prof_p.add_argument("profiles_cmd", choices=["list", "validate"],
                        help="Profile action")

    # --- Designer ---
    subparsers.add_parser("designer",
                          help="Open Box3D Designer Pro in the default browser")

    return parser


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool, log_file: str | None) -> None:
    root_log = logging.getLogger("box3d")
    root_log.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter("%(levelname)-8s | %(name)-14s | %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    root_log.addHandler(ch)

    if log_file is not None:
        path = (
            _DATA / "output" / "logs" / "box3d.log"
            if log_file == ""
            else Path(log_file)
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root_log.addHandler(fh)


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

def _auto_logo(assets_dir: Path, stem: str) -> Path | None:
    """Find a logo file by stem (e.g. 'logo_top') in the assets directory."""
    for ext in [".png", ".webp"]:
        p = assets_dir / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def print_summary(report: RenderSummary, output_dir: Path) -> None:
    """Print the render summary to the terminal, keeping the same format as before."""
    processed = report.succeeded + report.failed
    log.info("-" * 62)
    log.info("SUMMARY")
    log.info("  Total     : %d", report.total)
    log.info("  Succeeded : %d", report.succeeded)
    log.info("  Skipped   : %d", report.skipped)
    log.info("  Errors    : %d", report.failed)
    log.info("  Dry-run   : %d", report.dry)
    if report.breaker_tripped:
        log.info("  Breaker   : TRIPPED — execution was aborted")
    log.info("  Time      : %.2fs  (~%.2fs/image processed)",
             report.elapsed_time, report.elapsed_time / max(processed, 1))
    log.info("  Output    : %s", output_dir)
    log.info("-" * 62)
    if report.failed:
        log.warning("%d error(s) — check the log for details", report.failed)


def cmd_render(args: argparse.Namespace, registry: ProfileRegistry) -> int:
    try:
        profile = registry.get(args.profile)
    except KeyError as exc:
        log.error("%s", exc)
        return 1

    covers_dir = Path(args.input)  if args.input  else _DATA / "inputs"  / "covers"
    output_dir = Path(args.output) if args.output else _DATA / "output"  / "converted"
    temp_dir   = Path(args.temp)   if args.temp   else _DATA / "output"  / "temp"

    if not covers_dir.exists():
        log.error("Input directory not found: %s", covers_dir)
        log.error("Drop your cover images there, or pass --input to specify a different path.")
        return 1

    if not (0 <= args.darken <= 255):
        log.error("--darken %d is out of bounds (0-255).", args.darken)
        return 1

    if args.blur_radius < 0:
        log.error("--blur-radius %d must be >= 0.", args.blur_radius)
        return 1

    rgb_matrix = parse_rgb_str(args.rgb) if args.rgb else None
    if args.rgb and not rgb_matrix:
        log.error("Invalid RGB matrix format: %s", args.rgb)
        return 1

    logo_paths: dict[str, Path | None] = {"top": None, "bottom": None}
    if not args.no_logos:
        logo_paths["top"] = (
            Path(args.top_logo)    if args.top_logo
            else _auto_logo(profile.root / "assets", "logo_top")
        )
        logo_paths["bottom"] = (
            Path(args.bottom_logo) if args.bottom_logo
            else _auto_logo(profile.root / "assets", "logo_bottom")
        )

    marquees_dir = (
        Path(args.marquees_dir) if args.marquees_dir
        else _DATA / "inputs" / "marquees"
    )

    options = RenderOptions(
        blur_radius   = args.blur_radius,
        darken_alpha  = args.darken,
        rgb_matrix    = rgb_matrix,
        cover_fit     = args.cover_fit,
        spine_source  = args.spine_source,
        no_rotate     = args.no_rotate,
        output_format = args.output_format,
        skip_existing = args.skip_existing,
        workers       = max(1, args.workers),
        dry_run       = args.dry_run,
    )

    from core.pipeline import RenderPipeline
    pipeline = RenderPipeline(
        profile      = profile,
        covers_dir   = covers_dir,
        output_dir   = output_dir,
        temp_dir     = temp_dir,
        options      = options,
        logo_paths   = logo_paths,
        marquees_dir = marquees_dir,
    )

    _progress_shown = False

    def _on_progress(done: int, total: int, result: CoverResult) -> None:
        nonlocal _progress_shown
        _progress_shown = True
        pct = int(done / total * 100)
        print(f"\r  Progress: {done}/{total}  [{pct:3d}%]", end="", flush=True)

    report = pipeline.run(on_progress=_on_progress)

    if _progress_shown:
        print()  # close the \r line

    print_summary(report, output_dir)
    return 0 if report.failed == 0 else 1


def cmd_profiles_list(registry: ProfileRegistry) -> int:
    print("\nLoaded Profiles:")
    for name in registry.names():
        prof = registry.get(name)
        print(f"  - {name:<10} ({prof.geometry.template_w}x{prof.geometry.template_h})"
              f"  template: {prof.template_path}")
    print()
    return 0


def cmd_profiles_validate(registry: ProfileRegistry) -> int:
    """Validate every loaded profile: template exists + geometry within OOM bounds."""
    errors = 0
    for name in registry.names():
        prof = registry.get(name)
        g    = prof.geometry

        if not prof.template_path.exists():
            log.error("  [%s] template NOT FOUND: %s", name, prof.template_path)
            errors += 1
        else:
            log.info("  [%s] template OK  (%s)", name, prof.template_path.name)

        for label, w, h in (
            ("template", g.template_w, g.template_h),
            ("spine",    g.spine_w,    g.spine_h),
            ("cover",    g.cover_w,    g.cover_h),
        ):
            if w > 8192 or h > 8192:
                log.error("  [%s] %s dimension %dx%d exceeds 8192px OOM limit",
                          name, label, w, h)
                errors += 1
            else:
                log.info("  [%s] %s OK  (%dx%d)", name, label, w, h)

    if errors:
        log.error("Validation FAILED: %d error(s) across %d profile(s).",
                  errors, len(registry))
        return 1

    log.info("All %d profile(s) passed validation.", len(registry))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _bootstrap_data_dir()
    _bootstrap_instructions()

    parser = build_parser()
    args   = parser.parse_args()

    if getattr(args, "command", None) is None:
        parser.print_help()
        sys.exit(0)

    _setup_logging(args.verbose, args.log_file)

    registry = None
    if args.command in ("render", "profiles"):
        try:
            registry = ProfileRegistry(args.profiles_dir).load()
        except ProfileError as exc:
            log.error("Cannot load profiles: %s", exc)
            sys.exit(1)

    if args.command == "render":
        sys.exit(cmd_render(args, registry))

    elif args.command == "profiles":
        if args.profiles_cmd == "list":
            sys.exit(cmd_profiles_list(registry))
        elif args.profiles_cmd == "validate":
            sys.exit(cmd_profiles_validate(registry))

    elif args.command == "designer":
        designer_path = _BUNDLE / "tools" / "box3d_designer_pro" / "index.html"
        if not designer_path.exists():
            log.error("Designer not found: %s", designer_path)
            log.error("Ensure tools/box3d_designer_pro/index.html exists "
                      "and that the release was built with --add-data for tools/.")
            sys.exit(1)
        webbrowser.open(designer_path.as_uri())
        log.info("Designer opened in browser.")


if __name__ == "__main__":
    main()
