"""
cli/main.py — Command-line interface
======================================
Entry point for all box3d CLI commands.

Commands::

    box3d render   --profile <name> [options]
    box3d profiles list
    box3d profiles validate
    box3d designer
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# Project root (two levels up from cli/)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core.models    import RenderOptions
from core.registry  import ProfileRegistry, ProfileError
from engine.compositor import parse_rgb_str

log = logging.getLogger("box3d.cli")


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="box3d",
        description="box3d — Arcade game 3D box art generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  render            Render covers using a profile
  profiles list     List all loaded profiles
  profiles validate Validate all profiles
  designer          Launch Box3D Designer Pro

Examples:
  box3d render --profile mvs
  box3d render --profile arcade --workers 8 --rgb 1.15,1.0,0.85
  box3d profiles list
  box3d designer
""",
    )
    parser.add_argument(
        "--profiles-dir", default=str(_ROOT / "profiles"),
        metavar="DIR",
        help="Profiles directory (default: profiles/)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    parser.add_argument(
        "--log-file", nargs="?", const="", default=None, metavar="PATH",
        help="Enable file logging (omit PATH for default location)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── render ──────────────────────────────────────────────────────────
    rp = sub.add_parser("render", help="Render covers using a profile")
    rp.add_argument("--profile",   "-p", required=True, metavar="NAME",
                    help="Profile name (must exist in profiles/)")
    rp.add_argument("--input",     "-i", default=None, metavar="DIR",
                    help="Cover images directory (default: data/inputs/covers/)")
    rp.add_argument("--output",    "-o", default=None, metavar="DIR",
                    help="Output directory (default: data/output/converted/)")
    rp.add_argument("--temp",      default=None, metavar="DIR")
    rp.add_argument("--workers",   "-w", type=int, default=4, metavar="N")
    rp.add_argument("--blur-radius",  "-b", type=int, default=20, metavar="N")
    rp.add_argument("--darken",    "-d", type=int, default=180, metavar="0-255")
    rp.add_argument("--rgb",       default=None, metavar="R,G,B")
    rp.add_argument("--cover-fit", choices=["stretch","fit","crop"], default=None)
    rp.add_argument("--spine-source", choices=["left","right","center"], default=None)
    rp.add_argument("--no-rotate", action="store_true")
    rp.add_argument("--no-logos",  action="store_true")
    rp.add_argument("--top-logo",    default=None, metavar="PATH")
    rp.add_argument("--bottom-logo", default=None, metavar="PATH")
    rp.add_argument("--marquees-dir", default=None, metavar="DIR")
    rp.add_argument("--output-format", choices=["webp","png"], default="webp")
    rp.add_argument("--skip-existing", action="store_true")
    rp.add_argument("--dry-run", action="store_true")

    # ── profiles ────────────────────────────────────────────────────────
    pp = sub.add_parser("profiles", help="Profile management commands")
    pp_sub = pp.add_subparsers(dest="profiles_cmd", metavar="SUBCOMMAND")
    pp_sub.add_parser("list",     help="List all available profiles")
    pp_sub.add_parser("validate", help="Validate all profiles")

    # ── designer ────────────────────────────────────────────────────────
    sub.add_parser("designer", help="Launch Box3D Designer Pro in the browser")

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_render(args: argparse.Namespace, registry: ProfileRegistry) -> int:
    try:
        profile = registry.get(args.profile)
    except KeyError as exc:
        log.error("%s", exc)
        return 1

    data_root = _ROOT / "data"
    covers_dir = Path(args.input)  if args.input  else data_root / "inputs" / "covers"
    output_dir = Path(args.output) if args.output else data_root / "output" / "converted"
    temp_dir   = Path(args.temp)   if args.temp   else data_root / "output" / "temp"

    # Validate numeric ranges
    if not (0 <= args.darken <= 255):
        log.error("--darken %d is outside 0–255", args.darken)
        return 1
    if args.blur_radius < 0:
        log.error("--blur-radius %d must be >= 0", args.blur_radius)
        return 1

    rgb_matrix = parse_rgb_str(args.rgb) if args.rgb else None

    logo_paths: dict[str, Path | None] = {
        "top":    None,
        "bottom": None,
    }
    if not args.no_logos:
        if args.top_logo:
            logo_paths["top"] = Path(args.top_logo)
        else:
            logo_paths["top"] = _auto_logo(profile.root / "assets", "logo_top")

        if args.bottom_logo:
            logo_paths["bottom"] = Path(args.bottom_logo)
        else:
            logo_paths["bottom"] = _auto_logo(profile.root / "assets", "logo_bottom")

    marquees_dir = (
        Path(args.marquees_dir) if args.marquees_dir
        else _ROOT / "data" / "inputs" / "marquees"
    )

    options = RenderOptions(
        blur_radius   = args.blur_radius,
        darken_alpha  = args.darken,
        rgb_matrix    = rgb_matrix,
        cover_fit     = args.cover_fit,
        spine_source  = args.spine_source,
        rotate_logos  = False if args.no_rotate else None,
        with_logos    = not args.no_logos,
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
    stats = pipeline.run()
    return 0 if stats.get("error", 0) == 0 else 1


def cmd_profiles_list(registry: ProfileRegistry) -> int:
    names = registry.names()
    if not names:
        print("No profiles loaded.")
        return 0
    print(f"\n  {len(names)} profile(s) available:\n")
    for name in names:
        p = registry.get(name)
        g = p.geometry
        print(f"  ● {name:<20} "
              f"template: {g.template_w}×{g.template_h}  "
              f"spine: {g.spine_w}×{g.spine_h}")
    print()
    return 0


def cmd_profiles_validate(registry: ProfileRegistry) -> int:
    errors = 0
    for profile in registry.all():
        if not profile.template_path.exists():
            print(f"  ✘  {profile.name}: template.png not found")
            errors += 1
        else:
            print(f"  ✔  {profile.name}: OK")
    return 0 if errors == 0 else 1


def cmd_designer() -> int:
    designer = _ROOT / "tools" / "box3d_designer_pro" / "index.html"
    if not designer.exists():
        log.error("Designer not found: %s", designer)
        return 1
    import webbrowser
    webbrowser.open(designer.as_uri())
    print(f"  Opened: {designer}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_logo(assets_dir: Path, stem: str) -> Path | None:
    """Look for a logo file matching *stem* in *assets_dir*."""
    if not assets_dir.is_dir():
        return None
    exts = {".png", ".jpg", ".webp", ".jpeg"}
    for f in sorted(assets_dir.iterdir()):
        if f.stem.lower() == stem.lower() and f.suffix.lower() in exts:
            return f
    return None


def _setup_logging(verbose: bool, log_file: str | None, root: Path) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = logging.Formatter(
        "%(asctime)s | %(name)-22s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    root_log = logging.getLogger("box3d")
    root_log.setLevel(logging.DEBUG)
    root_log.propagate = False

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
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
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    _setup_logging(args.verbose, args.log_file, _ROOT)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Load registry for commands that need it
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
        else:
            parser.parse_args(["profiles", "--help"])

    elif args.command == "designer":
        sys.exit(cmd_designer())


if __name__ == "__main__":
    main()
