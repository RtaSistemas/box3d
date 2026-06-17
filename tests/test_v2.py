"""
tests/test_v2.py — Test suite for box3d v2 architecture
=========================================================
Covers: registry loading, profile parsing, geometry models,
rendering engine helpers, and the full render pipeline.

Run::

    pytest tests/test_v2.py -v
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.models    import LogoSlot, ProfileGeometry, Quad, RenderOptions, SpineLayout
from core.registry  import ProfileRegistry, ProfileError, _load_profile
from engine.blending    import (
    alpha_weighted_screen, apply_color_matrix, build_silhouette_mask,
    dst_in, linear_alpha_composite,
)
from engine.perspective import resize_for_fit, solve_coefficients, warp
from engine.spine_builder import build_spine

ASSETS   = ROOT / "tests" / "assets"
PROFILES = ROOT / "profiles"


# ===========================================================================
# core/models
# ===========================================================================

class TestModels:

    def test_quad_as_list(self):
        q = Quad(tl=(0,0), tr=(100,0), br=(100,200), bl=(0,200))
        lst = q.as_list()
        assert lst[0] == (0, 0)
        assert lst[2] == (100, 200)

    def test_render_options_defaults(self):
        opts = RenderOptions()
        assert opts.blur_radius  == 20
        assert opts.darken_alpha == 180
        assert opts.output_format == "webp"
        assert opts.workers == 4
        assert opts.no_rotate is False

    def test_render_options_invalid_opacity_raises(self):
        """template_opacity outside [0.0, 1.0] must raise ValueError."""
        with pytest.raises(ValueError, match="template_opacity"):
            RenderOptions(template_opacity=2.0)
        with pytest.raises(ValueError, match="template_opacity"):
            RenderOptions(template_opacity=-0.1)

    def test_render_options_invalid_kernel_raises(self):
        """warp_kernel not in the valid set must raise ValueError."""
        with pytest.raises(ValueError, match="warp_kernel"):
            RenderOptions(warp_kernel="invalid")
        with pytest.raises(ValueError, match="warp_kernel"):
            RenderOptions(warp_kernel="")

    def test_render_options_valid_kernels_accepted(self):
        """All valid warp_kernel values must be accepted without raising."""
        for kernel in ("lbb", "nohalo", "bicubic", "bilinear"):
            opts = RenderOptions(warp_kernel=kernel)
            assert opts.warp_kernel == kernel

    def test_render_options_opacity_boundary_values_accepted(self):
        """template_opacity at exactly 0.0 and 1.0 must be accepted."""
        assert RenderOptions(template_opacity=0.0).template_opacity == 0.0
        assert RenderOptions(template_opacity=1.0).template_opacity == 1.0

    def test_spine_layout_logo_slots(self):
        layout = SpineLayout(
            game   = LogoSlot(max_w=80,  max_h=320, center_y=453, rotate=-90),
            top    = LogoSlot(max_w=80,  max_h=120, center_y=150),
            bottom = LogoSlot(max_w=80,  max_h=80,  center_y=780),
        )
        assert layout.game.max_h == 320
        assert layout.game.rotate == -90
        assert layout.top.rotate  == 0     # default
        assert layout.logo_alpha  == 0.85


# ===========================================================================
# core/registry
# ===========================================================================

class TestRegistry:

    def test_load_all_builtin_profiles(self):
        reg = ProfileRegistry(PROFILES).load()
        assert set(reg.names()) == {"mvs", "arcade", "dvd"}

    def test_profile_count(self):
        reg = ProfileRegistry(PROFILES).load()
        assert len(reg) == 3

    def test_get_mvs_geometry(self):
        reg = ProfileRegistry(PROFILES).load()
        p   = reg.get("mvs")
        assert p.geometry.template_w == 703
        assert p.geometry.template_h == 1000
        assert p.geometry.spine_w    == 100

    def test_get_arcade_geometry(self):
        reg = ProfileRegistry(PROFILES).load()
        p   = reg.get("arcade")
        assert p.geometry.template_w == 665
        assert p.geometry.spine_w    == 100
        assert p.geometry.cover_w    == 471

    def test_get_dvd_geometry(self):
        reg = ProfileRegistry(PROFILES).load()
        p   = reg.get("dvd")
        assert p.geometry.spine_w == 72

    def test_get_unknown_raises(self):
        reg = ProfileRegistry(PROFILES).load()
        with pytest.raises(KeyError):
            reg.get("nonexistent_profile")

    def test_template_exists_for_all_profiles(self):
        reg = ProfileRegistry(PROFILES).load()
        for profile in reg.all():
            assert profile.template_path.exists(), \
                f"template.png missing for profile {profile.name!r}"

    def test_invalid_profiles_dir_raises(self):
        with pytest.raises(ProfileError):
            ProfileRegistry("/nonexistent/path").load()

    def test_missing_json_skipped(self, tmp_path):
        """Directory without profile.json is silently skipped."""
        (tmp_path / "incomplete").mkdir()
        (tmp_path / "incomplete" / "template.png").touch()
        reg = ProfileRegistry(tmp_path).load()
        assert len(reg) == 0

    def test_custom_profile_loaded(self, tmp_path):
        """A custom profile.json is loaded correctly."""
        prof_dir = tmp_path / "custom"
        prof_dir.mkdir()
        (prof_dir / "template.png").touch()
        data = {
            "name": "custom",
            "template_size": {"width": 500, "height": 700},
            "spine": {"width": 80, "height": 600},
            "cover": {"width": 380, "height": 600},
            "spine_quad": {"tl":[0,0],"tr":[80,0],"br":[80,600],"bl":[0,600]},
            "cover_quad": {"tl":[80,0],"tr":[460,0],"br":[460,600],"bl":[80,600]},
        }
        (prof_dir / "profile.json").write_text(json.dumps(data))
        reg = ProfileRegistry(tmp_path).load()
        assert "custom" in reg
        assert reg.get("custom").geometry.template_w == 500

    def test_contains_operator(self):
        reg = ProfileRegistry(PROFILES).load()
        assert "mvs"       in reg
        assert "unknown"   not in reg

    @pytest.mark.parametrize("name", ["mvs","arcade","dvd"])
    def test_spine_layout_loaded(self, name):
        reg = ProfileRegistry(PROFILES).load()
        layout = reg.get(name).layout
        assert layout.game.max_w > 0
        assert layout.top.max_h  > 0
        assert 0.0 < layout.logo_alpha <= 1.0
        assert layout.game.rotate == -90  # per-slot rotation from JSON


# ===========================================================================
# engine/perspective
# ===========================================================================

class TestPerspective:

    def test_solve_coefficients_returns_8(self):
        src = [(0,0),(100,0),(100,200),(0,200)]
        dst = [(0,10),(100,5),(100,195),(0,190)]
        assert len(solve_coefficients(src, dst)) == 8

    def test_warp_output_size(self):
        img = Image.new("RGBA", (100, 200), (255,0,0,255))
        dst = [(0,0),(300,0),(300,500),(0,500)]
        out = warp(img, 400, 600, dst)
        assert out.size == (400, 600)

    def test_warp_output_is_rgba(self):
        img = Image.new("RGBA", (50,100), (0,255,0,200))
        out = warp(img, 200, 300, [(0,0),(200,0),(200,300),(0,300)])
        assert out.mode == "RGBA"

    @pytest.mark.parametrize("mode", ["stretch","fit","crop"])
    def test_resize_for_fit_modes(self, mode):
        img = Image.new("RGBA", (400, 200), (100,100,100,255))
        out = resize_for_fit(img, 200, 200, mode)
        assert out.size == (200, 200)
        assert out.mode == "RGBA"

    def test_resize_fit_letterbox_transparent(self):
        img = Image.new("RGBA", (400, 100), (200,0,0,255))  # wide
        out = resize_for_fit(img, 200, 200, "fit")
        # Top-left corner must be transparent (letterbox)
        assert out.getpixel((0,0))[3] == 0

    @pytest.mark.parametrize("name", ["mvs","arcade","dvd"])
    def test_warp_all_profiles_no_crash(self, name):
        reg  = ProfileRegistry(PROFILES).load()
        p    = reg.get(name)
        g    = p.geometry
        img  = Image.new("RGBA", (g.cover_w, g.cover_h), (100,150,200,255))
        out  = warp(img, g.template_w, g.template_h, g.cover_quad.as_list())
        assert out.size == (g.template_w, g.template_h)


# ===========================================================================
# engine/blending
# ===========================================================================

class TestBlending:

    def test_alpha_weighted_screen_black_src_no_change(self):
        """Screen with opaque black source must leave dest unchanged (±1 rounding)."""
        dst = Image.new("RGBA", (10,10), (80,120,200,255))
        src = Image.new("RGBA", (10,10), (0,0,0,255))
        out = alpha_weighted_screen(dst, src)
        r, g, b, _ = out.getpixel((5,5))
        assert abs(r-80)<=1 and abs(g-120)<=1 and abs(b-200)<=1

    def test_alpha_weighted_screen_low_alpha_subtle(self):
        """Near-white source with alpha≈12 must not wash out a dark cover."""
        dst = Image.new("RGBA", (10,10), (80,80,80,255))
        src = Image.new("RGBA", (10,10), (246,246,246,12))
        out = alpha_weighted_screen(dst, src)
        r, _, _, _ = out.getpixel((5,5))
        assert r < 120, "cover was washed out"

    def test_alpha_weighted_screen_alpha_union(self):
        """Alpha result is union(dst, src) — ADR-004.

        The pipeline requires this so template pixels outside the
        spine/cover warp area survive the subsequent dst_in clip.
        A src with higher alpha MUST elevate the result alpha.
        """
        # src alpha (255) > dst alpha (128) → result must be 255
        dst = Image.new("RGBA", (10,10), (100,100,100,128))
        src = Image.new("RGBA", (10,10), (200,200,200,255))
        out = alpha_weighted_screen(dst, src)
        assert out.getpixel((5,5))[3] == 255, "alpha union failed: src alpha must win"

        # src alpha (64) < dst alpha (200) → result must stay 200
        dst2 = Image.new("RGBA", (10,10), (100,100,100,200))
        src2 = Image.new("RGBA", (10,10), (200,200,200,64))
        out2 = alpha_weighted_screen(dst2, src2)
        assert out2.getpixel((5,5))[3] == 200, "alpha union failed: dst alpha must win"

    def test_dst_in_white_mask_unchanged(self):
        dst  = Image.new("RGBA", (10,10), (255,0,0,200))
        mask = Image.new("L",    (10,10), 255)
        assert dst_in(dst, mask).getpixel((5,5))[3] == 200

    def test_dst_in_black_mask_transparent(self):
        dst  = Image.new("RGBA", (10,10), (255,0,0,200))
        mask = Image.new("L",    (10,10), 0)
        assert dst_in(dst, mask).getpixel((5,5))[3] == 0

    def test_dst_in_preserves_rgb(self):
        dst  = Image.new("RGBA", (10,10), (42,84,168,255))
        mask = Image.new("L",    (10,10), 128)
        r, g, b, _ = dst_in(dst, mask).getpixel((5,5))
        assert (r, g, b) == (42, 84, 168)

    def test_build_silhouette_union(self):
        import numpy as np
        a = Image.new("RGBA", (10,10), (255,0,0,0))
        b = Image.new("RGBA", (10,10), (0,0,255,200))
        mask = build_silhouette_mask(a, b)
        arr  = np.array(mask)
        assert arr.max() == 200

    def test_apply_color_matrix_scales_channel(self):
        img = Image.new("RGBA", (10,10), (100,100,100,255))
        out = apply_color_matrix(img, "1.5 0 0  0 1.0 0  0 0 0.8")
        r, g, b, _ = out.getpixel((5,5))
        assert r == 150 and g == 100 and b == 80

    def test_apply_color_matrix_clips_at_255(self):
        img = Image.new("RGBA", (10,10), (200,100,100,255))
        out = apply_color_matrix(img, "2.0 0 0  0 1.0 0  0 0 1.0")
        assert out.getpixel((5,5))[0] == 255

    def test_alpha_weighted_screen_uses_linear_space(self):
        """
        Screen blend of two identical medium-gray images in linear space must
        produce a result that is LESS bright than the sRGB-space computation.

        In sRGB space:  screen(128, 128) = 1−(1−128/255)² ≈ 192
        In linear space: the same inputs linearise to ≈ 0.216, producing a
        linear screen result that converts back to sRGB ≈ 169.

        If this test fails (result ≥ sRGB-space value) the blend is operating
        in sRGB rather than linear light.
        """
        dst = Image.new("RGBA", (10, 10), (128, 128, 128, 255))
        src = Image.new("RGBA", (10, 10), (128, 128, 128, 255))
        out = alpha_weighted_screen(dst, src)
        r, _, _, _ = out.getpixel((5, 5))
        # Screen must always lighten relative to either input
        assert r > 128, f"Screen blend must lighten the result; got {r}"
        # sRGB-space screen of (128, 128) ≈ 192; linear result ≈ 169
        srgb_space_result = int(255 * (1 - (1 - 128 / 255) ** 2))  # ≈ 192
        assert r < srgb_space_result, (
            f"Result {r} is ≥ sRGB-space screen result {srgb_space_result}; "
            "blend may not be operating in linear light."
        )


class TestLinearAlphaComposite:
    """
    Verifies linear_alpha_composite correctness across degenerate and
    mixed-alpha cases.
    """

    def test_transparent_dst_returns_src(self):
        """Compositing over a fully-transparent canvas gives the source."""
        src = Image.new("RGBA", (10, 10), (200, 100, 50, 200))
        dst = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        out = linear_alpha_composite(dst, src)
        r, g, b, a = out.getpixel((5, 5))
        assert a == 200
        assert abs(r - 200) <= 2 and abs(g - 100) <= 2 and abs(b - 50) <= 2

    def test_opaque_src_replaces_dst(self):
        """Fully-opaque src completely replaces dst regardless of dst content."""
        src = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        dst = Image.new("RGBA", (10, 10), (0, 255, 0, 255))
        out = linear_alpha_composite(dst, src)
        r, g, b, a = out.getpixel((5, 5))
        assert r == 255 and g == 0 and b == 0 and a == 255

    def test_transparent_src_leaves_dst_unchanged(self):
        """Fully-transparent src must not alter dst at all."""
        dst = Image.new("RGBA", (10, 10), (100, 150, 200, 180))
        src = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        out = linear_alpha_composite(dst, src)
        r, g, b, a = out.getpixel((5, 5))
        assert abs(r - 100) <= 1 and abs(g - 150) <= 1 and abs(b - 200) <= 1
        assert a == 180

    def test_output_mode_is_rgba(self):
        """Output is always RGBA."""
        dst = Image.new("RGBA", (5, 5), (0, 0, 0, 0))
        src = Image.new("RGBA", (5, 5), (128, 128, 128, 128))
        assert linear_alpha_composite(dst, src).mode == "RGBA"

    def test_output_size_matches_dst(self):
        """Output size matches dst size."""
        dst = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
        src = Image.new("RGBA", (32, 48), (64, 128, 192, 200))
        out = linear_alpha_composite(dst, src)
        assert out.size == (32, 48)

    def test_half_alpha_blend_is_brighter_than_srgb(self):
        """
        Compositing a bright half-alpha src over a dark dst in linear space
        produces a brighter mid-tone than the sRGB-space blend would.

        This is the canonical linear-blending quality test:
          dst_lin = srgb_to_linear(30)  ≈ 0.012  (very dark)
          src_lin = srgb_to_linear(230) ≈ 0.771  (bright)
          blend_lin = 0.012·(1−0.5) + 0.771·0.5 ≈ 0.392
          sRGB(0.392) ≈ 0.666 × 255 ≈ 170

          sRGB blend (incorrect):
          blend = (30/255)·0.5 + (230/255)·0.5 = 130/255 ≈ 130
        """
        dst = Image.new("RGBA", (10, 10), (30, 30, 30, 255))
        src = Image.new("RGBA", (10, 10), (230, 230, 230, 128))   # half-alpha
        out = linear_alpha_composite(dst, src)
        r, _, _, _ = out.getpixel((5, 5))
        srgb_blend = int(30 * 0.5 + 230 * 0.5)  # ≈ 130 (incorrect sRGB blend)
        assert r > srgb_blend, (
            f"Linear blend ({r}) should be brighter than sRGB blend ({srgb_blend})"
        )


# ===========================================================================
# engine/spine_builder
# ===========================================================================

class TestSpineBuilder:

    def _geom(self, name="mvs"):
        return ProfileRegistry(PROFILES).load().get(name).geometry

    def _layout(self, name="mvs"):
        return ProfileRegistry(PROFILES).load().get(name).layout

    def test_output_is_rgba(self):
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        strip = build_spine(cover, self._geom(), self._layout(),
                            blur_radius=10, darken_alpha=100,
                            game_logo=None, top_logo=None, bottom_logo=None)
        assert strip.mode == "RGBA"

    @pytest.mark.parametrize("name", ["mvs","arcade","dvd"])
    def test_output_dimensions(self, name):
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        geom  = self._geom(name)
        strip = build_spine(cover, geom, self._layout(name),
                            blur_radius=10, darken_alpha=100,
                            game_logo=None, top_logo=None, bottom_logo=None)
        assert strip.size == (geom.spine_w, geom.spine_h)

    def test_darken_zero_brighter(self):
        import numpy as np
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        dark  = build_spine(cover, self._geom(), self._layout(),
                            blur_radius=10, darken_alpha=220,
                            game_logo=None, top_logo=None, bottom_logo=None)
        light = build_spine(cover, self._geom(), self._layout(),
                            blur_radius=10, darken_alpha=0,
                            game_logo=None, top_logo=None, bottom_logo=None)
        assert np.array(light).mean() > np.array(dark).mean()

    def test_with_logos(self):
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        strip = build_spine(cover, self._geom(), self._layout(),
                            blur_radius=10, darken_alpha=100,
                            game_logo    = Image.open(ASSETS / "marquee.webp").convert("RGBA"),
                            top_logo     = Image.open(ASSETS / "logo_top.png").convert("RGBA"),
                            bottom_logo  = Image.open(ASSETS / "logo_bottom.png").convert("RGBA"))
        assert strip.mode == "RGBA"

    def test_missing_logo_skipped(self):
        """Passing None for a logo slot is silently accepted."""
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        strip = build_spine(cover, self._geom(), self._layout(),
                            blur_radius=5, darken_alpha=0,
                            game_logo   = None,
                            top_logo    = None,
                            bottom_logo = None)
        assert strip.mode == "RGBA"


# ===========================================================================
# Full pipeline (end-to-end)
# ===========================================================================

class TestPipeline:

    def test_render_mvs_produces_output(self, tmp_path):
        (tmp_path / "covers").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / "temp").mkdir()
        import shutil
        shutil.copy(ASSETS / "cover.webp", tmp_path / "covers" / "cover.webp")

        reg     = ProfileRegistry(PROFILES).load()
        profile = reg.get("mvs")
        opts    = RenderOptions(blur_radius=20, darken_alpha=180, workers=1)

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile      = profile,
            covers_dir   = tmp_path / "covers",
            output_dir   = tmp_path / "output",
            temp_dir     = tmp_path / "temp",
            options      = opts,
            logo_paths   = {"top": None, "bottom": None},
            marquees_dir = tmp_path / "nonexistent",
        ).run()

        assert stats.succeeded    == 1
        assert stats.failed == 0
        out = tmp_path / "output" / "cover.webp"
        assert out.exists() and out.stat().st_size > 0

    def test_render_output_has_cover_content(self, tmp_path):
        """Cover face must contain image data (not blank/white)."""
        import numpy as np, shutil
        (tmp_path / "covers").mkdir(); (tmp_path / "temp").mkdir()
        shutil.copy(ASSETS / "cover.webp", tmp_path / "covers" / "cover.webp")
        reg     = ProfileRegistry(PROFILES).load()
        profile = reg.get("mvs")
        opts    = RenderOptions(workers=1, dry_run=False)
        from core.pipeline import RenderPipeline
        RenderPipeline(
            profile=profile, covers_dir=tmp_path/"covers",
            output_dir=tmp_path, temp_dir=tmp_path/"temp",
            options=opts, logo_paths={}, marquees_dir=tmp_path/"m",
        ).run()
        result = Image.open(tmp_path / "cover.webp").convert("RGBA")
        arr    = np.array(result)
        cy, cx = result.height//2, result.width//2
        face   = arr[cy-80:cy+80, cx-40:cx+80, :3]
        assert face.std() > 5, "cover face is blank"

    def test_dry_run_no_output(self, tmp_path):
        import shutil
        (tmp_path / "covers").mkdir(); (tmp_path / "temp").mkdir()
        shutil.copy(ASSETS / "cover.webp", tmp_path / "covers" / "cover.webp")
        reg  = ProfileRegistry(PROFILES).load()
        opts = RenderOptions(workers=1, dry_run=True)
        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=reg.get("mvs"), covers_dir=tmp_path/"covers",
            output_dir=tmp_path/"output", temp_dir=tmp_path/"temp",
            options=opts, logo_paths={}, marquees_dir=tmp_path/"m",
        ).run()
        assert stats.dry == 1
        out_dir = tmp_path / "output"
        assert not out_dir.exists() or not any(out_dir.iterdir())

    @pytest.mark.parametrize("name", ["mvs","arcade","dvd"])
    def test_render_all_profiles(self, tmp_path, name):
        import shutil
        (tmp_path / "covers").mkdir(); (tmp_path / "temp").mkdir()
        shutil.copy(ASSETS / "cover.webp", tmp_path / "covers" / "cover.webp")
        reg  = ProfileRegistry(PROFILES).load()
        opts = RenderOptions(workers=1)
        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=reg.get(name), covers_dir=tmp_path/"covers",
            output_dir=tmp_path/"out", temp_dir=tmp_path/"temp",
            options=opts, logo_paths={}, marquees_dir=tmp_path/"m",
        ).run()
        assert stats.succeeded == 1
    def test_game_logo_fallback_uses_profile_asset(self, tmp_path):
        """When marquees_dir has no match, logo_game.* in profile assets/ is used."""
        import shutil, dataclasses
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        # Create a patched profile root with logo_game.webp in assets/
        assets_dir = tmp_path / "assets"; assets_dir.mkdir()
        shutil.copy(ASSETS / "marquee.webp", assets_dir / "logo_game.webp")
        # Also provide template.png at the patched root
        reg     = ProfileRegistry(PROFILES).load()
        profile = reg.get("mvs")
        shutil.copy(profile.root / "template.png", tmp_path / "template.png")
        patched = dataclasses.replace(profile, root=tmp_path)

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=patched, covers_dir=covers,
            output_dir=tmp_path / "out", temp_dir=tmp_path / "temp",
            options=RenderOptions(workers=1), logo_paths={},
            marquees_dir=tmp_path / "empty_marquees",
        ).run()
        assert stats.succeeded == 1 and stats.failed == 0

    def test_game_logo_dynamic_preferred_over_fallback(self, tmp_path):
        """Dynamic marquee in marquees_dir takes priority over logo_game in assets/."""
        import shutil
        covers   = tmp_path / "covers";   covers.mkdir()
        marquees = tmp_path / "marquees"; marquees.mkdir()
        shutil.copy(ASSETS / "cover.webp",   covers   / "cover.webp")
        shutil.copy(ASSETS / "marquee.webp", marquees / "cover.webp")  # stem matches

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out", temp_dir=tmp_path / "temp",
            options=RenderOptions(workers=1), logo_paths={},
            marquees_dir=marquees,
        ).run()
        assert stats.succeeded == 1

    def test_game_logo_none_when_both_missing(self, tmp_path):
        """Neither marquee nor logo_game → render succeeds with game_logo=None."""
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out", temp_dir=tmp_path / "temp",
            options=RenderOptions(workers=1), logo_paths={},
            marquees_dir=tmp_path / "no_marquees",
        ).run()
        # profiles/mvs/assets/ has no logo_game.* — runs fine with None
        assert stats.succeeded == 1

    def test_no_logos_suppresses_game_logo(self, tmp_path):
        """no_logos=True must prevent _load_game_logo() from being called.
        Regression test for BUG-02: with_logos field was dead; no_logos had no effect.
        """
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1),
            logo_paths={},
            marquees_dir=tmp_path / "marquees",
            no_logos=True,
        )
        with patch.object(pipeline, "_load_game_logo") as mock_load:
            stats = pipeline.run()
        assert stats.succeeded == 1
        mock_load.assert_not_called()  # no_logos=True must bypass game logo lookup

    def test_no_logos_flag_absent_loads_game_logo(self, tmp_path):
        """no_logos=False (default) must still attempt game logo resolution."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1),
            logo_paths={},
            marquees_dir=tmp_path / "marquees",
            no_logos=False,
        )
        with patch.object(pipeline, "_load_game_logo", return_value=None) as mock_load:
            stats = pipeline.run()
        assert stats.succeeded == 1
        mock_load.assert_called_once()  # must be called when no_logos=False


