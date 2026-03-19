#!/usr/bin/env python3
"""
tests/run_visual_tests.py — Visual integration tests (v2 architecture)
=======================================================================
Renders a 3D box for every parameter combination defined in MATRIX using
the plugin profile registry and assets in tests/assets/, then produces an
HTML report matching the v1 aesthetic.

Usage::

    python tests/run_visual_tests.py
    python tests/run_visual_tests.py --open
    python tests/run_visual_tests.py --workers 8
    python tests/run_visual_tests.py --groups 1_profiles 4_rgb
    python tests/run_visual_tests.py --out /tmp/visual_out
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import mimetypes
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT   = Path(__file__).parent.parent
ASSETS = Path(__file__).parent / "assets"
sys.path.insert(0, str(ROOT))

from PIL import Image

from core.models       import RenderOptions
from core.registry     import ProfileRegistry
from engine.compositor import _composite
from engine.spine_builder import build_spine


# ---------------------------------------------------------------------------
# Variant definition
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    id:           str
    group:        str
    title:        str
    description:  str
    profile_name: str         = "mvs"
    blur_radius:  int         = 20
    darken_alpha: int         = 180
    spine_source: str | None  = None
    cover_fit:    str | None  = None
    rotate_logos: bool | None = None
    with_logos:   bool        = True
    rgb_matrix:   str | None  = None
    fmt:          str         = "webp"


# ---------------------------------------------------------------------------
# Test matrix — 35 variants across 10 groups
# ---------------------------------------------------------------------------

MATRIX: list[Variant] = [

    # ── 1. Profiles ──────────────────────────────────────────────────────
    Variant("1_mvs_default",    "1_profiles", "MVS — default",
            "Default settings using the MVS (Neo Geo) profile"),
    Variant("1_arcade_default", "1_profiles", "Arcade — default",
            "Default settings using the Arcade profile",
            profile_name="arcade"),
    Variant("1_dvd_default",    "1_profiles", "DVD — default",
            "Default settings using the DVD profile",
            profile_name="dvd"),

    # ── 2. Blur radius ───────────────────────────────────────────────────
    Variant("2_blur_8",  "2_blur", "Blur radius 8",
            "Light blur — spine texture visible", blur_radius=8),
    Variant("2_blur_20", "2_blur", "Blur radius 20 (default)",
            "Default blur — smooth gradient"),
    Variant("2_blur_40", "2_blur", "Blur radius 40",
            "Heavy blur — near-uniform spine colour", blur_radius=40),

    # ── 3. Darken overlay ────────────────────────────────────────────────
    Variant("3_darken_0",   "3_darken", "Darken 0",
            "No dark overlay — raw cover colour", darken_alpha=0),
    Variant("3_darken_80",  "3_darken", "Darken 80",
            "Light darkening", darken_alpha=80),
    Variant("3_darken_180", "3_darken", "Darken 180 (default)",
            "Default overlay"),
    Variant("3_darken_230", "3_darken", "Darken 230",
            "Heavy darkening — spine almost black", darken_alpha=230),

    # ── 4. RGB colour matrix ─────────────────────────────────────────────
    Variant("4_rgb_neutral",     "4_rgb", "RGB neutral",
            "No colour change",
            rgb_matrix="1.0 0 0  0 1.0 0  0 0 1.0"),
    Variant("4_rgb_warm_light",  "4_rgb", "Warm light (1.15,1.0,0.85)",
            "Slight warm shift — good for retro art",
            rgb_matrix="1.15 0 0  0 1.0 0  0 0 0.85"),
    Variant("4_rgb_warm_strong", "4_rgb", "Warm strong (1.3,1.0,0.7)",
            "Strong warm shift",
            rgb_matrix="1.3 0 0  0 1.0 0  0 0 0.7"),
    Variant("4_rgb_cool_light",  "4_rgb", "Cool light (0.9,1.0,1.1)",
            "Slight cool / blue shift",
            rgb_matrix="0.9 0 0  0 1.0 0  0 0 1.1"),
    Variant("4_rgb_cool_strong", "4_rgb", "Cool strong (0.75,0.9,1.2)",
            "Strong cool shift",
            rgb_matrix="0.75 0 0  0 0.9 0  0 0 1.2"),
    Variant("4_rgb_brighter",    "4_rgb", "Brighter (1.2,1.2,1.2)",
            "Uniform brightness increase",
            rgb_matrix="1.2 0 0  0 1.2 0  0 0 1.2"),
    Variant("4_rgb_darker",      "4_rgb", "Darker (0.8,0.8,0.8)",
            "Uniform brightness decrease",
            rgb_matrix="0.8 0 0  0 0.8 0  0 0 0.8"),

    # ── 5. Logo rotation ─────────────────────────────────────────────────
    Variant("5_rotate_on",  "5_rotate", "Logos rotated (default)",
            "90 degrees CW — reads bottom-to-top on a standing box",
            profile_name="arcade"),
    Variant("5_rotate_off", "5_rotate", "Logos not rotated",
            "Logos in original orientation",
            profile_name="arcade", rotate_logos=False),

    # ── 6. Spine source edge ─────────────────────────────────────────────
    Variant("6_source_left",   "6_spine_source", "Source: left (default)",
            "Spine colour from the left edge of the cover"),
    Variant("6_source_right",  "6_spine_source", "Source: right",
            "Spine colour from the right edge",
            spine_source="right"),
    Variant("6_source_center", "6_spine_source", "Source: center",
            "Spine colour from the centre strip",
            spine_source="center"),

    # ── 7. Cover fit mode ────────────────────────────────────────────────
    Variant("7_fit_stretch", "7_cover_fit", "Fit: stretch (default)",
            "Force exact dimensions"),
    Variant("7_fit_fit",     "7_cover_fit", "Fit: fit",
            "Preserve aspect ratio, pad with transparency",
            cover_fit="fit"),
    Variant("7_fit_crop",    "7_cover_fit", "Fit: crop",
            "Preserve aspect ratio, crop to centre",
            cover_fit="crop"),

    # ── 8. Logos ─────────────────────────────────────────────────────────
    Variant("8_logos_all",  "8_logos", "All logos",
            "Game marquee + top + bottom logos"),
    Variant("8_logos_none", "8_logos", "No logos",
            "Spine background only", with_logos=False),

    # ── 9. Output format ─────────────────────────────────────────────────
    Variant("9_fmt_webp", "9_format", "Format: WebP",
            "WebP output (quality 92)"),
    Variant("9_fmt_png",  "9_format", "Format: PNG",
            "Lossless PNG output", fmt="png"),

    # ── 10. Full combinations ────────────────────────────────────────────
    Variant("10_combo_warm_arcade", "10_combos",
            "Arcade — warm, blur suave",
            "Arcade com tom quente, lombada texturizada",
            profile_name="arcade", blur_radius=15, darken_alpha=160,
            rgb_matrix="1.1 0 0  0 1.0 0  0 0 0.9"),
    Variant("10_combo_cold_dvd", "10_combos",
            "DVD — cold, dark",
            "DVD com tom frio, lombada escura e abstrata",
            profile_name="dvd", spine_source="left", darken_alpha=210,
            rgb_matrix="0.9 0 0  0 0.95 0  0 0 1.15", blur_radius=40),
    Variant("10_combo_natural", "10_combos",
            "Arcade — natural, sem logos",
            "Cor natural da capa, lombada limpa",
            profile_name="arcade", spine_source="center",
            darken_alpha=80, with_logos=False),
    Variant("10_combo_hicon", "10_combos",
            "MVS — high contrast logos",
            "Maximo contraste — logos dominam",
            darken_alpha=230, blur_radius=45,
            rgb_matrix="0.95 0 0  0 0.95 0  0 0 0.95"),
    Variant("10_combo_right_warm", "10_combos",
            "MVS — source right + warm",
            "Right edge colour with warm tint",
            spine_source="right", rgb_matrix="1.15 0 0  0 1.0 0  0 0 0.85"),
    Variant("10_combo_crop_cool", "10_combos",
            "Arcade — crop + cool",
            "Capa cortada ao centro, shading frio",
            profile_name="arcade", cover_fit="crop",
            rgb_matrix="0.85 0 0  0 0.9 0  0 0 1.2"),
]

# Human-readable group labels
GROUP_LABELS = {
    "1_profiles":     "Perfis",
    "2_blur":         "Blur radius",
    "3_darken":       "Darken overlay",
    "4_rgb":          "Correcao de cor (RGB)",
    "5_rotate":       "Rotacao de logos",
    "6_spine_source": "Spine source",
    "7_cover_fit":    "Cover fit",
    "8_logos":        "Logos",
    "9_format":       "Formato de saida",
    "10_combos":      "Combinacoes completas",
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@dataclass
class VariantResult:
    variant:   Variant
    ok:        bool
    elapsed:   float
    file_size: int  = 0
    error:     str  = ""


def _render(v: Variant, output_dir: Path, registry: ProfileRegistry) -> VariantResult:
    t0 = time.perf_counter()
    try:
        profile = registry.get(v.profile_name)
        geom    = profile.geometry
        layout  = profile.layout

        if v.spine_source is not None:
            geom = dataclasses.replace(geom, spine_source=v.spine_source)
        if v.cover_fit is not None:
            geom = dataclasses.replace(geom, cover_fit=v.cover_fit)
        if v.rotate_logos is not None:
            layout = dataclasses.replace(layout, rotate_logos=v.rotate_logos)

        cover_path    = ASSETS / "cover.webp"
        out_path      = output_dir / f"{v.id}.{v.fmt}"

        cover = Image.open(cover_path).convert("RGBA")

        top_logo    = (ASSETS / "logo_top.png")    if v.with_logos else None
        bottom_logo = (ASSETS / "logo_bottom.png") if v.with_logos else None
        game_logo   = (ASSETS / "marquee.webp")    if v.with_logos else None

        strip = build_spine(
            cover        = cover,
            geom         = geom,
            layout       = layout,
            blur_radius  = v.blur_radius,
            darken_alpha = v.darken_alpha,
            game_logo    = game_logo,
            top_logo     = top_logo,
            bottom_logo  = bottom_logo,
        )

        # OOM/Disk I/O Hardening: Passes Image.Image objects directly to _composite
        result = _composite(
            template_path = profile.template_path,
            cover_img     = cover,
            spine_img     = strip,
            geom          = geom,
            rgb_matrix    = v.rgb_matrix,
        )

        if v.fmt == "webp":
            result.save(str(out_path), "WEBP", quality=92, method=4)
        else:
            result.save(str(out_path), "PNG", optimize=False)

        elapsed   = time.perf_counter() - t0
        file_size = out_path.stat().st_size
        return VariantResult(v, ok=True, elapsed=elapsed, file_size=file_size)

    except Exception as exc:
        import traceback
        elapsed = time.perf_counter() - t0
        return VariantResult(v, ok=False, elapsed=elapsed, error=traceback.format_exc())


# ---------------------------------------------------------------------------
# HTML report  — v1 aesthetic
# Built via string concatenation to avoid f-string / JS brace conflicts.
# ---------------------------------------------------------------------------

def _badge(label: str, is_rgb: bool = False) -> str:
    cls = 'badge badge-rgb' if is_rgb else 'badge'
    return '<span class="' + cls + '">' + label + '</span>'


def _build_badges(v: Variant) -> str:
    parts = [
        _badge(v.profile_name),
        _badge("blur " + str(v.blur_radius)),
        _badge("drk " + str(v.darken_alpha)),
        _badge("src " + (v.spine_source or "left")),
        _badge("fit " + (v.cover_fit or "stretch")),
        _badge("rot " + ("\u2713" if (v.rotate_logos is not False) else "\u2717")),
        _badge("fmt " + v.fmt),
    ]
    if v.rgb_matrix:
        # Extract diagonal values r,g,b from "r 0 0  0 g 0  0 0 b"
        vals = v.rgb_matrix.split()
        rgb_label = "RGB " + vals[0] + "," + vals[4] + "," + vals[8]
        parts.append(_badge(rgb_label, is_rgb=True))
    return "\n".join(parts)


def _build_card(r: VariantResult) -> str:
    v = r.variant
    status = "status-ok" if r.ok else "status-error"
    lines = []
    lines.append('<div class="card ' + status + '">')
    # image area
    lines.append('<div class="card-img">')
    if r.ok:
        lines.append(
            '<img src="' + r.img + '" alt="' + v.id + '" loading="lazy">'
        )
    else:
        lines.append('<div style="height:180px;display:flex;align-items:center;')
        lines.append('justify-content:center;font-size:2rem">\u26a0</div>')
    lines.append('</div>')
    # body
    lines.append('<div class="card-body">')
    lines.append('<div class="card-title">' + v.title + '</div>')
    lines.append('<div class="card-desc">' + v.description + '</div>')
    lines.append('<div class="badges">')
    lines.append(_build_badges(v))
    lines.append('</div>')
    meta_str = (
        str(round(r.elapsed, 2)) + "s \u00b7 " + str(round(r.file_size / 1024, 1)) + " KB"
        if r.ok else str(round(r.elapsed, 2)) + "s"
    )
    lines.append('<div class="meta">' + meta_str + '</div>')
    if not r.ok:
        first_line = r.error.splitlines()[0] if r.error else "unknown error"
        lines.append('<div class="err-msg">' + first_line + '</div>')
    lines.append('</div>')  # card-body
    lines.append('</div>')  # card
    return "\n".join(lines)


def _build_report(results: list[VariantResult], output_dir: Path) -> Path:
    # Embed images
    for r in results:
        r.img = ""
        if r.ok:
            v = r.variant
            img_path = output_dir / (v.id + "." + v.fmt)
            if img_path.exists():
                mime = mimetypes.guess_type(str(img_path))[0] or "image/webp"
                b64  = base64.b64encode(img_path.read_bytes()).decode()
                r.img = "data:" + mime + ";base64," + b64

    ok_count  = sum(1 for r in results if r.ok)
    err_count = len(results) - ok_count
    total_s   = round(sum(r.elapsed for r in results), 1)
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ordered groups (preserve MATRIX order)
    seen_groups: list[str] = []
    for r in results:
        if r.variant.group not in seen_groups:
            seen_groups.append(r.variant.group)

    # Build sections
    sections_html = ""
    for g in seen_groups:
        label = GROUP_LABELS.get(g, g.replace("_", " "))
        group_results = [r for r in results if r.variant.group == g]
        cards_html = "\n".join(_build_card(r) for r in group_results)
        sections_html += (
            '\n    <section class="group" id="' + g + '">\n'
            '      <h2>' + label + '</h2>\n'
            '      <div class="grid">\n'
            + cards_html + "\n"
            '      </div>\n'
            '    </section>\n'
        )

    # Navigation links
    nav_links = "".join(
        '<a href="#' + g + '">' + GROUP_LABELS.get(g, g) + '</a>'
        for g in seen_groups
    )

    # Assemble HTML using string concatenation (no f-strings!)
    css = (
        '  :root {\n'
        '    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;\n'
        '    --accent: #4a9eff; --ok: #3ddc84; --err: #ff5252;\n'
        '    --text: #e0e0e0; --muted: #888;\n'
        '    --grid-min: 220px;\n'
        '    --img-min-h: 180px;\n'
        '    --img-max-h: 200px;\n'
        '  }\n'
        '  * { box-sizing: border-box; margin: 0; padding: 0; }\n'
        '  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; overflow-x: hidden; }\n'
        '\n'
        '  header {\n'
        '    background: var(--surface); border-bottom: 1px solid var(--border);\n'
        '    padding: 24px 32px; display: flex; align-items: center; flex-wrap: wrap; gap: 24px;\n'
        '  }\n'
        '  header h1 { font-size: 1.6rem; color: var(--accent); }\n'
        '\n'
        '  .zoom-control {\n'
        '    display: flex; align-items: center; gap: 12px;\n'
        '    background: #0f1117; padding: 8px 16px; border-radius: 20px;\n'
        '    border: 1px solid var(--border);\n'
        '  }\n'
        '  .zoom-control label { font-size: 0.85rem; color: var(--muted); font-weight: 600; }\n'
        '  .zoom-control input[type=range] { cursor: pointer; }\n'
        '  .zoom-control span { color: var(--accent); font-family: monospace; font-size: 0.9rem; min-width: 35px; display: inline-block; }\n'
        '\n'
        '  .summary { display: flex; gap: 20px; margin-left: auto; }\n'
        '  .stat { text-align: center; }\n'
        '  .stat .val { font-size: 1.5rem; font-weight: 700; }\n'
        '  .stat .lbl { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }\n'
        '  .ok-val { color: var(--ok); }\n'
        '  .err-val { color: var(--err); }\n'
        '\n'
        '  nav {\n'
        '    background: var(--surface); border-bottom: 1px solid var(--border);\n'
        '    padding: 12px 32px; display: flex; flex-wrap: wrap; gap: 8px;\n'
        '    position: sticky; top: 0; z-index: 1000;\n'
        '  }\n'
        '  nav a {\n'
        '    color: var(--muted); text-decoration: none; font-size: 0.8rem;\n'
        '    padding: 4px 10px; border: 1px solid var(--border); border-radius: 20px;\n'
        '    transition: all .15s;\n'
        '  }\n'
        '  nav a:hover { color: var(--accent); border-color: var(--accent); }\n'
        '\n'
        '  main { padding: 32px; }\n'
        '  section.group { margin-bottom: 48px; }\n'
        '  section.group h2 {\n'
        '    color: var(--accent); font-size: 1rem; text-transform: uppercase;\n'
        '    letter-spacing: .1em; margin-bottom: 16px;\n'
        '    padding-bottom: 8px; border-bottom: 1px solid var(--border);\n'
        '  }\n'
        '\n'
        '  .grid {\n'
        '    display: grid;\n'
        '    grid-template-columns: repeat(auto-fill, minmax(var(--grid-min), 1fr));\n'
        '    gap: 16px;\n'
        '  }\n'
        '  .card {\n'
        '    background: var(--surface); border: 1px solid var(--border);\n'
        '    border-radius: 10px; transition: transform .15s, border-color .15s;\n'
        '  }\n'
        '  .card:hover { z-index: 50; position: relative; border-color: var(--accent); }\n'
        '  .card.status-error { border-color: var(--err); }\n'
        '\n'
        '  .card-img {\n'
        '    background: #08090f;\n'
        '    display: flex; align-items: center; justify-content: center;\n'
        '    padding: 8px; min-height: var(--img-min-h);\n'
        '    border-top-left-radius: 9px; border-top-right-radius: 9px;\n'
        '  }\n'
        '  .card-img img {\n'
        '    max-width: 100%; max-height: var(--img-max-h); object-fit: contain;\n'
        '    transition: transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94);\n'
        '    transform-origin: center center;\n'
        '  }\n'
        '  .card-img:hover img {\n'
        '    transform: scale(2.0);\n'
        '    z-index: 100; position: relative;\n'
        '    box-shadow: 0 15px 35px rgba(0,0,0,0.9);\n'
        '    border-radius: 8px;\n'
        '    background: #08090f;\n'
        '  }\n'
        '\n'
        '  .card-body { padding: 12px; }\n'
        '  .card-title { font-weight: 600; font-size: 0.9rem; margin-bottom: 4px; }\n'
        '  .card-desc { font-size: 0.78rem; color: var(--muted); margin-bottom: 8px; line-height: 1.4; }\n'
        '  .badges { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }\n'
        '  .badge { font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; background: #252836; color: #aaa; font-family: monospace; }\n'
        '  .badge-rgb { background: #1a2a1a; color: #6fdb6f; }\n'
        '  .meta { font-size: 0.72rem; color: var(--muted); }\n'
        '  .err-msg { font-size: 0.7rem; color: var(--err); margin-top: 6px; font-family: monospace; word-break: break-all; }\n'
        '  footer { text-align: center; padding: 24px; color: var(--muted); font-size: 0.8rem; border-top: 1px solid var(--border); }\n'
    )

    js = (
        '  const slider = document.getElementById("zoomSlider");\n'
        '  const valDisplay = document.getElementById("zoomValue");\n'
        '  const root = document.documentElement;\n'
        '  const baseGridMin = 220;\n'
        '  const baseImgMinH = 180;\n'
        '  const baseImgMaxH = 200;\n'
        '  slider.addEventListener("input", function() {\n'
        '    const factor = parseFloat(this.value);\n'
        '    valDisplay.textContent = factor.toFixed(1) + "x";\n'
        '    root.style.setProperty("--grid-min", (baseGridMin * factor) + "px");\n'
        '    root.style.setProperty("--img-min-h", (baseImgMinH * factor) + "px");\n'
        '    root.style.setProperty("--img-max-h", (baseImgMaxH * factor) + "px");\n'
        '  });\n'
    )

    html = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>box3d \u2014 Visual Test Report</title>\n'
        '<style>\n'
        + css +
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '\n'
        '<header>\n'
        '  <h1>box3d \u00b7 Visual Test Report</h1>\n'
        '\n'
        '  <div class="zoom-control">\n'
        '    <label for="zoomSlider">Tamanho da Grade:</label>\n'
        '    <input type="range" id="zoomSlider" min="0.5" max="4.0" step="0.1" value="1.0">\n'
        '    <span id="zoomValue">1.0x</span>\n'
        '  </div>\n'
        '\n'
        '  <div class="summary">\n'
        '    <div class="stat"><div class="val">' + str(len(results)) + '</div><div class="lbl">Total</div></div>\n'
        '    <div class="stat"><div class="val ok-val">' + str(ok_count) + '</div><div class="lbl">OK</div></div>\n'
        '    <div class="stat"><div class="val err-val">' + str(err_count) + '</div><div class="lbl">Erros</div></div>\n'
        '    <div class="stat"><div class="val">' + str(total_s) + 's</div><div class="lbl">Tempo</div></div>\n'
        '  </div>\n'
        '</header>\n'
        '\n'
        '<nav>\n'
        + nav_links + '\n'
        '</nav>\n'
        '\n'
        '<main>\n'
        + sections_html +
        '</main>\n'
        '\n'
        '<footer>\n'
        '  Gerado em ' + now_str + ' \u00b7 box3d visual tests \u00b7\n'
        '  ' + str(ok_count) + '/' + str(len(results)) + ' variantes OK\n'
        '</footer>\n'
        '\n'
        '<script>\n'
        + js +
        '</script>\n'
        '</body>\n'
        '</html>\n'
    )

    report = output_dir / "report.html"
    report.write_text(html, encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="box3d v2 visual integration tests")
    parser.add_argument("--out",     default=str(ROOT / "tests" / "visual_output"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--open",    action="store_true",
                        help="Open report in browser after rendering")
    parser.add_argument("--groups",  nargs="+", default=None,
                        help="Render only specific groups, e.g. --groups 1_profiles 4_rgb")
    args = parser.parse_args()

    # Asset check
    for asset in ["cover.webp", "logo_top.png", "logo_bottom.png", "marquee.webp"]:
        if not (ASSETS / asset).exists():
            print(f"  \u2718  Missing test asset: tests/assets/{asset}")
            sys.exit(1)

    # Profile check
    registry = ProfileRegistry(ROOT / "profiles").load()
    for name in ["mvs", "arcade", "dvd"]:
        if name not in registry:
            print(f"  \u2718  Profile not found: {name}")
            sys.exit(1)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    variants = [v for v in MATRIX if args.groups is None or v.group in args.groups]
    total    = len(variants)

    print(f"\nbox3d v2 \u2014 Visual Tests")
    print("=" * 50)
    print(f"  Variants : {total}")
    print(f"  Workers  : {args.workers}")
    print(f"  Profiles : {registry.names()}")
    print(f"  Output   : {output_dir}")
    print("=" * 50)

    results: list[VariantResult] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_render, v, output_dir, registry): v for v in variants}
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            if r.ok:
                print(f"  \u2714  {r.variant.id:<42} {r.elapsed:.2f}s  {r.file_size/1024:.1f} KB")
            else:
                first_line = r.error.splitlines()[0] if r.error else "unknown error"
                print(f"  \u2718  {r.variant.id:<42} {first_line}")

    ok_count  = sum(1 for r in results if r.ok)
    err_count = total - ok_count
    elapsed   = sum(r.elapsed for r in results)

    print()
    print("-" * 50)
    print(f"  OK     : {ok_count}")
    print(f"  Errors : {err_count}")
    print(f"  Time   : {elapsed:.2f}s")

    # Sort results back to MATRIX order before building report
    order = {v.id: i for i, v in enumerate(MATRIX)}
    results.sort(key=lambda r: order.get(r.variant.id, 999))

    report = _build_report(results, output_dir)
    print(f"  Report : {report}")
    print("-" * 50)
    print()

    if args.open and report.exists():
        webbrowser.open(report.as_uri())

    sys.exit(0 if err_count == 0 else 1)


if __name__ == "__main__":
    main()