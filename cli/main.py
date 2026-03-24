"""
cli/main.py — Command-line interface
======================================
Entry point for all box3d CLI commands.

Commands::

    box3d render   --profile <n> [options]
    box3d profiles list
    box3d profiles validate
    box3d designer

PyInstaller notes
-----------------
Path resolution is split into two roots with different lifecycle semantics:

``_BUNDLE`` — read-only assets bundled with the executable (profiles/,
templates).  Resolves to ``sys._MEIPASS`` inside a frozen bundle and to
the project root during normal Python execution.

``_DATA`` — user-writable data directory (covers, output, marquees, logs).
Resolves to ``<directory of the executable>/data`` inside a frozen bundle
and to ``<project root>/data`` during normal Python execution.  This
directory is **never inside _MEIPASS**, so output files survive after the
process exits and the temp extraction directory is destroyed.

``_PROFILES`` — user-editable profiles directory, populated from the
bundle on the first run via ``_bootstrap_profiles()``.  Resolves to
``<directory of the executable>/profiles`` in a frozen bundle and to
``<project root>/profiles`` in development.  New built-in profiles added
in a later release are copied automatically; existing profiles are never
overwritten, preserving user edits.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


# ---------------------------------------------------------------------------
# Runtime path roots  (SUG-005)
# ---------------------------------------------------------------------------

def _bundle_dir() -> Path:
    """Read-only asset root.

    Frozen (PyInstaller --onefile): ``sys._MEIPASS`` — the temporary
    directory where the bundle is extracted at startup.

    Development / pip install: project root (two levels above ``cli/``),
    which contains ``profiles/``, ``engine/``, etc.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)           # type: ignore[attr-defined]
    return Path(__file__).parent.parent


def _data_dir() -> Path:
    """User-writable data root.

    Frozen (PyInstaller --onefile): ``<folder containing the exe>/data``.
    This folder is next to the binary and persists between runs.

    Development / pip install: ``<project root>/data``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return Path(__file__).parent.parent / "data"


_BUNDLE = _bundle_dir()   # profiles/, templates — read-only
_DATA   = _data_dir()     # covers, output, logs — writable


# ---------------------------------------------------------------------------
# Bootstrap (SUG-006) — create data/ tree on first run
# ---------------------------------------------------------------------------

def _bootstrap_data_dir() -> None:
    """Ensure the user-writable data tree exists.

    Creates the directory structure silently if absent.  All mkdir calls
    use ``exist_ok=True`` so the function is fully idempotent.

    Structure created::

        <_DATA>/
          inputs/
            covers/      <- drop cover images here
            marquees/    <- optional per-cover game marquees
          output/
            converted/   <- rendered 3-D box art written here
            temp/        <- pipeline temp files (auto-cleaned)
            logs/        <- log files when --log-file="" is used
    """
    for sub in (
        "inputs/covers",
        "inputs/marquees",
        "output/converted",
        "output/temp",
        "output/logs",
    ):
        (_DATA / sub).mkdir(parents=True, exist_ok=True)


def _bootstrap_profiles() -> Path:
    """Ensure an editable profiles/ directory exists next to the executable.

    In a frozen PyInstaller bundle:
      - Destination: ``<exe-dir>/profiles/``  (persistent, user-editable)
      - Source:      ``sys._MEIPASS/profiles/``  (read-only, inside the bundle)
      - First run:   the entire profiles/ tree is copied from the bundle.
      - Later runs:  only profile directories not yet present are added.
                     Existing profiles are **never overwritten**, preserving
                     any user edits to ``profile.json``, ``template.png``, or
                     ``assets/``.

    In development (not frozen):
      - Returns ``<project_root>/profiles/`` directly — no copying needed.

    Returns the path that should be used as the default ``--profiles-dir``.
    """
    if not getattr(sys, "frozen", False):
        return _BUNDLE / "profiles"          # dev: already on disk, editable

    dest = Path(sys.executable).parent / "profiles"
    src  = _BUNDLE / "profiles"              # sys._MEIPASS/profiles/

    if not dest.exists():
        # First run — copy the full bundled profiles/ tree
        shutil.copytree(str(src), str(dest))
        log_bootstrap = logging.getLogger("box3d.cli")
        log_bootstrap.info("profiles/ initialised at %s", dest)
    else:
        # Subsequent runs — add any new built-in profiles, skip existing ones
        log_bootstrap = logging.getLogger("box3d.cli")
        for profile_src in src.iterdir():
            if not profile_src.is_dir():
                continue
            profile_dest = dest / profile_src.name
            if not profile_dest.exists():
                shutil.copytree(str(profile_src), str(profile_dest))
                log_bootstrap.info("New built-in profile added: %s", profile_src.name)

    return dest


_PROFILES = _bootstrap_profiles()   # editable profiles/ — next to the exe


# ---------------------------------------------------------------------------
# Bootstrap — instructions.txt on first run
# ---------------------------------------------------------------------------

def _bootstrap_instructions() -> None:
    """Write instructions.txt next to the executable on first run only.

    The file is never overwritten — the user may edit or delete it freely.
    In development mode the file is written to the project root (harmless;
    add it to .gitignore if unwanted).
    """
    dest = _DATA.parent / "instructions.txt"
    if dest.exists():
        return

    version = "2.0.0"

    content = f"""\
