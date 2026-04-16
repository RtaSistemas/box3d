# CLAUDE.md — box3d AI Assistant Guide

## Project Overview

**box3d** (v2.0.0) is a Python CLI application that renders photorealistic 3D box art from flat game cover images. It warps front cover + spine images onto box templates using perspective transforms, composites them with RGBA templates, and outputs WebP/PNG files.

- **Language:** Python 3.11+
- **Runtime dependencies:** `Pillow >= 10.0`, `NumPy >= 1.24`
- **Optional extras:** `[dev]` pytest, `[web]` FastAPI + Uvicorn + httpx, `[gui]` CustomTkinter
- **Supported OS:** Linux, macOS, Windows (standalone .exe via PyInstaller)
- **License:** MIT

---

## Architecture

The codebase has a strict **3-tier layered architecture**. Never violate these boundaries:

```
cli/          ← Thin wiring layer: argparse → validation → core calls
  ↓
core/         ← Domain types + orchestration. No rendering logic. No I/O except pipeline.py
  ↓
engine/       ← Pure rendering primitives. No I/O. No profile knowledge. No state.
```

Optional components (`web/`, `gui/`) sit alongside this stack and call into `core/` directly.

### Module Map

| Module | Responsibility |
|---|---|
| `core/models.py` | Immutable frozen dataclasses (`Profile`, `RenderOptions`, `ProfileGeometry`, etc.) |
| `core/registry.py` | Profile discovery & lazy loading from filesystem |
| `core/pipeline.py` | Batch render orchestration (ThreadPoolExecutor). **Only module that reads/writes disk.** |
| `engine/perspective.py` | 8-coefficient perspective warp using numpy.linalg.solve + PIL BICUBIC |
| `engine/blending.py` | Alpha-weighted Screen blend, DstIn silhouette clipping, color matrix |
| `engine/spine_builder.py` | 2D spine strip generation (sample → blur → darken → logos) |
| `engine/compositor.py` | Entry point for single-cover composition (coordinates all engine modules) |
| `cli/main.py` | argparse setup, CLI command handlers (`render`, `profiles`, `designer`, `serve`), logging config |
| `cli/bootstrap.py` | First-run path resolution (PyInstaller-aware), folder creation, profile copying |
| `cli/utils.py` | `parse_rgb_str()` for "R,G,B" → color matrix conversion |
| `web/server.py` | Optional FastAPI HTTP API + SSE progress stream + static SPA mount |
| `gui/app.py` | Optional CustomTkinter desktop GUI with live preview |

### Profiles (Plugin System)

Profiles are self-contained directories in `profiles/<name>/`:
- `profile.json` — Geometry spec: template size, spine/cover quads, spine layout
- `template.png` — RGBA box template (user-editable copy is created on first run)
- `assets/` — Optional logo overlays (`logo_top.png`, `logo_bottom.png`, `logo_game.png`)

Built-in profiles: `mvs` (Neo Geo MVS), `arcade`, `dvd`

New profiles require **zero code changes** — drop a directory in `profiles/` and it's discovered automatically.

---

## Key Design Principles

1. **Engine modules are pure functions** — Accept `PIL.Image` objects, return `PIL.Image` objects. No disk I/O, no global state. Thread-safe by construction.

2. **I/O boundary is `core/pipeline.py` only** — All intermediate images live in RAM as `PIL.Image` objects. No temp files.

3. **OOM hardening at two independent layers:**
   - Profile load time: geometry validation (8192px hard ceiling)
   - Image load time: `_safe_open()` downscales inputs before loading; `resize_for_fit()` clamps target dims to 8192px

4. **Circuit breaker in pipeline:** Aborts batch if consecutive errors exceed `_CB_MAX_CONSECUTIVE = 10` OR total errors exceed `_CB_PCT_THRESHOLD = 20%` of processed files. The percentage branch requires a minimum of 3 errors before it can activate (prevents single bad files in small batches from aborting the run).

