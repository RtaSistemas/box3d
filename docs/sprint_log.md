# Sprint Log — box3d v2

Delivery tracking for the v2.x hardening and feature cycle.
Each sprint had a single focused scope; work was validated by the full test suite
(`pytest tests/ -v`) before closing.

---

## SPRINT-GUI-DESIGNER-01 — Desktop GUI Designer Tab & Modular Split

**Scope:** `gui/app.py`, `gui/control_tab.py`, `gui/designer_tab.py`, `gui/designer_engine.py`,
           `gui/constants.py`, `web/server.py`, `pyproject.toml`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| GUI-1 | `gui/designer_tab.py` | Full visual profile geometry editor natively in the desktop app. Template loading, spine/cover/logo/marquee object placement, quad-corner drag editing, spine-slot configuration, profile import/export, live JSON preview. Full feature parity with the browser-based Designer Pro. |
| GUI-2 | `gui/designer_engine.py` | Pure canvas interaction engine (zero CustomTkinter widgets). Zoom-to-cursor (scroll wheel), pan (middle button or Space+drag), drag/resize with corner handles, snap-to-grid, arrow-key nudge (1 px / 10 px with Shift), hit-testing (ray-casting polygon containment), profile import/export via `build_profile()` / `import_profile()`. |
| GUI-3 | `gui/constants.py` | Shared colour palette, font constants, and designer object colours extracted from monolithic `app.py` for reuse across all GUI modules. |
| GUI-4 | `gui/control_tab.py` | Control Center UI extracted from the monolithic `app.py` into a self-contained `ControlTab` class accepting an `on_status_change` callback. |
| GUI-5 | Two-tab `gui/app.py` | `CTkTabview` with **Control** and **Designer** tabs; `app.py` reduced from ~909 lines to ~130 lines. |
| GUI-6 | Logo fix — issue #24 | `gui/control_tab.py` now calls `_auto_logo(profile.root / "assets", stem)` — logos in a profile's `assets/` directory are no longer silently ignored. Same fix applied in `web/server.py`. |
| GUI-7 | Version bump | `pyproject.toml` version `2.0.0` → `2.1.0`. |

### Acceptance criteria

- `pytest tests/test_v2.py -v` → **90 passed** (no regressions).
- `pytest tests/test_web.py -v` → **30 passed** (logo fix covered).
- `box3d-gui` opens a two-tab window: **Control** tab runs renders; **Designer** tab edits profiles visually.
- Logo files in `profiles/<name>/assets/` are applied correctly in both GUI and web server.

---

## SPRINT-UX-FINAL — UX Polish & temp_dir Eradication

**Scope:** `core/pipeline.py`, `cli/bootstrap.py`, `cli/main.py`, `web/server.py`,
           `web/ui/index.html`, `web/ui/app.js`, `web/ui/style.css`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| UX-1 | temp_dir eradication | `RenderPipeline.__init__` makes `temp_dir` a silent legacy kwarg; `run()` no longer calls `.mkdir()`. `cli/bootstrap.py` drops `output/temp` from the scaffold. `--temp` flag removed from CLI. |
| UX-2 | Default-serve behaviour | `main()` with no command tries to import uvicorn/web.server; if available, starts server on `127.0.0.1:8000`; if not, prints help. |
| UX-3 | `/api/open-folder` | Opens a directory in the OS native file manager (Finder / Explorer / xdg-open). |
| UX-4 | `/api/preview/{filename}` | Serves rendered output image from `_last_output_dir`; path-sanitised. |
| UX-5 | `/designer/` static mount | Designer Pro accessible at `http://127.0.0.1:8000/designer/` |
| UX-6 | `rgb_matrix` on `RenderRequest` | Control Center sends `[r, g, b]` floats; neutral picker suppressed to `null`. |
| UX-7 | `first_stem` + `output_format` in SSE sentinel | Enables the UI to construct the preview URL. |
| UX-8 | Spine-source select | `<select>` for `left / right / center` in the Control Center options panel. |
| UX-9 | RGB colour picker | `<input type="color">` with normalised float readout and reset button. |
| UX-10 | Folder buttons | `📂` next to each path input — calls `POST /api/open-folder` with the typed path. |
| UX-11 | Output preview in modal | First successfully rendered cover displayed via `GET /api/preview/`. |
| UX-12 | Header nav | Control Center / Designer Pro ↗ nav links in the header. |
| UX-13 | "Open Output Folder" button | Modal action button calls `/api/open-folder` with `null` (uses `_last_output_dir`). |

