# Sprint Log — box3d v2

Delivery tracking for the v2.0.0 hardening cycle. Each sprint had a single focused scope;
work was validated by the full test suite (`pytest tests/test_v2.py`) before closing.

---

## Sprint 6 — Game Logo Fallback & First-Run Experience

**Scope:** `cli/main.py`, `core/pipeline.py`, `tests/test_v2.py`, `README.md`
**Status:** Done

### Deliverables

| # | Deliverable | File | Detail |
|---|---|---|---|
| 6.1 | Game logo fallback | `core/pipeline.py` | `_load_game_logo()` resolves in two stages: `marquees_dir/<stem>.*` then `profile/assets/logo_game.*`; three new tests in `TestGameLogoFallback` |
| 6.2 | `instructions.txt` on first run | `cli/main.py` | `_bootstrap_instructions()` writes a plain-text offline guide next to the executable on the first run only (never overwritten); covers folder layout, file naming, all render flags, aux commands, and "add a profile" steps |

### Acceptance criteria

- `pytest tests/test_v2.py -v` → **52 passed**.
- First run creates `instructions.txt` next to the executable (or at project root in dev).
- Subsequent runs leave `instructions.txt` untouched even if content differs.
- `box3d render -p mvs` resolves game logo as: `marquees_dir` stem → `profile/assets/logo_game.*` → None.

---

## Sprint 5 — PyInstaller Readiness & Release Closure

**Scope:** `cli/main.py`, `core/models.py`, `core/pipeline.py`, `engine/blending.py`,
`run.sh`, `test.sh`, `.github/workflows/release.yml`, `docs/`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 5.1 | PyInstaller path split (SUG-005) | Replaced single `_ROOT` with `_bundle_dir()` (read-only assets → `sys._MEIPASS` when frozen) and `_data_dir()` (user-writable → `exe-dir/data` when frozen); all I/O defaults now derive from `_DATA` |
| 5.2 | Bootstrap on first run (SUG-006) | `_bootstrap_data_dir()` called at startup creates `data/{inputs/covers,inputs/marquees,output/converted,output/temp,output/logs}` idempotently; replaces shell-only bootstrap from `run.sh` |
| 5.3 | PYTHONPATH corrected (SUG-007) | `run.sh` and `test.sh` fixed from `${SCRIPT_DIR}/src` (non-existent) to `${SCRIPT_DIR}`; redundant `sys.path.insert` removed from `cli/main.py` |
| 5.4 | Circuit Breaker aligned (SUG-008) | `_CB_MAX_CONSECUTIVE` lowered from 10 to 2 to match MULTI-AI-PROTO-V3.4 HIGH policy; comment documents the percentage guard rationale |
| 5.5 | ADR-004: alpha semantics documented | `alpha_weighted_screen` uses `np.maximum(dst_alpha, src_alpha)` — confirmed correct; prior docstring was wrong; test replaced with `test_alpha_weighted_screen_alpha_union` verifying both union directions |
| 5.6 | `cmd_profiles_validate` implemented | Now checks template file existence and OOM dimension bounds per profile; returns exit code 1 on failure |
| 5.7 | Designer command fixed | Replaced dead `subprocess.call(app.py)` with `webbrowser.open(index.html)`; `release.yml` gains `--add-data "tools:tools"` |
| 5.8 | `with_logos` domain ghost removed | Field removed from `RenderOptions`; logo control is the caller's responsibility via `logo_paths={}` |
| 5.9 | Python 3.13 classifier added | `pyproject.toml` classifiers aligned with CI matrix (3.11/3.12/3.13) |

### Acceptance criteria

- All 49 tests pass (`pytest tests/test_v2.py -v`).
- `python cli/main.py profiles validate` reports per-profile template and geometry status with correct exit codes.
- `python cli/main.py designer` opens `tools/box3d_designer_pro/index.html` in the default browser without error.
- Running the compiled PyInstaller executable without `--input`/`--output` flags creates output in `<exe-dir>/data/output/converted/` (not inside `sys._MEIPASS`).
- `run.sh` and `test.sh` work without installing the package via pip.

### Notes

