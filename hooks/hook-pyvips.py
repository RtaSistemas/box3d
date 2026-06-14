"""
hooks/hook-pyvips.py — PyInstaller hook for pyvips
====================================================
pyvips loads the native libvips library at runtime via cffi.dlopen().
PyInstaller's static analysis cannot trace this dependency.

This hook runs on the BUILD machine where libvips is already installed
(added to PATH on Windows, installed via apt on Linux).  It:

  1. Calls collect_all('pyvips') to bundle all pyvips Python files.
  2. Locates the native library by loading it via ctypes (which succeeds
     because libvips is in PATH/ldconfig on the build machine).
  3. Resolves the full filesystem path of the loaded library.
  4. Adds it — and all co-located native DLLs (Windows) — to the bundle
     root ('.'), which is sys._MEIPASS at runtime.

Why bundle root?
  cffi.dlopen('libvips-42.dll') and the Windows DLL loader both search
  the executable directory (sys._MEIPASS for --onefile, the dist folder
  for --onedir) and PATH.  A subdirectory such as pyvips/ is NOT searched
  by the Windows loader, even if Python can import it.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import warnings
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("pyvips")


# ---------------------------------------------------------------------------
# Windows: load libvips-42.dll via ctypes, resolve full path via Win32 API,
# then collect every DLL co-located in the same bin/ directory.
# ---------------------------------------------------------------------------

def _collect_windows() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    try:
        lib = ctypes.CDLL("libvips-42.dll")
    except OSError as exc:
        warnings.warn(
            f"hook-pyvips: cannot load libvips-42.dll — "
            f"is libvips installed and in PATH? ({exc})"
        )
        return result

    # GetModuleFileNameW(hModule, lpFilename, nSize) → full path of the DLL.
    buf = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetModuleFileNameW(lib._handle, buf, len(buf))
    libvips_path = Path(buf.value)

    if not libvips_path.exists():
        warnings.warn(
            f"hook-pyvips: GetModuleFileNameW returned non-existent path: "
            f"{libvips_path}"
        )
        return result

    vips_bin = libvips_path.parent
    dlls = list(vips_bin.glob("*.dll"))
    print(
        f"hook-pyvips [Windows]: bundling {len(dlls)} DLL(s) "
        f"from {vips_bin} → bundle root"
    )
    for dll in dlls:
        result.append((str(dll), "."))

    return result


# ---------------------------------------------------------------------------
# Linux: find libvips.so.42 via ldconfig, add to bundle root.
# ---------------------------------------------------------------------------

def _collect_linux() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    try:
        import subprocess
        output = subprocess.check_output(["ldconfig", "-p"], text=True)
    except Exception as exc:
        warnings.warn(f"hook-pyvips: ldconfig failed: {exc}")
        return result

    for line in output.splitlines():
        if "libvips.so." in line and "=>" in line:
            so_path = Path(line.split("=>")[-1].strip())
            if so_path.exists():
                print(f"hook-pyvips [Linux]: bundling {so_path.name} → bundle root")
                result.append((str(so_path), "."))
                break
    else:
        warnings.warn("hook-pyvips: libvips.so not found in ldconfig output")

    return result


if sys.platform == "win32":
    binaries += _collect_windows()
elif sys.platform.startswith("linux"):
    binaries += _collect_linux()