### Acceptance criteria

- `pytest tests/ -v` → **120 passed** (90 test_v2 + 30 test_web).
- `box3d` (no args) with `[web]` installed starts server on port 8000; without `[web]` prints help.
- `📂` buttons open the correct directory in the OS file manager.
- After a successful render, the summary modal shows a preview of the first output image.
- No `data/output/temp/` directory is created on first run.

---

## SPRINT-DISTRIBUTION-FINAL — `box3d serve` + PyInstaller Packaging

**Scope:** `cli/main.py`, `.github/workflows/release.yml`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| D-1 | `box3d serve` CLI command | `cmd_serve(args)` with `--host` and `--port`; defensive import of uvicorn/web.server |
| D-2 | PyInstaller packaging | `release.yml` updated: test gate includes `.[web]`; `--add-data "web/ui:web/ui"` and `--add-data "tools:tools"`; 10 `--hidden-import` flags for uvicorn/fastapi internals |

### Acceptance criteria

- `box3d serve` starts the FastAPI server; exits cleanly if `[web]` not installed.
- Standalone binary serves the Control Center at `http://127.0.0.1:8000`.

---

## SPRINT-WEB-DOCS-QA-01 — TestClient Suite + README/docs updates

**Scope:** `tests/test_web.py`, `pyproject.toml`, `README.md`, `docs/web_manual.md`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| QA-1 | `tests/test_web.py` | 30 `TestClient` tests across `TestGetProfiles`, `TestValidatePath`, `TestRenderEndpoint`, `TestProgressStream`, `TestOpenFolder`, `TestPreviewImage` |
| QA-2 | `pytest.importorskip` isolation | Module skipped automatically when `fastapi` not installed |
| QA-3 | `httpx` in `[web]` extra | Added to `pyproject.toml`; required by `starlette.testclient` |
| QA-4 | README web section | Architecture, API table, install instructions |
| QA-5 | `docs/web_manual.md` | Full user manual for the Control Center |

### Acceptance criteria

- `pytest tests/test_web.py -v` → **30 passed**.
- `pytest tests/test_v2.py tests/test_web.py -v` on a machine without `[web]` skips `test_web.py` gracefully.

---

## SPRINT-WEB-FRONTEND-01 — Control Center Browser UI

**Scope:** `web/ui/index.html`, `web/ui/app.js`, `web/ui/style.css`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| FE-1 | `index.html` | Two-panel SPA: sidebar (profile, paths, options) + progress panel (bar, log) |
| FE-2 | `app.js` | Boot → fetchProfiles; path validation on blur; SSE render loop; summary modal |
| FE-3 | `style.css` | Dark neon palette (`--accent: #00eaff`) matching Designer Pro |
| FE-4 | Real-time progress | `EventSource /api/progress`; one log line per cover; progress bar driven by SSE |
| FE-5 | Summary modal | Stats grid + circuit breaker indicator + error list |

### Acceptance criteria

- Profile dropdown populated on load; path inputs show green/red border.
- Progress bar and log update in real time during a batch render.
- Summary modal appears after sentinel event with correct stats.
- `_setRendering()` locks/unlocks all inputs atomically.

---

## SPRINT-WEB-BACKEND-01 — FastAPI Server with SSE Progress