This sprint closes all blocking items identified in the MULTI-AI-PROTO-V3.4 audit
(SUG-005 through SUG-008) and completes the hardening cycle started in Sprint 1.
The codebase is now ready for the `v2.0.0-rc1` tag.

---

## Sprint 4 — Peripheral Asset Hardening (Spine)

**Scope:** `engine/spine_builder.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 4.1 | OOM protection on logo loading | `PIL.Image.thumbnail` applied to every logo before compositing; prevents runaway allocation from oversized asset files |
| 4.2 | Remove NumPy from transparency operations | Replaced `np.array` alpha compositing with `PIL.Image.putalpha` / `ImageChops.multiply`; native C path, no intermediate array allocation |

### Acceptance criteria

- All 7 `TestSpineBuilder` tests pass.
- Logo compositing produces visually identical output for all built-in profiles.
- Memory usage during spine generation is bounded by the 8 192 px ceiling introduced in Sprint 2.

---

## Sprint 3 — Orchestration Optimization (Zero-Disk)

**Scope:** `engine/compositor.py`, `core/pipeline.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 3.1 | Remove intermediate disk writes | Eliminated `spine_tmp` temp-file pattern; `build_spine()` now returns a `PIL.Image` in RAM |
| 3.2 | Pre-loaded template singleton | `RenderPipeline` loads `template.png` once before spawning workers and passes it as a read-only argument; no per-worker re-read |
| 3.3 | Thread-safe rendering contract | Verified that `compositor.render_cover()` holds no shared mutable state; confirmed linear scaling under `ThreadPoolExecutor` |

### Acceptance criteria

- All 8 `TestPipeline` tests pass, including parallel and dry-run variants.
- No temporary files created in `data/output/` or `/tmp/` during a batch run.
- Throughput improvement measurable (I/O no longer on the critical path).

### Notes

This sprint implements ADR-003 (Zero-Disk-Churn Architecture).

---

## Sprint 2 — Graphics Engine Hardening (Phase 1)

**Scope:** `engine/blending.py`, `engine/perspective.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 2.1 | Eliminate redundant NumPy allocations | Replaced `np.zeros_like` / `np.ones_like` intermediate buffers with in-place operations where safe |
| 2.2 | Migrate color transforms to Pillow native C | `apply_color_matrix()` now uses `PIL.ImageMath` / channel operations backed by Pillow's C extension; removed the NumPy diagonal-matrix path |
| 2.3 | Preventive downscale on warp inputs | `resize_for_fit()` calls `thumbnail((8192, 8192))` before perspective coefficient computation; hard ceiling enforced before heavy allocation |

### Acceptance criteria

- All 9 `TestPerspective` and all 9 `TestBlending` tests pass.
- Warp output is pixel-identical to the pre-hardening baseline for standard inputs.
- A 16 000 × 16 000 input image is downscaled without raising `MemoryError`.

### Notes

This sprint implements ADR-002 (OOM Hardening) at the engine layer.

---

## Sprint 1 — Foundation & Ingestion Security

**Scope:** `core/models.py`, `core/registry.py`
**Status:** Done

### Deliverables

| # | Deliverable | Detail |
|---|---|---|
| 1.1 | Strict type validation in JSON parser | Every field in `registry._load_profile()` validated with `isinstance` before access; `None` checks on all optional fields |
| 1.2 | Path-traversal mitigation | Profile directory names validated against `^[a-zA-Z0-9_-]+$` regex before filesystem access; symlink-following prevented |
| 1.3 | OOM boundary in domain model | `ProfileGeometry.__post_init__` raises `ValueError` if any dimension exceeds 8 192 px; enforced at object construction time |
| 1.4 | Graceful degradation on malformed profiles | Deserialization errors caught per profile; logged at `WARNING` with field name and received type; remaining profiles continue loading |

### Acceptance criteria

- All 13 `TestRegistry` tests pass, including path-traversal and malformed-profile tests.
- All 3 `TestModels` tests pass, including OOM boundary assertion.
- A directory containing one malformed and one valid profile loads the valid profile successfully.

### Notes

This sprint implements ADR-001 (Strict Boundary Type Enforcement) and the profile-load portion
of ADR-002 (OOM Hardening).