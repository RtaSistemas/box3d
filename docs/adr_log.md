# Architecture Decision Records — box3d

This document records significant architectural decisions made during the development of box3d.
Each entry follows the [MADR](https://adr.github.io/madr/) lightweight format.

---

## ADR-001: Strict Boundary Type Enforcement at Profile Load Time

**Status:** Accepted

**Date:** 2026-01

### Context

Profile configuration is loaded at runtime from JSON files contributed by third parties or end
users. Dynamic JSON parsing offers no type guarantees: a malformed or intentionally crafted
`profile.json` can inject `null` values, wrong numeric types, or missing keys into the
application's domain objects. Without explicit validation, these defects surface as cryptic
`AttributeError` or `TypeError` exceptions deep inside the rendering pipeline — far from the
actual fault, and with no actionable message.

### Decision

All JSON-to-domain-object deserialization in `core/registry.py` must:

1. Validate every field with an explicit `isinstance` check before access.
2. Check for `None` / missing keys before any method call or arithmetic.
3. Reject the entire profile with a structured log message if any field fails validation.
4. Never propagate a partially-constructed profile to the engine.

The `ProfileRegistry` catches all deserialization errors per profile, logs them at `WARNING`
level with the offending key and received type, and continues loading remaining profiles.

### Consequences

- **Positive:** A malformed or adversarial `profile.json` is silently discarded; it cannot crash
  the batch run or corrupt another cover's output.
- **Positive:** Error messages produced during profile discovery are diagnostic and actionable.
- **Positive:** The engine layer receives only fully-validated, type-correct domain objects.
- **Negative:** Valid profiles with minor typos (e.g., `"width": "703"` as a string) are
  rejected rather than coerced. Authors must fix the JSON.

---

## ADR-002: OOM Hardening — Hard 8 192 px Ceiling at Two Independent Layers

**Status:** Accepted

**Date:** 2026-01

### Context

Image processing workloads are vulnerable to out-of-memory conditions caused by oversized
inputs ("pixel bombs"). A single 16 000 × 16 000 RGBA image requires ~1 GiB of RAM; two of
them in a warp pipeline can trigger kernel OOM-kill on constrained targets (handheld emulation
devices, 1 GiB containers). The original implementation imposed no upper bounds.

### Decision

Enforce a hard maximum of **8 192 px** in any single dimension at two independent enforcement
points:

1. **Profile load time** — `ProfileGeometry.__post_init__` raises `ValueError` if
   `template_size`, `spine`, or `cover` dimensions exceed 8 192 px. An oversized profile
   template is rejected at startup; it can never reach the engine.

2. **Input image processing** — `engine/perspective.py:resize_for_fit` calls
   `PIL.Image.thumbnail((8192, 8192))` on every input image before any heavy computation.
   This is a proportional downscale, so aspect ratio is preserved.

The two layers are independent: a profile within bounds cannot be exploited by providing a
large input image, and vice versa.

### Consequences

- **Positive:** The system is resilient to pixel-bomb inputs and pathological profile templates.
- **Positive:** Peak RAM usage is bounded to a predictable range for any input.
- **Positive:** Defense-in-depth: neither layer alone is a single point of failure.
- **Negative:** Legitimate ultra-high-resolution workflows (e.g., 10K print masters) are
  outside the supported envelope. The limit is documented and surfaced with a clear error.

---

## ADR-003: Zero-Disk-Churn — In-Memory Intermediate Images

**Status:** Accepted

**Date:** 2026-02

### Context

The initial implementation wrote intermediate pipeline artifacts (primarily the spine strip) to
temporary files on disk before the compositor read them back. This introduced:

- Measurable I/O latency proportional to batch size.
- Unnecessary SSD write amplification in long batch runs (thousands of covers).
- Fragility: temp-file paths had to be managed, cleaned up, and made unique per worker thread.

### Decision

Eliminate all intermediate disk I/O from the rendering pipeline. All pipeline stages
communicate via in-memory `PIL.Image.Image` objects passed as function arguments:

```
build_spine()     → PIL.Image  (in RAM)
warp(spine_img)   → PIL.Image  (in RAM)
alpha_screen()    → PIL.Image  (in RAM)
dst_in()          → PIL.Image  (in RAM)
image.save(path)  → disk       (final output only)
```

The template image is a special case: it is loaded once per pipeline run by `RenderPipeline`
and passed as an argument to every worker (read-only singleton). Workers never write to shared
state.

### Consequences

- **Positive:** Render throughput increases significantly for large batches (disk I/O removed
  from the critical path).
- **Positive:** No temporary file management — no naming collisions, no cleanup failures.
- **Positive:** Worker threads are stateless; adding more workers scales linearly without
  synchronization overhead.
- **Positive:** SSD wear is reduced to a single write per output cover.
- **Negative:** Peak RAM usage increases proportionally to the number of parallel workers,
  since each holds a full pipeline of in-memory images. The 8 192 px ceiling from ADR-002
  bounds this growth.

---

## ADR-004: Alpha Semantics of alpha_weighted_screen — Preserve dst Alpha

**Status:** Accepted

**Date:** 2026-03

### Context

`engine/blending.py:alpha_weighted_screen` blends a source image (the coloured template)
over a destination image (the partially-composited box canvas) using a screen formula
weighted by the source's alpha channel.  The original implementation computed the output
alpha channel as `np.maximum(dst_alpha, src_alpha)`.  This caused the alpha of the
destination to be elevated to the source's alpha wherever the source was more opaque,
violating the documented contract ("alpha channel of dst is preserved unchanged") and
silently breaking any downstream operation that relied on the canvas alpha — notably
`dst_in`, which clips the final silhouette using that alpha.

A dedicated test (`test_alpha_weighted_screen_preserves_dst_alpha`) had been commented out
because it failed under the old implementation.

### Decision

The output alpha of `alpha_weighted_screen` is set unconditionally to `dst_arr[:, :, 3]`
(the destination alpha, copied verbatim).  The source alpha is used only as a blend weight
for the RGB channels, not to modify the alpha channel of the result.

### Consequences

- **Positive:** The documented contract is now enforced and tested.
- **Positive:** The compositing pipeline is correct end-to-end: `dst_in` receives a canvas
  whose alpha strictly reflects the warped geometry, not an inflated value from the template.
- **Positive:** The previously commented test is now active (49 tests pass).
- **Neutral:** Visual output changes are expected to be imperceptible for fully-opaque
  templates (alpha = 255 everywhere), since `maximum(255, 255) = 255 = preserved`.  The
  difference is visible only when the template contains semi-transparent pixels.
- **Negative:** None identified.
