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

## ADR-004: Alpha Semantics of alpha_weighted_screen — Union, Not Preservation

**Status:** Accepted

**Date:** 2026-03 (revised after visual regression analysis)

### Context

`engine/blending.py:alpha_weighted_screen` blends the template image (src) over the
partially-composited box canvas (dst) using a screen formula weighted by the template's
alpha.  The compositing pipeline is:

1. Warp spine strip onto transparent canvas → `canvas`
2. Warp cover image onto canvas → `canvas`
3. **Screen-blend template over canvas** → `canvas` *(this function)*
4. Build silhouette mask = union(spine_warped, cover_warped, template)
5. DstIn: clip canvas by the silhouette mask

The template PNG for every profile contains a large number of pixels with non-zero alpha
that lie **outside** the spine and cover warp quads — for example, the bevelled edges,
corner reflections, and the 3-D plastic rim of the box art.  After steps 1–2, these
template pixels have no corresponding opaque area in the canvas (canvas alpha = 0 there).

A first attempt set the output alpha to `dst_arr[:, :, 3]` (preserve dst).  This caused a
**total visual regression**: the template overlay disappeared completely in all rendered
outputs.  Root cause: the silhouette mask in step 4 correctly includes the template, but
after step 3 the canvas alpha at those positions is still 0.  Step 5 (dst_in) multiplies
canvas alpha by the mask — multiplying 0 by anything is 0 — so every template pixel outside
the warp area is erased before the final save.

Measurement: the arcade profile template has 454 094 pixels with alpha > 0, of which
106 642 have canvas alpha = 0 after the warp steps.  Those 106 642 pixels are exactly the
ones that form the visible 3-D plastic edges of the box.

### Decision

The output alpha of `alpha_weighted_screen` is `np.maximum(dst_alpha, src_alpha)` — a
pixel-wise union of the two alpha channels.  This ensures that every pixel where the
template is opaque is also opaque in the canvas before dst_in executes, so no template
geometry is lost during the silhouette clip.

### Consequences

- **Positive:** Template overlay is fully preserved across all profiles and RGB variants.
- **Positive:** The semantics are consistent with the silhouette mask construction: both
  use the union of all contributing layers.
- **Positive:** Test `test_alpha_weighted_screen_alpha_union` now verifies both directions
  of the union (src wins when src_alpha > dst_alpha; dst wins otherwise).
- **Negative:** The function cannot be used as a generic 'preserve-dst-alpha screen'
  blend.  Its contract is specific to this pipeline and is documented as such.