# ===========================================================================
# TASK-ENGINE-IO-PURGE-01 — engine/compositor.py
# ===========================================================================

class TestCompositor:
    """Validate all changes introduced by TASK-ENGINE-IO-PURGE-01."""

    # ------------------------------------------------------------------
    # Public API: compose_cover()
    # ------------------------------------------------------------------

    def test_compose_cover_importable(self):
        from engine.compositor import compose_cover
        assert callable(compose_cover)

    def test_render_cover_removed(self):
        """render_cover() must not exist in engine.compositor (HIGH-1)."""
        import engine.compositor as ec
        assert not hasattr(ec, "render_cover"), (
            "render_cover must be removed from engine.compositor — HIGH-1"
        )

    def test_compose_cover_returns_rgba_image(self):
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img=cover, profile=profile, options=RenderOptions(),
            template_img=template,
        )
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    def test_compose_cover_output_size_matches_template(self):
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img=cover, profile=profile, options=RenderOptions(),
            template_img=template,
        )
        assert result.size == template.size

    def test_compose_cover_with_all_logos(self):
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img    = cover,
            profile      = profile,
            options      = RenderOptions(),
            game_logo    = Image.open(ASSETS / "marquee.webp").convert("RGBA"),
            top_logo     = Image.open(ASSETS / "logo_top.png").convert("RGBA"),
            bottom_logo  = Image.open(ASSETS / "logo_bottom.png").convert("RGBA"),
            template_img = template,
        )
        assert result.mode == "RGBA"
        assert result.size == template.size

    def test_compose_cover_game_logo_none_accepted(self):
        """All logo params are optional — None must not crash."""
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img=cover, profile=profile, options=RenderOptions(),
            game_logo=None, top_logo=None, bottom_logo=None,
            template_img=template,
        )
        assert result.mode == "RGBA"

    def test_compose_cover_none_template_raises(self):
        """compose_cover with template_img=None must raise AssertionError."""
        from engine.compositor import compose_cover
        profile = ProfileRegistry(PROFILES).load().get("mvs")
        cover   = Image.open(ASSETS / "cover.webp").convert("RGBA")
        with pytest.raises(AssertionError):
            compose_cover(
                cover_img=cover, profile=profile, options=RenderOptions(),
                template_img=None,
            )

    @pytest.mark.parametrize("name", ["mvs", "arcade", "dvd"])
    def test_compose_cover_all_profiles(self, name):
        """compose_cover must succeed for every built-in profile."""
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get(name)
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img=cover, profile=profile, options=RenderOptions(),
            template_img=template,
        )
        assert result.size == (profile.geometry.template_w, profile.geometry.template_h)

    def test_compose_cover_rgb_matrix_changes_output(self):
        """rgb_matrix override must visibly alter pixel values."""
        import numpy as np
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")

        neutral = compose_cover(
            cover_img=cover, profile=profile,
            options=RenderOptions(rgb_matrix=None), template_img=template,
        )
        warm = compose_cover(
            cover_img=cover, profile=profile,
            options=RenderOptions(rgb_matrix="1.4 0 0  0 1.0 0  0 0 0.6"),
            template_img=template,
        )
        assert not (np.array(neutral) == np.array(warm)).all(), (
            "rgb_matrix had no effect on output pixels"
        )

    def test_compose_cover_no_rotate_override(self):
        """no_rotate=True produces valid RGBA output without crash."""
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("arcade")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")
        result   = compose_cover(
            cover_img=cover, profile=profile,
            options=RenderOptions(no_rotate=True), template_img=template,
        )
        assert result.mode == "RGBA"

    # ------------------------------------------------------------------
    # _composite() signature / contract
    # ------------------------------------------------------------------

    def test_composite_template_path_param_removed(self):
        """_composite() must not accept template_path (vestigial arg gone)."""
        import inspect
        from engine.compositor import _composite
        sig = inspect.signature(_composite)
        assert "template_path" not in sig.parameters, (
            "_composite() still has template_path — it was supposed to be removed"
        )

    def test_composite_none_template_raises_assertion(self):
        """_composite() with template_img=None must raise AssertionError."""
        from engine.compositor import _composite
        reg  = ProfileRegistry(PROFILES).load()
        geom = reg.get("mvs").geometry
        w, h = geom.spine_w, geom.spine_h
        with pytest.raises(AssertionError):
            _composite(
                cover_img    = Image.new("RGBA", (w, h), (100, 150, 200, 255)),
                spine_img    = Image.new("RGBA", (w, h), (80,  80,  80,  255)),
                geom         = geom,
                rgb_matrix   = None,
                template_img = None,
            )

    # ------------------------------------------------------------------
    # Zero-I/O contract
    # ------------------------------------------------------------------

    def test_compose_cover_performs_no_disk_read(self):
        """compose_cover must not call Image.open — engine is zero I/O."""
        from unittest.mock import patch
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")

        with patch("PIL.Image.open") as mock_open:
            compose_cover(
                cover_img=cover, profile=profile, options=RenderOptions(),
                template_img=template,
            )
            mock_open.assert_not_called()

    def test_compositor_module_has_no_path_import(self):
        """engine.compositor must not import Path (removed with render_cover)."""
        import ast, inspect, engine.compositor as ec
        src  = inspect.getsource(ec)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "pathlib":
                    names = [a.name for a in node.names]
                    assert "Path" not in names, (
                        "from pathlib import Path found in engine.compositor — dead import"
                    )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "time", (
                        "import time found in engine.compositor — dead import"
                    )

    def test_compositor_module_no_coverresult_import(self):
        """engine.compositor must not import CoverResult (removed with render_cover)."""
        import ast, inspect, engine.compositor as ec
        src  = inspect.getsource(ec)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                src_line = ast.get_source_segment(src, node) or ""
                assert "CoverResult" not in src_line, (
                    "CoverResult still imported in engine.compositor — dead import"
                )

    def test_template_opacity_zero_blanks_template(self):
        """template_opacity=0.0 must render with zero template contribution."""
        import numpy as np
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")

        result_zero = compose_cover(
            cover_img=cover, profile=profile,
            options=RenderOptions(template_opacity=0.0), template_img=template,
        )
        result_full = compose_cover(
            cover_img=cover, profile=profile,
            options=RenderOptions(template_opacity=1.0), template_img=template,
        )
        arr_zero = np.array(result_zero)
        arr_full = np.array(result_full)
        # With opacity=0 template has no effect; outputs must differ from opacity=1
        assert not np.array_equal(arr_zero, arr_full), (
            "template_opacity=0.0 produced the same output as template_opacity=1.0"
        )

    def test_template_opacity_half_is_between_zero_and_full(self):
        """template_opacity=0.5 output must differ from both 0.0 and 1.0."""
        import numpy as np
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")

        r0 = np.array(compose_cover(cover_img=cover, profile=profile,
                                    options=RenderOptions(template_opacity=0.0),
                                    template_img=template))
        r5 = np.array(compose_cover(cover_img=cover, profile=profile,
                                    options=RenderOptions(template_opacity=0.5),
                                    template_img=template))
        r1 = np.array(compose_cover(cover_img=cover, profile=profile,
                                    options=RenderOptions(template_opacity=1.0),
                                    template_img=template))
        assert not np.array_equal(r0, r5), "opacity=0.5 matches opacity=0.0"
        assert not np.array_equal(r5, r1), "opacity=0.5 matches opacity=1.0"

    def test_warp_kernel_propagated_through_options(self):
        """compose_cover must pass warp_kernel from options down to the warp call."""
        from unittest.mock import patch, call
        from engine.compositor import compose_cover
        import engine.compositor as ec
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        cover    = Image.open(ASSETS / "cover.webp").convert("RGBA")
        template = Image.open(profile.template_path).convert("RGBA")

        called_kernels: list[str | None] = []
        original_warp = ec.warp

        def recording_warp(*args, kernel=None, **kwargs):
            called_kernels.append(kernel)
            return original_warp(*args, kernel=kernel, **kwargs)

        with patch.object(ec, "warp", side_effect=recording_warp):
            compose_cover(
                cover_img=cover, profile=profile,
                options=RenderOptions(warp_kernel="nohalo"), template_img=template,
            )

        assert all(k == "nohalo" for k in called_kernels), (
            f"Expected kernel='nohalo' in all warp calls, got: {called_kernels}"
        )


