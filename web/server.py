"""
web/server.py — Box3D Web Control Center (API backend)
=======================================================
Optional FastAPI server that exposes the Box3D rendering engine over HTTP.

Install the optional dependencies before running::

    pip install .[web]

Run::

    uvicorn web.server:app --reload

Architecture
------------
This module is a *thin API layer* — it only instantiates and calls
``core/`` objects.  No rendering logic lives here.

The ``RenderPipeline`` is synchronous and CPU-bound.  To prevent it from
blocking the async event loop it is dispatched via ``asyncio.to_thread()``.
Progress updates are streamed to the browser through Server-Sent Events
(SSE) using a ``queue.Queue`` as the thread-safe bridge between the worker
thread and the async generator.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import queue
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Annotated, Literal

from cli.bootstrap import _BUNDLE, _PROFILES
from cli.utils import auto_logo as _auto_logo
from core.models import CoverResult, RenderOptions
from core.registry import ProfileRegistry, ProfileError
from core.version import __version__

app = FastAPI(
    title="Box3D Web Control Center",
    description="HTTP API for the Box3D 3D box-art rendering engine.",
    version="3.0.0RC",
)

# Restrict CORS to localhost origins only — the server exposes filesystem
# endpoints (render, validate-path, open-folder) that must not be callable
# from arbitrary web pages opened in the same browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ---------------------------------------------------------------------------
# Global state (single-operator desktop model)
# ---------------------------------------------------------------------------
_progress_queue: queue.Queue[dict] = queue.Queue()
_last_output_dir: Path | None = None   # set by _run_pipeline; read by /api/open-folder
_render_lock     = asyncio.Lock()       # prevents concurrent render sessions
# Single-thread executor reserved for the render pipeline so it never ties
# up a slot from asyncio's shared default pool for the full render duration.
_render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="box3d-render")


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class RenderRequest(BaseModel):
    profile:      str  = Field(...,  description="Profile name (e.g. 'mvs', 'arcade')")
    covers_dir:   str  = Field(...,  description="Absolute path to input covers directory")
    output_dir:   str  = Field(...,  description="Absolute path to output directory")
    marquees_dir: str | None = Field(None, description="Path to marquees directory (optional)")
    workers:      int  = Field(4,    ge=1, description="Parallel worker threads")
    blur_radius:  int  = Field(20,   ge=0, le=100, description="Spine background blur radius (0-100)")
    darken_alpha: int  = Field(180,  ge=0, le=255, description="Spine dark overlay alpha")
    cover_fit:    Literal["stretch", "fit", "crop"] | None = Field(None, description="Cover fit mode")
    spine_source: str | None = Field(
        None,
        description="Spine background sample position: left | right | center (None = profile default)",
        pattern=r"^(left|right|center)$",
    )
    output_format:    Literal["webp", "png"] = Field("webp", description="Output image format")
    skip_existing:    bool  = Field(False)
    dry_run:          bool  = Field(False)
    no_logos:         bool  = Field(False)
    template_opacity: float = Field(1.0, ge=0.0, le=1.0,
                                    description="Template lighting opacity (0.0=none, 1.0=full)")
    rgb_matrix:   Annotated[
        list[Annotated[float, Field(ge=0.0, le=5.0)]], Field(min_length=3, max_length=3)
    ] | None = Field(None, description="[r, g, b] channel scale factors (0.0–5.0)")


class OpenFolderRequest(BaseModel):
    path: str | None = Field(None, description="Directory to open (default: last output dir)")


class PathCheckRequest(BaseModel):
    path: str = Field(..., description="Filesystem path to validate")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_registry_cache: ProfileRegistry | None = None
_registry_mtime: float = 0.0


def _get_registry() -> ProfileRegistry:
    """Return a cached ProfileRegistry, refreshed when profiles/ mtime changes."""
    global _registry_cache, _registry_mtime
    try:
        mtime = _PROFILES.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _registry_cache is None or mtime != _registry_mtime:
        _registry_cache = ProfileRegistry(str(_PROFILES)).load()
        _registry_mtime = mtime
    return _registry_cache


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/version", summary="Return the application version string")
def get_version() -> JSONResponse:
    """Return ``{"version": "3.0.0RC"}`` for display in the web UI."""
    return JSONResponse({"version": __version__})


@app.get("/api/profiles", summary="List available profiles")
def list_profiles() -> JSONResponse:
    """Return the names of all profiles discovered in the profiles/ directory."""
    try:
        registry = _get_registry()
        names = registry.names()
        details = []
        for name in names:
            p = registry.get(name)
            details.append({
                "name":       name,
                "template_w": p.geometry.template_w,
                "template_h": p.geometry.template_h,
            })
        return JSONResponse({"profiles": details})
    except ProfileError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/validate-path", summary="Check whether a directory path exists")
def validate_path(payload: PathCheckRequest) -> JSONResponse:
    """
    Return ``{"valid": true}`` if the path resolves to an existing directory,
    ``{"valid": false}`` otherwise.  Never raises — safe to call from the UI
    while the user is typing.
    """
    try:
        valid = bool(payload.path) and Path(payload.path).is_dir()
    except (OSError, ValueError):
        valid = False
    return JSONResponse({"valid": valid, "path": payload.path})


@app.get("/api/progress", summary="SSE stream of render progress events")
async def progress_stream() -> StreamingResponse:
    """
    Server-Sent Events endpoint.  Connect once before starting a render;
    each completed cover emits one JSON event::

        data: {"done": 3, "total": 10, "stem": "sonic", "status": "ok", "elapsed": 1.23}\\n\\n

    A sentinel event ``{"done": -1}`` is emitted when the render finishes.
    """
    async def _generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                # Non-blocking get; yield control to the event loop between polls.
                event = _progress_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            yield f"data: {json.dumps(event)}\n\n"

            # Sentinel: render finished (or failed); close the stream.
            if event.get("done") == -1:
                break

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/api/render", summary="Start an async render job")
async def start_render(
    payload: RenderRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Validate inputs and start a render job in a background thread.

    Returns ``{"status": "started"}`` immediately so the caller can begin
    consuming ``/api/progress`` without waiting for the full batch to finish.
    Returns ``{"status": "busy"}`` (HTTP 409) when another render is in progress.
    Returns ``{"status": "error", "detail": "..."}`` on validation failure.
    """
    # --- Reject concurrent renders to prevent queue/state corruption ---
    if _render_lock.locked():
        return JSONResponse(
            {"status": "busy", "detail": "A render is already in progress."},
            status_code=409,
        )

    # --- Registry & profile lookup ---
    try:
        registry = _get_registry()
        profile  = registry.get(payload.profile)
    except (ProfileError, KeyError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=400)

    # --- Path resolution ---
    covers_dir   = Path(payload.covers_dir)
    output_dir   = Path(payload.output_dir)
    marquees_dir = Path(payload.marquees_dir) if payload.marquees_dir else None

    if not covers_dir.is_dir():
        return JSONResponse(
            {"status": "error", "detail": f"covers_dir not found: {covers_dir}"},
            status_code=400,
        )

    # --- RGB matrix ---
    # RenderOptions.rgb_matrix expects the diagonal matrix string consumed by
    # engine/blending.apply_color_matrix() — e.g. "1.1 0 0  0 1.0 0  0 0 0.9".
    # Payload sends [r, g, b] floats validated by Pydantic (ge=0.0, le=5.0 each).
    rgb_matrix_str: str | None = None
    if payload.rgb_matrix and len(payload.rgb_matrix) == 3:
        r, g, b = payload.rgb_matrix
        rgb_matrix_str = f"{r} 0 0  0 {g} 0  0 0 {b}"

    # --- Options ---
    options = RenderOptions(
        blur_radius      = payload.blur_radius,
        darken_alpha     = payload.darken_alpha,
        rgb_matrix       = rgb_matrix_str,
        template_opacity = payload.template_opacity,
        cover_fit        = payload.cover_fit,
        spine_source     = payload.spine_source,  # type: ignore[arg-type]  (Literal validated by Pydantic pattern)
        output_format    = payload.output_format,
        skip_existing    = payload.skip_existing,
        workers          = payload.workers,
        dry_run          = payload.dry_run,
    )

    # --- Drain any stale events from a previous run ---
    while not _progress_queue.empty():
        _progress_queue.get_nowait()

    def _run_pipeline() -> None:
        """Executed in a worker thread via asyncio.to_thread()."""
        global _last_output_dir
        _last_output_dir = output_dir

        from core.pipeline import RenderPipeline

        pipeline = RenderPipeline(
            profile      = profile,
            covers_dir   = covers_dir,
            output_dir   = output_dir,
            options      = options,
            logo_paths   = {
                "top":    _auto_logo(profile.root / "assets", "logo_top"),
                "bottom": _auto_logo(profile.root / "assets", "logo_bottom"),
            },
            marquees_dir = marquees_dir or (profile.root / "assets"),
            no_logos     = payload.no_logos,
        )

        first_stem: str | None = None

        def on_progress(done: int, total: int, result: CoverResult) -> None:
            nonlocal first_stem
            if result.status == "ok" and first_stem is None:
                first_stem = result.stem
            _progress_queue.put({
                "done":    done,
                "total":   total,
                "stem":    result.stem,
                "status":  result.status,
                "elapsed": round(result.elapsed, 3),
            })

        report = pipeline.run(on_progress=on_progress)

        # Emit sentinel with summary so the UI can display final stats.
        _progress_queue.put({
            "done":            -1,
            "total":           report.total,
            "succeeded":       report.succeeded,
            "skipped":         report.skipped,
            "failed":          report.failed,
            "dry":             report.dry,
            "elapsed_time":    round(report.elapsed_time, 2),
            "breaker_tripped": report.breaker_tripped,
            "errors":          report.errors,
            "first_stem":      first_stem,
            "output_format":   payload.output_format,
        })

    async def _locked_run() -> None:
        async with _render_lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(_render_executor, _run_pipeline)

    background_tasks.add_task(_locked_run)

    return JSONResponse({"status": "started", "profile": payload.profile,
                         "covers_dir": str(covers_dir)})


