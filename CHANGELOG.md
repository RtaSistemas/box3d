# Changelog

All notable changes to box3d are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Expert audit report** (`EXPERT-REPORT.md`) — Full UX + implementation
  quality review covering 17 files / ~6,017 lines; 23 findings with
  file:line citations, evidence, and concrete recommendations. Includes
  Mermaid priority matrix and treatment-track flowchart.
- **`GET /api/version`** (`web/server.py`) — New endpoint returning
  `{"version": __version__}` sourced from `core/version.py`. Web UI
  version badge now fetches from this endpoint on boot instead of
  displaying a hardcoded string.
- **`core/version.py`** — Single canonical version string (`__version__
  = "3.0.0RC"`). `cli/main.py`, `cli/bootstrap.py`, and `web/server.py`
  all import from this module, eliminating the three divergent version
  strings (v2.0.0 / v2.1.0 / 3.0.0RC) that previously appeared across
  different surfaces.
- **`stop_event` parameter** on `RenderPipeline.run()` — Callers can
  pass a `threading.Event` for cooperative cancellation. `_process_one`
  checks the event before starting work and returns `status="skip"`;
  the `as_completed` loop cancels pending futures when the event is set.
  Replaces the previous pattern of raising `InterruptedError` inside the
  progress callback (which left pool threads running after the loop exited).
- **`asyncio.Lock` render mutex** (`web/server.py`) — `_render_lock`
  prevents concurrent render sessions. A second POST `/api/render` while
  one is in progress receives HTTP 409 `{"status":"busy"}` immediately,
  preventing the progress queue and `_last_output_dir` from being shared
  across sessions.
- **Dedicated render executor** (`web/server.py`) — `_render_executor`
  (single-thread `ThreadPoolExecutor`) reserved for the pipeline so that
  long renders do not hold a slot in asyncio's shared default pool.
- **`_VALID_VIPS_KERNELS` validation** (`engine/perspective.py`) —
  `BOX3D_WARP_BACKEND` is validated at module import time. Invalid values
  raise `ValueError` with the list of valid kernels immediately instead of
  crashing inside `pyvips.Interpolate.new()` during the first batch render.
- **LRU coordinate cache** (`engine/perspective.py`) — `_COORD_CACHE`
  is now an `OrderedDict` capped at `_COORD_CACHE_MAX=16` entries with
  LRU eviction, bounding memory growth in long-lived server processes.
- **Registry mtime cache** (`web/server.py`) — `_get_registry()` caches
  the `ProfileRegistry` and invalidates it only when `profiles/` directory
  mtime changes, avoiding a full disk scan on every API call.
- **Modal keyboard focus trap** (`web/ui/app.js`) — Summary modal receives
  focus on open; `Tab`/`Shift+Tab` is confined to modal buttons (WCAG 2.2
  §2.1.2 No Keyboard Trap).
- **`TestInputValidation`** (`tests/test_v2.py`) — 6 new tests covering
  `parse_rgb_str` edge cases (negative, above 5.0, wrong count, boundary
  values) and the version consistency invariant.
- **`test_stop_event_cancels_pipeline_cooperatively`** (`tests/test_v2.py`)
  — Verifies that a pre-set `stop_event` produces zero errors and zero
  successes for a two-cover batch (all covers skipped cooperatively).
- **`test_coord_cache_evicts_oldest_entry`** (`tests/test_v2.py`) —
  Verifies that `_COORD_CACHE` never exceeds `_COORD_CACHE_MAX` entries.

### Fixed

- **`Image.open` file handle leak** (`core/pipeline.py`) — `_safe_open`
  now uses `with Image.open(path) as raw:` to guarantee the file descriptor
  is released immediately after decode. Previously an implicit reference
  kept the handle open until GC, which could exhaust OS limits on Windows
  during large batches and prevent source file rename/delete operations.
- **Lock-safe circuit-breaker stats read** (`core/pipeline.py`) — The
  `total_errors` snapshot for the circuit-breaker percentage check is now
  read inside `self._lock`, consistent with all stat writes.
- **Marquees-directory warning spam** (`core/pipeline.py`) — The
  "Marquees directory not found" warning now fires only when the caller
  explicitly provided a `marquees_dir` path. For profiles that don't
  populate `assets/`, the default fallback path is silently skipped.
- **GUI cancellation via `InterruptedError`** (`gui/control_tab.py`) —
  Replaced exception injection into the progress callback with
  `stop_event`-based cooperative cancellation. Pool threads no longer
  continue after the loop exits.
- **`--blur-radius` upper bound** (`cli/main.py`) — CLI now validates
  `0 <= n <= 100` (was only `>= 0`), consistent with web and GUI bounds.
- **RGB matrix upper bound** (`cli/utils.py`, `web/server.py`) —
  `parse_rgb_str` rejects channel values outside `[0.0, 5.0]`. Web API
  Pydantic model uses `Annotated[float, Field(ge=0, le=5.0)]` per element.