# ===========================================================================
# TASK-ENGINE-IO-PURGE-01 — HIGH-2 template via _safe_open
# ===========================================================================

class TestPipelineEngineIoPurge:

    def test_template_loaded_via_safe_open(self, tmp_path):
        """HIGH-2: template must be loaded through _safe_open, not Image.open."""
        import shutil
        from unittest.mock import patch
        from core.pipeline import RenderPipeline

        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")
        profile = ProfileRegistry(PROFILES).load().get("mvs")

        # Record every path passed to _safe_open
        from core import pipeline as _pipeline_mod
        original = _pipeline_mod._safe_open
        recorded: list[Path] = []

        def recording_safe_open(path: Path):
            recorded.append(path)
            return original(path)

        with patch.object(_pipeline_mod, "_safe_open", side_effect=recording_safe_open):
            stats = RenderPipeline(
                profile=profile, covers_dir=covers,
                output_dir=tmp_path / "out", temp_dir=tmp_path / "temp",
                options=RenderOptions(workers=1), logo_paths={},
                marquees_dir=tmp_path / "m",
            ).run()

        assert any(p == profile.template_path for p in recorded), (
            "template was NOT passed to _safe_open — HIGH-2 not fixed"
        )
        assert stats.succeeded == 1

    def test_safe_open_oom_guard_downscales(self, tmp_path):
        """_safe_open must call thumbnail on the lazy raw object when image exceeds 8192px."""
        from unittest.mock import patch, MagicMock, PropertyMock
        from core.pipeline import _safe_open

        # Write a real tiny file so Image.open succeeds at the file level
        real = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        img_path = tmp_path / "big.png"
        real.save(str(img_path))

        # Mock the lazy `raw` object returned by `with Image.open(...) as raw:`
        # The guard now checks raw.width/height BEFORE calling raw.convert("RGBA").
        mock_raw = MagicMock(spec=Image.Image)
        type(mock_raw).width  = PropertyMock(return_value=10000)
        type(mock_raw).height = PropertyMock(return_value=100)
        mock_raw.convert.return_value = Image.new("RGBA", (4, 4))

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_raw
            _safe_open(img_path)

        mock_raw.thumbnail.assert_called_once_with((8192, 8192), Image.BICUBIC)

    def test_safe_open_no_downscale_when_within_limit(self, tmp_path):
        """_safe_open must NOT call thumbnail for images within 8192px."""
        from unittest.mock import patch, MagicMock, PropertyMock
        from core.pipeline import _safe_open

        real = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        img_path = tmp_path / "normal.png"
        real.save(str(img_path))

        mock_raw = MagicMock(spec=Image.Image)
        type(mock_raw).width  = PropertyMock(return_value=800)
        type(mock_raw).height = PropertyMock(return_value=1000)
        mock_raw.convert.return_value = Image.new("RGBA", (4, 4))

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_raw
            _safe_open(img_path)

        mock_raw.thumbnail.assert_not_called()

    def test_stop_event_cancels_pipeline_cooperatively(self, tmp_path):
        """stop_event set before run() skips pending covers without raising exceptions."""
        import threading
        from core.pipeline import RenderPipeline
        from core.models import RenderOptions
        from core.registry import ProfileRegistry

        covers = tmp_path / "covers"
        covers.mkdir()
        # Create two covers so we have something to process
        for name in ("a.png", "b.png"):
            Image.new("RGBA", (100, 100), (1, 2, 3, 255)).save(str(covers / name))

        out = tmp_path / "out"
        profile = ProfileRegistry(PROFILES).load().get("mvs")

        stop = threading.Event()
        stop.set()   # pre-set: _process_one checks event before starting work

        pipeline = RenderPipeline(
            profile=profile, covers_dir=covers, output_dir=out,
            options=RenderOptions(workers=1), logo_paths={},
        )
        report = pipeline.run(stop_event=stop)

        # With stop pre-set, every cover returns "skip" — none should error
        assert report.failed == 0
        assert report.succeeded == 0

    def test_compositor_module_has_no_image_open_call(self):
        """engine.compositor must contain no Image.open() call (zero I/O contract)."""
        import ast, inspect
        import engine.compositor as ec
        src  = inspect.getsource(ec)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # Detect `Image.open(...)` — Attribute node whose value is Name "Image"
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "open"
                and isinstance(node.value, ast.Name)
                and node.value.id == "Image"
            ):
                pytest.fail(
                    "Image.open() call found in engine.compositor — zero I/O contract violated"
                )

    def test_skip_existing_returns_skip_status(self, tmp_path):
        """_process_one with skip_existing=True must skip pre-existing output."""
        import shutil
        from core.pipeline import RenderPipeline

        covers = tmp_path / "covers"; covers.mkdir()
        out    = tmp_path / "out";    out.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")
        # Pre-create the output so it already exists
        (out / "cover.webp").write_bytes(b"already_rendered")

        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers, output_dir=out, temp_dir=tmp_path / "temp",
            options=RenderOptions(workers=1, skip_existing=True),
            logo_paths={}, marquees_dir=tmp_path / "m",
        ).run()

        assert stats.skipped == 1
        assert stats.succeeded == 0
        # Pre-existing file must not be overwritten
        assert (out / "cover.webp").read_bytes() == b"already_rendered"

    def test_process_one_dry_run_no_output_file(self, tmp_path):
        """_process_one with dry_run=True must not write any file."""
        import shutil
        from core.pipeline import RenderPipeline

        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers, output_dir=tmp_path / "out",
            temp_dir=tmp_path / "temp",
            options=RenderOptions(workers=1, dry_run=True),
            logo_paths={}, marquees_dir=tmp_path / "m",
        ).run()

        assert stats.dry == 1
        out_dir = tmp_path / "out"
        assert not out_dir.exists() or not any(out_dir.iterdir())