@app.post("/api/open-folder", summary="Open a directory in the native file manager")
def open_folder(payload: OpenFolderRequest) -> JSONResponse:
    """
    Open the given directory (or the last output directory when path is omitted)
    in the operating system's native file manager.

    Supported platforms: macOS (Finder), Windows (Explorer), Linux (xdg-open).
    Returns ``{"opened": true}`` on success, ``{"opened": false, "detail": "..."}`` otherwise.
    """
    target = Path(payload.path) if payload.path else _last_output_dir
    if target is None:
        return JSONResponse({"opened": False, "detail": "No output directory known yet."})
    if not target.is_dir():
        return JSONResponse({"opened": False, "detail": f"Not a directory: {target}"})

    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(target))           # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return JSONResponse({"opened": True, "path": str(target)})
    except Exception as exc:
        return JSONResponse({"opened": False, "detail": str(exc)})


@app.get("/api/preview/{filename}", summary="Serve a rendered output image for preview")
def preview_image(filename: str) -> FileResponse:
    """
    Return a rendered output image by its bare filename (stem + extension).
    The image is read from the last known output directory.

    This avoids exposing arbitrary filesystem paths — callers can only request
    files that live inside the output directory produced by the most recent render.
    """
    if _last_output_dir is None:
        return JSONResponse(  # type: ignore[return-value]
            {"detail": "No render has been started yet."},
            status_code=404,
        )
    # Sanitise: only allow the bare filename, no path traversal
    safe_name = Path(filename).name
    image_path = _last_output_dir / safe_name
    if not image_path.is_file():
        return JSONResponse(  # type: ignore[return-value]
            {"detail": f"File not found: {safe_name}"},
            status_code=404,
        )
    return FileResponse(str(image_path))


# ---------------------------------------------------------------------------
# Static mounts
# Mounted AFTER all /api/* route handlers so FastAPI matches API routes first.
# ---------------------------------------------------------------------------

# Designer Pro — served at /designer/
_DESIGNER_DIR = _BUNDLE / "tools" / "box3d_designer_pro"
if _DESIGNER_DIR.is_dir():
    app.mount("/designer", StaticFiles(directory=str(_DESIGNER_DIR), html=True), name="designer")

# Control Center UI — SPA fallback for any unmatched path.
# _BUNDLE resolves correctly in both environments:
#   - Development / pip install : project root   → <root>/web/ui/
#   - PyInstaller --onefile     : sys._MEIPASS   → <MEIPASS>/web/ui/
_UI_DIR = _BUNDLE / "web" / "ui"
if _UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")


# ---------------------------------------------------------------------------
# Entry point (development)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.server:app", host="0.0.0.0", port=8000, reload=True)
