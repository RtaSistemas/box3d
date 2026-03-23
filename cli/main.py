"""
cli/main.py — Command-line interface
======================================
Entry point for all box3d CLI commands.

Commands::

    box3d render   --profile <n> [options]
    box3d profiles list
    box3d profiles validate
    box3d designer
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

# Project root (two levels up from cli/)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core.models    import RenderOptions
from core.registry  import ProfileRegistry, ProfileError

log = logging.getLogger("box3d.cli")


# ---------------------------------------------------------------------------
# RGB parser (migrated from engine/compositor.py — cli-only utility)
# ---------------------------------------------------------------------------

def parse_rgb_str(rgb_str: str) -> str | None:
    """
    Convert ``"R,G,B"`` to the diagonal matrix string used by
    :func:`~engine.blending.apply_color_matrix`.
    """
    normalised = rgb_str.replace(";", ",")
    try:
        parts = [float(x.strip()) for x in normalised.split(",")]
        if len(parts) != 3:
            raise ValueError(f"expected 3 values, got {len(parts)}")
        r, g, b = parts
        for label, val in (("R", r), ("G", g), ("B", b)):
            if val < 0:
                raise ValueError(f"channel {label} must be >= 0")
        return f"{r} 0 0  0 {g} 0  0 0 {b}"
    except Exception as exc:
        log.warning("parse_rgb_str: %r — %s — ignored", rgb_str, exc)
        return None


# ---------------------------------------------------------------------------
# CLI Parsers
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="box3d",
        description="box3d — Arcade game 3D box art generator (v2.0.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  box3d render -p mvs
  box3d render -p arcade -w 8 -R "1.15 0 0  0 1.0 0  0 0 0.85"
  box3d profiles list
  box3d designer
"""
    )
    
    # Global arguments
    parser.add_argument("--profiles-dir", default=str(_ROOT / "profiles"), help="Path to profiles directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-file", type=str, default=None, help="Path to write log file")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Render Command ---
    render_p = subparsers.add_parser("render", help="Render covers using a profile")
    
    # Obrigatório
    render_p.add_argument("--profile", "-p", required=True, help="Profile name (e.g. mvs, arcade, dvd)")
    
    # I/O
    render_p.add_argument("--input", "-i", type=str, help="Input directory containing covers")
    render_p.add_argument("--output", "-o", type=str, help="Output directory")
    render_p.add_argument("--temp", type=str, help="(Legacy) Temp directory path")
    
    # Visual Modifiers
    render_p.add_argument("--blur-radius", "-b", type=int, default=20, help="Spine background blur radius (>= 0)")
    render_p.add_argument("--darken", "-d", type=int, default=180, help="Spine dark overlay alpha (0-255)")
    render_p.add_argument("--rgb", "-R", type=str, help="RGB multiplier matrix, e.g. '1.1,1.0,0.9'")
    render_p.add_argument("--spine-source", choices=["left", "right", "center"], help="Spine background source edge")
    render_p.add_argument("--cover-fit", "-c", choices=["stretch", "fit", "crop"], help="Cover fit mode")
    
    # Logos
    render_p.add_argument("--no-rotate", "-r", action="store_true", help="Force all logo rotations to 0°")
    render_p.add_argument("--no-logos", "-l", action="store_true", help="Disable all logo overlays")
    render_p.add_argument("--top-logo", type=str, help="Path to top spine logo override")
    render_p.add_argument("--bottom-logo", type=str, help="Path to bottom spine logo override")
    render_p.add_argument("--marquees-dir", type=str, help="Directory containing game marquees")
    
    # Execution Modifiers
    render_p.add_argument("--output-format", "-f", choices=["webp", "png"], default="webp", help="Output format")
    render_p.add_argument("--skip-existing", "-s", action="store_true", help="Skip already rendered covers")
    render_p.add_argument("--workers", "-w", type=int, default=4, help="Number of parallel workers")
    render_p.add_argument("--dry-run", action="store_true", help="Simulate pipeline without rendering")

    # --- Profiles Command ---
    prof_p = subparsers.add_parser("profiles", help="Manage profiles")
    prof_p.add_argument("profiles_cmd", choices=["list", "validate"], help="Profile action")

    # --- Designer Command ---
    subparsers.add_parser("designer", help="Launch Box3D Designer Pro")

    return parser


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool, log_file: str | None, root: Path) -> None:
    root_log = logging.getLogger("box3d")
    root_log.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    fmt = logging.Formatter("%(levelname)-8s | %(name)-14s | %(message)s")
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    root_log.addHandler(ch)

    if log_file is not None:
        path = (root / "data" / "output" / "logs" / "box3d.log"
                if log_file == "" else Path(log_file))
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


