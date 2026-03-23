# Engineering Notes — box3d v2

This document captures the reasoning behind key technical choices made during the v2.0.0
hardening cycle. It is written for engineers maintaining or extending the codebase.

---

## 1. Dependency Philosophy

The explicit goal was: **Pillow and NumPy, nothing else.**

This constraint was not arbitrary. box3d is intended to run on constrained targets —
handheld gaming devices, Raspberry Pi-class ARM boards, minimal Docker images. Every
additional dependency increases the binary size (PyInstaller bundles), the attack surface,
and the maintenance burden.

The constraint forced a useful discipline: if an operation can be expressed with Pillow's
existing compositing model, it should be. NumPy enters only where linear algebra is
genuinely required (perspective coefficient solving via `numpy.linalg.solve`). Color
operations that looked "obviously NumPy" (diagonal matrix multiply for RGB scaling) were
replaced with Pillow's native C path once we measured that the latter was both faster and
allocation-free.

---

## 2. The Bottleneck Was Not Where We Expected

Initial profiling assumptions:

> "The bottleneck will be the perspective warp — solving an 8-variable linear system and
> resampling thousands of pixels must dominate runtime."

Profiling reality:

> The dominant costs were (a) redundant NumPy array allocations in the blending stage and
> (b) disk I/O for the intermediate spine temp file.

This is a common pattern in image processing: the linear algebra is cheap because it's a
constant-size system (8 equations); the allocation and I/O costs scale with the image
resolution and batch size.

Lessons applied:

- Removed all intermediate `np.zeros_like` / `np.empty_like` allocations in `blending.py`
  by operating in-place where safe.
- Replaced the spine temp-file pattern with direct `PIL.Image` object passing (ADR-003).

---

## 3. Memory Safety: Two Layers Beats One

The OOM hardening strategy (ADR-002) deliberately enforces the 8 192 px ceiling at two
independent points:

1. **Profile validation** (`core/models.py`) — prevents a profile template from being
   declared at a size that would trigger OOM during the compositing stage.

2. **Input downscale** (`engine/perspective.py`) — prevents a user-supplied cover image
   from exhausting memory even if the profile itself is within bounds.

The reason for two layers is defense-in-depth: neither layer should be the sole guard.
If a future refactor moves profile loading to a lazy path, the engine layer still protects
against oversized inputs. If a future engine changes the resize logic, the profile
validator still prevents oversized templates from being declared.

The 8 192 px value was chosen as a practical ceiling: a 8 192 × 8 192 RGBA image consumes
~256 MiB, which is within the RAM budget of all supported targets while still exceeding
the practical resolution of any retro game cover art (typically 550–1 000 px wide).

---

## 4. Thread Safety

`RenderPipeline` uses `concurrent.futures.ThreadPoolExecutor`. Thread safety is achieved
by structural design rather than by locking:

- The template image is loaded once before workers start and passed as a read-only
  argument. No worker modifies it.
- `compositor.render_cover()` takes all inputs as arguments and returns a `CoverResult`.
  It has no access to shared mutable state.
- The only shared structure is the `futures` dict inside `RenderPipeline.run()`, which is
  written only in the submission loop (single thread) and read only after `as_completed()`
  (safe by the executor contract).

This means adding more workers scales the throughput linearly without requiring any
synchronization primitives. The downside is higher peak RAM: each worker holds one full
in-memory pipeline of images. With the 8 192 px ceiling in place, worst-case per-worker
RAM is bounded.

---

## 5. Profile Security: Path Traversal

Profile names come from directory entries on the filesystem and, in future, potentially
from user input via the CLI. The `ProfileRegistry` applies a strict allowlist regex
before any filesystem operation:

```python
_SAFE_NAME = re.compile(r'^[a-zA-Z0-9_-]+$')
```

A profile name that does not match is rejected with a warning. This prevents:

- `../etc/passwd` style traversal via crafted directory names.
- Names with shell metacharacters that could be dangerous if the name is ever interpolated
  into a shell command by a wrapper script.

The profiles directory itself is resolved to an absolute path at registry construction
time, so symlink-following out of the directory is not possible via the name validator.

---

## 6. The Compositing Model

The five-step pipeline (perspective → perspective → screen blend → DstIn → save) was
arrived at iteratively. The two non-obvious choices:

**Alpha-weighted Screen blend (step 3).**
A naive `Image.blend` or straight Screen blend washes out dark covers because
near-transparent template pixels (alpha ≈ 12) still contribute luminance at full weight.
Weighting the Screen contribution by `template_alpha / 255` means that transparent
template pixels contribute nothing, and the blend is proportional to how much the template
is actually "there". This is the correct physical model: the template overlay should only
be visible where the template itself is visible.

**Union silhouette for DstIn (step 4).**
The MVS (Neo Geo) profile uses a template that is mostly transparent — it provides
shading only at the spine edge and top/bottom borders. A DstIn keyed solely on template
alpha would erase the cover face where `template.alpha = 0`. The fix is to take the
union (max) of the template alpha and the cover-painted canvas alpha as the clip mask.
This preserves the cover wherever it was painted, regardless of template transparency.

---

## 7. Box3D Designer Pro: Scope Decisions

The visual profile editor is delivered as a single self-contained HTML file with embedded
JavaScript and CSS. The key scope decisions:

- **No server.** The file opens directly via `file://` or via Python's `webbrowser` module.
  No `localhost` server, no build step, no npm.
- **No persistence.** The editor is stateless; profiles are exported as JSON downloads.
  This avoids the need for a backend and keeps the tool portable.
- **No framework dependency.** The canvas engine, profile import/export, and UI are
  implemented in vanilla JavaScript. This keeps the file self-contained and eliminates
  the JS dependency management problem.

The trade-off is that the file grows large as features are added. The current limit is
acceptable; if the file exceeds ~500 kB, it should be split into linked external assets
(still no build step required).