# ===========================================================================
# BLOCO 2 — Internal engine asserts
# ===========================================================================

class TestEngineAsserts:
    """Verify that asserts in engine/ fire correctly on invalid inputs."""

    # ------------------------------------------------------------------
    # compose_cover() — public boundary asserts
    # ------------------------------------------------------------------

    def test_compose_cover_rejects_none_cover(self):
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        template = Image.open(profile.template_path).convert("RGBA")
        with pytest.raises(AssertionError, match="cover_img must not be None"):
            from engine.compositor import compose_cover
            compose_cover(
                cover_img=None, profile=profile,
                options=RenderOptions(), template_img=template,
            )

    def test_compose_cover_rejects_non_rgba_cover(self):
        from engine.compositor import compose_cover
        profile  = ProfileRegistry(PROFILES).load().get("mvs")
        template = Image.open(profile.template_path).convert("RGBA")
        rgb_cover = Image.new("RGB", (100, 200), (100, 150, 200))
        with pytest.raises(AssertionError, match="RGBA mode"):
            compose_cover(
                cover_img=rgb_cover, profile=profile,
                options=RenderOptions(), template_img=template,
            )

    def test_compose_cover_rejects_non_rgba_template(self):
        from engine.compositor import compose_cover
        profile = ProfileRegistry(PROFILES).load().get("mvs")
        cover   = Image.open(ASSETS / "cover.webp").convert("RGBA")
        rgb_tpl = Image.new("RGB", (703, 1000), (0, 0, 0))
        with pytest.raises(AssertionError, match="RGBA mode"):
            compose_cover(
                cover_img=cover, profile=profile,
                options=RenderOptions(), template_img=rgb_tpl,
            )

    # ------------------------------------------------------------------
    # build_spine() — geometry and layout asserts
    # ------------------------------------------------------------------

    def _base_geom(self, name="mvs"):
        return ProfileRegistry(PROFILES).load().get(name).geometry

    def _base_layout(self, name="mvs"):
        return ProfileRegistry(PROFILES).load().get(name).layout

    def test_build_spine_rejects_negative_blur(self):
        from engine.spine_builder import build_spine
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        with pytest.raises(AssertionError, match="blur_radius"):
            build_spine(
                cover=cover, geom=self._base_geom(), layout=self._base_layout(),
                blur_radius=-1, darken_alpha=180,
                game_logo=None, top_logo=None, bottom_logo=None,
            )

    def test_build_spine_rejects_darken_out_of_range(self):
        from engine.spine_builder import build_spine
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        with pytest.raises(AssertionError, match="darken_alpha"):
            build_spine(
                cover=cover, geom=self._base_geom(), layout=self._base_layout(),
                blur_radius=20, darken_alpha=300,
                game_logo=None, top_logo=None, bottom_logo=None,
            )

    def test_build_spine_rejects_darken_negative(self):
        from engine.spine_builder import build_spine
        cover = Image.open(ASSETS / "cover.webp").convert("RGBA")
        with pytest.raises(AssertionError, match="darken_alpha"):
            build_spine(
                cover=cover, geom=self._base_geom(), layout=self._base_layout(),
                blur_radius=20, darken_alpha=-1,
                game_logo=None, top_logo=None, bottom_logo=None,
            )

    def test_build_spine_rejects_invalid_logo_alpha(self):
        import dataclasses
        from engine.spine_builder import build_spine
        cover  = Image.open(ASSETS / "cover.webp").convert("RGBA")
        layout = dataclasses.replace(self._base_layout(), logo_alpha=1.5)
        with pytest.raises(AssertionError, match="logo_alpha"):
            build_spine(
                cover=cover, geom=self._base_geom(), layout=layout,
                blur_radius=20, darken_alpha=180,
                game_logo=None, top_logo=None, bottom_logo=None,
            )

    def test_build_spine_rejects_center_y_out_of_bounds(self):
        import dataclasses
        from core.models import LogoSlot
        from engine.spine_builder import build_spine
        cover  = Image.open(ASSETS / "cover.webp").convert("RGBA")
        geom   = self._base_geom()
        # Place game logo center_y way beyond spine height
        bad_slot = dataclasses.replace(
            self._base_layout().game, center_y=geom.spine_h + 500
        )
        layout = dataclasses.replace(self._base_layout(), game=bad_slot)
        with pytest.raises(AssertionError, match="center_y"):
            build_spine(
                cover=cover, geom=geom, layout=layout,
                blur_radius=20, darken_alpha=180,
                game_logo=None, top_logo=None, bottom_logo=None,
            )

    def test_build_spine_valid_boundary_passes(self):
        """Asserts must not fire for correctly configured inputs."""
        import dataclasses
        from core.models import LogoSlot
        from engine.spine_builder import build_spine
        cover  = Image.open(ASSETS / "cover.webp").convert("RGBA")
        geom   = self._base_geom()
        # center_y exactly at spine boundary — must pass
        edge_slot = dataclasses.replace(self._base_layout().game, center_y=geom.spine_h)
        layout    = dataclasses.replace(self._base_layout(), game=edge_slot)
        result = build_spine(
            cover=cover, geom=geom, layout=layout,
            blur_radius=0, darken_alpha=0,
            game_logo=None, top_logo=None, bottom_logo=None,
        )
        assert result.mode == "RGBA"