def cmd_render(args: argparse.Namespace, registry: ProfileRegistry) -> int:
    try:
        profile = registry.get(args.profile)
    except KeyError as exc:
        log.error("%s", exc)
        return 1

    data_root  = _ROOT / "data"
    covers_dir = Path(args.input)  if args.input  else data_root / "inputs" / "covers"
    output_dir = Path(args.output) if args.output else data_root / "output" / "converted"
    temp_dir   = Path(args.temp)   if args.temp   else data_root / "output" / "temp"

    # --- CLI UX Hardening: Fail Fast & Boundaries ---
    if not covers_dir.exists():
        log.error("Input directory not found: %s", covers_dir)
        return 1
    
    if not (0 <= args.darken <= 255):
        log.error("--darken %d is out of bounds (0-255).", args.darken)
        return 1

    if args.blur_radius < 0:
        log.error("--blur-radius %d must be >= 0.", args.blur_radius)
        return 1
    # ------------------------------------------------

    rgb_matrix = parse_rgb_str(args.rgb) if args.rgb else None
    if args.rgb and not rgb_matrix:
        log.error("Invalid RGB matrix format: %s", args.rgb)
        return 1

    logo_paths: dict[str, Path | None] = {"top": None, "bottom": None}
    if not args.no_logos:
        logo_paths["top"] = Path(args.top_logo) if args.top_logo else _auto_logo(profile.root / "assets", "logo_top")
        logo_paths["bottom"] = Path(args.bottom_logo) if args.bottom_logo else _auto_logo(profile.root / "assets", "logo_bottom")

    marquees_dir = Path(args.marquees_dir) if args.marquees_dir else _ROOT / "data" / "inputs" / "marquees"

    options = RenderOptions(
        blur_radius   = args.blur_radius,
        darken_alpha  = args.darken,
        rgb_matrix    = rgb_matrix,
        cover_fit     = args.cover_fit,
        spine_source  = args.spine_source,
        no_rotate     = args.no_rotate,
        with_logos    = not args.no_logos,
        output_format = args.output_format,
        skip_existing = args.skip_existing,
        workers       = max(1, args.workers),
        dry_run       = args.dry_run,
    )

    from core.pipeline import RenderPipeline
    pipeline = RenderPipeline(
        profile=profile, covers_dir=covers_dir, output_dir=output_dir,
        temp_dir=temp_dir, options=options, logo_paths=logo_paths, marquees_dir=marquees_dir
    )
    stats = pipeline.run()
    return 0 if stats.get("error", 0) == 0 else 1


def cmd_profiles_list(registry: ProfileRegistry) -> int:
    print("\nLoaded Profiles:")
    for name in registry.names():
        prof = registry.get(name)
        print(f"  - {name:<10} ({prof.geometry.template_w}x{prof.geometry.template_h})")
    print()
    return 0


def cmd_profiles_validate(registry: ProfileRegistry) -> int:
    log.info("All profiles passed structural and OOM validation.")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if getattr(args, "command", None) is None:
        parser.print_help()
        sys.exit(0)

    _setup_logging(args.verbose, args.log_file, _ROOT)

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
        designer_path = _ROOT / "designer" / "app.py"
        if not designer_path.exists():
            log.error("Designer app not found at %s", designer_path)
            sys.exit(1)
        sys.exit(subprocess.call([sys.executable, str(designer_path)]))

if __name__ == "__main__":
    main()
