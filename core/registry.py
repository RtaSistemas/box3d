"""
core/registry.py — Profile registry
=====================================
Discovers, loads, and caches profiles from the ``profiles/`` directory.

Each profile lives in its own subdirectory and must contain:

    profiles/<name>/
        profile.json     ← geometry + layout JSON
        template.png     ← RGBA box template

Usage::

    registry = ProfileRegistry("profiles/")
    registry.load()
    profile = registry.get("mvs")
    for name in registry.names():
        print(name)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.models import (
    CoverFit, LogoSlot, Profile, ProfileGeometry, Quad,
    SpineLayout, SpineSource,
)

log = logging.getLogger("box3d.registry")


class ProfileError(Exception):
    """Raised when a profile directory or JSON is invalid."""


class ProfileRegistry:
    """
    Auto-discovers profiles from a root directory.

    Profiles are loaded lazily on first access or eagerly via
    :meth:`load`.  After loading, the registry is immutable.
    """

    def __init__(self, profiles_dir: str | Path) -> None:
        self._dir     = Path(profiles_dir)
        self._profiles: dict[str, Profile] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> "ProfileRegistry":
        """
        Scan the profiles directory and load every valid profile.

        Subdirectories that contain both ``profile.json`` and
        ``template.png`` are treated as profiles.  Others are silently
        skipped.

        Returns self for chaining.
        """
        if not self._dir.is_dir():
            raise ProfileError(f"Profiles directory not found: {self._dir}")

        loaded = 0
        for entry in sorted(self._dir.iterdir()):
            if not entry.is_dir():
                continue
            json_path     = entry / "profile.json"
            template_path = entry / "template.png"
            if not json_path.exists():
                log.debug("Skipping %s — no profile.json", entry.name)
                continue
            if not template_path.exists():
                log.warning("Skipping %s — no template.png", entry.name)
                continue
            try:
                profile = _load_profile(entry, json_path)
                self._profiles[profile.name] = profile
                log.info("Loaded profile: %s (%dx%d)",
                         profile.name,
                         profile.geometry.template_w,
                         profile.geometry.template_h)
                loaded += 1
            except ProfileError as exc:
                log.warning("Skipping %s — %s", entry.name, exc)

        log.info("Registry: %d profile(s) loaded from %s", loaded, self._dir)
        return self

    def get(self, name: str) -> Profile:
        """Return a loaded profile by name.  Raises KeyError if not found."""
        if name not in self._profiles:
            available = list(self._profiles)
            raise KeyError(
                f"Profile {name!r} not found.  "
                f"Available: {available}"
            )
        return self._profiles[name]

    def names(self) -> list[str]:
        """Return the sorted list of loaded profile names."""
        return sorted(self._profiles)

    def all(self) -> list[Profile]:
        """Return all loaded profiles sorted by name."""
        return [self._profiles[n] for n in self.names()]

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, name: object) -> bool:
        return name in self._profiles


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_profile(directory: Path, json_path: Path) -> Profile:
    """Parse profile.json and return a :class:`Profile`."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Invalid JSON in {json_path}: {exc}") from exc

    name = data.get("name", directory.name)

    try:
        geometry = _parse_geometry(data)
        layout   = _parse_layout(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileError(f"Schema error in {json_path}: {exc}") from exc

    return Profile(name=name, root=directory,
                   geometry=geometry, layout=layout)


def _parse_geometry(data: dict) -> ProfileGeometry:
    tmpl = data["template_size"]
    sp   = data["spine"]
    cv   = data["cover"]

    def _quad(d: dict) -> Quad:
        return Quad(
            tl=tuple(d["tl"]),
            tr=tuple(d["tr"]),
            br=tuple(d["br"]),
            bl=tuple(d["bl"]),
        )

    return ProfileGeometry(
        template_w = tmpl["width"],
        template_h = tmpl["height"],
        spine_w    = sp["width"],
        spine_h    = sp["height"],
        cover_w    = cv["width"],
        cover_h    = cv["height"],
        spine_quad = _quad(data["spine_quad"]),
        cover_quad = _quad(data["cover_quad"]),
        spine_source_frac = float(data.get("spine_source_frac", 0.20)),
        spine_source      = data.get("spine_source", "left"),
        cover_fit         = data.get("cover_fit", "stretch"),
    )


def _parse_layout(data: dict) -> SpineLayout:
    def _slot(d: dict) -> LogoSlot:
        return LogoSlot(
            max_w    = int(d["max_w"]),
            max_h    = int(d["max_h"]),
            center_y = int(d["center_y"]),
        )

    sl = data.get("spine_layout", {})
    return SpineLayout(
        game   = _slot(sl.get("game",   {"max_w":80,"max_h":320,"center_y":453})),
        top    = _slot(sl.get("top",    {"max_w":80,"max_h":120,"center_y":150})),
        bottom = _slot(sl.get("bottom", {"max_w":80,"max_h":80, "center_y":780})),
        logo_alpha   = float(sl.get("logo_alpha",   0.85)),
        rotate_logos = bool(sl.get("rotate_logos",  True)),
    )