box3d v{version} — Quick-Start Guide
{"=" * 52}

Generated automatically on first run. Edit freely — this file is never
overwritten by the application.

FOLDER STRUCTURE
----------------

  <this folder>/
  ├── box3d-linux-x64   (or box3d-windows-x64.exe)
  ├── instructions.txt  ← this file
  ├── profiles/         ← plugin profiles (edit freely, never overwritten)
  │   ├── mvs/
  │   │   ├── profile.json      geometry + spine layout
  │   │   ├── template.png      RGBA box art template
  │   │   └── assets/
  │   │       ├── logo_top.png       system logo — top of spine
  │   │       ├── logo_bottom.png    system logo — bottom of spine
  │   │       └── logo_game.png      fallback game logo (optional)
  │   ├── arcade/  (same structure)
  │   └── dvd/     (same structure)
  └── data/
      ├── inputs/
      │   ├── covers/       ← PUT YOUR COVER IMAGES HERE
      │   └── marquees/     ← per-game logos (matched by filename stem)
      └── output/
          ├── converted/    ← rendered 3-D box art appears here
          ├── temp/         ← auto-managed scratch space
          └── logs/         ← log files (use --log-file "")

FILE NAMING CONVENTIONS
-----------------------

  Cover images:   any name, any supported format
                  (WebP, PNG, JPG, JPEG, BMP, TIFF)

  Marquees:       <cover-stem>.<ext>
                  Example: cover sf2.webp → marquee sf2.png

  Game logo fallback (inside profile assets/):
                  logo_game.<ext>
                  Used when no matching marquee is found in data/inputs/marquees/

  System logos (inside profile assets/):
                  logo_top.<ext>
                  logo_bottom.<ext>

GLOBAL OPTIONS
--------------

  These flags apply to ALL commands and must be placed BEFORE the subcommand.

  box3d [global options] <command> [command options]

      --profiles-dir <dir>   Profiles directory to load from
                             Default: profiles/ next to the executable
                             Use this to load profiles from any external path.
                             Example: box3d --profiles-dir ~/my-profiles render -p ps2

      --verbose / -v         Enable DEBUG-level logging
      --log-file  <path>     Write log to file (pass "" for default location)

