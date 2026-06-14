"""
hooks/hook-pyvips.py — PyInstaller hook for pyvips
====================================================
pyvips loads the native libvips library at runtime via cffi.dlopen().
PyInstaller's static analysis cannot trace this dependency.

This hook runs on the BUILD machine where libvips is already installed
(added to PATH on Windows, installed via apt on Linux).  It:

  1. Calls collect_all('pyvips') to bundle all pyvips Python files.
  2. Locates the native library using three independent strategies
     (env var -> PATH search -> ctypes) so hook execution is robust even
     when the hook's Python environment differs from the build shell.
  3. Adds all co-located native DLLs/SOs to the bundle ROOT ('.'),
     which is sys._MEIPASS at runtime — where cffi.dlopen() and the
     Windows DLL loader search.

Why bundle root?
  cffi.dlopen('libvips-42.dll') and the Windows DLL loader both search
  the executable directory (sys._MEIPASS/_internal for --onedir) and
  PATH.  A subdirectory such as pyvips/ is NOT searched by the OS
  loader even if Python can import from it.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import sys
import warnings
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("pyvips")


# ---------------------------------------------------------------------------
# Windows: three-strategy search for libvips-42.dll
# ---------------------------------------------------------------------------

def _collect_windows() -> list[tuple[str, str]]:
    """
    Find libvips-42.dll on Windows using three cascading strategies.

    Strategy 1 — VIPS_BIN env var (set explicitly by CI workflow):
        Most reliable; survives any PATH inheritance quirks in the hook
        execution environment.

    Strategy 2 — PATH search:
        Walks os.environ["PATH"] looking for libvips-42.dll directly on
        the filesystem.  Does not require ctypes.CDLL to succeed.

    Strategy 3 — ctypes.CDLL + GetModuleFileNameW:
        Fallback for local dev builds where VIPS_BIN is not set.
        Loads the DLL via the Windows loader and asks the kernel for its
        full path.
    """
    vips_bin: Path | None = None

    # Strategy 1: VIPS_BIN env var set by CI workflow
    env_bin = os.environ.get("VIPS_BIN", "").strip()
    if env_bin:
        candidate = Path(env_bin)
        if candidate.is_dir() and (candidate / "libvips-42.dll").exists():
            vips_bin = candidate
            print(f"hook-pyvips [Win/S1]: vips bin via VIPS_BIN -> {vips_bin}")

    # Strategy 2: Walk PATH looking for libvips-42.dll
    if vips_bin is None:
        for dir_str in os.environ.get("PATH", "").split(os.pathsep):
            if not dir_str:
                continue
            dll_candidate = Path(dir_str) / "libvips-42.dll"
            if dll_candidate.exists():
                vips_bin = dll_candidate.parent
                print(f"hook-pyvips [Win/S2]: vips bin via PATH -> {vips_bin}")
                break

    # Strategy 3: ctypes.CDLL + GetModuleFileNameW
    if vips_bin is None:
        try:
            lib = ctypes.CDLL("libvips-42.dll")
            buf = ctypes.create_unicode_buffer(32768)
            ctypes.windll.kernel32.GetModuleFileNameW(
                ctypes.c_void_p(lib._handle), buf, len(buf)
            )
            resolved = Path(buf.value)
            if resolved.exists():
                vips_bin = resolved.parent
                print(f"hook-pyvips [Win/S3]: vips bin via ctypes -> {vips_bin}")
        except Exception as exc:
            warnings.warn(f"hook-pyvips: ctypes strategy failed: {exc}")

    if vips_bin is None:
        warnings.warn(
            "hook-pyvips [Windows]: libvips-42.dll not found via any strategy.\n"
            "  Tried: VIPS_BIN env var, PATH search, ctypes.CDLL.\n"
            "  The bundle will fall back to PIL (jagged edges).\n"
            "  Ensure libvips is installed and in PATH before running PyInstaller."
        )
        return []

    dlls = list(vips_bin.glob("*.dll"))
    if not dlls:
        warnings.warn(
            f"hook-pyvips [Windows]: vips_bin={vips_bin} found but contains no *.dll files.\n"
            "  Ensure the libvips installation is complete.\n"
            "  The bundle will fall back to PIL (jagged edges)."
        )
        return []
    print(
        f"hook-pyvips [Windows]: bundling {len(dlls)} DLL(s) "
        f"from {vips_bin} -> bundle root"
    )
    return [(str(dll), ".") for dll in dlls]


# ---------------------------------------------------------------------------
# Linux: ldconfig search for libvips.so.42
# ---------------------------------------------------------------------------

def _collect_linux() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    try:
        output = subprocess.check_output(["ldconfig", "-p"], text=True)
    except Exception as exc:
        warnings.warn(f"hook-pyvips: ldconfig failed: {exc}")
        return result

    for line in output.splitlines():
        if "libvips.so." in line and "=>" in line:
            so_path = Path(line.split("=>")[-1].strip())
            if so_path.exists():
                print(f"hook-pyvips [Linux]: bundling {so_path.name} -> bundle root")
                result.append((str(so_path), "."))
                break
    else:
        warnings.warn("hook-pyvips: libvips.so not found in ldconfig output")

    return result


if sys.platform == "win32":
    binaries += _collect_windows()
elif sys.platform.startswith("linux"):
    binaries += _collect_linux()