# ===========================================================================
# Circuit Breaker — BUG-03 + BUG-04 regression tests
# ===========================================================================

class TestCircuitBreaker:
    """Regression tests for circuit breaker threshold and on_progress ordering."""

    def _make_pipeline(self, tmp_path, covers_dir, no_logos=False):
        from core.pipeline import RenderPipeline
        reg = ProfileRegistry(PROFILES).load()
        return RenderPipeline(
            profile      = reg.get("mvs"),
            covers_dir   = covers_dir,
            output_dir   = tmp_path / "out",
            options      = RenderOptions(workers=1),
            logo_paths   = {},
            marquees_dir = tmp_path / "m",
            no_logos     = no_logos,
        )

    def test_single_bad_file_in_3_cover_batch_does_not_trip(self, tmp_path):
        """BUG-03: 1 corrupt file out of 3 must NOT trip the circuit breaker.
        Previously error_threshold=max(1, int(3*0.20))=1, so a single error
        would abort the batch and skip the remaining 2 valid covers.
        """
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "good1.webp")
        shutil.copy(ASSETS / "cover.webp", covers / "good2.webp")
        (covers / "bad.webp").write_bytes(b"not an image")  # corrupt

        pipeline = self._make_pipeline(tmp_path, covers)
        stats = pipeline.run()
        # 2 should succeed, 1 should fail, breaker must NOT trip
        assert stats.succeeded == 2
        assert stats.failed    == 1
        assert stats.breaker_tripped is False

    def test_all_bad_files_trips_breaker(self, tmp_path):
        """All 5 files corrupt → total errors (5) > threshold (3) → breaker trips."""
        # 5 bad files: error_threshold = max(3, int(5*0.20)) = 3.
        # After 4 errors total_errors > 3 → breaker trips; 5th is cancelled.
        covers = tmp_path / "covers"; covers.mkdir()
        for i in range(5):
            (covers / f"bad{i}.webp").write_bytes(b"not an image")

        pipeline = self._make_pipeline(tmp_path, covers)
        stats = pipeline.run()
        assert stats.breaker_tripped is True

    def test_20pct_threshold_trips_on_large_batch(self, tmp_path):
        """BUG-03: 4 errors out of 15 covers (>20%) must trip the breaker."""
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        for i in range(11):
            shutil.copy(ASSETS / "cover.webp", covers / f"good{i}.webp")
        for i in range(4):
            (covers / f"bad{i}.webp").write_bytes(b"not an image")

        pipeline = self._make_pipeline(tmp_path, covers)
        stats = pipeline.run()
        assert stats.breaker_tripped is True

    def test_on_progress_called_for_trip_item(self, tmp_path):
        """BUG-04: on_progress must be called for the item that trips the breaker.
        Previously the break happened before the on_progress call, leaving the
        UI progress bar stuck on the last successfully-reported cover.
        """
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        # 3 good + enough bad to trip (consecutive errors > 10 needs many, but
        # total errors > max(3, ...) is enough here with 11 bad out of 14)
        for i in range(3):
            shutil.copy(ASSETS / "cover.webp", covers / f"good{i}.webp")
        for i in range(11):
            (covers / f"bad{i}.webp").write_bytes(b"not an image")

        progress_calls: list[tuple[int, int, object]] = []
        pipeline = self._make_pipeline(tmp_path, covers)
        stats = pipeline.run(
            on_progress=lambda done, total, result: progress_calls.append(
                (done, total, result)
            )
        )
        assert stats.breaker_tripped is True
        # on_progress must have been called for every item that completed,
        # including the trip item (BUG-04 fix: call before break, not after).
        # With workers=1 total_processed = succeeded + failed.
        total_processed = stats.succeeded + stats.failed
        assert len(progress_calls) == total_processed
        # done values must be contiguous 1..N with no gap
        reported_done = [c[0] for c in progress_calls]
        assert reported_done == list(range(1, total_processed + 1))


# ===========================================================================
# Warp backend: pyvips (lbb) vs PIL (BICUBIC) regression suite
# ===========================================================================