- **`cover_fit` and `output_format` enum validation** (`web/server.py`) —
  Changed from `str | None` with description strings to
  `Literal["stretch","fit","crop"] | None` and `Literal["webp","png"]`.
  Invalid values now return HTTP 422 instead of silently defaulting.
- **CORS wildcard** (`web/server.py`) — Restricted to localhost/127.0.0.1
  origins only. `allow_origins=["*"]` on a server with filesystem endpoints
  allowed any web page to trigger renders or probe local paths.
- **`SpineLayout` and `Profile` are now frozen** (`core/models.py`) —
  Consistent with the `frozen=True` invariant already applied to all other
  domain dataclasses. All call sites already use `dataclasses.replace()`.
- **Designer spine layout rotation defaults** (`gui/designer_tab.py`) —
  Default rotation changed from `-90` to `0` (matching `LogoSlot.rotate`
  default). Import fallback also corrected. Previously an import+re-export
  round-trip silently changed `rotate=0` profiles to `-90`.
- **No-command startup notice** (`cli/main.py`) — Now prints an explicit
  `stdout` notice before starting uvicorn so users know a server launched
  on port 8000, independent of logging configuration.
- **SSE `onerror` false disconnects** (`web/ui/app.js`) — Handler now
  checks `readyState === EventSource.CLOSED` before reporting "connection
  lost". Transient `CONNECTING` states (browser auto-retrying) no longer
  close the stream prematurely or show false error messages.
- **Web UI version badge** (`web/ui/index.html`, `web/ui/app.js`) — Static
  `v2.1.0` replaced with dynamic fetch from `/api/version` on boot.
- **`parse_rgb_str` double-log** (`cli/utils.py`) — Removed internal
  `log.warning` from `parse_rgb_str`; error reporting consolidated at the
  call site in `cli/main.py`, eliminating duplicate log entries for a
  single user error.
- **Per-field GUI validation** (`gui/control_tab.py`) — Workers, Blur, and
  Darken are now parsed independently with field-specific error messages
  and range checks. Previously a single `except ValueError` showed the
  Workers error message for any of the three fields.
- **Output directory empty-string check** (`gui/control_tab.py`) — The
  check now runs before `Path(output_str)` construction and before the
  `mkdir` call, so it can actually trigger.

- **pyvips warp backend** (`engine/perspective.py`) — When `pyvips` is
  installed (`pip install -e ".[quality]"`), the perspective warp uses
  `pyvips.Image.mapim` with the `lbb` (locally bounded bicubic) interpolator
  instead of `PIL.Image.transform(BICUBIC)`.  `lbb` produces a smooth
  anti-aliased alpha gradient at quad boundaries (≥ 200 unique alpha values)
  versus PIL's binary 0/255 edge — eliminating stair-step aliasing at box
  outlines without post-warp blur.  Falls back to PIL automatically when
  `pyvips` is absent; no code changes required.
- **`BOX3D_WARP_BACKEND` env var** — Selects the pyvips interpolation kernel
  at process start: `lbb` (default) | `nohalo` (EWA, best quality for extreme
  distortions, ~1.7× slower) | `bicubic` | `bilinear`.
- **`quality = ["pyvips>=2.2"]`** optional dependency group in `pyproject.toml`.
- **`--collect-all pyvips --hidden-import pyvips`** added to the PyInstaller
  CLI build steps (Linux + Windows) in `release.yml` so the Python bindings
  are bundled; falls back to PIL automatically when `libvips` is absent.
- **Linear-light blending** (`engine/blending.py`) — All RGB blend operations
  now operate in linear light (IEC 61966-2-1 sRGB transfer function) rather
  than in gamma-encoded sRGB values.  Operating in sRGB causes Screen blend to
  over-brighten highlights and alpha compositing to darken mid-tones at
  partial-alpha boundaries.  A 256-entry float32 LUT (`_SRGB_TO_LINEAR`) makes
  the sRGB→linear conversion O(1) per pixel; the linear→sRGB inverse uses a
  vectorised `np.power` call, adding ≈ 3–5 ms per image.
- **`linear_alpha_composite()`** (`engine/blending.py`) — Public Porter-Duff
  'over' compositing function in linear light.  Used by the compositor's
  cover-over-spine step (step 2) where the lbb-feathered alpha boundary causes
  real partial-alpha blending.
- **`TestWarpBackend`** (`tests/test_v2.py`) — 18 regression tests for the
  pyvips/PIL warp backend: output contract, alpha smoothness (lbb ≥ 200 unique
  values vs PIL ≤ 3), PIL fallback mocking, coordinate-cache correctness,
  8-thread concurrency, edge cases.
- **`TestLinearAlphaComposite`** (`tests/test_v2.py`) — 6 tests for
  `linear_alpha_composite`: transparent dst, opaque src, transparent src,
  output mode/size, and the canonical linear-vs-sRGB brightness test.
- **`test_alpha_weighted_screen_uses_linear_space`** (`tests/test_v2.py`) —
  Verifies that Screen blend of two gray-128 inputs produces a result in the
  linear range (≈ 169) rather than the sRGB range (≈ 192), proving the blend
  is computed in linear light.

