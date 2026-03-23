# Changelog

All notable changes to box3d are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [2.0.0-rc1] — 2026-03

### Added

- **Plugin profile system** — new box styles added by dropping a directory into
  `profiles/`; zero code changes required. Profiles discovered at startup via
  filesystem scan with path-traversal mitigation (`^[a-zA-Z0-9_-]+$` regex).
- **Three built-in profiles** — `mvs` (Neo Geo MVS, 703×1000), `arcade`
  (Arcade cabinet, 665×907), `dvd` (DVD case, 633×907).
- **Per-slot logo rotation** — `LogoSlot.rotate` (int degrees) replaces the
  old boolean `rotate_logos` flag; each slot can have an independent angle.
- **Circuit Breaker** — pipeline aborts after 2 consecutive errors or when total
  errors exceed 20 % of the batch (MULTI-AI-PROTO-V3.4 HIGH policy).
- **Centralised asset loader** — `pipeline._safe_open()` applies OOM hardening
  (thumbnail to ≤ 8 192 px) to every image at the single point of disk read.
  Logos and marquees pre-loaded once and shared across workers as read-only
  `PIL.Image` objects.
- **PyInstaller standalone executables** — `cli/main.py` splits path resolution
  into `_bundle_dir()` (read-only assets, resolves to `sys._MEIPASS` when
  frozen) and `_data_dir()` (user-writable, resolves to `<exe-dir>/data` when
  frozen). CI release workflow produces signed executables for Linux x86-64 and
  Windows x86-64 via PyInstaller `--onefile`.
- **Automatic data directory bootstrap** — `_bootstrap_data_dir()` called at
  startup creates `data/{inputs/covers,inputs/marquees,output/converted,
  output/temp,output/logs}` idempotently on first run.
- **`profiles validate` command** — checks template file existence and geometry
  dimension bounds for every loaded profile; returns exit code 1 on any failure.
- **`designer` command** — opens `tools/box3d_designer_pro/index.html` in the
  default browser via `webbrowser.open()`; no Python runtime required inside the
  tool.
- **`--log-file ""` shorthand** — passing an empty string writes logs to
  `<data>/output/logs/box3d.log`.
- **Four ADRs** documented in MADR format covering boundary type enforcement,
  OOM hardening, zero-disk-churn, and alpha blend semantics.
- **49-test suite** across 6 classes: `TestModels`, `TestRegistry`,
  `TestPerspective`, `TestBlending`, `TestSpineBuilder`, `TestPipeline`.
- **35-variant visual regression runner** (`tests/run_visual_tests.py`) covering
  all profiles, blur, darken, RGB matrix, rotation, spine source, cover fit,
  logo, format, and combination groups.
- **CI matrix** — Python 3.11 / 3.12 / 3.13, `fail-fast: false`,
  `cancel-in-progress` on stale runs, pip cache.
- **Box3D Designer Pro** — self-contained HTML visual editor for authoring and
  editing profiles (`tools/box3d_designer_pro/index.html`).

### Changed

- **Architecture** — v1 was a monolithic script; v2 introduces strict layer
  separation: `core/` (domain, no rendering), `engine/` (rendering, no I/O),
  `cli/` (thin wiring layer).
- **Spine generation** — `build_spine()` now accepts pre-loaded `PIL.Image`
  objects instead of file paths; no disk I/O inside `engine/`.
- **Compositing** — `_composite()` requires `template_img` as a pre-loaded
  argument; raises `ValueError` if `None` to enforce the no-I/O contract.
- **OOM hardening** — extended to three independent layers: profile load time
  (`ProfileGeometry.__post_init__`), asset load time (`pipeline._safe_open()`),
  and warp time (`resize_for_fit()`).
- **`alpha_weighted_screen` semantics clarified** — output alpha is
  `max(dst_alpha, src_alpha)` (union); this is intentional and required for the
  template overlay to survive the subsequent `dst_in` clip. ADR-004 documents
  the rationale with measured pixel counts.
- **`run.sh` / `test.sh`** — `PYTHONPATH` corrected from non-existent `src/` to
  project root; `sys.path.insert` removed from `cli/main.py`.
- **`release.yml`** — test gate added before build job; `--add-data "tools:tools"`
  included so the Designer Pro is bundled in the executable.

### Removed

- `RenderOptions.with_logos` — field was declared but never read by the pipeline
  or compositor. Logo control is the caller's responsibility via `logo_paths={}`.
- `parse_rgb_str` from `engine/compositor.py` — moved to `cli/main.py` where it
  belongs (CLI-only input validation utility).
- Intermediate temp files (`spine_tmp`) — replaced by in-memory `PIL.Image`
  transfer (ADR-003).
- `sys.path.insert(0, str(_ROOT))` from `cli/main.py` — redundant after correct
  `PYTHONPATH` setup in shell scripts and `pip install -e .`.

### Fixed

- **PyInstaller output breakage** — default I/O paths (covers, output, marquees,
  logs) now resolve to `<exe-dir>/data/` instead of `sys._MEIPASS`, which is
  read-only and destroyed on process exit.
- **`profiles validate` was a no-op** — command now performs real validation
  (template existence + OOM bounds) and returns exit code 1 on failure.
- **`designer` command crashed** — was calling `subprocess.call(app.py)` on a
  non-existent file; replaced with `webbrowser.open(index.html)`.
- **`PYTHONPATH` in shell scripts** — pointed to `${SCRIPT_DIR}/src` which does
  not exist; scripts worked only because `sys.path.insert` was in `cli/main.py`.
- **`alpha_weighted_screen` docstring** — incorrectly stated "alpha channel of
  dst is preserved unchanged"; actual behaviour is `np.maximum(dst, src)` which
  is correct and required by the pipeline.

---

## [1.x]

Version 1.x was a single-file script without plugin profiles, parallel rendering,
or formal test coverage. No changelog was maintained for that series.

---

[Unreleased]: https://github.com/RtaSistemas/box3d/compare/v2.0.0-rc1...HEAD
[2.0.0-rc1]:  https://github.com/RtaSistemas/box3d/releases/tag/v2.0.0-rc1