5. **Immutable domain models:** All dataclasses use `@dataclass(frozen=True)`.

6. **Path-traversal protection in registry:** Profile names must match `^[a-zA-Z0-9_-]+$` before any filesystem access.

7. **Cached homography:** `_solve_cached()` uses `@lru_cache` on perspective coefficients — identical quad geometry is computed only once per process.

8. **Contract assertions at engine boundaries:** `compose_cover()` and `build_spine()` validate RGBA mode, dimension bounds, and parameter ranges at call sites; fail fast on invalid state.

---

## Development Workflow

### Setup

```bash
# Core + tests only
pip install -e ".[dev]"

# With web server support
pip install -e ".[dev,web]"

# With desktop GUI support
pip install -e ".[dev,gui]"
```

### Running the CLI

```bash
# Via script (sets PYTHONPATH automatically)
./run.sh render --profile mvs

# Via installed entrypoint
box3d render --profile mvs

# Desktop GUI
box3d-gui

# Direct module
python -m cli.main render --profile mvs
```

### Running Tests

```bash
# Primary test suite (78 unit + integration tests) — always run this
pytest tests/test_v2.py -v

# Web API tests (requires [web] extra)
pytest tests/test_web.py -v

# Visual regression tests
python tests/run_visual_tests.py
python tests/run_visual_tests.py --open     # Open HTML report
python tests/run_visual_tests.py --workers 8

# CLI structural validation
./test_cli_variations.sh
```

### Data Directory Structure

On first run, the following structure is created (at project root in dev mode, next to executable in frozen mode):

```
data/
├── inputs/
│   ├── covers/     ← Input .webp/.png/.jpg cover images
│   └── marquees/   ← Optional per-game spine logos
└── output/
    ├── converted/  ← Rendered 3D box output
    ├── temp/       ← Pipeline scratch (currently unused)
    └── logs/       ← Log files (if --log-file used)
```

---

## Optional Components

### Web Control Center (`web/`)

Requires `pip install -e ".[web]"` (FastAPI, Uvicorn, httpx).

```bash
box3d serve                  # Default: http://127.0.0.1:8000
box3d serve --host 0.0.0.0 --port 9000
```

**API endpoints in `web/server.py`:**

| Method | Path | Description |
|---|---|---|
| GET | `/api/profiles` | List discovered profiles with dimensions |
| POST | `/api/validate-path` | Check directory existence |
| POST | `/api/render` | Start async batch render |
| GET | `/api/progress` | Server-Sent Events stream (real-time progress) |
| POST | `/api/open-folder` | Open native file manager |
| GET | `/api/preview/{filename}` | Serve rendered images |

Static mounts: `/designer/` → Designer Pro, `/` → Control Center SPA (`web/ui/`).

### Desktop GUI (`gui/`)

Requires `pip install -e ".[gui]"` (CustomTkinter).

```bash
box3d-gui
```

Full feature parity with the web Control Center. Dark theme, live preview, background threading + queue polling for real-time updates. Entry point: `gui/app.py:main`.

---

## CI/CD

### GitHub Actions

- **`ci.yml`** — Runs on push to `main` and all PRs. Tests Python 3.11, 3.12, 3.13 in matrix. Cancels in-flight runs on new commits.
- **`release.yml`** — Triggered by `v*` tags. Runs test gate first, then builds standalone executables for Windows x64 and Linux x64 via PyInstaller. Bundles: CLI + GUI executables, `profiles/`, `web/ui/`, `tools/`.

### Install command used in CI

```bash
pip install -e ".[dev]"
pytest tests/test_v2.py -v --tb=short
```

---

## Code Conventions

- **Python 3.11+** features allowed (`from __future__ import annotations` is used)
- **Type hints** throughout — maintain this on all new code
- **4-space indentation**, PEP 8 naming (`snake_case` functions, `CamelCase` classes)
- **Private helpers** prefixed with `_` (e.g., `_safe_open`, `_load_profile`)
- **Logging:** `log = logging.getLogger(__name__)` per module; use appropriate levels
- **No linter config files** in repo — follow existing style conventions
- **Test classes:** `Test*`; test methods: `test_*`; fixtures live in `tests/assets/`
- **Comments:** Mix of English and Portuguese found in existing code — either is acceptable

