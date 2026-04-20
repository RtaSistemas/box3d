# Box3D Control Center — User Manual

<img width="1918" height="912" alt="Control Center" src="https://github.com/user-attachments/assets/c1570fb6-1d3f-4b13-9956-07e74008b318" />

> **Version:** 3.0.0RC
> **Interface:** Browser (`http://127.0.0.1:8000`)
> **Requires:** `pip install box3d[web]`

---

## Overview

Box3D ships with three interfaces that use the same rendering engine:

| Interface | Best for | Requirements |
|---|---|---|
| **CLI** (`box3d render`) | Automation, scripts, batch jobs | Pillow + NumPy only |
| **Control Center** (this doc) | Browser-based interactive use | `pip install .[web]` |
| **Desktop GUI** (`box3d-gui`) | Native desktop, includes Designer tab | `pip install .[gui]` |

Both produce identical output. The Control Center is a visual layer on top of the same `RenderPipeline`.

---

## Starting the Server

### Recommended — no-arg launch

If the `[web]` extra is installed, running `box3d` with no subcommand starts the server automatically:

```bash
box3d
# Server starts at http://127.0.0.1:8000
```

### Explicit serve command

```bash
box3d serve                                    # http://127.0.0.1:8000
box3d serve --host 0.0.0.0 --port 9000        # expose on LAN
```

### From source (development)

```bash
pip install -e ".[web]"
uvicorn web.server:app --reload
# --reload restarts automatically when source files change
```

---

## Navigating the UI

The header contains two navigation links:

| Link | Destination |
|---|---|
| **Control Center** | This page (render jobs) |
| **Designer Pro ↗** | Opens Box3D Designer Pro in a new tab (`/designer/`) |

---

## Configuration Panel (left sidebar)

### Profile

Select which box template to render onto. The dropdown is populated automatically from your `profiles/` directory. The dimensions shown (e.g. `703 × 1 000 px`) are the pixel size of the output image.

Built-in profiles:

| Name | Description | Output size |
|---|---|---|
| `mvs` | Neo Geo MVS cartridge | 703 × 1 000 px |
| `arcade` | Arcade cabinet | 665 × 907 px |
| `dvd` | Standard DVD case | 633 × 907 px |

To add a custom profile, drop a directory into `profiles/` with a `profile.json` and `template.png`. It appears in the dropdown on the next page load.

---

### Paths

Each path input has a `📂` button that opens the typed directory in your OS file manager. Path validation runs on `blur` (when you click out of the field).

| Colour | Meaning |
|---|---|
| Green border | Directory exists |
| Red border | Directory not found |

#### Covers Directory (required)

