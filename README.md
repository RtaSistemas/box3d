# box3d

[![CI](https://github.com/RtaSistemas/box3d/actions/workflows/ci.yml/badge.svg)](https://github.com/RtaSistemas/box3d/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**3D box art generator for retro game collections — plugin-based profiles, pure Python.**

`box3d` takes flat front-cover images and renders them as photorealistic 3D boxes with textured spines, logo overlays, and baked-in shading. Output is a transparency-correct RGBA image (WebP or PNG) ready for EmulationStation, Pegasus, or any launcher that supports boxart.

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
  - [Global options](#global-options)
- [Architecture](#architecture)
- [Compositing Pipeline](#compositing-pipeline)
- [Profiles](#profiles)
  - [Using Custom Profiles](#using-custom-profiles)
  - [Built-in Profiles](#built-in-profiles)
  - [Creating a Profile](#creating-a-profile)
  - [Profile JSON Schema](#profile-json-schema)
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
| **Parallel rendering** | ThreadPoolExecutor with configurable worker count |
| **Batch circuit breaker** | Aborts a batch after 2 consecutive errors or when errors exceed 20% of processed files, preventing cascading failures |
| **OOM hardening** | Hard 8 192 px ceiling at three independent layers; immune to pixel-bomb inputs |
| **Zero-disk-churn** | All intermediate data lives in RAM as `PIL.Image` objects — no temp files |
| **Pure Python** | Pillow ≥ 10 and NumPy ≥ 1.24 only — no external binaries |
| **Visual editor** | Browser-based Box3D Designer Pro for authoring profiles interactively |
| **Multiple formats** | WebP (q 92, default) or PNG output |
| **Incremental runs** | `--skip-existing` skips already-rendered outputs |
| **Dry-run mode** | `--dry-run` validates inputs and reports without writing |

---

## Requirements

| Component | Version |
|---|---|
| Python | 3.11 or later |
| Pillow | ≥ 10.0 |
| NumPy | ≥ 1.24 |
| OS | Linux · macOS · Windows |

---

## Installation

### Development install (recommended)

```bash
git clone https://github.com/RtaSistemas/box3d.git
cd box3d

# Ubuntu / Debian
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev

python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -U pip setuptools wheel
pip install -e .                   # Installs in editable mode with all runtime deps
```

### With dev dependencies (for running tests)

```bash
pip install -e ".[dev]"
```

### Pre-built binaries

Standalone executables (no Python required) are available on the
[Releases page](https://github.com/RtaSistemas/box3d/releases):

| Platform | Asset |
|---|---|
| Linux x86-64 | `box3d-linux-x64` |
| Windows x86-64 | `box3d-windows-x64.exe` |

---

### Standalone executable — first run

On first launch, the executable automatically creates the folder structure it needs
next to itself — no installer, no configuration required.

**Linux / macOS**

```bash
# Download and make executable
chmod +x box3d-linux-x64

# First run — profiles/ and data/ are created next to the binary
./box3d-linux-x64 profiles list

# Drop covers into data/inputs/covers/ then render
cp /path/to/covers/*.webp data/inputs/covers/
./box3d-linux-x64 render --profile mvs
# Output appears in data/output/converted/
```

**Windows**

```powershell
# First run — profiles\ and data\ are created next to the .exe
.\box3d-windows-x64.exe profiles list

# Drop covers into data\inputs\covers\ then render
copy C:\path\to\covers\*.webp data\inputs\covers\
.\box3d-windows-x64.exe render --profile mvs
# Output appears in data\output\converted\
```

**Full layout created automatically:**

```
<folder containing the exe>/
├── profiles/                    ← editable plugin profiles (copied from bundle)
│   ├── mvs/
│   │   ├── profile.json         ← edit to adjust geometry
│   │   ├── template.png         ← replace with your own box art template
│   │   └── assets/
│   │       ├── logo_top.png     ← system logo top of spine
│   │       ├── logo_bottom.png  ← system logo bottom of spine
│   │       └── logo_game.png    ← fallback game logo (optional)
│   ├── arcade/  ...
│   └── dvd/     ...
├── data/
│   ├── inputs/
│   │   ├── covers/              ← put your flat cover images here (WebP, PNG, JPG)
│   │   └── marquees/            ← per-game logos matched by filename stem
│   └── output/
│       ├── converted/           ← rendered 3-D box art appears here
│       ├── temp/                ← pipeline scratch space (auto-managed)
│       └── logs/                ← log files when --log-file="" is used
└── instructions.txt             ← quick-start guide (generated on first run)
```

> **Editing profiles:** `profiles/` is yours to modify. Change `profile.json` to
> adjust geometry, swap `template.png` for a custom box art, or add `logo_game.png`
> to `assets/` as a system-wide fallback marquee. New built-in profiles released in
> future versions are added automatically without overwriting your edits.

> **Adding a new profile:** create a subdirectory inside `profiles/` with a
> `profile.json` and `template.png`. It is immediately available on the next run
> without restarting or recompiling.

> **Using profiles stored elsewhere:** pass `--profiles-dir /path/to/your/profiles/`
> to point box3d at any directory on your system. This is the recommended workflow
> for Windows executable users who want profiles outside the default location
> (see [Using Custom Profiles](#using-custom-profiles)).



```bash
# 1. Clone and install (see Installation above)

# 2. Prepare your data directories
mkdir -p data/inputs/covers data/inputs/marquees data/output/converted

# 3. Drop flat cover images into data/inputs/covers/
cp /path/to/my/covers/*.webp data/inputs/covers/

# 4. Render using the MVS (Neo Geo) profile
python cli/main.py render --profile mvs

# 5. Find the output in data/output/converted/
```

Preview a run without writing any files:

```bash
python cli/main.py render --profile mvs --dry-run --verbose
```

---

## CLI Reference

### Global options

These flags apply to **all commands** and must be placed **before** the subcommand name.

```
python cli/main.py [global options] <command> [command options]
```

| Option | Default | Description |
|---|---|---|
| `--profiles-dir` | `profiles/` next to the executable | Path to the profiles directory. Override to load profiles from an external location (see [Using Custom Profiles](#using-custom-profiles)). |
| `--verbose` / `-v` | — | Enable DEBUG-level logging |
| `--log-file` | — | Write log output to a file (`""` uses `data/output/logs/box3d.log`) |

---

### `render`

Renders all cover images in the input directory using the specified profile.

```
python cli/main.py render --profile <name> [options]
```

| Option | Short | Default | Description |
|---|---|---|---|
| `--profile` | `-p` | *(required)* | Profile name (must exist in `profiles/`) |
| `--input` | `-i` | `data/inputs/covers/` | Directory containing source cover images |
| `--output` | `-o` | `data/output/converted/` | Output directory |
| `--workers` | `-w` | `4` | Number of parallel render threads |
| `--blur-radius` | `-b` | `20` | Gaussian blur radius applied to sampled spine background (`>= 0`) |
| `--darken` | `-d` | `180` | Spine dark overlay intensity (`0`–`255`; 0 = off, 255 = solid black) |
| `--rgb` | | `1.0,1.0,1.0` | RGB channel multipliers in `R,G,B` comma-separated format (e.g. `0.9,0.9,1.1`). Each value scales the respective channel (`> 1` brightens, `< 1` darkens). Must be `>= 0`. |
| `--cover-fit` | | *(profile default)* | How the cover fills its quad: `stretch`, `fit`, or `crop` |
| `--spine-source` | | *(profile default)* | Which edge of the cover to sample for the spine: `left`, `right`, or `center` |
| `--no-rotate` | | *(profile default)* | Disable 90° CW logo rotation on the spine |
| `--no-logos` | | — | Render spine without any logo overlays |
| `--output-format` | | `webp` | Output format: `webp` or `png` |
| `--skip-existing` | | — | Skip covers that already have an output file |
| `--dry-run` | | — | Validate inputs and report; do not write any files |
| `--verbose` | `-v` | — | Enable DEBUG-level logging |
| `--log-file` | | — | Optional path for persistent log output |

**Examples:**

```bash
# Render all covers with the arcade profile, 8 workers, PNG output
python cli/main.py render -p arcade -w 8 --output-format png

# Override spine appearance inline
python cli/main.py render -p mvs --blur-radius 30 --darken 200 --rgb 0.85,0.85,1.0

# Incremental update — only process new covers
python cli/main.py render -p dvd --skip-existing
```

---

### `profiles`

```bash
python cli/main.py profiles list      # List all discovered profiles with metadata
python cli/main.py profiles validate  # Verify that each profile's template.png exists
```

---

### `designer`

Opens Box3D Designer Pro in the default browser.

```bash
python cli/main.py designer
```

---

## Architecture

```
box3d/
├── core/                        # Domain & orchestration — no rendering logic
│   ├── models.py                # Immutable dataclasses: Profile, ProfileGeometry,
│   │                            #   RenderOptions, CoverResult, …
│   ├── registry.py              # Plugin discovery & JSON validation
│   └── pipeline.py              # Parallel rendering orchestrator (ThreadPoolExecutor)
│
├── engine/                      # Pure rendering primitives — no I/O, no profiles
│   ├── perspective.py           # 8-coefficient perspective warp (numpy.linalg.solve)
│   ├── blending.py              # alpha_weighted_screen, dst_in, build_silhouette_mask
│   ├── spine_builder.py         # 2-D spine strip: blur → overlay → logos
│   └── compositor.py           # Per-cover entry point; coordinates engine modules
│
├── profiles/                    # Plugin bundles (JSON + template + assets)
│   ├── mvs/                     # Neo Geo MVS cartridge  703×1000
│   │   ├── profile.json         # Geometry + spine layout
│   │   ├── template.png         # RGBA box template
│   │   └── assets/
│   │       ├── logo_top.png     # System logo — top of spine
│   │       ├── logo_bottom.png  # System logo — bottom of spine
│   │       └── logo_game.png    # Fallback game logo (used when no marquee found)
│   ├── arcade/                  # Arcade cabinet          665×907
│   └── dvd/                     # DVD case                633×907
│
├── cli/
│   └── main.py                  # Thin wiring layer — argparse → core → engine
│
├── tools/
│   └── box3d_designer_pro/
│       └── index.html           # Self-contained visual profile editor
│
└── tests/
    ├── test_v2.py               # 52 unit & integration tests
    ├── run_visual_tests.py      # Manual visual verification runner
    └── assets/                  # Fixtures: cover, marquee, logos, templates
```

### Design Principles

**1. Profiles as plugins.**
No code change is required to add a new box style. Drop a directory into `profiles/` containing `profile.json` and `template.png` and it is immediately available. The registry discovers profiles at startup via filesystem scan with path-traversal mitigation.

**2. Strict layer separation.**
`core/` declares domain types and orchestrates work — it has no rendering knowledge.
`engine/` implements rendering primitives — it has no profile or I/O knowledge.
`cli/` is a thin wiring layer that parses arguments and connects the two.

**3. Pure Python rendering.**
No external binaries. Perspective warps use `numpy.linalg.solve` for coefficient computation and `PIL.Image.transform` for pixel resampling (BICUBIC). Color operations use Pillow's native C path wherever possible.

**4. Defense-in-depth memory safety.**
OOM protection exists at two independent layers: profile load time (geometry validation) and image processing time (preventive downscale). The hard ceiling is 8 192 px in any dimension.

**5. Zero-disk-churn.**
Intermediate images (spine strip, warped cover, blended result) exist only as in-memory `PIL.Image` objects. No temporary files are written. This reduces latency and SSD wear in batch workloads.

**6. Thread safety by design.**
Render functions hold no shared mutable state. The pipeline pre-loads the template once and passes it as an argument to each worker.

---

## Compositing Pipeline

Each cover goes through a five-step pipeline inside `engine/compositor.py`:

```
transparent canvas  (template_size)
        │
        ├─ 1. Perspective warp — spine strip
        │       build_spine() → warp(spine_quad, spine_size)
        │
        ├─ 2. Perspective warp — front cover
        │       resize_for_fit(cover_fit) → warp(cover_quad, cover_size)
        │
        ├─ 3. Alpha-weighted Screen blend — template overlay
        │       alpha_weighted_screen(canvas, template)
        │
        ├─ 4. DstIn — clip to union silhouette
        │       build_silhouette_mask(canvas, template) → dst_in(canvas, mask)
        │
        └─ 5. Save  (WebP q 92  or  PNG lossless)
```

**Why alpha-weighted Screen blend?**
Standard Screen blend would cause near-white, near-transparent template pixels (common in arcade/dvd profiles, alpha ≈ 12/255) to wash out dark covers. Weighting by alpha preserves intended shading at opaque borders while keeping transparent regions unaffected.

**Why union silhouette for DstIn?**
The MVS profile uses a mostly-transparent template. A DstIn keyed only on the template alpha would erase the cover face. The union of template alpha and canvas alpha is used as the clip mask, ensuring the cover remains visible.

---

## Profiles

### Using Custom Profiles

The `--profiles-dir` global flag lets you load profiles from any directory, not just the default `profiles/` folder next to the executable.

**When is this useful?**

- Running the **Windows or Linux executable** and wanting profiles in a separate folder
- Managing **multiple profile sets** for different systems without mixing them
- Using profiles on a **network drive** or shared storage

**Workflow:**

```bash
# 1. Create your external profiles directory
mkdir ~/my-box3d-profiles

# 2. Copy an existing profile as a starting point
cp -r profiles/mvs ~/my-box3d-profiles/ps2

# 3. Edit ~/my-box3d-profiles/ps2/profile.json and template.png as needed

# 4. Render using the external directory
python cli/main.py --profiles-dir ~/my-box3d-profiles render --profile ps2
```

**Windows executable:**

```powershell
.\box3d-windows-x64.exe --profiles-dir C:\MyProfiles render --profile ps2
```

> Profiles inside `--profiles-dir` are discovered by the same filesystem scan as built-in
> profiles. All rules apply: each subdirectory needs `profile.json` and `template.png`.

---

### Built-in Profiles

| Name | Box Style | Template Size | Cover Fit | Spine Source |
|---|---|---|---|---|
| `mvs` | Neo Geo MVS cartridge | 703 × 1 000 px | stretch | left |
| `arcade` | Arcade cabinet | 665 × 907 px | stretch | left |
| `dvd` | DVD case | 633 × 907 px | stretch | left |

---

### Creating a Profile

#### Step 1 — Scaffold the directory

```
profiles/
└── ps2/
    ├── profile.json          ← required
    ├── template.png          ← required (RGBA, any size up to 8192 × 8192)
    └── assets/               ← optional
        ├── logo_top.png      ← system logo placed at the top of the spine
        ├── logo_bottom.png   ← system logo placed at the bottom of the spine
        └── logo_game.png     ← fallback game logo (used when no marquee found
                                 in data/inputs/marquees/ for the current cover)
```

Supported extensions for all logo files: `.png`, `.webp`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`.

#### Step 2 — Author the profile JSON

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

#### Step 3 — Use Box3D Designer Pro for visual alignment

```bash
python cli/main.py designer
```

Load your `template.png`, position the `spine` and `cover` quads interactively, and export the resulting `profile.json`.

#### Step 4 — Test

```bash
# Dry-run to validate geometry without writing output
python cli/main.py render --profile ps2 --dry-run --verbose

# Full render against a test cover
python cli/main.py render --profile ps2 --input tests/assets/ --output /tmp/ps2-test/
```

---

### Profile JSON Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Identifier (must match directory name) |
| `description` | string | no | Human-readable description |
| `version` | string | no | Semver string for the profile |
| `template_size` | `{width, height}` | yes | Pixel dimensions of `template.png` |
| `spine` | `{width, height}` | yes | Logical spine strip dimensions |
| `cover` | `{width, height}` | yes | Logical cover dimensions |
| `spine_quad` | `{tl, tr, br, bl}` | yes | Target quad in template space for spine warp |
| `cover_quad` | `{tl, tr, br, bl}` | yes | Target quad in template space for cover warp |
| `spine_source_frac` | float | no | Fraction of cover width to sample (default `0.20`) |
| `spine_source` | `left\|right\|center` | no | Edge of cover to sample for spine background |
| `cover_fit` | `stretch\|fit\|crop` | no | How the cover image fills `cover` dimensions |
| `spine_layout.game` | `{max_w, max_h, center_y, rotate}` | yes | Game-logo slot on the spine |
| `spine_layout.top` | `{max_w, max_h, center_y, rotate}` | no | Top-logo slot on the spine |
| `spine_layout.bottom` | `{max_w, max_h, center_y, rotate}` | no | Bottom-logo slot on the spine |
| `spine_layout.logo_alpha` | float 0–1 | no | Opacity of composited logos (default `0.85`) |
| `spine_layout.*.rotate` | int (degrees) | no | Rotation angle per slot in degrees (PIL convention: negative = CW). Default `0`. |

Each quad point is `[x, y]` in pixel coordinates within `template_size`.

#### Logo resolution order

For each cover, the game logo on the spine is resolved in this order:

1. `data/inputs/marquees/<cover-stem>.*` — dynamic per-game marquee matched by filename.
2. `profiles/<n>/assets/logo_game.*` — profile-level fallback (e.g. system manufacturer logo).
3. None — spine is rendered without a game logo.

The `--no-logos` flag disables all logo rendering (game, top, and bottom).

---

## Box3D Designer Pro

A self-contained, browser-based visual editor for authoring and editing profiles.

```bash
python cli/main.py designer
```

Located at `tools/box3d_designer_pro/index.html` — no server or build step required.

**Capabilities:**

- Load any PNG template image as the design canvas
- Add and position `spine`, `cover`, `logo`, and `marquee` regions
- Drag to move; corner handles to resize; quad-point editing for perspective regions
- Configurable grid with snap-to-grid
- Real-time JSON preview of the generated `profile.json`
- Export `profile.json` directly or as an embeddable Python snippet
- Import existing profiles for editing

---

## Testing

### Running the test suite

```bash
pytest tests/test_v2.py -v
```

Expected output: **52 tests passed**.

### Test coverage breakdown

| Class | Tests | Scope |
|---|---|---|
| `TestModels` | 3 | Domain dataclass invariants, OOM boundary |
| `TestRegistry` | 13 | Profile discovery, JSON validation, custom profiles, path-traversal rejection |
| `TestPerspective` | 9 | Warp correctness, `stretch`/`fit`/`crop` modes, all built-in profiles |
| `TestBlending` | 9 | Screen blend, DstIn, diagonal color matrix, silhouette mask |
| `TestSpineBuilder` | 7 | Spine generation for all built-in profiles |
| `TestPipeline` | 8 | End-to-end batch render, dry-run, worker scaling, all profiles |
| `TestGameLogoFallback` | 3 | Logo resolution: fallback to profile asset, None when absent, dynamic priority |

### Visual regression tests

```bash
python tests/run_visual_tests.py
# Output written to tests/visual_output/ (gitignored)
```

---

## Contributing

1. Fork the repository and create a feature branch.
2. Run `pip install -e ".[dev]"` to install dev dependencies.
3. Make your changes and add tests covering the new behaviour.
4. Run `pytest tests/test_v2.py -v` — all 52 tests must pass.
5. Open a pull request against `main`.

**Adding a new built-in profile** follows the same process as [Creating a Profile](#creating-a-profile). Include the `template.png` and at least one end-to-end test in `TestPipeline`.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history of changes, including
all additions, fixes, and removals since v1.x.

---

## License

MIT — see [LICENSE](LICENSE).