class TestWarpBackend:
    """
    Covers the pyvips lbb warp path and its PIL fallback.

    Quality invariants validated here:
    - Geometry: output size and mode are identical between backends.
    - Alpha smoothness: pyvips lbb produces a full gradient (≥200 unique alpha
      values) versus PIL's binary (≤3) pre-feathering state.
    - Transparency: pixels outside the destination quad are fully transparent.
    - Content: solid-colour source maps to a recognisable colour in the warped
      output interior.
    - Thread safety: 8 concurrent warps do not corrupt each other.
    - Cache: the coordinate-map cache is keyed correctly so distinct geometries
      never collide.
    - Fallback: PIL path is invoked when pyvips is unavailable.
    """

    # Shared fixture geometry
    _SRC_W, _SRC_H = 400, 300
    _CW, _CH       = 600, 500          # canvas size
    _DST_NEAR      = [(80,60),(480,40),(500,440),(60,460)]   # quad inside canvas
    _DST_FAR_CORNER = [(0,0),(_CW,0),(_CW,_CH),(0,_CH)]     # full-canvas identity

    def _solid_src(self, color=(200, 100, 50, 255)):
        return Image.new("RGBA", (self._SRC_W, self._SRC_H), color)

    # ------------------------------------------------------------------
    # Output contract (both backends must satisfy)
    # ------------------------------------------------------------------

    def test_warp_output_size(self):
        """Canvas size must equal (canvas_w, canvas_h) regardless of backend."""
        out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR)
        assert out.size == (self._CW, self._CH)

    def test_warp_output_mode_is_rgba(self):
        """Output must always be RGBA."""
        out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR)
        assert out.mode == "RGBA"

    def test_warp_rgb_source_converted_to_rgba(self):
        """RGB input must be accepted and output RGBA."""
        rgb_src = Image.new("RGB", (self._SRC_W, self._SRC_H), (100, 150, 200))
        out = warp(rgb_src, self._CW, self._CH, self._DST_NEAR)
        assert out.mode == "RGBA"

    def test_warp_outside_quad_is_transparent(self):
        """Pixels clearly outside the destination quad must be fully transparent."""
        import numpy as np
        out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR)
        arr = np.array(out)
        # top-left corner is outside the quad (quad starts at x=80, y=60)
        corner = arr[5:20, 5:20, 3]
        assert corner.max() == 0, (
            f"pixels outside quad are not transparent (max alpha={corner.max()})"
        )

    def test_warp_quad_interior_is_opaque(self):
        """Centre of the warped quad must be fully opaque for a solid-colour source."""
        import numpy as np
        out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR)
        arr = np.array(out)
        cy, cx = self._CH // 2, self._CW // 2
        patch = arr[cy-10:cy+10, cx-10:cx+10, 3]
        assert patch.min() == 255, (
            f"centre of warped quad is not opaque (min alpha={patch.min()})"
        )

    def test_warp_solid_colour_preserved_in_interior(self):
        """Interior pixels must carry the source colour (±8 rounding tolerance)."""
        import numpy as np
        r, g, b = 200, 100, 50
        out = warp(self._solid_src((r, g, b, 255)), self._CW, self._CH, self._DST_NEAR)
        arr = np.array(out)
        cy, cx = self._CH // 2, self._CW // 2
        patch = arr[cy-5:cy+5, cx-5:cx+5]
        opaque = patch[patch[:,:,3] == 255]
        assert len(opaque) > 0, "no fully-opaque pixels found in interior"
        assert abs(int(opaque[:,0].mean()) - r) <= 8
        assert abs(int(opaque[:,1].mean()) - g) <= 8
        assert abs(int(opaque[:,2].mean()) - b) <= 8

    # ------------------------------------------------------------------
    # pyvips quality: smooth alpha edges
    # ------------------------------------------------------------------

    def test_vips_lbb_produces_smooth_alpha(self):
        """
        pyvips lbb must produce a smooth anti-aliased alpha gradient at quad
        boundaries (≥200 unique values across the canvas).

        PIL BICUBIC without feathering produces binary alpha (≤3 unique values).
        The pyvips path must NOT require external feathering to be smooth.
        """
        import numpy as np
        import engine.perspective as ep

        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed — skipping quality assertion")

        out  = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR, feather=0)
        arr  = np.array(out)
        alpha_unique = len(np.unique(arr[:, :, 3]))
        assert alpha_unique >= 200, (
            f"pyvips lbb produced only {alpha_unique} unique alpha values; "
            f"expected ≥200 (smooth gradient). Backend may have regressed to PIL."
        )

    def test_pil_fallback_has_binary_alpha_without_feather(self):
        """
        PIL BICUBIC without feathering must produce near-binary alpha — confirms
        that feathering IS needed in the PIL path and that the pyvips path is
        providing something fundamentally different.
        """
        import numpy as np
        from unittest.mock import patch
        import engine.perspective as ep

        with patch.object(ep, "_PYVIPS_AVAILABLE", False):
            out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR, feather=0)
        arr = np.array(out)
        alpha_unique = len(np.unique(arr[:, :, 3]))
        assert alpha_unique <= 3, (
            f"PIL feather=0 produced {alpha_unique} unique alpha values; "
            f"expected ≤3 (binary 0/255 from BICUBIC perspective transform)."
        )

    def test_pil_feather_smooths_alpha(self):
        """PIL with feather=1.2 must produce more unique alpha values than feather=0."""
        import numpy as np
        from unittest.mock import patch
        import engine.perspective as ep

        with patch.object(ep, "_PYVIPS_AVAILABLE", False):
            hard = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR, feather=0)
            soft = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR, feather=1.2)

        n_hard = len(np.unique(np.array(hard)[:,:,3]))
        n_soft = len(np.unique(np.array(soft)[:,:,3]))
        assert n_soft > n_hard, "feather=1.2 did not increase alpha diversity"

    # ------------------------------------------------------------------
    # PIL fallback path
    # ------------------------------------------------------------------

    def test_pil_fallback_invoked_when_vips_unavailable(self):
        """warp() must still return valid RGBA when pyvips is mocked out."""
        from unittest.mock import patch
        import engine.perspective as ep

        with patch.object(ep, "_PYVIPS_AVAILABLE", False):
            out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR)
        assert out.mode == "RGBA"
        assert out.size == (self._CW, self._CH)

    def test_pil_fallback_feather_zero(self):
        """PIL fallback with feather=0 must not crash and must return RGBA."""
        from unittest.mock import patch
        import engine.perspective as ep

        with patch.object(ep, "_PYVIPS_AVAILABLE", False):
            out = warp(self._solid_src(), self._CW, self._CH, self._DST_NEAR, feather=0)
        assert out.mode == "RGBA"

    # ------------------------------------------------------------------
    # Coordinate-map cache correctness
    # ------------------------------------------------------------------

    def test_index_cache_different_geometries_independent(self):
        """
        Two distinct quad geometries must produce distinct cache entries.
        If cache keying is wrong, one quad's map would corrupt the other's warp.
        """
        import numpy as np
        import engine.perspective as ep

        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed")

        # Quad A: left-tilted
        dstA = [(50,50),(350,100),(370,440),(30,460)]
        # Quad B: right-tilted (mirror of A)
        dstB = [(250,100),(550,50),(570,460),(230,440)]

        src  = self._solid_src()
        outA = warp(src, self._CW, self._CH, dstA)
        outB = warp(src, self._CW, self._CH, dstB)

        arrA = np.array(outA)
        arrB = np.array(outB)
        # The two warps must differ (different quads → different pixel positions)
        assert not np.array_equal(arrA, arrB), (
            "Two distinct quad geometries produced identical output — cache collision?"
        )

    def test_index_cache_same_geometry_reused(self):
        """
        Calling warp() twice with identical geometry must hit the cache on the
        second call and produce bit-identical output.
        """
        import numpy as np
        import engine.perspective as ep

        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed")

        src  = self._solid_src()
        out1 = warp(src, self._CW, self._CH, self._DST_NEAR)
        out2 = warp(src, self._CW, self._CH, self._DST_NEAR)

        assert np.array_equal(np.array(out1), np.array(out2)), (
            "Identical geometry produced different outputs — cache may be corrupted"
        )

    # ------------------------------------------------------------------
    # Thread safety
    # ------------------------------------------------------------------

    def test_thread_safety_concurrent_warps(self):
        """
        8 threads running warp() concurrently on the same geometry must all
        succeed and produce identical results.
        """
        import numpy as np
        import threading
        import engine.perspective as ep

        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed — thread-safety test targets pyvips path")

        src     = self._solid_src()
        results = [None] * 8
        errors  = []

        def worker(idx):
            try:
                results[idx] = np.array(
                    warp(src, self._CW, self._CH, self._DST_NEAR)
                )
            except Exception as exc:
                errors.append(f"thread {idx}: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors, f"Thread errors: {errors}"
        assert all(r is not None for r in results), "Some threads returned None"
        ref = results[0]
        for i, r in enumerate(results[1:], 1):
            assert np.array_equal(ref, r), (
                f"Thread {i} produced a different result — possible race condition"
            )

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_warp_minimum_source_size(self):
        """1×1 source image must not crash and must return correct canvas size."""
        tiny = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        out  = warp(tiny, self._CW, self._CH, self._DST_NEAR)
        assert out.size == (self._CW, self._CH)
        assert out.mode == "RGBA"

    def test_warp_all_profiles_backend_geometry(self):
        """All built-in profiles must produce output matching template dimensions."""
        reg = ProfileRegistry(PROFILES).load()
        for name in ["mvs", "arcade", "dvd"]:
            p   = reg.get(name)
            g   = p.geometry
            img = Image.new("RGBA", (g.cover_w, g.cover_h), (128, 128, 128, 255))
            out = warp(img, g.template_w, g.template_h, g.cover_quad.as_list())
            assert out.size == (g.template_w, g.template_h), (
                f"Profile '{name}': expected {(g.template_w, g.template_h)}, "
                f"got {out.size}"
            )

    def test_warp_identity_quad_fills_canvas(self):
        """Full-canvas quad (identity-like transform) must fill the interior of the canvas.

        The pyvips lbb/nohalo interpolation kernel samples a neighbourhood of
        pixels around each output coordinate.  At the very edges of a
        full-canvas quad the kernel reaches outside the source boundary and
        pulls from the transparent background, giving a 1-2 px anti-aliased
        fade along each canvas edge.  The interior (5 px from each edge) must
        be fully opaque.
        """
        import numpy as np
        full_dst = [(0,0),(self._CW,0),(self._CW,self._CH),(0,self._CH)]
        out = warp(self._solid_src(), self._CW, self._CH, full_dst)
        arr = np.array(out)
        # Interior of the canvas must be fully opaque
        interior = arr[5:-5, 5:-5, 3]
        assert interior.min() == 255, (
            "Identity-like quad left transparent pixels in the canvas interior "
            f"(min alpha in 5px-inset interior = {interior.min()})"
        )

    # ------------------------------------------------------------------
    # Backend env-var (BOX3D_WARP_BACKEND)
    # ------------------------------------------------------------------

    def test_vips_kernel_env_var_is_read(self):
        """_VIPS_KERNEL must reflect BOX3D_WARP_BACKEND at import time."""
        import engine.perspective as ep
        # _VIPS_KERNEL defaults to 'lbb' if env var is absent
        assert ep._VIPS_KERNEL in ("lbb", "nohalo", "bicubic", "bilinear"), (
            f"Unexpected _VIPS_KERNEL value: {ep._VIPS_KERNEL!r}"
        )

    def test_get_backend_label_reflects_kernel(self):
        """get_backend_label() must include the requested kernel name in its output."""
        import engine.perspective as ep
        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed")
        for kernel in ("lbb", "nohalo", "bicubic", "bilinear"):
            label = ep.get_backend_label(kernel)
            assert kernel in label, (
                f"get_backend_label({kernel!r}) did not include kernel in label: {label!r}"
            )
        # Fallback for invalid kernel uses module default
        label_invalid = ep.get_backend_label("bad_kernel")
        assert ep._VIPS_KERNEL in label_invalid

    def test_get_backend_label_pil_fallback(self):
        """get_backend_label() must return PIL fallback string when pyvips unavailable."""
        from unittest.mock import patch
        import engine.perspective as ep
        with patch.object(ep, "_PYVIPS_AVAILABLE", False):
            label = ep.get_backend_label("lbb")
        assert "PIL" in label and "fallback" in label

    def test_coord_cache_evicts_oldest_entry(self):
        """_COORD_CACHE must not exceed _COORD_CACHE_MAX entries."""
        import engine.perspective as ep

        if not ep._PYVIPS_AVAILABLE:
            pytest.skip("pyvips not installed")

        original_cache = ep._COORD_CACHE
        from collections import OrderedDict
        ep._COORD_CACHE = OrderedDict()

        try:
            max_entries = ep._COORD_CACHE_MAX
            # Fill cache beyond its limit using different canvas sizes
            for w in range(max_entries + 3):
                src = Image.new("RGBA", (10, 10), (128, 128, 128, 255))
                pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
                ep._get_coord_array(100 + w, 100, ep.solve_coefficients(
                    [(0, 0), (10, 0), (10, 10), (0, 10)], pts,
                ))
            assert len(ep._COORD_CACHE) <= max_entries, (
                f"Cache grew to {len(ep._COORD_CACHE)} entries, "
                f"exceeding limit of {max_entries}"
            )
        finally:
            ep._COORD_CACHE = original_cache


# ===========================================================================
# Input validation (F-04, F-05, F-08 remediation coverage)
# ===========================================================================

class TestInputValidation:

    def test_parse_rgb_str_rejects_negative_channel(self):
        """parse_rgb_str must return None for negative channel values."""
        from cli.utils import parse_rgb_str
        assert parse_rgb_str("-0.1,1.0,1.0") is None

    def test_parse_rgb_str_rejects_value_above_5(self):
        """parse_rgb_str must return None for channel values above 5.0."""
        from cli.utils import parse_rgb_str
        assert parse_rgb_str("6.0,1.0,1.0") is None

    def test_parse_rgb_str_accepts_boundary_values(self):
        """parse_rgb_str must accept exactly 0.0 and 5.0."""
        from cli.utils import parse_rgb_str
        assert parse_rgb_str("0.0,5.0,1.0") is not None

    def test_parse_rgb_str_rejects_wrong_count(self):
        """parse_rgb_str must return None for fewer or more than 3 values."""
        from cli.utils import parse_rgb_str
        assert parse_rgb_str("1.0,1.0") is None
        assert parse_rgb_str("1.0,1.0,1.0,1.0") is None

    def test_parse_rgb_str_valid_returns_matrix_string(self):
        """parse_rgb_str with valid input must return the diagonal matrix string."""
        from cli.utils import parse_rgb_str
        result = parse_rgb_str("1.1,1.0,0.9")
        assert result is not None
        assert "1.1" in result and "1.0" in result and "0.9" in result

    def test_version_is_consistent(self):
        """core/version.__version__ must match the string in bootstrap._VERSION."""
        from core.version import __version__
        from cli.bootstrap import _VERSION
        assert __version__ == _VERSION, (
            f"Version mismatch: core.version={__version__!r}, "
            f"bootstrap._VERSION={_VERSION!r}"
        )


# ---------------------------------------------------------------------------
# cli/diagnostics.py
# ---------------------------------------------------------------------------

class TestDiagnostics:
    """Tests for cli.diagnostics.write_pyvips_diagnostic()."""

    def test_writes_file_to_directory(self, tmp_path):
        """write_pyvips_diagnostic must create a log file under the given directory."""
        from cli.diagnostics import write_pyvips_diagnostic

        result = write_pyvips_diagnostic(tmp_path)

        assert result.exists(), "diagnostic file was not created"
        assert result.parent == tmp_path
        assert result.name.startswith("pyvips_diagnostic_")
        assert result.suffix == ".log"

    def test_returns_path_object(self, tmp_path):
        """write_pyvips_diagnostic must return a Path, not a string."""
        from cli.diagnostics import write_pyvips_diagnostic

        result = write_pyvips_diagnostic(tmp_path)

        assert isinstance(result, Path)

    def test_creates_directory_if_missing(self, tmp_path):
        """write_pyvips_diagnostic must create log_dir when it does not exist."""
        from cli.diagnostics import write_pyvips_diagnostic

        nested = tmp_path / "sub" / "logs"
        result = write_pyvips_diagnostic(nested)

        assert nested.exists()
        assert result.exists()

    def test_report_contains_expected_sections(self, tmp_path):
        """The written report must contain all mandatory diagnostic sections."""
        from cli.diagnostics import write_pyvips_diagnostic

        path = write_pyvips_diagnostic(tmp_path)
        content = path.read_text(encoding="utf-8")

        for section in ("[PLATFORM]", "[PYINSTALLER]", "[SYS.PATH]",
                        "[PYVIPS IMPORT]", "[CTYPES DLL LOAD PROBES]"):
            assert section in content, f"Missing section {section!r} in diagnostic report"

    def test_handles_oserror_gracefully(self, tmp_path, capsys):
        """write_pyvips_diagnostic must not raise when write_text fails with OSError."""
        from unittest.mock import patch
        from cli.diagnostics import write_pyvips_diagnostic

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            result = write_pyvips_diagnostic(tmp_path)

        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "disk full" in captured.err
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# --no-spine and granular logo flags
# ---------------------------------------------------------------------------

class TestNoSpineAndGranularLogos:
    """Tests for --no-spine (RenderOptions.no_spine) and granular logo flags
    (no_game_logo / no_fixed_logos on RenderPipeline)."""

    # ── no_spine ──────────────────────────────────────────────────────────────

    def test_no_spine_renders_without_error(self, tmp_path):
        """RenderOptions(no_spine=True) must produce a successful render."""
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1, no_spine=True),
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
        ).run()
        assert stats.succeeded == 1

    def test_no_spine_result_differs_from_default(self, tmp_path):
        """A no-spine render must produce a pixel-different result from the normal render."""
        import shutil, numpy as np
        from PIL import Image
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        registry = ProfileRegistry(PROFILES).load()
        common = dict(
            profile=registry.get("mvs"),
            covers_dir=covers,
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
        )

        from core.pipeline import RenderPipeline

        out_normal = tmp_path / "normal"; out_normal.mkdir()
        RenderPipeline(
            output_dir=out_normal,
            options=RenderOptions(workers=1, no_spine=False),
            **common,
        ).run()

        out_nospine = tmp_path / "nospine"; out_nospine.mkdir()
        RenderPipeline(
            output_dir=out_nospine,
            options=RenderOptions(workers=1, no_spine=True),
            **common,
        ).run()

        img_normal  = np.array(Image.open(next(out_normal.glob("*.webp"))).convert("RGBA"), dtype=np.float32)
        img_nospine = np.array(Image.open(next(out_nospine.glob("*.webp"))).convert("RGBA"), dtype=np.float32)
        assert not np.array_equal(img_normal, img_nospine), \
            "no_spine render should differ from normal render"

    def test_no_spine_skips_build_spine(self, tmp_path):
        """With no_spine=True, build_spine must never be called."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        from engine import compositor as ec

        with patch.object(ec, "build_spine", wraps=ec.build_spine) as mock_bs:
            RenderPipeline(
                profile=ProfileRegistry(PROFILES).load().get("mvs"),
                covers_dir=covers,
                output_dir=tmp_path / "out",
                options=RenderOptions(workers=1, no_spine=True),
                logo_paths={},
                marquees_dir=tmp_path / "nomarq",
            ).run()

        mock_bs.assert_not_called()

    # ── granular logo flags ───────────────────────────────────────────────────

    def test_no_game_logo_suppresses_marquee_only(self, tmp_path):
        """no_game_logo=True must skip _load_game_logo; fixed logos are still loaded."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1),
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
            no_game_logo=True,
        )
        with patch.object(pipeline, "_load_game_logo") as mock_game, \
             patch.object(pipeline, "_load_logo") as mock_fixed:
            pipeline.run()

        mock_game.assert_not_called()
        mock_fixed.assert_called()  # top/bottom logos still attempted

    def test_no_fixed_logos_suppresses_system_logos_only(self, tmp_path):
        """no_fixed_logos=True must skip top/bottom logos; game marquee is still loaded."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1),
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
            no_fixed_logos=True,
        )
        with patch.object(pipeline, "_load_game_logo") as mock_game, \
             patch.object(pipeline, "_load_logo") as mock_fixed:
            pipeline.run()

        mock_fixed.assert_not_called()
        mock_game.assert_called()  # game logo still attempted

    def test_no_logos_still_suppresses_all(self, tmp_path):
        """Backward compat: no_logos=True must still suppress game logo + fixed logos."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1),
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
            no_logos=True,
        )
        with patch.object(pipeline, "_load_game_logo") as mock_game, \
             patch.object(pipeline, "_load_logo") as mock_fixed:
            pipeline.run()

        mock_game.assert_not_called()
        mock_fixed.assert_not_called()

    def test_no_spine_and_no_logos_combined(self, tmp_path):
        """no_spine=True + no_logos=True must render successfully without any logos or spine."""
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        stats = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=tmp_path / "out",
            options=RenderOptions(workers=1, no_spine=True),
            logo_paths={},
            marquees_dir=tmp_path / "nomarq",
            no_logos=True,
        ).run()
        assert stats.succeeded == 1