**Scope:** `web/server.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| BE-1 | `GET /api/profiles` | Returns profile list with name + dimensions from the registry |
| BE-2 | `POST /api/validate-path` | Returns `{valid: bool}` — empty string fixed (`Path("").is_dir()` → cwd guard) |
| BE-3 | `GET /api/progress` | SSE generator polling `_progress_queue`; sentinel `done=-1` closes stream |
| BE-4 | `POST /api/render` | Profile + path validation → `asyncio.to_thread(_run_pipeline)` |
| BE-5 | Static UI mount | `StaticFiles(directory=_UI_DIR, html=True)` served at `/` |
| BE-6 | `_BUNDLE` path resolution | Correct in dev (`project root`) and in PyInstaller frozen build (`sys._MEIPASS`) |

### Acceptance criteria

- CORS enabled; all endpoints return JSON.
- `POST /api/render` returns `{"status": "started"}` within < 100 ms; render runs in background.
- SSE stream emits events until sentinel; sentinel carries full `RenderSummary` fields.

---

## SPRINT-API-FOUNDATION-01 — Observable Pipeline

**Scope:** `core/models.py`, `core/pipeline.py`, `cli/main.py`, `tests/test_v2.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| API-1 | `RenderSummary` dataclass | Structured result: `total`, `succeeded`, `skipped`, `failed`, `dry`, `elapsed_time`, `errors`, `breaker_tripped`, `.to_dict()` |
| API-2 | `on_progress` callback | `run(on_progress=None)`; fired after each cover; `(done, total, CoverResult)` |
| API-3 | `print_summary()` | CLI-only display of `RenderSummary`; decoupled from pipeline |
| API-4 | Test suite updated | All `stats["ok"]` → `stats.succeeded`, etc. across `TestPipeline` |

### Acceptance criteria

- `pytest tests/test_v2.py -v` → **52 passed** (at the time of this sprint).
- `RenderSummary.to_dict()` is JSON-serialisable.
- `on_progress` callback receives correct `done`/`total` counters.

---

## SPRINT-PERF-BATCH-01 — Vectorised Homography + LRU Cache + `--workers auto`

**Scope:** `engine/perspective.py`, `cli/main.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| P-1 | Vectorised matrix construction | `build_matrix()` uses `np.zeros((8,8))` with even/odd row indexing; no Python loop |
| P-2 | `lru_cache` for coefficients | `_solve_cached(src_pts: tuple, dst_pts: tuple)` cached with `maxsize=64`; public `solve_coefficients()` converts lists → tuples before delegating |
| P-3 | `--workers auto` | `_workers_type()` argparse type accepts int or `"auto"` → `os.cpu_count()` |

### Acceptance criteria

- All `TestPerspective` tests pass unchanged.
- `box3d render -p mvs --workers auto` resolves to `os.cpu_count()` threads.

---

## Sprint 5.1 — Plugin System & First-Run Experience

**Scope:** `cli/main.py`, `core/pipeline.py`, `tests/test_v2.py`, `README.md`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 5.1.1 | Game logo fallback | `_load_game_logo()` resolves marquees_dir → profile assets/logo_game.* → None; 3 new tests |
| 5.1.2 | Editable profiles/ bootstrap | `_bootstrap_profiles()` copies built-ins on first run; never overwrites existing |
| 5.1.3 | README revision | Architecture tree, scaffold filenames, JSON Schema `rotate` per slot, logo resolution order |
| 5.1.4 | `instructions.txt` generation | `_bootstrap_instructions()` writes a 4 KB plain-text quick-start guide on first run |

### Acceptance criteria

- `pytest tests/test_v2.py -v` → **52 passed**.
- First run creates `<exe-dir>/profiles/`, `<exe-dir>/data/` tree, and `<exe-dir>/instructions.txt`.
- Subsequent runs add only new built-in profiles; existing files are never overwritten.

---

## Sprint 5 — PyInstaller Readiness & Release Closure

**Scope:** `cli/main.py`, `core/models.py`, `core/pipeline.py`, `engine/blending.py`,
           `run.sh`, `test.sh`, `.github/workflows/release.yml`, `docs/`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 5.1 | PyInstaller path split | `_bundle_dir()` (read-only → `sys._MEIPASS`) + `_data_dir()` (writable → `<exe-dir>/data`) |
| 5.2 | Bootstrap on first run | `_bootstrap_data_dir()` creates data tree idempotently |
| 5.3 | PYTHONPATH corrected | `run.sh` / `test.sh` fixed from non-existent `src/` to project root |
| 5.4 | Circuit Breaker initial threshold | `_CB_MAX_CONSECUTIVE` was set to 2 in this sprint (historical); later corrected to 10 in the v2.0.0-rc1 hardening pass |
| 5.5 | ADR-004 alpha semantics | `alpha_weighted_screen` union alpha confirmed correct; test updated |
| 5.6 | `profiles validate` | Checks template existence + OOM bounds; exit code 1 on failure |
| 5.7 | Designer command fixed | `webbrowser.open(index.html)` replaces dead `subprocess.call(app.py)` |
| 5.8 | `with_logos` removed | Field removed from `RenderOptions`; logo control via `logo_paths={}` |
| 5.9 | Python 3.13 classifier | `pyproject.toml` classifiers aligned with CI matrix |

### Acceptance criteria

- All 49 tests pass.
- `profiles validate` returns correct exit codes.
- `designer` opens Designer Pro in browser without error.
- PyInstaller executable writes output to `<exe-dir>/data/output/converted/`.

---

## Sprint 4 — Peripheral Asset Hardening (Spine)

**Scope:** `engine/spine_builder.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 4.1 | OOM protection on logo loading | `PIL.Image.thumbnail` applied to every logo before compositing |
| 4.2 | Remove NumPy from transparency operations | Replaced `np.array` alpha compositing with `PIL.Image.putalpha` / `ImageChops.multiply` |

