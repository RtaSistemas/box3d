"""
core/pipeline.py — Rendering pipeline
=======================================
``RenderPipeline`` orchestrates the full processing run.

This module is the **sole I/O boundary** for disk reads.  All image
assets (covers, logos, marquees, templates) are opened here with
OOM Hardening applied, then passed as in-memory PIL Image objects
to the rendering engine.

Circuit Breaker: if consecutive errors exceed 10 or total errors
exceed 20% of the batch, the pipeline aborts with a critical log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from PIL import Image

from core.models import CoverResult, Profile, RenderOptions, RenderSummary

log = logging.getLogger("box3d.pipeline")

VALID_EXT: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")

# Circuit Breaker thresholds
_CB_MAX_CONSECUTIVE = 10
_CB_PCT_THRESHOLD   = 0.20


# ---------------------------------------------------------------------------
# OOM-safe asset loader
# ---------------------------------------------------------------------------

def _safe_open(path: Path) -> Image.Image:
    """
    Open an image from disk and apply OOM Hardening (Lei de Ferro).

    If the image exceeds 8192px on either axis, it is immediately
    downscaled proportionally before being returned.
    """
    img = Image.open(path).convert("RGBA")
    if img.width > 8192 or img.height > 8192:
        log.warning("OOM Hardening: downscaling %s (%dx%d → ≤8192px)",
                    path.name, img.width, img.height)
        img.thumbnail((8192, 8192), Image.BICUBIC)
    return img


def _find_asset(directory: Path, stem: str) -> Path | None:
    """Find the first file with *stem* in any supported extension."""
    if not directory.is_dir():
        return None
    stem_l = stem.lower()
    exts   = {e.lower() for e in VALID_EXT}
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.stem.lower() == stem_l and f.suffix.lower() in exts:
            return f
    return None


class RenderPipeline:
    def __init__(
        self,
        profile:      Profile,
        covers_dir:   Path,
        output_dir:   Path,
        options:      RenderOptions,
        logo_paths:   dict[str, Path | None] | None = None,
        marquees_dir: Path | None = None,
        temp_dir:     Path | None = None,   # legacy param — ignored; kept for API compat
    ) -> None:
        self.profile      = profile
        self.covers_dir   = covers_dir
        self.output_dir   = output_dir
        self.options      = options
        self.logo_paths   = logo_paths or {}
        self.marquees_dir = marquees_dir or (profile.root / "assets")
        self._stats: dict[str, int] = {"ok": 0, "skip": 0, "error": 0, "dry": 0}
        self._lock  = Lock()

    # ------------------------------------------------------------------
    # Pre-load shared assets (logos)
    # ------------------------------------------------------------------

    def _load_logo(self, key: str) -> Image.Image | None:
        """Load a logo by key from logo_paths with OOM Hardening."""
        path = self.logo_paths.get(key)
        if path is None or not path.exists():
            return None
        try:
            return _safe_open(path)
        except Exception as exc:
            log.warning("Cannot open %s logo '%s': %s", key, path, exc)
            return None

    def _load_game_logo(self, stem: str) -> Image.Image | None:
        """Find and load the per-cover game logo with OOM Hardening.

        Resolution order
        ----------------
        1. <marquees_dir>/<stem>.*  — dynamic per-game marquee.
        2. <profile>/assets/logo_game.*  — profile-level fallback logo
           (e.g. the system manufacturer logo used when no specific marquee
           exists for the current cover).
        3. None  — spine rendered without a game logo.
        """
        # Stage 1: dynamic marquee matched by cover filename stem
        path = _find_asset(self.marquees_dir, stem)

        # Stage 2: profile-level fallback — logo_game.* inside assets/
        if path is None:
            path = _find_asset(self.profile.root / "assets", "logo_game")

        if path is None:
            return None

        try:
            return _safe_open(path)
        except Exception as exc:
            log.warning("Cannot open game logo '%s': %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(
        self,
        on_progress: Callable[[int, int, CoverResult], None] | None = None,
    ) -> RenderSummary:
        """
        Execute the full render batch.

        Parameters
        ----------
        on_progress:
            Optional callback invoked after each cover completes.
            Signature: ``(done: int, total: int, result: CoverResult) -> None``.
            Fired inside the ``as_completed`` loop so the caller receives
            real-time updates (useful for progress bars, WebSocket pushes, …).

        Returns
        -------
        RenderSummary
            Structured result with counters, timing, and per-error details.
            Call ``.to_dict()`` for JSON serialisation.
        """
        t_start = time.perf_counter()
        errors:  list[str] = []

        log.info("=" * 62)
        log.info("box3d pipeline — starting")
        log.info("  Profile  : %s  (%dx%d)",
                 self.profile.name,
                 self.profile.geometry.template_w,
                 self.profile.geometry.template_h)
        log.info("  Covers   : %s", self.covers_dir)
        log.info("  Output   : %s  [%s]",
                 self.output_dir, self.options.output_format)
        log.info("  Workers  : %d", self.options.workers)
        log.info("=" * 62)

        if not self._validate():
            log.error("Validation failed — aborting.")
            return RenderSummary(
                total=0, succeeded=0, skipped=0, failed=0, dry=0,
                elapsed_time=time.perf_counter() - t_start,
                errors=["Validation failed — see log for details"],
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        covers = self._collect()
        if not covers:
            log.warning("No cover images found in %s", self.covers_dir)
            return RenderSummary(
                total=0, succeeded=0, skipped=0, failed=0, dry=0,
                elapsed_time=time.perf_counter() - t_start,
                errors=[],
            )

        total = len(covers)
        log.info("Processing %d cover(s) with %d thread(s)…", total, self.options.workers)

        # --- Pre-load shared assets (once) ---
        log.info("Pre-loading profile template into memory...")
        template_img = _safe_open(self.profile.template_path)

        log.info("Pre-loading spine logos into memory...")
        top_logo_img    = self._load_logo("top")
        bottom_logo_img = self._load_logo("bottom")

        # --- Circuit Breaker state ---
        consecutive_errors = 0
        error_threshold    = max(1, int(total * _CB_PCT_THRESHOLD))
        breaker_tripped    = False

        with ThreadPoolExecutor(max_workers=self.options.workers) as pool:
            futures = {
                pool.submit(
                    self._process_one, path, template_img,
                    top_logo_img, bottom_logo_img
                ): path
                for path in covers
            }
            done = 0
            for future in as_completed(futures):
                result: CoverResult = future.result()
                done += 1
                with self._lock:
                    self._stats[result.status] = \
                        self._stats.get(result.status, 0) + 1

                if result.status == "error" and result.error:
                    errors.append(f"{result.stem}: {result.error}")

                # --- Circuit Breaker logic ---
                if result.status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                total_errors = self._stats.get("error", 0)

                if consecutive_errors > _CB_MAX_CONSECUTIVE or \
                   total_errors > error_threshold:
                    log.critical(
                        "CIRCUIT BREAKER ACTIVATED: %d consecutive errors, "
                        "%d total errors (threshold: %d). Aborting pipeline.",
                        consecutive_errors, total_errors, error_threshold
                    )
                    cancelled = sum(1 for f in futures if f.cancel())
                    log.critical("Cancelled %d pending task(s).", cancelled)
                    breaker_tripped = True
                    break

                if on_progress is not None:
                    on_progress(done, total, result)

        return RenderSummary(
            total=total,
            succeeded=self._stats.get("ok",    0),
            skipped=self._stats.get("skip",  0),
            failed=self._stats.get("error", 0),
            dry=self._stats.get("dry",   0),
            elapsed_time=time.perf_counter() - t_start,
            errors=errors,
            breaker_tripped=breaker_tripped,
        )

    def _process_one(
        self,
        cover_path:      Path,
        template_img:    Image.Image,
        top_logo_img:    Image.Image | None,
        bottom_logo_img: Image.Image | None,
    ) -> CoverResult:
        """
        Process one cover: open, compose, save.
        All disk I/O is concentrated here — engine/ is I/O-free.
        """
        from engine.compositor import compose_cover

        stem = cover_path.stem
        t0   = time.perf_counter()

        rel         = cover_path.relative_to(self.covers_dir)
        output_path = self.output_dir / rel.with_suffix(f".{self.options.output_format}")

        if self.options.dry_run:
            log.info("[DRY-RUN] %s", rel)
            return CoverResult(stem=stem, status="dry", elapsed=0.0)

        if self.options.skip_existing and output_path.exists():
            log.info("[SKIP]    %s — already exists", rel)
            return CoverResult(stem=stem, status="skip", elapsed=0.0)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # --- Disk read: cover + game logo (OOM Hardened) ---
            cover_img     = _safe_open(cover_path)
            game_logo_img = self._load_game_logo(cover_path.stem)

            # --- Pure composition (zero I/O) ---
            result_img = compose_cover(
                cover_img    = cover_img,
                profile      = self.profile,
                options      = self.options,
                game_logo    = game_logo_img,
                top_logo     = top_logo_img,
                bottom_logo  = bottom_logo_img,
                template_img = template_img,
            )

            # --- Disk write: save final output ---
            ext = output_path.suffix.lower()
            if ext == ".webp":
                result_img.save(str(output_path), "WEBP", quality=92, method=4)
            else:
                result_img.save(str(output_path), "PNG", optimize=False)

            elapsed = time.perf_counter() - t0
            log.info("✔  %-46s (%.2fs)", str(rel), elapsed)
            return CoverResult(stem=stem, status="ok", elapsed=elapsed)

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            msg = str(exc).strip()
            log.error("✘  %s: %s", rel, msg, exc_info=True)
            return CoverResult(stem=stem, status="error", elapsed=elapsed, error=msg)

    def _validate(self) -> bool:
        ok = True
        if not self.profile.template_path.exists():
            log.error("Template not found: %s", self.profile.template_path)
            ok = False
        if not self.covers_dir.exists():
            log.error("Covers directory not found: %s", self.covers_dir)
            ok = False
        else:
            sample = next(
                (f for f in self.covers_dir.rglob("*")
                 if f.is_file() and f.suffix.lower() in VALID_EXT),
                None,
            )
            if sample is None:
                log.error("No valid images in covers directory: %s", self.covers_dir)
                ok = False
        for label, path in self.logo_paths.items():
            if path is not None and not path.exists():
                log.error("--%s-logo: file not found: %s", label, path)
                ok = False
        if self.marquees_dir and not self.marquees_dir.is_dir():
            log.warning("Marquees directory not found: %s — no game logos", self.marquees_dir)
        return ok

    def _collect(self) -> list[Path]:
        files = sorted(
            f for f in self.covers_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in VALID_EXT
        )
        log.info("Covers found: %d", len(files))
        return files