RENDER COMMAND — ALL OPTIONS
-----------------------------

  box3d render --profile <name> [options]

  REQUIRED
    -p, --profile <name>       Profile to use (mvs | arcade | dvd | custom)

  INPUT / OUTPUT
    -i, --input   <dir>        Cover images directory
                               Default: data/inputs/covers/
    -o, --output  <dir>        Output directory
                               Default: data/output/converted/
    -f, --output-format <fmt>  Output format: webp (default) | png

  SPINE APPEARANCE
    -b, --blur-radius <n>      Gaussian blur on spine background  (default: 20, must be >= 0)
    -d, --darken      <n>      Dark overlay intensity 0–255       (default: 180)
        --rgb <R,G,B>          RGB channel multipliers, comma-separated (default: 1.0,1.0,1.0)
                               Example: --rgb 1.1,1.0,0.9  (warm tone)
                               Values > 1 brighten, < 1 darken. Must be >= 0.
        --spine-source <edge>  Cover edge to sample: left | right | center
        --cover-fit    <mode>  Cover scaling: stretch | fit | crop

  LOGOS
        --no-logos             Disable all logo overlays
        --no-rotate            Force all logo rotations to 0°
        --top-logo    <file>   Override top spine logo
        --bottom-logo <file>   Override bottom spine logo
        --marquees-dir <dir>   Override marquees directory

  EXECUTION
    -w, --workers  <n>         Parallel render threads  (default: 4)
    -s, --skip-existing        Skip covers already rendered
        --dry-run              Validate inputs without writing output
    -v, --verbose              Enable DEBUG-level logging
        --log-file  <path>     Write log to file (pass "" for default location)

QUICK EXAMPLES
--------------

  # Render all covers with the MVS profile
  box3d render -p mvs

  # Arcade profile, 8 workers, PNG output, warm colour tone
  box3d render -p arcade -w 8 --output-format png --rgb 1.1,1.0,0.9

  # Preview run — no files written
  box3d render -p dvd --dry-run --verbose

  # Only process covers not yet rendered
  box3d render -p mvs --skip-existing

  # Custom spine: strong dark overlay, cool colour shift, crop-fit cover
  box3d render -p arcade --darken 220 --rgb 0.85,0.9,1.15 --cover-fit crop

OTHER COMMANDS
--------------

  box3d profiles list       List all available profiles with geometry info
  box3d profiles validate   Check each profile for missing files / OOM bounds
  box3d designer            Open the visual profile editor in the browser

ADDING A NEW PROFILE
--------------------

  1. Create a directory inside profiles/:
       profiles/myprofile/

  2. Add the required files:
       profile.json    — geometry and spine layout (see built-in examples)
       template.png    — RGBA box art template (max 8192 × 8192 px)

  3. Optionally add to profiles/myprofile/assets/:
       logo_top.png        system logo top of spine
       logo_bottom.png     system logo bottom of spine
       logo_game.png       fallback game logo

  4. Use the Designer Pro to adjust quad coordinates:
       box3d designer

  5. Test the new profile:
       box3d render -p myprofile --dry-run --verbose

The profile is available immediately — no restart required.

EXTERNAL / CUSTOM PROFILES
---------------------------

  You can store profiles anywhere on your system and point box3d to them
  using the --profiles-dir global flag:

    box3d --profiles-dir /path/to/my-profiles render -p myprofile

  This is useful when:
  - You want profiles on a shared or network drive
  - You are using the standalone executable and prefer to keep profiles
    in a separate folder that survives updates
  - You maintain multiple profile sets for different systems

  Copy a built-in profile as a starting point:

    cp -r profiles/mvs /path/to/my-profiles/ps2
    # edit /path/to/my-profiles/ps2/profile.json and template.png
    box3d --profiles-dir /path/to/my-profiles render -p ps2

  Windows example:
    box3d-windows-x64.exe --profiles-dir C:\\MyProfiles render -p ps2
"""

    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as exc:
        logging.getLogger("box3d.cli").debug(
            "Could not write instructions.txt: %s", exc
        )


# ---------------------------------------------------------------------------
# Imports that depend on path roots being set
# ---------------------------------------------------------------------------

from core.models    import RenderOptions                    # noqa: E402
from core.registry  import ProfileRegistry, ProfileError    # noqa: E402

log = logging.getLogger("box3d.cli")


# ---------------------------------------------------------------------------
# RGB parser
# ---------------------------------------------------------------------------

def parse_rgb_str(rgb_str: str) -> str | None:
    """Convert ``"R,G,B"`` to the diagonal matrix string used by
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
  box3d render -p arcade -w 8 --rgb 1.1,1.0,0.9
  box3d --profiles-dir ~/my-profiles render -p ps2
  box3d profiles list
  box3d designer
