<img width="1920" height="1032" alt="Control" src="https://github.com/user-attachments/assets/32d9fe97-b66a-4c01-8990-0813e4a60ccd" />
# box3d

[![CI](https://github.com/RtaSistemas/box3d/actions/workflows/ci.yml/badge.svg)](https://github.com/RtaSistemas/box3d/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**3D box art renderer for retro game collections — plugin profiles, pure Python, optional web UI.**

`box3d` takes flat front-cover images and renders them as photorealistic 3D boxes: warped spine, logo overlays, baked shading — ready for EmulationStation, Pegasus, or any launcher that supports boxart.

```
covers/sf2.webp  +  profiles/mvs/  →  output/sf2.webp
```

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Web Control Center](#web-control-center)
- [Architecture](#architecture)
- [Compositing Pipeline](#compositing-pipeline)
- [Profiles](#profiles)
- [Box3D Designer Pro](#box3d-designer-pro)
- [Testing](#testing)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **Plugin profiles** | Add new box styles by dropping a directory into `profiles/` — zero code changes |
| **Web Control Center** | Browser UI: profile selector, path validation, live progress, preview, file-manager integration |
| **Parallel rendering** | `ThreadPoolExecutor` with configurable workers; `--workers auto` uses all CPU cores |
| **Cached homography** | Perspective coefficients are cached with `lru_cache`; identical quads are computed once |
| **Batch circuit breaker** | Aborts after 10 consecutive errors or when errors exceed 20 % of processed files |
| **OOM hardening** | Hard 8 192 px ceiling at two independent layers; immune to pixel-bomb inputs |
| **Zero-disk-churn** | All intermediate images live in RAM as `PIL.Image` objects — no temp files |
| **Pure Python core** | Pillow ≥ 10 and NumPy ≥ 1.24 only — no external binaries required |
| **Visual profile editor** | Box3D Designer Pro: browser-based and native GUI authoring tool, Dark/Light/Retro themes |
| **Desktop GUI** | CustomTkinter app with Control + Designer tabs — no browser required |
| **Standalone executables** | PyInstaller `--onefile` builds for Linux x86-64 and Windows x86-64 |
| **Multiple output formats** | WebP (q 92, default) or lossless PNG |
| **Incremental batches** | `--skip-existing` skips already-rendered outputs |
| **Dry-run validation** | `--dry-run` validates inputs and reports without writing any files |

---

## Requirements

| Component | Version |
|---|---|
| Python | 3.11 or later |
| Pillow | ≥ 10.0 |
| NumPy | ≥ 1.24 |
| OS | Linux · macOS · Windows |
| **Web extra** (optional) | FastAPI ≥ 0.111, Uvicorn ≥ 0.29, httpx ≥ 0.27 |

---

## Installation

### Development install

```bash
git clone https://github.com/RtaSistemas/box3d.git
cd box3d

python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .            # Pillow + NumPy only — full CLI
```

### With web Control Center

<img width="1918" height="912" alt="Control Center" src="https://github.com/user-attachments/assets/b166634a-9532-4d87-bf92-008f9a301eda" />

<img width="520" height="638" alt="result" src="https://github.com/user-attachments/assets/bb01f8db-8907-4153-a645-ea2a9c97a249" />

```bash
pip install -e ".[web]"     # adds FastAPI + Uvicorn + httpx
```

### With desktop GUI

<img width="1920" height="1032" alt="Control" src="https://github.com/user-attachments/assets/6574f9ec-136d-4cfa-ab8c-1ffafb8460f2" />

<img width="1920" height="1032" alt="Designer" src="https://github.com/user-attachments/assets/2f5eb802-444e-43d8-9be8-267c8e0ed49d" />



```bash
pip install -e ".[gui]"     # adds CustomTkinter
box3d-gui                   # opens two-tab window: Control + Designer
```

### With dev dependencies (tests)

```bash
pip install -e ".[dev]"
```

### Pre-built standalone executables

No Python required. Download from the [Releases page](https://github.com/RtaSistemas/box3d/releases):

| Platform | Asset |
|---|---|
| Linux x86-64 | `box3d-linux-x64` |
| Windows x86-64 | `box3d-windows-x64.exe` |

On first launch the executable automatically creates the directory structure it needs next to itself.

---

## Quick Start

### CLI

```bash
# Drop flat cover images into the default input directory
cp /path/to/covers/*.webp data/inputs/covers/

# Render with the MVS (Neo Geo) profile
box3d render --profile mvs

# Output appears in data/output/converted/
```

### Web Control Center

```bash
pip install -e ".[web]"

# Launch the server (or just run `box3d` with no arguments)
box3d serve

# Open http://127.0.0.1:8000 in your browser
```

Running `box3d` with **no subcommand** automatically starts the web server if the `[web]` extra is installed. If it is not installed, the help text is shown instead.

### Desktop GUI

```bash
pip install -e ".[gui]"
box3d-gui
```

The GUI has two tabs:
- **Control** — same functionality as the web Control Center (profile selector, paths, render options, live preview)
- **Designer** — visual profile editor (drag quads, edit spine slots, import/export `profile.json`)

<img width="1914" height="920" alt="box3d_gui" src="https://github.com/user-attachments/assets/881a3da2-3704-4fae-810f-e29e8ac105f8" />


### Dry-run (validate without rendering)

```bash
box3d render --profile mvs --dry-run --verbose
```

---

## CLI Reference

### Global options

These apply to **all commands** and must appear **before** the subcommand.

```
box3d [global options] <command> [command options]
```

| Option | Default | Description |
|---|---|---|
| `--profiles-dir` | `profiles/` next to the exe | Path to the profiles directory |
| `--verbose` / `-v` | — | Enable DEBUG-level logging |
| `--log-file` | — | Write log to a file (`""` uses `data/output/logs/box3d.log`) |

---

### `render`

Renders all cover images in the input directory using the specified profile.

```
box3d render --profile <name> [options]
```

| Option | Short | Default | Description |
|---|---|---|---|
| `--profile` | `-p` | *(required)* | Profile name (must exist in `profiles/`) |
| `--input` | `-i` | `data/inputs/covers/` | Source directory containing cover images |
| `--output` | `-o` | `data/output/converted/` | Output directory |
| `--workers` | `-w` | `4` | Parallel threads, or `auto` for `os.cpu_count()` |
| `--blur-radius` | `-b` | `20` | Gaussian blur on spine background (`≥ 0`) |
| `--darken` | `-d` | `180` | Spine dark overlay alpha (`0`–`255`) |
| `--rgb` | `-R` | `1.0,1.0,1.0` | RGB channel multipliers, comma-separated (e.g. `0.9,0.9,1.1`) |
| `--cover-fit` | `-c` | *(profile default)* | `stretch` · `fit` · `crop` |
| `--spine-source` | | *(profile default)* | Edge sampled for spine: `left` · `right` · `center` |
| `--no-rotate` | `-r` | — | Disable logo rotation on the spine |
| `--no-logos` | `-l` | — | Skip all spine logo overlays |
| `--top-logo` | | — | Override path to top spine logo |
| `--bottom-logo` | | — | Override path to bottom spine logo |
| `--marquees-dir` | | `data/inputs/marquees/` | Per-game marquee directory |
| `--output-format` | `-f` | `webp` | `webp` or `png` |
| `--skip-existing` | `-s` | — | Skip covers that already have an output file |
| `--dry-run` | | — | Validate inputs without writing any files |

**Examples:**

```bash
# Render all covers with 8 workers, PNG output
box3d render -p arcade -w 8 --output-format png

# Tinted spine (slight blue shift)
box3d render -p mvs --blur-radius 30 --darken 200 --rgb 0.85,0.85,1.0

# Incremental — only process new covers
box3d render -p dvd --skip-existing

# Use all available CPU cores
box3d render -p mvs --workers auto
```

---

### `profiles`

```bash
box3d profiles list       # List all discovered profiles with dimensions
box3d profiles validate   # Verify each profile's template.png exists and geometry is within OOM bounds
```

---

### `serve`

Starts the Box3D Web Control Center (requires the `[web]` extra).

```
box3d serve [--host HOST] [--port PORT]
```

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | TCP port |

```bash
box3d serve                           # http://127.0.0.1:8000
box3d serve --host 0.0.0.0 --port 9000  # expose on LAN
```

> Running `box3d` with no subcommand is equivalent to `box3d serve` when the `[web]` extra is installed.

---

### `designer`

Opens Box3D Designer Pro in the default browser.
<img width="1918" height="860" alt="designer" src="https://github.com/user-attachments/assets/2ccc36bf-9b48-4e8a-9085-26a8599f9b07" />

```bash
box3d designer
```

The Designer Pro is also reachable at `http://127.0.0.1:8000/designer/` when the web server is running.

---

## Web Control Center

A browser-based graphical interface for running render jobs without the CLI.

### Start

```bash
pip install -e ".[web]"
box3d serve
# Open http://127.0.0.1:8000
```

### Features

| Panel | What it does |
|---|---|
| **Profile** | Dropdown auto-populated from `profiles/`; shows template dimensions |
| **Paths** | Three path inputs (covers / output / marquees) with real-time directory validation; `📂` button opens each folder in the native file manager |
| **Options** | Workers, blur radius, darken alpha, cover fit, spine source, output format, RGB tint picker |
| **RGB tint** | Colour picker maps to `[r, g, b]` channel multipliers; neutral (#808080) sends `null` (no tinting) |
| **Start Render** | Locked while rendering; sends `POST /api/render` then opens an SSE stream |
| **Live progress** | Progress bar + per-cover log driven by real-time Server-Sent Events |
| **Summary modal** | Post-render stats, first-output preview image, and "Open Output Folder" button |
| **Designer Pro nav** | Header link opens the visual profile editor in a new tab |

### API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/profiles` | `GET` | List profiles with name and dimensions |
| `/api/validate-path` | `POST` | Check if a path resolves to an existing directory |
| `/api/render` | `POST` | Start a render job (returns immediately) |
| `/api/progress` | `GET` | SSE stream of per-cover progress events |
| `/api/open-folder` | `POST` | Open a directory in the OS file manager |
| `/api/preview/{filename}` | `GET` | Serve a rendered output image for in-browser preview |
| `/designer/` | static | Box3D Designer Pro embedded in the server |

Interactive Swagger docs: `http://127.0.0.1:8000/docs`

> Full user manual: [`docs/web_manual.md`](docs/web_manual.md)

---

## Architecture

```
box3d/
├── cli/
│   ├── main.py          ← argparse wiring, command handlers, logging setup
│   ├── bootstrap.py     ← PyInstaller-aware path resolution (_BUNDLE, _DATA, _PROFILES)
│   │                       first-run folder creation and profile copying
│   └── utils.py         ← parse_rgb_str() helper
│
├── core/                ← Domain types and orchestration — no rendering logic
│   ├── models.py        ← Frozen dataclasses: Profile, RenderOptions, RenderSummary, …
│   ├── registry.py      ← Plugin discovery, JSON validation, path-traversal protection
│   └── pipeline.py      ← Batch render orchestrator (ThreadPoolExecutor + circuit breaker)
│
├── engine/              ← Pure rendering primitives — no I/O, no profiles, no global state
│   ├── perspective.py   ← 8-coefficient perspective warp (numpy.linalg.solve + lru_cache)
│   ├── blending.py      ← alpha_weighted_screen, dst_in, build_silhouette_mask
│   ├── spine_builder.py ← 2-D spine strip: sample → blur → darken → logo composite
│   └── compositor.py    ← Per-cover entry point; coordinates all engine modules
│
├── web/                 ← Optional FastAPI backend (pip install .[web])
│   ├── server.py        ← REST + SSE API; static mounts for UI and Designer Pro
│   └── ui/
│       ├── index.html   ← Control Center SPA (vanilla JS, no build step)
│       ├── app.js       ← Fetch + EventSource client logic
│       └── style.css    ← Dark neon palette matching Designer Pro
│
├── gui/                 ← Optional desktop GUI (pip install .[gui], CustomTkinter)
│   ├── app.py           ← Thin entry point: header + CTkTabview wiring
│   ├── constants.py     ← Shared colour palette and font constants
│   ├── control_tab.py   ← Control Center tab (render pipeline, live preview)
│   ├── designer_tab.py  ← Designer Pro tab (canvas UI, profile I/O)
│   └── designer_engine.py ← Pure canvas engine (zoom/pan, quad editing, hit-testing)
│
├── profiles/            ← Plugin bundles (JSON + template + assets)
│   ├── mvs/             ← Neo Geo MVS cartridge  703 × 1 000 px
│   │   ├── profile.json
│   │   ├── template.png
│   │   └── assets/
│   │       ├── logo_top.png
│   │       ├── logo_bottom.png
│   │       └── logo_game.png
│   ├── arcade/          ← Arcade cabinet  665 × 907 px
│   └── dvd/             ← DVD case  633 × 907 px
│
├── tools/
│   └── box3d_designer_pro/
│       └── index.html   ← Self-contained visual profile editor (v1.3.0)
│
└── tests/
    ├── test_v2.py       ← 90 unit + integration tests
    ├── test_web.py      ← 30 FastAPI / SSE tests (skipped if [web] not installed)
    ├── run_visual_tests.py
    └── assets/          ← Fixtures: cover, marquee, logos, templates
```

### Design Principles

**1. Three-tier layered architecture.**  
`cli/` parses and validates, `core/` orchestrates, `engine/` renders. No cross-layer imports in the wrong direction.

**2. Profiles as zero-code plugins.**  
Drop a directory containing `profile.json` + `template.png` into `profiles/` and it is immediately discovered. The registry applies strict validation (`^[a-zA-Z0-9_-]+$` name regex, type checking on every field) before any profile reaches the engine.

**3. Pure-function rendering.**  
Every `engine/` function accepts `PIL.Image` objects and returns `PIL.Image` objects. No disk I/O, no global state, no side effects. Thread-safe by construction.

**4. Defense-in-depth memory safety.**  
OOM protection exists at two independent layers: profile load time (geometry validation, hard 8 192 px ceiling) and image open time (`_safe_open()` applies `.thumbnail()`). A pathological input cannot exhaust RAM even if one layer is bypassed.

**5. Zero-disk-churn.**  
All intermediate images (spine strip, warped cover, blended result) are `PIL.Image` objects in RAM. The only writes are the final output files. No temp directories.

**6. Observable pipeline.**  
`RenderPipeline.run()` accepts an `on_progress` callback invoked after each cover completes. The web server uses this to push SSE events without polling.

---

## Compositing Pipeline

Each cover goes through five steps inside `engine/compositor.py`:

```
transparent canvas  (template_size)
        │
        ├─ 1. Perspective warp — spine strip
        │       build_spine() → warp(spine_quad)
        │
        ├─ 2. Perspective warp — front cover
        │       resize_for_fit(mode) → warp(cover_quad)
        │
        ├─ 3. Alpha-weighted Screen blend — template overlay
        │       alpha_weighted_screen(canvas, template)
        │
        ├─ 4. DstIn — clip to union silhouette
        │       build_silhouette_mask() → dst_in(canvas, mask)
        │
        └─ 5. Save  (WebP q 92  or  PNG lossless)
```

**Alpha-weighted Screen blend (step 3):** Standard Screen blend washes out dark covers because near-transparent template pixels still contribute luminance. Weighting by `template_alpha / 255` means zero contribution where the template is fully transparent — the correct physical model.

**Union silhouette for DstIn (step 4):** The MVS profile uses a mostly-transparent template. Keying DstIn only on template alpha would erase the cover face. The union (`max`) of template alpha and canvas alpha is used as the clip mask, preserving the cover regardless of template transparency.

---

## Profiles

### Built-in profiles

| Name | Box style | Template size | Cover fit | Spine source |
|---|---|---|---|---|
| `mvs` | Neo Geo MVS cartridge | 703 × 1 000 px | stretch | left |
| `arcade` | Arcade cabinet | 665 × 907 px | stretch | left |
| `dvd` | DVD case | 633 × 907 px | stretch | left |

### Folder structure

```
profiles/ps2/
├── profile.json          ← required
├── template.png          ← required (RGBA, max 8 192 × 8 192 px)
└── assets/               ← optional
    ├── logo_top.png      ← placed at top of spine
    ├── logo_bottom.png   ← placed at bottom of spine
    └── logo_game.png     ← fallback if no per-game marquee is found
```

Supported extensions for logo files: `.png`, `.webp`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`.

### Game logo resolution order

For each cover, the game logo on the spine is resolved in this order:

1. `data/inputs/marquees/<cover-stem>.*` — per-game marquee matched by filename stem.
2. `profiles/<name>/assets/logo_game.*` — profile-level fallback.
3. `None` — spine rendered without a game logo.

### Creating a profile

#### Step 1 — Scaffold

```
profiles/ps2/
├── profile.json
└── template.png
```

#### Step 2 — Author `profile.json`

```json
{
  "name": "ps2",
  "description": "PlayStation 2 DVD case",
  "version": "1.0.0",
  "template_size": { "width": 550, "height": 770 },
  "spine": { "width": 55, "height": 690 },
  "cover": { "width": 430, "height": 690 },
  "spine_quad": {
    "tl": [4,  40], "tr": [59, 22],
    "br": [59, 748], "bl": [4, 730]
  },
  "cover_quad": {
    "tl": [59,  22], "tr": [490,  68],
    "br": [490, 702], "bl": [ 59, 748]
  },
  "spine_source_frac": 0.20,
  "spine_source": "left",
  "cover_fit": "stretch",
  "spine_layout": {
    "game":   { "max_w": 45, "max_h": 240, "center_y": 350 },
    "top":    { "max_w": 45, "max_h":  90, "center_y": 110 },
    "bottom": { "max_w": 45, "max_h":  60, "center_y": 620 },
    "logo_alpha": 0.85,
    "rotate_logos": true
  }
}
```

#### Step 3 — Visual alignment with Designer Pro

```bash
box3d designer
# or navigate to http://127.0.0.1:8000/designer/ when the server is running
```

Load your `template.png`, position the quads, export `profile.json`.

#### Step 4 — Test

```bash
box3d render --profile ps2 --dry-run --verbose
box3d render --profile ps2 --input tests/assets/ --output /tmp/ps2-test/
```

### Profile JSON Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Identifier (must match directory name) |
| `description` | string | no | Human-readable description |
| `version` | string | no | Semver string |
| `template_size` | `{width, height}` | yes | Pixel dimensions of `template.png` (max 8 192 px) |
| `spine` | `{width, height}` | yes | Logical spine strip dimensions |
| `cover` | `{width, height}` | yes | Logical cover dimensions |
| `spine_quad` | `{tl, tr, br, bl}` | yes | Spine warp target quad in template space |
| `cover_quad` | `{tl, tr, br, bl}` | yes | Cover warp target quad in template space |
| `spine_source_frac` | float | no | Fraction of cover width to sample (default `0.20`) |
| `spine_source` | `left\|right\|center` | no | Cover edge sampled for spine background |
| `cover_fit` | `stretch\|fit\|crop` | no | How the cover fills the `cover` quad |
| `spine_layout.game` | `{max_w, max_h, center_y}` | yes | Game-logo slot |
| `spine_layout.top` | `{max_w, max_h, center_y}` | no | Top-logo slot |
| `spine_layout.bottom` | `{max_w, max_h, center_y}` | no | Bottom-logo slot |
| `spine_layout.logo_alpha` | float 0–1 | no | Logo opacity (default `0.85`) |
| `spine_layout.*.rotate` | int (degrees) | no | Rotation per slot (negative = CW) |

Each quad point is `[x, y]` in pixel coordinates within `template_size`.

### Custom profiles directory

```bash
# Load profiles from any path
box3d --profiles-dir ~/my-profiles render --profile ps2

# Windows executable
.\box3d-windows-x64.exe --profiles-dir C:\MyProfiles render --profile ps2
```

---

## Standalone executable — first run

On first launch, the executable creates the entire working tree next to itself:

```
<exe-directory>/
├── profiles/                ← editable copy of built-in profiles
│   ├── mvs/
│   │   ├── profile.json
│   │   ├── template.png
│   │   └── assets/
│   ├── arcade/
│   └── dvd/
├── data/
│   ├── inputs/
│   │   ├── covers/          ← drop your flat cover images here
│   │   └── marquees/        ← per-game spine logos (matched by filename stem)
│   └── output/
│       ├── converted/       ← rendered 3-D box art written here
│       └── logs/            ← log files when --log-file is used
└── instructions.txt         ← generated quick-start guide
```

> Future updates add new built-in profiles to `profiles/` automatically without overwriting your edits.

---

## Box3D Designer Pro

A visual editor for authoring and editing profiles. Available in two forms:

**Browser version** (`tools/box3d_designer_pro/index.html`)
- No server, no build step — open directly in any browser, or navigate to `/designer/` when the Control Center is running.
- Dark / Light / Retro themes — toggle from the toolbar; preference is saved in `localStorage`.

**Native GUI version** (built into `box3d-gui`, **Designer** tab)
- No browser required — available directly in the desktop application alongside the Control Center.
- Same capabilities: load any PNG/WebP template, drag spine/cover/logo/marquee objects, edit quad corners precisely, configure spine layout slots, real-time JSON preview, import/export `profile.json`.

```bash
box3d designer          # opens browser Designer Pro
box3d-gui               # opens desktop app (select Designer tab)
```

---

## Testing

### Unit and integration tests

```bash
pytest tests/test_v2.py -v
```

Expected: **90 tests passed**.

### Web API tests

```bash
pytest tests/test_web.py -v    # skipped automatically if [web] extra not installed
```

Expected: **30 tests passed**.

### Full suite

```bash
pytest tests/ -v               # 120 tests total
```

### Test coverage breakdown

| Class | Tests | Scope |
|---|---|---|
| `TestModels` | 3 | Frozen dataclass invariants, OOM boundary |
| `TestRegistry` | 13 | Profile discovery, JSON validation, custom dirs, path-traversal rejection |
| `TestPerspective` | 9 | Warp correctness, stretch/fit/crop modes, all built-in profiles |
| `TestBlending` | 9 | Screen blend, DstIn, color matrix, silhouette mask |
| `TestSpineBuilder` | 7 | Spine generation for all built-in profiles |
| `TestPipeline` | 8 | End-to-end batch render, dry-run, worker scaling |
| `TestGameLogoFallback` | 3 | Marquee priority, profile fallback, absent logo |
| `TestCaching` | ... | `lru_cache` hit/miss for perspective coefficients |
| `TestGetProfiles` | 5 | `/api/profiles` — status, schema, built-ins, OOM limit |
| `TestValidatePath` | 5 | `/api/validate-path` — valid dir, missing, file, empty, 422 |
| `TestRenderEndpoint` | 4 | `/api/render` — unknown profile, bad dir, started, 422 |
| `TestProgressSSE` | 8 | `/api/progress` — SSE stream delivery and event format |
| `TestPreviewEndpoint` | 8 | `/api/preview/{filename}` — file serving, not-found, format |

### Visual regression tests

```bash
python tests/run_visual_tests.py
python tests/run_visual_tests.py --open    # open HTML report
python tests/run_visual_tests.py --workers 8
```

Output written to `tests/visual_output/` (gitignored).

---

## Contributing

1. Fork and create a feature branch.
2. `pip install -e ".[dev,web,gui]"` to install all dev dependencies.
3. Add tests for any new behaviour.
4. `pytest tests/ -v` — all 120 tests must pass.
5. Open a pull request against `main`.

**Adding a new built-in profile:** follow [Creating a profile](#creating-a-profile). Include `template.png` and at least one end-to-end test in `TestPipeline`.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history.

---

## License

MIT — see [LICENSE](LICENSE).
