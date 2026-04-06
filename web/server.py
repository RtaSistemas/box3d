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
import queue
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cli.bootstrap import _BUNDLE, _PROFILES
from core.models import CoverResult, RenderOptions
from core.registry import ProfileRegistry, ProfileError

app = FastAPI(
    title="Box3D Web Control Center",
    description="HTTP API for the Box3D 3D box-art rendering engine.",
    version="1.0.0",
)

# Allow browser clients running on any origin (dev-friendly default).
# Tighten to specific origins before deploying to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global progress queue
# A single queue is sufficient for the single-operator desktop use-case this
# server targets.  Replace with a keyed dict[session_id, Queue] if multiple
# concurrent render sessions are ever needed.
# ---------------------------------------------------------------------------
_progress_queue: queue.Queue[dict] = queue.Queue()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class RenderRequest(BaseModel):
    profile:      str  = Field(...,  description="Profile name (e.g. 'mvs', 'arcade')")
    covers_dir:   str  = Field(...,  description="Absolute path to input covers directory")
    output_dir:   str  = Field(...,  description="Absolute path to output directory")
    marquees_dir: str | None = Field(None, description="Path to marquees directory (optional)")
    workers:      int  = Field(4,    ge=1, description="Parallel worker threads")
    blur_radius:  int  = Field(20,   ge=0, description="Spine background blur radius")
    darken_alpha: int  = Field(180,  ge=0, le=255, description="Spine dark overlay alpha")
    cover_fit:    str | None = Field(None, description="stretch | fit | crop")
    spine_source: str | None = Field(None, description="left | center | right")
    output_format: str = Field("webp", description="webp | png")
    skip_existing: bool = Field(False)
    dry_run:       bool = Field(False)
    no_logos:      bool = Field(False)


class PathCheckRequest(BaseModel):
    path: str = Field(..., description="Filesystem path to validate")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_registry() -> ProfileRegistry:
    return ProfileRegistry(str(_PROFILES)).load()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
    Returns ``{"status": "error", "detail": "..."}`` on validation failure.
    """
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

    # --- Options ---
    options = RenderOptions(
        blur_radius   = payload.blur_radius,
        darken_alpha  = payload.darken_alpha,
        cover_fit     = payload.cover_fit,       # type: ignore[arg-type]
        spine_source  = payload.spine_source,    # type: ignore[arg-type]
        output_format = payload.output_format,   # type: ignore[arg-type]
        skip_existing = payload.skip_existing,
        workers       = payload.workers,
        dry_run       = payload.dry_run,
        with_logos    = not payload.no_logos,
    )

    # --- Drain any stale events from a previous run ---
    while not _progress_queue.empty():
        _progress_queue.get_nowait()

    def _run_pipeline() -> None:
        """Executed in a worker thread via asyncio.to_thread()."""
        from core.pipeline import RenderPipeline

        pipeline = RenderPipeline(
            profile      = profile,
            covers_dir   = covers_dir,
            output_dir   = output_dir,
            temp_dir     = output_dir / ".tmp",
            options      = options,
            logo_paths   = {"top": None, "bottom": None},
            marquees_dir = marquees_dir or (profile.root / "assets"),
        )

        def on_progress(done: int, total: int, result: CoverResult) -> None:
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
        })

    # Dispatch to a thread so the async event loop stays responsive.
    background_tasks.add_task(asyncio.to_thread, _run_pipeline)

    return JSONResponse({"status": "started", "profile": payload.profile,
                         "covers_dir": str(covers_dir)})


# ---------------------------------------------------------------------------
# Static UI
# Mounted AFTER all /api/* route handlers so FastAPI matches API routes first.
# StaticFiles with html=True serves index.html for any unmatched path (SPA
# fallback), so the browser can navigate directly to http://localhost:8000.
#
# _BUNDLE resolves correctly in both environments:
#   - Development / pip install : project root   → <root>/web/ui/
#   - PyInstaller --onefile     : sys._MEIPASS   → <MEIPASS>/web/ui/
# ---------------------------------------------------------------------------

_UI_DIR = _BUNDLE / "web" / "ui"
if _UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")


# ---------------------------------------------------------------------------
# Entry point (development)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.server:app", host="0.0.0.0", port=8000, reload=True)