---

## Adding a New Profile

1. Create `profiles/<name>/` directory
2. Add `profile.json` with geometry spec (see existing profiles for schema)
3. Add `template.png` — RGBA box template image
4. Optionally add `assets/logo_top.png`, `assets/logo_bottom.png`, `assets/logo_game.png`
5. Run `pytest tests/test_v2.py -v` — the registry tests will detect it automatically

No code changes required.

### Profile JSON Schema

```json
{
  "name": "<profile-name>",
  "template_size": { "width": <int>, "height": <int> },
  "spine": { "width": <int>, "height": <int> },
  "cover": { "width": <int>, "height": <int> },
  "spine_quad": { "tl": [x,y], "tr": [x,y], "br": [x,y], "bl": [x,y] },
  "cover_quad": { "tl": [x,y], "tr": [x,y], "br": [x,y], "bl": [x,y] },
  "spine_layout": {
    "game":   { "max_w": <int>, "max_h": <int>, "center_y": <int>, "rotate": <deg> },
    "top":    { "max_w": <int>, "max_h": <int>, "center_y": <int>, "rotate": <deg> },
    "bottom": { "max_w": <int>, "max_h": <int>, "center_y": <int>, "rotate": <deg> },
    "logo_alpha": <0.0–1.0>
  }
}
```

All pixel coordinates are within the `template_size` canvas. No dimension may exceed 8192px.

---

## Common CLI Options Reference

```bash
box3d render --profile <name>
  --input <dir>           Source directory (default: data/inputs/covers)
  --output <dir>          Output directory (default: data/output/converted)
  --workers <n>           Parallel workers (default: 4)
  --blur-radius <n>       Spine background blur 0–50 (default: 8)
  --darken <f>            Spine darkness multiplier 0.0–1.0 (default: 0.55)
  --rgb <R,G,B>           RGB channel scaling (default: 1.0,1.0,1.0)
  --cover-fit <mode>      stretch | fit | crop (default: stretch)
  --spine-source <mode>   left | right | center  (cover edge used as spine background)
  --output-format <fmt>   webp | png (default: webp)
  --skip-existing         Skip already-rendered files
  --dry-run               Validate inputs without rendering
  --no-rotate             Disable cover rotation detection
  --no-logos              Skip spine logo overlays
  --verbose               DEBUG-level logging
  --log-file <path>       Write log to file

box3d profiles list       List all discovered profiles
box3d profiles validate   Check template.png exists for each profile
box3d designer            Open Box3D Designer Pro in browser
box3d serve               Start web Control Center (requires [web] extra)
  --host <ip>             Bind address (default: 127.0.0.1)
  --port <n>              Port (default: 8000)
```

---

## Visual Editor

`tools/box3d_designer_pro/index.html` is a self-contained browser UI for visually designing profile geometry (quad placement, spine layout). Open it directly in a browser — no server needed. Also served at `/designer/` when the web server is running.

---

## Important Constraints

- **Do not add I/O to engine modules** — they must remain pure rendering functions
- **Do not add rendering logic to core modules** — keep the layer separation
- **Do not add temp file writes** — all intermediate images stay in RAM
- **OOM ceiling is 8192px** — do not raise or remove this limit without a security review
- **Circuit breaker thresholds** (`_CB_MAX_CONSECUTIVE = 10`, `_CB_PCT_THRESHOLD = 0.20`, min 3 errors) are regression-tested — change only with justification
- **Profile path traversal checks in `registry.py`** — do not weaken the `^[a-zA-Z0-9_-]+$` validation
- **BUG-04 ordering:** `on_progress` is called *before* circuit breaker evaluation so the triggering item is always reported to the UI — preserve this ordering
