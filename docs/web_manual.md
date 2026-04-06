# Box3D Control Center — User Manual

> **Version:** 2.1.0  
> **Interface:** Browser (localhost:8000)  
> **Requires:** `pip install box3d[web]`

---

## Overview

Box3D ships with two interfaces that use exactly the same rendering engine:

| Interface | Best for | Requirements |
|---|---|---|
| **CLI** (`box3d render`) | Automation, scripts, batch jobs | Python only (Pillow + NumPy) |
| **Control Center** (this UI) | Interactive use, first-time users | `pip install .[web]` |

Both produce identical output. The Control Center is a visual layer on top of the same `RenderPipeline` — choosing one does not prevent using the other.

---

## Starting the Server

```bash
# 1. Install the web extra (once)
pip install "box3d[web]"

# 2. Start the server from the box3d project directory
uvicorn web.server:app --reload

# 3. Open your browser
# http://localhost:8000
```

The `--reload` flag restarts the server automatically when you change source files. For production-like usage, omit it.

To bind to a different port:

```bash
uvicorn web.server:app --host 0.0.0.0 --port 9000
```

---

## UI Walkthrough

### Profile

Select which box template to render onto. The dropdown is populated automatically from your `profiles/` directory. The dimensions shown (e.g. `703 × 1000 px`) are the pixel size of the output image.

Built-in profiles:

| Name | Description | Output size |
|---|---|---|
| `mvs` | Neo Geo MVS cartridge | 703 × 1000 px |
| `arcade` | Arcade cabinet marquee | 665 × 907 px |
| `dvd` | Standard DVD case | 633 × 907 px |

To add a custom profile, drop a directory into `profiles/` with a `profile.json` and `template.png`. It appears in the dropdown on the next page load.

---

### Paths