### Acceptance criteria

- All 7 `TestSpineBuilder` tests pass.
- Memory usage bounded by 8 192 px ceiling.

---

## Sprint 3 — Orchestration Optimization (Zero-Disk)

**Scope:** `engine/compositor.py`, `core/pipeline.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 3.1 | Remove intermediate disk writes | Eliminated `spine_tmp` temp-file pattern; `build_spine()` returns `PIL.Image` in RAM |
| 3.2 | Pre-loaded template singleton | `RenderPipeline` loads `template.png` once and passes it read-only to each worker |
| 3.3 | Thread-safe rendering contract | Verified `compositor.render_cover()` holds no shared mutable state |

### Acceptance criteria

- All 8 `TestPipeline` tests pass, including parallel and dry-run variants.
- No temporary files created during a batch run.

---

## Sprint 2 — Graphics Engine Hardening

**Scope:** `engine/blending.py`, `engine/perspective.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 2.1 | Eliminate redundant NumPy allocations | Replaced `np.zeros_like` / `np.ones_like` with in-place operations |
| 2.2 | Migrate color transforms to Pillow C | `apply_color_matrix()` uses `PIL.ImageMath`; removed NumPy diagonal path |
| 2.3 | Preventive downscale on warp inputs | `resize_for_fit()` calls `thumbnail((8192, 8192))` before perspective coefficients |

### Acceptance criteria

- All 9 `TestPerspective` and 9 `TestBlending` tests pass.
- A 16 000 × 16 000 input is downscaled without `MemoryError`.

---

## Sprint 1 — Foundation & Ingestion Security

**Scope:** `core/models.py`, `core/registry.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 1.1 | Strict type validation | Every field in `registry._load_profile()` validated with `isinstance` |
| 1.2 | Path-traversal mitigation | Profile names validated against `^[a-zA-Z0-9_-]+$`; symlink-following prevented |
| 1.3 | OOM boundary in domain model | `ProfileGeometry.__post_init__` raises `ValueError` for dimensions > 8 192 px |
| 1.4 | Graceful degradation | Deserialization errors caught per profile; remaining profiles continue loading |

### Acceptance criteria

- All 13 `TestRegistry` tests pass, including path-traversal and malformed-profile tests.
- All 3 `TestModels` tests pass, including OOM boundary assertion.