# ===========================================================================
# TestAuditFixes — regression tests for BOX3D-AUDIT findings
# ===========================================================================

class TestAuditFixes:
    """Regression tests for every critical finding in BOX3D-AUDIT.md."""

    # -----------------------------------------------------------------------
    # HV-04 — blending RGBA mode assertions
    # -----------------------------------------------------------------------

    def test_alpha_weighted_screen_rejects_rgb_dst(self):
        """alpha_weighted_screen must assert-fail when dst is RGB, not silently IndexError."""
        dst_rgb = Image.new("RGB",  (10, 10), (128, 64, 32))
        src     = Image.new("RGBA", (10, 10), (200, 100, 50, 128))
        with pytest.raises(AssertionError, match="dst must be RGBA"):
            alpha_weighted_screen(dst_rgb, src)

    def test_linear_alpha_composite_rejects_rgb_dst(self):
        """linear_alpha_composite must assert-fail when dst is RGB."""
        dst_rgb = Image.new("RGB",  (10, 10), (50, 100, 150))
        src     = Image.new("RGBA", (10, 10), (200, 100, 50, 200))
        with pytest.raises(AssertionError, match="dst must be RGBA"):
            linear_alpha_composite(dst_rgb, src)

    def test_alpha_weighted_screen_accepts_rgba_dst(self):
        """Sanity: alpha_weighted_screen must succeed when dst is RGBA."""
        dst = Image.new("RGBA", (10, 10), (128, 64, 32, 255))
        src = Image.new("RGBA", (10, 10), (200, 100, 50, 128))
        result = alpha_weighted_screen(dst, src)
        assert result.mode == "RGBA"

    # -----------------------------------------------------------------------
    # AF-04 — _COORD_CACHE thread safety with >_COORD_CACHE_MAX geometries
    # -----------------------------------------------------------------------

    def test_coord_cache_concurrent_17_geometries(self):
        """_get_coord_array must not raise KeyError with 17 unique geometries in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from engine.perspective import _get_coord_array, solve_coefficients

        # 17 distinct quad shapes — forces cache eviction with concurrent access
        quads = [
            [(0, 0), (w, 0), (w, h), (0, h)]
            for w, h in [(200 + i * 10, 300 + i * 10) for i in range(17)]
        ]

        def compute(q):
            src_pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
            coeffs  = solve_coefficients(src_pts, q)
            return _get_coord_array(400, 400, coeffs)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(compute, q) for q in quads]
            # Any KeyError/race would surface here
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 17
        for arr in results:
            assert arr.shape == (400, 400, 2)

    # -----------------------------------------------------------------------
    # RD-02 — Atomic delivery: temp+rename
    # -----------------------------------------------------------------------

    def test_atomic_delivery_no_tmp_files_on_success(self, tmp_path):
        """No .tmp files must survive in output_dir after a successful render."""
        import shutil
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")

        from core.pipeline import RenderPipeline
        out = tmp_path / "out"
        RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=out,
            options=RenderOptions(workers=1),
        ).run()

        tmp_files = list(out.rglob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files found: {tmp_files}"

    def test_atomic_delivery_cleanup_on_save_error(self, tmp_path):
        """On save failure the .tmp file must be deleted (no partial files left)."""
        import shutil
        from unittest.mock import patch
        covers = tmp_path / "covers"; covers.mkdir()
        shutil.copy(ASSETS / "cover.webp", covers / "cover.webp")
        out = tmp_path / "out"; out.mkdir()

        from core.pipeline import RenderPipeline
        pipeline = RenderPipeline(
            profile=ProfileRegistry(PROFILES).load().get("mvs"),
            covers_dir=covers,
            output_dir=out,
            options=RenderOptions(workers=1),
        )

        # Simulate a disk-write failure on the .tmp file
        orig_save = __import__("PIL.Image", fromlist=["Image"]).Image.save

        def boom(self, fp, *args, **kwargs):
            if str(fp).endswith(".tmp"):
                raise OSError("simulated disk full")
            return orig_save(self, fp, *args, **kwargs)

        with patch("PIL.Image.Image.save", boom):
            summary = pipeline.run()

        # The cover must be recorded as an error (not ok)
        assert summary.failed == 1
        # No .tmp file must remain
        tmp_files = list(out.rglob("*.tmp"))
        assert tmp_files == [], f"Temp file not cleaned up: {tmp_files}"

    # -----------------------------------------------------------------------
    # PF-01 / RD-01 — _safe_open: thumbnail before convert
    # -----------------------------------------------------------------------

    def test_safe_open_downscales_large_image(self, tmp_path):
        """_safe_open must return an image ≤8192px even for inputs >8192px."""
        from core.pipeline import _safe_open
        # Create an image slightly over the 8192px limit
        big = Image.new("RGB", (9000, 500), (200, 100, 50))
        big_path = tmp_path / "big.png"
        big.save(str(big_path))

        result = _safe_open(big_path)
        assert result.width <= 8192
        assert result.height <= 8192
        assert result.mode == "RGBA"

    def test_safe_open_no_decompression_bomb_error(self, tmp_path):
        """_safe_open must not raise DecompressionBombError for inputs >89 Mpx."""
        from core.pipeline import _safe_open
        # 10000×10000 = 100 Mpx > PIL default limit of ~89 Mpx
        huge = Image.new("RGB", (10_000, 10_000), (100, 150, 200))
        huge_path = tmp_path / "huge.png"
        huge.save(str(huge_path))

        # Should complete without DecompressionBombError or any exception
        result = _safe_open(huge_path)
        assert result.width  <= 8192
        assert result.height <= 8192
        assert result.mode == "RGBA"

    # -----------------------------------------------------------------------
    # AF-01 — engine/perspective.py must not read os.environ
    # -----------------------------------------------------------------------

    def test_vips_kernel_is_constant_not_env_driven(self):
        """_VIPS_KERNEL must be a plain constant, not influenced by os.environ."""
        import os
        import importlib
        import engine.perspective as ep

        # Store original value
        original = ep._VIPS_KERNEL

        # Setting env var after import must have no effect
        os.environ["BOX3D_WARP_BACKEND"] = "bilinear"
        try:
            # Reload module to check if it re-reads env
            importlib.reload(ep)
            assert ep._VIPS_KERNEL == "lbb", (
                f"_VIPS_KERNEL should always be 'lbb' default, got {ep._VIPS_KERNEL!r}"
            )
        finally:
            os.environ.pop("BOX3D_WARP_BACKEND", None)
            importlib.reload(ep)  # restore module to clean state

    # -----------------------------------------------------------------------
    # HV-03 — parse_rgb_str only catches ValueError
    # -----------------------------------------------------------------------

    def test_parse_rgb_str_returns_none_on_bad_format(self):
        """parse_rgb_str must return None (not raise) for malformed input."""
        from cli.utils import parse_rgb_str
        assert parse_rgb_str("not,numbers,here") is None
        assert parse_rgb_str("1.0,2.0")          is None   # only 2 values
        assert parse_rgb_str("1.0,2.0,99.9")     is None   # out of [0..5] range

    def test_parse_rgb_str_valid_input(self):
        """parse_rgb_str must return a matrix string for valid R,G,B input."""
        from cli.utils import parse_rgb_str
        result = parse_rgb_str("1.0,0.9,1.1")
        assert result is not None
        assert "1.0" in result and "0.9" in result and "1.1" in result

    # -----------------------------------------------------------------------
    # PF-04 — spine logo alpha via PIL.point() (no NumPy round-trip)
    # -----------------------------------------------------------------------

    def test_spine_logo_alpha_applied_correctly(self):
        """Logo alpha=0.5 must halve all alpha values in the logo strip."""
        from engine.spine_builder import _paste_logo
        from core.models import LogoSlot, ProfileGeometry, Quad, SpineLayout

        canvas = Image.new("RGBA", (60, 200), (0, 0, 0, 0))
        logo   = Image.new("RGBA", (40, 40),  (255, 255, 255, 200))

        result = _paste_logo(canvas, logo, 60, 200, 50, 50, 100, 0.5, 0)

        # After pasting with alpha=0.5, the composited logo alpha at the
        # paste region should be roughly 100 (200 * 0.5), not the original 200.
        # Check a pixel in the center of the paste area.
        px = result.getpixel((30, 100))  # center of paste area
        assert px[3] <= 110, f"Expected alpha ≈100 after 0.5 scale, got {px[3]}"