#### Covers Directory (required)
The folder containing your flat cover images (`.webp`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`). All images in the directory and its subdirectories are processed.

Example: `/home/user/box3d/data/inputs/covers`

The border turns **green** when the path resolves to an existing directory, **red** if it does not. The render button stays disabled until both required paths are valid.

#### Output Directory (required)
Where the rendered 3D box images are written. The directory is created automatically if it does not exist.

Example: `/home/user/box3d/data/output/converted`

#### Marquees Directory (optional)
Per-game logo images matched by filename stem. If `sonic.webp` is in Covers, the pipeline looks for `sonic.*` here and uses it as the game logo on the spine.

Leave blank to skip per-game logos (the profile-level `assets/logo_game.*` fallback still applies if present).

---

### Render Options

#### Workers
Number of parallel threads used to process covers simultaneously.

- Default: `4`
- Recommended: Set to the number of CPU cores for maximum throughput.
- Tip: Use `--workers auto` from the CLI to let the engine detect `os.cpu_count()` automatically. The UI equivalent is to match your system's core count manually.

#### Blur Radius
Controls the Gaussian blur applied to the spine background before the dark overlay.

- Default: `20`
- Range: `0` – ~`100` (values above 50 have diminishing returns)
- `0` = no blur (sharp sample from cover edge)
- Higher values = softer, more atmospheric spine

#### Darken Alpha
Opacity of the dark overlay applied on top of the blurred spine background. Controls how dark the spine strip appears.

- Default: `180`
- Range: `0` (transparent — no overlay) to `255` (fully opaque black)
- Lower values let the cover colour show through more strongly.
- Higher values produce a near-black spine (logo-dominant look).

#### Cover Fit
How the cover image is scaled to fill the template's cover quad:

| Mode | Behaviour |
|---|---|
| `stretch` (default) | Fills the quad exactly, may distort aspect ratio |
| `fit` | Scales to fit within the quad, letterboxed with transparency |
| `crop` | Scales to fill the quad, centre-crops the overflow |

Leave blank to use the profile's default.

#### Output Format
- `webp` (default) — smaller file size, excellent quality at 92% quality setting
- `png` — lossless, larger files

#### Skip Existing
When checked, covers whose output file already exists in the Output Directory are silently skipped. Useful for resuming an interrupted batch.

#### Dry Run
Simulates the pipeline without writing any files. Use this to verify that all covers are discovered and inputs are valid before committing a long render.

#### No Logos
Disables all logo overlays on the spine (game logo, top logo, bottom logo). Useful when you want to inspect raw spine generation without branding.

---

## Progress View

Once you click **Start Render**, the form is locked and the progress panel activates.

**Progress bar** — fills from 0% to 100% as covers complete. Driven by real-time Server-Sent Events (SSE) from the backend.

**Log** — shows one line per cover:
- `✔ sonic.webp  (1.23s)` — rendered successfully
- `⊘ mario.webp` — skipped (already exists)
- `◌ zelda.webp` — dry-run (not written)
- `✘ kirby.webp` — error (see summary for details)

The log auto-scrolls to the latest entry.

---

## Render Summary Modal

When the job finishes, a modal displays:

| Field | Meaning |
|---|---|
| Total | All covers discovered in the input directory |
| Succeeded | Covers rendered and saved successfully |
| Skipped | Covers skipped due to `skip_existing` |
| Errors | Covers that failed (see error list below stats) |
| Dry-run | Covers that would have been processed (dry-run mode) |
| Time | Total wall-clock time for the batch |

If there were errors, each one appears as `<stem>: <error message>` below the stats. Use this to identify which specific files failed.

Click **Close** or anywhere outside the modal to dismiss it. The form re-enables and you can start another render.

---

## Troubleshooting

### Red border on a path input

The path validation runs when you click out of the field (`onblur`). A red border means the path you typed is not a directory that currently exists.

**Fix:** Verify the path with your file manager or terminal:
```bash
ls /your/path/here
```
Make sure there are no typos, and that the directory already exists (the Output directory is created automatically by the engine, but it still needs a valid *parent*).

### Render button stays disabled

The Start Render button activates only when both **Covers Directory** and **Output Directory** show green borders. Tab through the required inputs to trigger validation, or click into each field and then click elsewhere.

### Circuit Breaker tripped

If you see `Circuit Breaker: TRIPPED` in the summary, the pipeline aborted because too many consecutive covers failed. This protects against runaway batch jobs consuming resources indefinitely.

**Common causes:**
- Corrupt or truncated image files in the covers directory
- Covers with extreme resolutions being rejected by the OOM guard (> 8192 px on either axis)
- Insufficient disk space in the output directory

**Fix:**
1. Check the error list in the summary — the affected filenames are listed.
2. Open `data/output/logs/box3d.log` (if `--log-file ""` was set) for the full stack trace.
3. Remove or replace the problematic files and re-run. Use **Skip Existing** to continue from where the batch stopped.

### Progress bar stuck at 0%

The SSE stream (`/api/progress`) may have failed to connect. This can happen if:
- The server was restarted mid-render
- An ad-blocker or browser extension blocked the streaming response
- A network proxy buffered the SSE response

**Fix:** Reload the page and start the render again. If the issue persists, try a different browser or disable extensions.

### "Cannot reach server" in the profile dropdown

The JavaScript failed to fetch `/api/profiles`. Ensure the Uvicorn server is running:

```bash
uvicorn web.server:app --reload
```

And that you are navigating to the correct port (default `http://localhost:8000`).

---

## API Reference (for developers)

The Control Center is backed by a REST API you can call directly:

| Endpoint | Method | Description |
|---|---|---|
| `/api/profiles` | `GET` | List all profiles with name and dimensions |
| `/api/validate-path` | `POST` | Check if a path is an existing directory |
| `/api/render` | `POST` | Start a render job (returns immediately) |
| `/api/progress` | `GET` | SSE stream of per-cover progress events |

Interactive API documentation (Swagger UI) is available at:
`http://localhost:8000/docs`

---

## Uninstalling the Web Extra

The web extra does not affect the CLI. To remove it:

```bash
pip uninstall fastapi uvicorn
# Core box3d (CLI + engine) continues to work normally
```
