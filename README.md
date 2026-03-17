# box3d v2

**Arcade game 3D box art generator — plugin profiles, pure Python.**

box3d takes a flat front-cover image and renders it as a photorealistic 3D
box with a textured spine, logo overlays, and the shading baked into the
template.  Output is a transparency-correct RGBA image ready for
EmulationStation, Pegasus, or any other launcher.

```
covers/sf2.webp  +  profiles/mvs/  →  output/sf2.webp
```

| | |
|---|---|
| **Profiles** | MVS, Arcade, DVD — JSON plugins, zero code changes |
| **Dependencies** | Pillow ≥ 10, NumPy ≥ 1.24 |
| **Python** | 3.11 + |
| **OS** | Linux · macOS · Windows |

---

## Quick start

```bash
git clone https://github.com/RtaSistemas/box3d.git
cd box3d
pip install -e .

# Drop covers into data/inputs/covers/
python cli/main.py render --profile mvs
```

---

## Architecture

```
box3d/
├── core/
│   ├── models.py       ← Domain types (Profile, ProfileGeometry, RenderOptions…)
│   ├── registry.py     ← Auto-discovers profiles/ plugins
│   └── pipeline.py     ← Parallel rendering orchestrator
│
├── engine/
│   ├── perspective.py  ← Perspective warp (numpy.linalg.solve + PIL.transform)
│   ├── blending.py     ← alpha_weighted_screen, dst_in, build_silhouette_mask
│   ├── spine_builder.py← 2-D spine strip (blur, overlay, logos)
│   └── compositor.py   ← Per-cover renderer (coordinates all engine modules)
│
├── profiles/
│   ├── mvs/            ← profile.json + template.png + assets/
│   ├── arcade/
│   └── dvd/
│
├── cli/
│   └── main.py         ← box3d render / profiles list / designer
│
├── tools/
│   └── box3d_designer_pro/   ← Visual profile editor (browser-based)
│
└── tests/
    └── test_v2.py      ← 49 tests covering every module
```

### Design principles

- **Profiles are plugins.** No code change is needed to add a new box type.
  Drop a directory with `profile.json` + `template.png` into `profiles/` and
  it is available immediately.
- **Layers never cross.** `core/` knows nothing about rendering.  `engine/`
  knows nothing about profiles.  `cli/` is a thin wiring layer.
- **Pure Python rendering.** No external binaries — Pillow and NumPy only.

---

## CLI reference

### `box3d render`

```
python cli/main.py render --profile <name> [options]

Options:
  --profile, -p     Profile name (required)
  --input,   -i     Cover images directory  (default: data/inputs/covers/)
  --output,  -o     Output directory        (default: data/output/converted/)
  --workers, -w     Parallel threads        (default: 4)
  --blur-radius,-b  Gaussian blur radius    (default: 20)
  --darken,  -d     Spine dark overlay 0-255(default: 180)
  --rgb R,G,B       RGB multipliers on template
  --cover-fit       stretch | fit | crop
  --spine-source    left | right | center
  --no-rotate       Disable logo rotation
  --no-logos        No spine logos
  --output-format   webp | png              (default: webp)
  --skip-existing   Incremental run
  --dry-run         Simulate without writing
  --verbose, -v     Debug logging
  --log-file [PATH] File logging (opt-in)
```

### `box3d profiles`

```
python cli/main.py profiles list       # list loaded profiles
python cli/main.py profiles validate   # check template files exist
```

### `box3d designer`

```
python cli/main.py designer            # open Box3D Designer Pro in browser
```

---

## Adding a profile

1. Create `profiles/<name>/` with:
   - `profile.json` — geometry, spine layout, warp quads
   - `template.png` — RGBA box template image
   - `assets/`      — optional logos and marquees

2. Minimal `profile.json`:

```json
{
  "name": "ps2",
  "template_size": { "width": 550, "height": 770 },
  "spine": { "width": 55, "height": 690 },
  "cover": { "width": 430, "height": 690 },
  "spine_quad": {
    "tl": [4, 40], "tr": [59, 22],
    "br": [59, 748], "bl": [4, 730]
  },
  "cover_quad": {
    "tl": [59, 22], "tr": [490, 68],
    "br": [490, 702], "bl": [59, 748]
  },
  "spine_source": "left",
  "cover_fit": "stretch",
  "spine_layout": {
    "game":   { "max_w": 45, "max_h": 240, "center_y": 350 },
    "top":    { "max_w": 45, "max_h": 90,  "center_y": 110 },
    "bottom": { "max_w": 45, "max_h": 60,  "center_y": 620 },
    "logo_alpha": 0.85, "rotate_logos": true
  }
}
```

3. Use **Box3D Designer Pro** to visually position elements:

```bash
python cli/main.py designer
```

4. Test:

```bash
python cli/main.py render --profile ps2 --dry-run
```

---

## Box3D Designer Pro

A browser-based visual editor for creating and editing profiles.

```
tools/box3d_designer_pro/
├── index.html      ← Full UI (single file, no server needed)
├── canvas.js       ← Interactive canvas engine (drag, resize, grid, zoom)
├── profile.js      ← Import / export profile JSON + Python snippet
├── app.js          ← Application wiring
└── styles/
    ├── main.css    ← Layout system
    └── retro.css   ← Neon / retro-futuristic visual identity
```

**Features:**
- Load any PNG template image
- Add and position `spine`, `cover`, `logo`, `marquee` regions
- Drag to move, corner handles to resize
- Grid with configurable size and snap-to-grid
- Real-time JSON preview
- Export `profile.json` or a Python snippet
- Import existing profiles
- Retro neon aesthetic with optional scanline overlay

---

## Compositing pipeline

```
transparent canvas  (template size)
        │
        ├─ 1. Perspective warp — spine strip
        ├─ 2. Perspective warp — front cover  (cover_fit respected)
        ├─ 3. Alpha-weighted Screen blend — template overlay
        ├─ 4. DstIn — clip to union silhouette
        └─ 5. Save  (WebP q92 or PNG)
```

The **alpha-weighted Screen blend** prevents near-white template pixels
(arcade/dvd profiles, alpha ≈ 12) from washing out dark covers, while
still applying the intended shading at opaque borders.

The **union silhouette** for DstIn ensures the cover face is visible even
where `template.alpha = 0` (MVS profile uses a mostly-transparent template).

---

## Testing

```bash
pytest tests/test_v2.py -v        # 49 tests
```

| Class | Tests | What |
|---|---|---|
| `TestModels` | 3 | Domain dataclasses |
| `TestRegistry` | 13 | Profile loading, validation, custom profiles |
| `TestPerspective` | 9 | Warp, resize modes, all profiles |
| `TestBlending` | 9 | Screen, DstIn, color matrix, silhouette |
| `TestSpineBuilder` | 7 | Spine generation for all profiles |
| `TestPipeline` | 8 | End-to-end renders, dry-run, all profiles |

---

## License

MIT — see [LICENSE](LICENSE).
