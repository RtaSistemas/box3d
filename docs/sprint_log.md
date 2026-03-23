# Sprint Log — box3d v2

Delivery tracking for the v2.0.0 hardening cycle. Each sprint had a single focused scope;
work was validated by the full test suite (`pytest tests/test_v2.py`) before closing.

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
