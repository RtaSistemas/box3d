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
from engine.blending    import alpha_weighted_screen, apply_color_matrix, build_silhouette_mask, dst_in
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

    #def test_alpha_weighted_screen_preserves_dst_alpha(self):
    #    dst = Image.new("RGBA", (10,10), (100,100,100,128))
    #    src = Image.new("RGBA", (10,10), (200,200,200,255))
    #    out = alpha_weighted_screen(dst, src)
    #    assert out.getpixel((5,5))[3] == 128

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

        assert stats["ok"]    == 1
        assert stats["error"] == 0
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
        assert stats["dry"] == 1
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
        assert stats["ok"] == 1
