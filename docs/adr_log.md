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

---

## ADR-005: Web API — Sync Pipeline in Async Server via `asyncio.to_thread`

**Status:** Accepted

**Date:** 2026-03

### Context

Box3D added an optional FastAPI web server (`web/server.py`) to expose the rendering
engine over HTTP with a browser-based Control Center.  `RenderPipeline` is synchronous
and CPU-bound.  Running it directly inside an `async def` route handler blocks the
event loop: the browser cannot receive any response — including SSE progress events —
until the entire batch completes.

### Decision

Dispatch `_run_pipeline` to a thread via `asyncio.to_thread()` inside a FastAPI
`BackgroundTask`:

```python
background_tasks.add_task(asyncio.to_thread, _run_pipeline)
return JSONResponse({"status": "started"})
```

Progress events are bridged from the sync worker thread to the async SSE generator
using a `queue.Queue[dict]`.  The async generator polls the queue with
`queue.get_nowait()` and yields control between polls with `await asyncio.sleep(0.05)`.

### Consequences

- **Positive:** The event loop stays responsive during a batch; SSE events flow in real
  time.
- **Positive:** No changes to `RenderPipeline` — it remains a pure synchronous class.
- **Positive:** `queue.Queue` is thread-safe by design; no locks required.
- **Negative:** A single `_progress_queue` serves the single-operator desktop use-case.
  Multi-user deployments would need a keyed `dict[session_id, Queue]`.
- **Negative:** If the browser disconnects before the sentinel, the worker still runs to
  completion and the queue fills; events are silently dropped.

---

## ADR-006: Observable Pipeline — `on_progress` Callback

**Status:** Accepted

**Date:** 2026-03

### Context

Both the CLI and the web server need progress reporting, but with different output
channels: the CLI writes to stdout; the web server pushes to an SSE queue.
Hardcoding either channel inside `RenderPipeline.run()` would couple the pipeline to
a specific output mechanism and make the other impossible without modification.

### Decision

`RenderPipeline.run()` accepts an optional `on_progress` callback:

```python
def run(
    self,
    on_progress: Callable[[int, int, CoverResult], None] | None = None,
) -> RenderSummary:
```

The callback is fired inside the `as_completed` loop immediately after each cover
completes.  Callers supply their own implementation:
- CLI: a closure that calls `print()`.
- Web server: a closure that calls `_progress_queue.put()`.

`run()` returns a `RenderSummary` dataclass regardless of whether a callback is supplied.

### Consequences

- **Positive:** `RenderPipeline` has no knowledge of how progress is displayed.
- **Positive:** The same pipeline class is used by CLI and web server without modification.
- **Positive:** `RenderSummary` provides a structured result for programmatic consumption.
- **Negative:** The callback runs inside the `as_completed` loop on the main thread of
  the `ThreadPoolExecutor` context; heavy callback implementations could become a
  bottleneck.  In practice both implementations are O(1) (print + queue.put).

---

## ADR-007: Desktop GUI — Modular Split of the Monolithic `gui/app.py`

**Status:** Accepted

**Date:** 2026-04

### Context

The desktop GUI initially lived entirely in a single `gui/app.py` file that grew to
~909 lines as the Control Center tab, Designer canvas, constants, and application shell
were added incrementally. A monolith of this size has several failure modes:

- Any change to the canvas engine requires reading and understanding 900+ lines of
  unrelated UI code.
- The CustomTkinter widget layer and the pure-canvas interaction logic are interleaved,
  making the canvas engine impossible to unit-test in isolation.
- Constants (colour palette, font sizes) duplicated across the file are a source of
  drift when the theme changes.
- The `App` class (the window shell) is coupled to rendering logic, path-management
  logic, and canvas hit-testing logic simultaneously.

### Decision

Split `gui/app.py` into five focused modules:

| Module | Responsibility |
|---|---|
| `gui/app.py` | Thin shell: window setup, header, `CTkTabview` with two tabs |
| `gui/control_tab.py` | Control Center tab: all batch-render UI and pipeline invocation |
| `gui/designer_tab.py` | Designer Pro tab: layout, right-panel sections, profile I/O |
| `gui/designer_engine.py` | Pure canvas interaction: zero CTk widgets, no I/O, no profile logic |
| `gui/constants.py` | Shared colour palette and font constants |

The split follows the same boundary principle as the CLI/core/engine tiers: each module
has one clear owner, and the most volatile logic (canvas interaction) is isolated in a
module with no UI framework dependency.

`gui/designer_engine.py` is kept free of all CustomTkinter imports so it can be tested
as a pure Python class (instantiated with a plain `tk.Canvas`), independent of the
full application lifecycle.

### Consequences

- **Positive:** `gui/app.py` is now ~130 lines; the module is readable in one sitting.
- **Positive:** `gui/designer_engine.py` has no CTk dependency — changes to the canvas
  interaction logic do not require understanding the tab layout.
- **Positive:** `gui/constants.py` is the single source of truth for the colour palette;
  changing a theme colour requires editing one file.
- **Negative:** Five files instead of one; contributors must know which module owns which
  behaviour. The module map in `CLAUDE.md` documents this.

---

## ADR-008: Logo Auto-Discovery — `_auto_logo()` Must Be Called in All Interfaces

**Status:** Accepted

**Date:** 2026-04

### Context

The CLI (`cli/main.py`) correctly resolved logo files from a profile's `assets/`
directory using `_auto_logo(assets_dir, stem)`, which checks `.png` then `.webp`
extensions before returning `None`.

Both the desktop GUI (`gui/control_tab.py`) and the web server (`web/server.py`) were
independently hardcoding:

```python
logo_paths = {"top": None, "bottom": None}
```

This meant that `logo_top.png` and `logo_bottom.png` placed in a profile's `assets/`
directory were silently ignored — a regression from the CLI's documented behaviour.
The root cause was copy-paste of the pipeline instantiation block without porting the
logo resolution step (issue #24).

### Decision

Define `_auto_logo(assets_dir: Path, stem: str) -> Path | None` in each module that
constructs a `RenderPipeline`. Each definition is identical:

```python
def _auto_logo(assets_dir: Path, stem: str) -> Path | None:
    for ext in (".png", ".webp"):
        p = assets_dir / f"{stem}{ext}"
        if p.exists():
            return p
    return None
```

Every `RenderPipeline` instantiation in every interface (CLI, GUI, web server) must
pass:

```python
logo_paths = {
    "top":    _auto_logo(profile.root / "assets", "logo_top"),
    "bottom": _auto_logo(profile.root / "assets", "logo_bottom"),
}
```

The rule is documented as a constraint in `CLAUDE.md` to prevent future regressions.

### Consequences

- **Positive:** Logo overlays work consistently across all three interfaces.
- **Positive:** No interface silently ignores assets that the user placed correctly.
- **Positive:** `CLAUDE.md` constraint makes the rule visible to AI assistants and
  future contributors before they write new interface code.
- **Negative:** The helper is defined three times (CLI, GUI, web). A future refactor
  could extract it to `core/` or a shared utility, but the current scope does not
  justify the coupling.