"""
cli/diagnostics.py — pyvips runtime diagnostic report
=======================================================
Writes a self-contained text report to data/output/logs/ on every startup
so that pyvips loading failures can be diagnosed without source access.

Captured information
---------------------
* Python / OS / architecture
* PyInstaller frozen state, sys._MEIPASS contents (DLLs at bundle root)
* pyvips package directory contents inside the bundle
* sys.path and PATH environment variable
* ctypes direct DLL load attempt (libvips-42.dll / libvips.so.42)
* ctypes.util.find_library('vips') result
* Full traceback of pyvips import failure (if applicable)
* WARP_BACKEND_LABEL confirming which backend is active
"""

from __future__ import annotations

import ctypes
import importlib.util
import logging
import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("box3d.cli")


def write_pyvips_diagnostic(log_dir: Path) -> Path:
    """
    Write a detailed pyvips diagnostic to *log_dir*/pyvips_diagnostic_<ts>.log.

    Always writes (success and failure) so both states are archived.
    Returns the path of the written file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = log_dir / f"pyvips_diagnostic_{ts}.log"

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    # ------------------------------------------------------------------ header
    w("=" * 70)
    w(f"box3d pyvips diagnostic  —  {datetime.now().isoformat()}")
    w("=" * 70)
    w()

    # ------------------------------------------------------------ platform info
    w("[PLATFORM]")
    w(f"  Python       : {sys.version}")
    w(f"  Platform     : {platform.platform()}")
    w(f"  Machine      : {platform.machine()}")
    w(f"  Architecture : {' / '.join(platform.architecture())}")
    w(f"  OS           : {os.name}")
    w()

    # --------------------------------------------------------- PyInstaller state
    frozen  = getattr(sys, "frozen", False)
    meipass = getattr(sys, "_MEIPASS", None)
    w("[PYINSTALLER]")
    w(f"  sys.frozen     : {frozen}")
    w(f"  sys.executable : {sys.executable}")
    w(f"  sys._MEIPASS   : {meipass}")
    w()

    # ------------------------------------------------------- bundle root listing
    if meipass:
        meipass_path = Path(meipass)
        w("[BUNDLE ROOT  (sys._MEIPASS)]")
        try:
            all_items = sorted(meipass_path.iterdir())
            dlls      = [f for f in all_items if f.suffix.lower() == ".dll"]
            others    = [f for f in all_items if f.suffix.lower() != ".dll"]
            w(f"  Total entries  : {len(all_items)}")
            w(f"  DLLs at root   : {len(dlls)}")
            for d in sorted(dlls, key=lambda f: f.name.lower()):
                w(f"    {d.name:<40}  {d.stat().st_size:>10,} bytes")
            vips_dlls = [d for d in dlls if "vips" in d.name.lower()]
            w(f"  vips-related   : {len(vips_dlls)}")
            for d in vips_dlls:
                w(f"    *** {d.name}")
            w(f"  Other entries  : {len(others)}")
            for o in others[:30]:
                w(f"    {o.name}")
            if len(others) > 30:
                w(f"    ... and {len(others) - 30} more")
        except Exception as exc:
            w(f"  ERROR listing MEIPASS: {exc}")
        w()

        # ------------------------------------------------------ pyvips/ subdir
        pyvips_bundle_dir = meipass_path / "pyvips"
        w("[BUNDLE  pyvips/  SUBDIRECTORY]")
        if pyvips_bundle_dir.exists():
            try:
                pv_files = sorted(pyvips_bundle_dir.iterdir())
                pv_dlls  = [f for f in pv_files if f.suffix.lower() == ".dll"]
                pv_ext   = [f for f in pv_files if f.suffix.lower() in (".so", ".pyd")]
                pv_py    = [f for f in pv_files if f.suffix.lower() == ".py"]
                w(f"  Exists     : YES  ({len(pv_files)} files)")
                w(f"  DLLs       : {len(pv_dlls)}")
                for d in pv_dlls:
                    w(f"    {d.name}")
                w(f"  .so / .pyd : {len(pv_ext)}")
                for s in pv_ext:
                    w(f"    {s.name}")
                w(f"  .py files  : {len(pv_py)}")
            except Exception as exc:
                w(f"  ERROR: {exc}")
        else:
            w("  Exists: NO  (pyvips/ directory not found inside bundle)")
        w()

    # ----------------------------------------------------------------- sys.path
    w("[SYS.PATH]")
    for i, p in enumerate(sys.path):
        w(f"  [{i:02d}] {p}")
    w()

    # ------------------------------------------------------------ PATH env var
    w("[PATH environment variable]")
    path_entries = os.environ.get("PATH", "(not set)").split(os.pathsep)
    for i, p in enumerate(path_entries[:20]):
        w(f"  [{i:02d}] {p}")
    if len(path_entries) > 20:
        w(f"  ... and {len(path_entries) - 20} more entries")
    w()

    # ------------------------------------------- ctypes direct DLL load probes
    w("[CTYPES DLL LOAD PROBES]")
    for dll_name in ("libvips-42.dll", "libvips.so.42", "libvips.dylib"):
        try:
            lib = ctypes.CDLL(dll_name)
            w(f"  {dll_name:<30}  OK  ({lib})")
        except Exception as exc:
            w(f"  {dll_name:<30}  FAILED — {exc}")

    try:
        from ctypes.util import find_library
        found = find_library("vips")
        w(f"  find_library('vips')           : {found!r}")
    except Exception as exc:
        w(f"  find_library error             : {exc}")
    w()

    # -------------------------------------- importlib.find_spec probe (no load)
    w("[IMPORTLIB  find_spec('pyvips')]")
    try:
        spec = importlib.util.find_spec("pyvips")
        if spec is None:
            w("  Result : NOT FOUND")
        else:
            w(f"  Result : FOUND")
            w(f"  origin : {spec.origin}")
            w(f"  submodule_search_locations : {list(spec.submodule_search_locations or [])}")
    except Exception as exc:
        w(f"  ERROR: {exc}")
    w()

    # ------------------------------------------------- pyvips actual import
    w("[PYVIPS IMPORT]")
    from engine.perspective import _PYVIPS_AVAILABLE, WARP_BACKEND_LABEL  # noqa: PLC0415

    w(f"  _PYVIPS_AVAILABLE  : {_PYVIPS_AVAILABLE}")
    w(f"  WARP_BACKEND_LABEL : {WARP_BACKEND_LABEL}")

    if not _PYVIPS_AVAILABLE:
        w()
        w("  ** pyvips FAILED to load at engine/perspective.py import time **")
        w("  Re-attempting import now to capture full exception:")
        try:
            import pyvips  # noqa: F401
            w("  (import succeeded on retry — unexpected)")
        except Exception:
            w()
            for line in traceback.format_exc().splitlines():
                w(f"  {line}")
    else:
        try:
            import pyvips
            w(f"  pyvips version : {pyvips.__version__}")
            w(f"  libvips version: {pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}")
        except Exception as exc:
            w(f"  version query error: {exc}")
    w()

    # ----------------------------------------------------------------- footer
    w("=" * 70)
    w("END OF DIAGNOSTIC")
    w("=" * 70)

    report = "\n".join(lines)
    out_path.write_text(report, encoding="utf-8")

    if _PYVIPS_AVAILABLE:
        _log.info("pyvips diagnostic OK — report: %s", out_path)
    else:
        _log.warning(
            "pyvips NOT available (PIL fallback active) — diagnostic: %s", out_path
        )

    return out_path
