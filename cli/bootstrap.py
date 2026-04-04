"""
cli/bootstrap.py — Runtime path resolution and first-run bootstrap
===================================================================
Handles two concerns that must be resolved before any other import:

1. **Path roots** — ``_BUNDLE`` (read-only assets) and ``_DATA``
   (user-writable data directory) with correct semantics for both
   PyInstaller frozen bundles and normal Python execution.

2. **First-run bootstrap** — create the ``data/`` directory tree,
   copy profiles next to the executable, and write ``instructions.txt``.

All public symbols are re-exported from ``cli.main`` so callers do not
need to import from this module directly.
"""

from __future__ import annotations

import logging
import shutil
import sys
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

_INSTRUCTIONS_TEMPLATE = Path(__file__).parent / "instructions_template.txt"
_VERSION = "2.0.0"


def _bootstrap_instructions() -> None:
    """Write instructions.txt next to the executable on first run only.

    The file is never overwritten — the user may edit or delete it freely.
    In development mode the file is written to the project root (harmless;
    add it to .gitignore if unwanted).
    """
    dest = _DATA.parent / "instructions.txt"
    if dest.exists():
        return

    try:
        content = _INSTRUCTIONS_TEMPLATE.read_text(encoding="utf-8")
        content = content.replace("{{VERSION}}", _VERSION)
        dest.write_text(content, encoding="utf-8")
    except OSError as exc:
        logging.getLogger("box3d.cli").debug(
            "Could not write instructions.txt: %s", exc
        )