"""
    )

    # Global arguments
    parser.add_argument(
        "--profiles-dir",
        default=str(_PROFILES),
        help="Path to profiles directory (default: profiles/ next to the executable)",
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Path to write log file (pass '' for default location)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- Render Command ---
    render_p = subparsers.add_parser("render", help="Render covers using a profile")

    render_p.add_argument("--profile", "-p", required=True,
                          help="Profile name (e.g. mvs, arcade, dvd)")

    # I/O — defaults derived from _DATA so they work in the bundle
    render_p.add_argument("--input", "-i", type=str,
                          help=f"Input directory containing covers "
                               f"(default: <data>/inputs/covers)")
    render_p.add_argument("--output", "-o", type=str,
                          help="Output directory (default: <data>/output/converted)")
    render_p.add_argument("--temp", type=str,
                          help="(Legacy) Temp directory path")

    # Visual Modifiers
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

    # Logos
    render_p.add_argument("--no-rotate", "-r", action="store_true",
                          help="Force all logo rotations to 0 degrees")
    render_p.add_argument("--no-logos", "-l", action="store_true",
                          help="Disable all logo overlays")
    render_p.add_argument("--top-logo",    type=str,
                          help="Path to top spine logo override")
    render_p.add_argument("--bottom-logo", type=str,
                          help="Path to bottom spine logo override")
    render_p.add_argument("--marquees-dir", type=str,
                          help="Directory containing game marquees "
                               "(default: <data>/inputs/marquees)")

    # Execution Modifiers
    render_p.add_argument("--output-format", "-f", choices=["webp", "png"],
                          default="webp", help="Output format")
    render_p.add_argument("--skip-existing", "-s", action="store_true",
                          help="Skip already rendered covers")
    render_p.add_argument("--workers", "-w", type=int, default=4,
                          help="Number of parallel workers")
    render_p.add_argument("--dry-run", action="store_true",
                          help="Simulate pipeline without rendering")

    # --- Profiles Command ---
    prof_p = subparsers.add_parser("profiles", help="Manage profiles")
    prof_p.add_argument("profiles_cmd", choices=["list", "validate"],
                        help="Profile action")

    # --- Designer Command ---
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
        # Empty string -> use the default location inside _DATA
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


def cmd_render(args: argparse.Namespace, registry: ProfileRegistry) -> int:
    try:
        profile = registry.get(args.profile)
    except KeyError as exc:
        log.error("%s", exc)
        return 1

    # All default I/O paths derived from _DATA (writable) — never from _BUNDLE (SUG-005)
    covers_dir = Path(args.input)  if args.input  else _DATA / "inputs"  / "covers"
    output_dir = Path(args.output) if args.output else _DATA / "output"  / "converted"
    temp_dir   = Path(args.temp)   if args.temp   else _DATA / "output"  / "temp"

    # --- CLI UX Hardening: Fail Fast & Boundaries ---
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
    # ------------------------------------------------

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
    stats = pipeline.run()
    return 0 if stats.get("error", 0) == 0 else 1


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

        # 1. Template file presence
        if not prof.template_path.exists():
            log.error("  [%s] template NOT FOUND: %s", name, prof.template_path)
            errors += 1
        else:
            log.info("  [%s] template OK  (%s)", name, prof.template_path.name)

        # 2. OOM dimension guard (belt-and-suspenders — __post_init__ checks at load time)
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
    _bootstrap_data_dir()          # create data/ tree if absent (idempotent)
    _bootstrap_instructions()      # write instructions.txt on first run only
    # _PROFILES already populated at import time via _bootstrap_profiles()

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
        # tools/box3d_designer_pro/index.html is a static HTML tool.
        # In the bundle it lives under _BUNDLE; in development, under the project root.
        # Opening via webbrowser requires no Python runtime inside the tool.
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