"""
core/pipeline.py — Rendering pipeline
=======================================
``RenderPipeline`` orchestrates the full processing run.

This module is the **sole I/O boundary** for disk reads.  All image
assets (covers, logos, marquees, templates) are opened here with
OOM Hardening applied, then passed as in-memory PIL Image objects
to the rendering engine.

Circuit Breaker: if consecutive errors exceed 2 (MULTI-AI-PROTO-V3.4 HIGH policy)
or total errors exceed 20% of the batch, the pipeline aborts with a critical log.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from PIL import Image

from core.models import CoverResult, Profile, RenderOptions

log = logging.getLogger("box3d.pipeline")

VALID_EXT: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")

# Circuit Breaker thresholds (MULTI-AI-PROTO-V3.4 §3)
# HIGH severity: 2 consecutive failures → freeze.
# Percentage guard: abort if total errors exceed 20 % of the batch
# (protects large runs where 2 consecutive errors could be transient noise).
_CB_MAX_CONSECUTIVE = 2
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

        Resolution order:
        1. marquees_dir/<stem>.* — dynamic marquee matched by cover filename.
        2. profile/assets/logo_game.* — profile-level fallback logo.
        3. None — spine rendered without a game logo.
        """
        # 1ª tentativa: marquee dinâmica por nome da capa
        path = _find_asset(self.marquees_dir, stem)

        # 2ª tentativa: logo_game.* dentro do assets/ do perfil
        if path is None:
            path = _find_asset(self.profile.root / "assets", "logo_game")

        if path is None:
            return None  # nenhum encontrado — spine sem logo de jogo
        try:
            return _safe_open(path)
        except Exception as exc:
            log.warning("Cannot open game logo '%s': %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> dict[str, int]:
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

        # --- Pre-load shared assets (once) ---
        log.info("Pre-loading profile template into memory...")
        template_img = Image.open(self.profile.template_path).convert("RGBA")

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

                pct = int(done / total * 100)
                print(f"\r  Progress: {done}/{total}  [{pct:3d}%]",
                      end="", flush=True)

        print()
        self._report(total, time.perf_counter() - t_start, breaker_tripped)
        return self._stats

    def _process_one(
        self,
        cover_path:      Path,
        template_img:    Image.Image,
        top_logo_img:    Image.Image | None,
        bottom_logo_img: Image.Image | None,
    ) -> CoverResult:
        """
        Open one cover (with OOM Hardening), resolve its game marquee,
        and delegate to the compositor.  All disk reads happen here.
        """
        from engine.compositor import render_cover

        # --- Cover: disk read + OOM Hardening ---
        cover_img = _safe_open(cover_path)

        # --- Game marquee: per-cover lookup + OOM Hardening ---
        game_logo_img = self._load_game_logo(cover_path.stem)

        return render_cover(
            cover_path   = cover_path,
            cover_img    = cover_img,
            covers_dir   = self.covers_dir,
            profile      = self.profile,
            options      = self.options,
            output_dir   = self.output_dir,
            game_logo    = game_logo_img,
            top_logo     = top_logo_img,
            bottom_logo  = bottom_logo_img,
            template_img = template_img,
        )

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

    def _report(self, total: int, elapsed: float,
                breaker_tripped: bool = False) -> None:
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
        if breaker_tripped:
            log.info("  Breaker   : TRIPPED — execution was aborted")
        log.info("  Time      : %.2fs  (~%.2fs/image processed)",
                 elapsed, elapsed / max(processed, 1))
        log.info("  Output    : %s", self.output_dir)
        log.info("-" * 62)
        if err_count:
            log.warning("%d error(s) — check the log for details", err_count)
