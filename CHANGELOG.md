# Changelog

All notable changes to box3d are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_No unreleased changes._

---

## [2.1.0] — 2026-04

### Added

- **Desktop GUI — Designer Pro tab** (`gui/designer_tab.py`) — Visual profile geometry editor
  built natively into the `box3d-gui` desktop application. Full feature parity with the
  browser-based Designer Pro: template loading, spine/cover/logo/marquee object placement,
  quad-corner drag editing, spine-slot configuration, profile import/export, live JSON preview.
- **`gui/designer_engine.py`** — Pure canvas interaction engine (zero CustomTkinter widgets).
  Handles zoom-to-cursor (scroll wheel), pan (middle button, Space+drag), drag/resize with
  corner handles, snap-to-grid, arrow-key nudge (1 px / 10 px with Shift), hit-testing
  (ray-casting polygon containment), and profile import/export via `build_profile()` /
  `import_profile()`.
- **`gui/constants.py`** — Shared colour palette, font constants, and designer object colours
  extracted from `app.py` for reuse across all GUI modules.
- **`gui/control_tab.py`** — Control Center UI extracted from the monolithic `app.py` into a
  self-contained class (`ControlTab`), accepting an `on_status_change` callback.
- **Two-tab layout** in `gui/app.py` — `CTkTabview` with **Control** and **Designer** tabs;
  `app.py` reduced from 909 lines to ~130 lines.

### Fixed

