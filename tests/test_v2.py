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
        assert stats["ok"] == 1 and stats["error"] == 0

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
        assert stats["ok"] == 1

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
        assert stats["ok"] == 1


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
        assert stats["ok"] == 1

    def test_safe_open_oom_guard_downscales(self, tmp_path):
        """_safe_open must call thumbnail when image exceeds 8192px."""
        from unittest.mock import patch, MagicMock, PropertyMock
        from core.pipeline import _safe_open

        # Write a real tiny file so Image.open succeeds at the file level
        real = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        img_path = tmp_path / "big.png"
        real.save(str(img_path))

        # Make the in-memory image report itself as oversized
        mock_img = MagicMock(spec=Image.Image)
        type(mock_img).width  = PropertyMock(return_value=10000)
        type(mock_img).height = PropertyMock(return_value=100)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = mock_img
            _safe_open(img_path)

        mock_img.thumbnail.assert_called_once_with((8192, 8192), Image.BICUBIC)

    def test_safe_open_no_downscale_when_within_limit(self, tmp_path):
        """_safe_open must NOT call thumbnail for images within 8192px."""
        from unittest.mock import patch, MagicMock, PropertyMock
        from core.pipeline import _safe_open

        real = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        img_path = tmp_path / "normal.png"
        real.save(str(img_path))

        mock_img = MagicMock(spec=Image.Image)
        type(mock_img).width  = PropertyMock(return_value=800)
        type(mock_img).height = PropertyMock(return_value=1000)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = mock_img
            _safe_open(img_path)

        mock_img.thumbnail.assert_not_called()

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

        assert stats["skip"] == 1
        assert stats.get("ok", 0) == 0
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

        assert stats["dry"] == 1
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
