"""
core/pipeline.py — Rendering pipeline
=======================================
``RenderPipeline`` orchestrates the full processing run:

1. Validate environment.
2. Collect cover images.
3. Dispatch workers in parallel.
4. Print the summary report.

The pipeline is decoupled from the engine and the profile registry —
it receives a :class:`~core.models.Profile` and delegates all image
work to ``engine.compositor``.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from core.models import CoverResult, Profile, RenderOptions

log = logging.getLogger("box3d.pipeline")

# Supported input extensions (case-insensitive)
VALID_EXT: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")


class RenderPipeline:
    """
    Processes every cover image in *covers_dir* using *profile*.

    Subdirectory structure under *covers_dir* is mirrored in
    *output_dir*::

        covers/Capcom/sf2.webp  →  output/Capcom/sf2.webp

    Parameters
    ----------
    profile:
        Loaded profile (geometry + layout + template path).
    covers_dir:
        Directory containing flat or nested cover images.
    output_dir:
        Root output directory.
    temp_dir:
        Scratch directory for intermediate files (auto-created).
    options:
        Runtime rendering options.
    logo_paths:
        Optional ``{"top": Path, "bottom": Path}`` for spine logos.
    marquees_dir:
        Optional directory of game marquee images (matched by stem).
    """

    def __init__(
        self,
        profile:      Profile,
        covers_dir:   Path,
        output_dir:   Path,
        temp_dir:     Path,
        options:      RenderOptions,
        logo_paths:   dict[str, Path | None] | None = None,
        marquees_dir: Path | None = None,
    ) -> None:
        self.profile      = profile
        self.covers_dir   = covers_dir
        self.output_dir   = output_dir
        self.temp_dir     = temp_dir
        self.options      = options
        self.logo_paths   = logo_paths or {}
        self.marquees_dir = marquees_dir or (profile.root / "assets")
        self._stats: dict[str, int] = {"ok": 0, "skip": 0, "error": 0, "dry": 0}
        self._lock  = Lock()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> dict[str, int]:
        """
        Execute the pipeline and return the stats dict
        ``{"ok": N, "skip": N, "error": N, "dry": N}``.
        """
        t_start = time.perf_counter()

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
            return self._stats

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        covers = self._collect()
        if not covers:
            log.warning("No cover images found in %s", self.covers_dir)
            return self._stats

        total = len(covers)
        log.info("Processing %d cover(s) with %d thread(s)…", total, self.options.workers)

        with ThreadPoolExecutor(max_workers=self.options.workers) as pool:
            futures = {
                pool.submit(self._process_one, path): path
                for path in covers
            }
            done = 0
            for future in as_completed(futures):
                result: CoverResult = future.result()
                done += 1
                with self._lock:
                    self._stats[result.status] = \
                        self._stats.get(result.status, 0) + 1
                pct = int(done / total * 100)
                print(f"\r  Progress: {done}/{total}  [{pct:3d}%]",
                      end="", flush=True)

        print()
        self._report(total, time.perf_counter() - t_start)
        return self._stats

    # ------------------------------------------------------------------
    # Per-cover worker
    # ------------------------------------------------------------------

    def _process_one(self, cover_path: Path) -> CoverResult:
        """Process a single cover.  Dispatched by the thread pool."""
        # Deferred import to avoid circular dependency at module load time
        from engine.compositor import render_cover
        return render_cover(
            cover_path   = cover_path,
            covers_dir   = self.covers_dir,
            profile      = self.profile,
            options      = self.options,
            output_dir   = self.output_dir,
            temp_dir     = self.temp_dir,
            logo_paths   = self.logo_paths,
            marquees_dir = self.marquees_dir,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def _report(self, total: int, elapsed: float) -> None:
        ok_count  = self._stats.get("ok",    0)
        err_count = self._stats.get("error", 0)
        processed = ok_count + err_count
        log.info("-" * 62)
        log.info("SUMMARY")
        log.info("  Total     : %d", total)
        log.info("  Succeeded : %d", ok_count)
        log.info("  Skipped   : %d", self._stats.get("skip", 0))
        log.info("  Errors    : %d", err_count)
        log.info("  Dry-run   : %d", self._stats.get("dry",  0))
        log.info("  Time      : %.2fs  (~%.2fs/image processed)",
                 elapsed, elapsed / max(processed, 1))
        log.info("  Output    : %s", self.output_dir)
        log.info("-" * 62)
        if err_count:
            log.warning("%d error(s) — check the log for details", err_count)
