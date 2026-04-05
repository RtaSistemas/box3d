# CLAUDE.md — box3d AI Assistant Guide

## Project Overview

**box3d** is a Python CLI application that renders photorealistic 3D box art from flat game cover images. It warps front cover + spine images onto box templates using perspective transforms, composites them with RGBA templates, and outputs WebP/PNG files.

- **Language:** Python 3.11+
- **Runtime dependencies:** `Pillow >= 10.0`, `NumPy >= 1.24`
- **Dev dependencies:** `pytest >= 8.0`
- **Supported OS:** Linux, macOS, Windows (standalone .exe via PyInstaller)

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
| `cli/main.py` | argparse setup, CLI command handlers, logging config |
| `cli/bootstrap.py` | First-run path resolution (PyInstaller-aware), folder creation, profile copying |
| `cli/utils.py` | `parse_rgb_str()` for "R,G,B" → color matrix conversion |

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
   - Image load time: `_safe_open()` downscales inputs before loading

4. **Circuit breaker in pipeline:** Aborts batch after 2 consecutive errors OR errors exceed 20% of processed files.

5. **Immutable domain models:** All dataclasses use `@dataclass(frozen=True)`.

6. **Path-traversal protection in registry:** Profile names are validated before filesystem access.

---

## Development Workflow

### Setup

```bash
pip install -e ".[dev]"
```

### Running the CLI

```bash
# Via script (sets PYTHONPATH automatically)
./run.sh render --profile mvs

# Via installed entrypoint
box3d render --profile mvs

# Direct module
python -m cli.main render --profile mvs
```

### Running Tests

```bash
# Primary test suite (52 unit + integration tests) — always run this
pytest tests/test_v2.py -v

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

## CI/CD

### GitHub Actions

- **`ci.yml`** — Runs on push to `main` and all PRs. Tests Python 3.11, 3.12, 3.13 in matrix. Cancels in-flight runs on new commits.
- **`release.yml`** — Triggered by `v*` tags. Runs test gate first, then builds standalone executables for Windows x64 and Linux x64 via PyInstaller.

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
  --spine-source <mode>   auto | cover | marquee
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
```

---

## Visual Editor

`tools/box3d_designer_pro/index.html` is a self-contained browser UI for visually designing profile geometry (quad placement, spine layout). Open it directly in a browser — no server needed.

---

## Important Constraints

- **Do not add I/O to engine modules** — they must remain pure rendering functions
- **Do not add rendering logic to core modules** — keep the layer separation
- **Do not add temp file writes** — all intermediate images stay in RAM
- **OOM ceiling is 8192px** — do not raise or remove this limit without a security review
- **Circuit breaker thresholds** (2 consecutive errors, 20% threshold) are load-tested — change only with justification
- **Profile path traversal checks in `registry.py`** — do not weaken this validation