The folder containing flat cover images (`.webp`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`). All images found recursively in the directory are processed.

Example: `/home/user/box3d/data/inputs/covers`

#### Output Directory (required)

Where rendered 3D box images are written. Created automatically if it does not exist.

Example: `/home/user/box3d/data/output/converted`

#### Marquees Directory (optional)

Per-game logos matched by filename stem. If `sonic.webp` is in Covers, the pipeline looks for `sonic.*` here and uses it as the game logo on the spine.

Leave blank to skip per-game logos (the profile-level `assets/logo_game.*` fallback still applies).

---

### Options

#### Workers

Number of parallel threads for simultaneous cover processing.

- Default: `4`
- Tip: set to your machine's CPU core count for maximum throughput.
- From the CLI you can use `--workers auto` to set this automatically.

#### Blur Radius

Gaussian blur applied to the spine background strip sampled from the cover edge.

- Default: `20` · Range: `0`–~`100`
- `0` = sharp edge sample · Higher = softer, more atmospheric spine

#### Darken Alpha

Opacity of the dark overlay applied over the blurred spine background.

- Default: `180` · Range: `0` (off) – `255` (solid black)
- Lower values let the cover colour show through; higher values produce a near-black, logo-dominant look.

#### Cover Fit

How the cover image is scaled to fill the template's cover quad:

| Mode | Behaviour |
|---|---|
| `stretch` | Fills the quad exactly — may distort aspect ratio |
| `fit` | Scales within the quad — letterboxed with transparency |
| `crop` | Scales to fill — centre-crops overflow |

Leave blank to use the profile's default.

#### Spine Source

Which edge of the cover image is sampled to create the spine background strip:

| Value | Behaviour |
|---|---|
| (blank) | Profile default (usually `left`) |
| `left` | Samples the left edge of the cover |
| `right` | Samples the right edge of the cover |
| `center` | Samples the centre strip of the cover |

#### Output Format

- `webp` (default) — smaller files, excellent quality at q 92
- `png` — lossless, larger files

#### RGB Tint

A colour picker that applies per-channel RGB multipliers to the spine background:

- White (`#ffffff`) → `[2.0, 2.0, 2.0]` (doubled luminance)
- Neutral (`#808080`) → `[1.0, 1.0, 1.0]` (no tinting; picker default)
- Black (`#000000`) → `[0.0, 0.0, 0.0]` (full darkness)

The `↺` button resets the picker to neutral. When neutral, the field is sent as `null` to the backend (no processing overhead).

#### Skip Existing

When checked, covers whose output file already exists are silently skipped. Useful for resuming an interrupted batch.

#### Dry Run

Simulates the pipeline without writing any files. Use this to verify inputs are valid before a long render.

#### No Logos

Disables all logo overlays on the spine (game logo, top logo, bottom logo).

---

## Running a Render

1. Select a profile.
2. Enter and validate the Covers and Output directory paths (both must show green).
3. Adjust any options.
4. Click **▶ START RENDER**.

The form locks while rendering. The progress panel takes over the right side.

---

## Progress Panel

**Progress bar** — fills from 0 % to 100 % driven by real-time Server-Sent Events (SSE).

**Log** — one line per cover:

| Icon | Meaning |
|---|---|
| `✔` | Rendered successfully |
| `⊘` | Skipped (skip existing) |
| `◌` | Dry-run (not written) |
| `✘` | Error |

The log auto-scrolls to the latest entry.

---

## Render Summary Modal

When the job finishes, a modal displays:

| Field | Meaning |
|---|---|
| Total | All covers found in the input directory |
| Succeeded | Covers rendered and saved |
| Skipped | Covers skipped (`skip_existing`) |
| Errors | Covers that failed |
| Dry-run | Covers simulated in dry-run mode |
| Time | Total wall-clock duration |
| Circuit Breaker | `TRIPPED` if the breaker aborted the batch early |

**Preview image** — if at least one cover rendered successfully, the first output image is shown inline.

**Open Output Folder** — opens the output directory in your OS file manager.

**Error list** — if errors occurred, each one is shown as `<stem>: <message>`.

Click **Close** or outside the modal to dismiss it. The form re-enables for another run.

---

## Troubleshooting

### Red border on a path input

Path validation runs on `blur`. A red border means the path does not resolve to an existing directory.

- Verify the path exists: `ls /your/path/`
- Ensure there are no typos.
- The output directory is created automatically — but its *parent* must exist.

### Render button stays disabled

The **▶ START RENDER** button enables only when both required paths show green. Tab through each input to trigger validation.

### Circuit Breaker tripped

The pipeline aborted because the error rate exceeded the safety thresholds:
- **10 consecutive failures**, OR
- **> 20 % of processed covers** failed (minimum 3 errors before this branch activates)

**Common causes:**
- Corrupt or truncated images in the covers directory
- Extreme resolutions rejected by the OOM guard (> 8 192 px)
- Insufficient disk space in the output directory
- Wrong covers directory (contains non-image files)

**Fix:**
1. Review the error list in the summary modal.
2. Check `data/output/logs/box3d.log` for full stack traces.
3. Remove or fix the problematic files, then re-run with **Skip Existing** to continue from where the batch stopped.

### Progress bar stuck at 0 %

The SSE stream failed to connect. Possible causes:
- Server restarted mid-render.
- Browser extension or proxy buffered the streaming response.

**Fix:** Reload the page and start again. If the issue persists, try a different browser.

### "Cannot reach server" in the profile dropdown

The browser could not fetch `/api/profiles`. Ensure the server is running:

```bash
box3d serve
```

Navigate to the correct address (default `http://127.0.0.1:8000`).

### Preview image not shown in the summary

The preview requires at least one cover to render successfully (`succeeded > 0`).
In dry-run mode no files are written, so no preview is available.

---

## API Reference

The Control Center is backed by a REST API you can call directly:

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/api/profiles` | `GET` | — | List all profiles with name and dimensions |
| `/api/validate-path` | `POST` | `{"path": "..."}` | Check if a path is an existing directory |
| `/api/render` | `POST` | `RenderRequest` | Start a render job (returns immediately) |
| `/api/progress` | `GET` | — | SSE stream of per-cover progress events |
| `/api/open-folder` | `POST` | `{"path": "..."}` | Open a directory in the OS file manager |
| `/api/preview/{filename}` | `GET` | — | Serve a rendered output image |

Interactive Swagger UI: `http://127.0.0.1:8000/docs`

### `RenderRequest` schema

```json
{
  "profile":       "mvs",
  "covers_dir":    "/path/to/covers",
  "output_dir":    "/path/to/output",
  "marquees_dir":  null,
  "workers":       4,
  "blur_radius":   20,
  "darken_alpha":  180,
  "cover_fit":     null,
  "spine_source":  null,
  "output_format": "webp",
  "skip_existing": false,
  "dry_run":       false,
  "no_logos":      false,
  "rgb_matrix":    null
}
```

`rgb_matrix` is `[r, g, b]` floats in the `0.0`–`2.0` range, or `null` for no tinting.

### SSE event format

Each progress event is a JSON object on `data:`:

```json
{"done": 3, "total": 10, "stem": "sonic", "status": "ok", "elapsed": 1.23}
```

The final sentinel event has `done: -1` and carries the full `RenderSummary` fields:

```json
{
  "done": -1,
  "total": 10, "succeeded": 9, "skipped": 0, "failed": 1, "dry": 0,
  "elapsed_time": 12.5,
  "breaker_tripped": false,
  "errors": ["kirby: unsupported image format"],
  "first_stem": "sonic",
  "output_format": "webp"
}
```

---

## Uninstalling the Web Extra

```bash
pip uninstall fastapi uvicorn httpx
# The CLI and rendering engine continue to work normally
```