- **Logo paths always `None` in GUI and web server** (issue #24) — `gui/control_tab.py` and
  `web/server.py` were hardcoding `logo_paths = {"top": None, "bottom": None}`, so
  `logo_top.png` / `logo_bottom.png` in a profile's `assets/` directory were silently ignored.
  Both modules now call `_auto_logo(profile.root / "assets", stem)` — matching the CLI
  behaviour that was already correct.

### Changed

- **`gui/app.py`** refactored from a 909-line monolith to a ~130-line thin shell. All
  application logic now lives in the focused module that owns it.
- **`pyproject.toml`** version bumped `2.0.0` → `2.1.0`.
- **`CLAUDE.md`** updated: version, test counts, module map, CLI defaults, new constraints.
- **`README.md`** updated: test counts, circuit breaker description, GUI section, Designer Pro
  section, architecture tree.

---

## [2.0.0] — 2026-03

### Added (SPRINT-UX-FINAL)

- **Default-serve behaviour** — running `box3d` with no subcommand now launches
  the web server on `127.0.0.1:8000` when the `[web]` extra is installed.
  Falls back to the help text otherwise.
- **`POST /api/open-folder`** — opens a directory in the OS native file manager
  (Finder on macOS, Explorer on Windows, xdg-open on Linux). Used by the
  `📂` buttons and the "Open Output Folder" button in the summary modal.
- **`GET /api/preview/{filename}`** — serves a rendered output image from
  `_last_output_dir` for in-browser preview. Path-sanitised (bare filename only).
- **`/designer/` static mount** — Box3D Designer Pro is now accessible at
  `http://127.0.0.1:8000/designer/` alongside the Control Center.
- **`rgb_matrix` on `RenderRequest`** — Control Center can now send RGB channel
  multipliers to the pipeline; the colour picker converts hex → `[r, g, b]` floats.
- **`first_stem` + `output_format` in SSE sentinel** — allows the UI to construct
  the preview URL after a successful render.
- **Spine-source `<select>`** in the Control Center — exposes `left / right / center`
  without requiring the CLI.
- **RGB colour picker** — `<input type="color">` with a normalised float readout
  and a ↺ reset button that returns to neutral (`1.0, 1.0, 1.0`).
- **`📂` folder buttons** next to each path input — click to open the typed path
  in the OS file manager via `POST /api/open-folder`.
- **Output preview image** in the summary modal — displays the first successfully
  rendered cover via `GET /api/preview/{stem}.{format}`.
- **"Open Output Folder" button** in the summary modal.
- **Header nav** in the Control Center — links to Control Center (active state)
  and to Designer Pro in a new tab.

### Removed (SPRINT-UX-FINAL)

- **`temp_dir` parameter** — `RenderPipeline.__init__` keeps `temp_dir` as a
  silent legacy keyword for API compatibility but no longer stores or uses it.
  `run()` no longer calls `self.temp_dir.mkdir()`.
- **`data/output/temp` bootstrap folder** — removed from `_bootstrap_data_dir()`.
  Box3D has used zero temp files since Sprint 3 (ADR-003); the directory was
  scaffolded but never written to.
- **`--temp` CLI flag** — removed from the `render` subparser.

---

### Added (SPRINT-PERF-BATCH-01)

- **Vectorised homography matrix** — `engine/perspective.py:build_matrix` now
  constructs the 8×8 system with NumPy array indexing instead of a Python loop.
- **`lru_cache` for perspective coefficients** — `solve_coefficients()` delegates
  to a cached inner function `_solve_cached(src_pts: tuple, dst_pts: tuple)`.
  Identical quad pairs (same-profile batch) are solved once.
- **`--workers auto`** — CLI accepts `"auto"` as a workers value (resolved via
  `os.cpu_count()`). `_workers_type()` argparse type handles the conversion.

---

### Added (SPRINT-API-FOUNDATION-01)

- **`RenderSummary` dataclass** in `core/models.py` — structured result object
  replacing the plain `dict[str, int]`. Fields: `total`, `succeeded`, `skipped`,
  `failed`, `dry`, `elapsed_time`, `errors`, `breaker_tripped`. `.to_dict()`
  returns a JSON-serialisable dict.
- **`on_progress` callback** on `RenderPipeline.run()` — fired after each cover
  completes; signature `(done: int, total: int, result: CoverResult) -> None`.
- **`print_summary()`** in `cli/main.py` — formats the `RenderSummary` for
  terminal display; decoupled from the pipeline.

---

### Added (SPRINT-WEB-BACKEND-01 / SPRINT-WEB-FRONTEND-01 / SPRINT-WEB-DOCS-QA-01 / SPRINT-DISTRIBUTION-FINAL)

- **`web/server.py`** — FastAPI server with CORS, SSE progress streaming, and
  a static mount for the Control Center UI.
- **`web/ui/`** — Control Center: vanilla JS SPA (`index.html`, `app.js`,
  `style.css`). No framework, no build step.
- **`box3d serve`** CLI command — starts Uvicorn; `--host` and `--port` flags.
- **`tests/test_web.py`** — `TestClient` tests for the API; uses
  `pytest.importorskip("fastapi")` so the suite is skipped when `[web]` is absent.
- **`httpx`** added to the `[web]` optional dependency group (required by
  Starlette `TestClient`).
- **PyInstaller packaging** — `release.yml` updated with `--add-data "web/ui:web/ui"`,
  `--add-data "tools:tools"`, and 10 `--hidden-import` flags for uvicorn/fastapi.

---

### Added (Designer Pro theme system)

- **Dark / Light / Retro themes** in `tools/box3d_designer_pro/index.html` — toggle
  from the toolbar; preference persisted in `localStorage`. Retro theme adds a CRT
  flicker animation on the logo. Version bumped to v1.3.0.

---

## [2.0.0-rc1] — 2026-03

### Added

- Plugin profile system (`profiles/` directory; zero code changes for new styles)
- Three built-in profiles: `mvs` (703×1000), `arcade` (665×907), `dvd` (633×907)
- Per-slot logo rotation (`LogoSlot.rotate` int degrees)
- Circuit breaker: aborts after 10 consecutive errors or > 20 % error rate
- `_safe_open()` — centralised OOM-hardened image loader (thumbnail ≤ 8 192 px)
- PyInstaller standalone executables (`_bundle_dir()` / `_data_dir()` split)
- `_bootstrap_data_dir()` — idempotent first-run folder creation
- `_bootstrap_profiles()` — copies built-in profiles to `<exe-dir>/profiles/` on first run
- `_bootstrap_instructions()` — generates `instructions.txt` on first run
- `profiles validate` command
- `designer` command (opens Designer Pro via `webbrowser.open()`)
- `--log-file ""` shorthand for the default log path
- Four ADRs in MADR format (boundary enforcement, OOM hardening, zero-disk-churn, alpha semantics)
- 49-test suite across 6 classes
- 35-variant visual regression runner
- CI matrix: Python 3.11 / 3.12 / 3.13 with `cancel-in-progress`
- Box3D Designer Pro self-contained visual editor

### Changed

- Architecture: monolithic script → strict `cli/` → `core/` → `engine/` tiers
- `build_spine()` accepts pre-loaded `PIL.Image` objects (no disk I/O in engine)
- OOM hardening extended to two independent layers (profile load + `_safe_open()`)
- `alpha_weighted_screen` output alpha corrected to `np.maximum(dst, src)` (union)
- `run.sh` / `test.sh`: `PYTHONPATH` corrected from non-existent `src/`

### Removed

- Intermediate spine temp files (replaced by in-memory `PIL.Image` transfer, ADR-003)
- `RenderOptions.with_logos` (logo control via `logo_paths={}`)
- `sys.path.insert` from `cli/main.py`

### Fixed

- PyInstaller output breakage (default paths now resolve to `<exe-dir>/data/`)
- `profiles validate` was a no-op
- `designer` command crashed (`subprocess.call` on non-existent file)
- `PYTHONPATH` in shell scripts pointed to non-existent `src/`
- `alpha_weighted_screen` docstring mismatch

---

## [1.x]

Version 1.x was a single-file script without plugin profiles, parallel rendering, or formal tests. No changelog was maintained for that series.

---

[Unreleased]: https://github.com/RtaSistemas/box3d/compare/v2.1.0...HEAD
[2.1.0]:      https://github.com/RtaSistemas/box3d/compare/v2.0.0...v2.1.0
[2.0.0]:      https://github.com/RtaSistemas/box3d/compare/v2.0.0-rc1...v2.0.0
[2.0.0-rc1]:  https://github.com/RtaSistemas/box3d/releases/tag/v2.0.0-rc1