### Fixed

- **Silhouette edge aliasing** (`engine/compositor.py`) — `GaussianBlur
  (radius=1.0)` applied to the union silhouette mask before `dst_in` so the
  hard binary alpha of template PNGs is anti-aliased; eliminates the stair-step
  outline visible in previous releases.
- **Over-aggressive unsharp mask** (`engine/compositor.py`) — Reduced from
  `UnsharpMask(r=0.8, 40%, threshold=2)` to `r=0.6, 25%, threshold=3`;
  stronger values amplified RGB contrast at the feathered warp boundary, making
  aliasing more visible.
- **`.gitignore` malformed entries** — `.coverage` and `coverage.json` were
  stored as a single line with a literal `\n` (written by `echo`); now two
  separate lines under a `# Test coverage artefacts` header.

---

## [3.0.0RC] — 2026-04

### Added

- **`gui/config.py`** — Shared config persistence layer (`data/gui_config.json`).
  Both Control and Designer tabs load/save to the same flat JSON using merge-based
  writes so neither tab overwrites the other's keys.
- **Cancel render button** — `⏹ CANCEL` replaces the render button while a batch is
  running; uses `threading.Event` + `InterruptedError` raised inside `on_progress` so
  the pipeline exits cleanly without modifying `core/pipeline.py`.
- **Profile reload button (↻)** — Reloads the profile list from disk without
  restarting the application. Public `ControlTab.reload_profiles(select=)` method used
  by the install-profile cross-tab flow.
- **Designer canvas background picker** — `◉ Pick` button opens the OS native colour
  chooser; canvas background changes in real time. Colour is persisted under
  `dsn_canvas_bg` in the config file.
- **"Usar no Control" (install profile) flow** — Designer installs a profile to
  `profiles/<name>/`, then calls `App.reload_and_select_profile(name)` which reloads
  the registry and switches to the Control tab automatically.
- **`assets/box3d.ico`** — Multi-size (16–256 px) isometric cube icon for the Windows
  GUI executable. Embedded via `--icon assets/box3d.ico` in `release.yml`.
- **`tools/fix_template_alpha.py`** — Standalone PIL script that anti-aliases the alpha
  channel of a template PNG (threshold → GaussianBlur). Supports glob for all profiles.
- **"✦ Fix Template Alpha" button** in the Designer left panel; applies the same
  algorithm in-place and reloads the result into the canvas.

### Fixed

- **PyInstaller relative-import crash** (`gui/app.py`) — Changed all three `from .x`
  imports to absolute `from gui.x` imports so the frozen executable (where the module
  has no parent package) loads correctly.
- **GUI executable opens terminal/CMD** — Added `--noconsole` to both Linux and Windows
  GUI PyInstaller build steps in `release.yml`.
- **Live preview never showed images** — Two root causes fixed:
  1. `core/pipeline.py`: `stem` was `cover_path.stem` (filename only), so covers inside
     subdirectories produced output at `output/sub/game.webp` but the preview searched
     for `output/game.webp`. Now `stem` is the full relative path from `covers_dir`.
  2. `gui/control_tab.py`: `except Exception: pass` silently swallowed all failures;
     errors now appear in the progress log.
- **Designer config not persisted** — `DesignerTab.save_config()` and `_restore_config()`
  added with `dsn_`-prefixed keys; `_restore_config` deferred via `after(200, ...)` to
  ensure canvas is initialised before state is applied.
- **`save_config()` overwrote the other tab's settings** — Both tabs now use load →
  update → write (merge-based) to preserve keys belonging to the other tab.
- **Logo rotation aliasing** — `spine_builder.py`: `Image.rotate()` now uses
  `resample=Image.BICUBIC` (was defaulting to `NEAREST`, causing stair-step edges on
  non-90° rotated logos).

### Improved

- **Warp alpha feathering** (`engine/perspective.py`) — `GaussianBlur(radius=1.2)` on
  the alpha channel only after `Image.transform`; smooths the hard binary edge at quad
  boundaries without touching RGB content.
- **Cover resize LANCZOS** (`engine/perspective.py`) — `resize_for_fit` stretch mode
  changed from `BICUBIC` to `LANCZOS` for better high-frequency detail preservation.
- **Post-warp unsharp mask** (`engine/compositor.py`) — Mild `UnsharpMask(r=0.8, 40%,
  threshold=2)` applied to RGB only after cover warp, recovering softness introduced by
  perspective resampling; alpha is unchanged.

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

[Unreleased]:  https://github.com/RtaSistemas/box3d/compare/v3.0.0RC...HEAD
[3.0.0RC]:     https://github.com/RtaSistemas/box3d/compare/v2.1.0...v3.0.0RC
[2.1.0]:       https://github.com/RtaSistemas/box3d/compare/v2.0.0...v2.1.0
[2.0.0]:       https://github.com/RtaSistemas/box3d/compare/v2.0.0-rc1...v2.0.0
[2.0.0-rc1]:   https://github.com/RtaSistemas/box3d/releases/tag/v2.0.0-rc1
