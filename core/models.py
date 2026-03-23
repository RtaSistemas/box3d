"""
core/models.py — Domain models
================================
Pure dataclasses that describe every object in the system.
No rendering logic, no I/O.  These are the shared language between
the core engine, the rendering engine, and the profile registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Primitive geometry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rect:
    """Axis-aligned bounding rectangle in template pixel coordinates."""
    x:      int
    y:      int
    width:  int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x2, self.y2)


@dataclass(frozen=True)
class Quad:
    """
    Four corner points (clockwise: TL → TR → BR → BL) in template
    pixel coordinates.  Used for perspective warp targets.
    """
    tl: tuple[int, int]
    tr: tuple[int, int]
    br: tuple[int, int]
    bl: tuple[int, int]

    def as_list(self) -> list[tuple[int, int]]:
        return [self.tl, self.tr, self.br, self.bl]


# ---------------------------------------------------------------------------
# Logo placement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LogoSlot:
    """
    A named slot on the spine strip where a logo is composited.

    Coordinates are in *spine-strip* space (not template space).
    ``rotate`` is the rotation angle in degrees passed directly to
    PIL ``Image.rotate`` (negative = clockwise).  Default 0 = no rotation.
    """
    max_w:    int    # maximum logo width  after rotation
    max_h:    int    # maximum logo height
    center_y: int    # vertical centre in the spine strip (px)
    rotate:   int = 0  # rotation angle in degrees (PIL convention)


# ---------------------------------------------------------------------------
# Profile definition
# ---------------------------------------------------------------------------

SpineSource = Literal["left", "right", "center"]
CoverFit    = Literal["stretch", "fit", "crop"]
OutFormat   = Literal["webp", "png"]


@dataclass(frozen=True)
class ProfileGeometry:
    """
    Full geometric description of one box profile.
    Loaded from profile.json and used by the rendering engine.
    """
    # Template canvas
    template_w: int
    template_h: int

    # Spine strip dimensions
    spine_w: int
    spine_h: int

    # Cover face dimensions (before warp)
    cover_w: int
    cover_h: int

    # Warp targets on the template canvas
    spine_quad: Quad
    cover_quad: Quad

    # Sampling behaviour
    spine_source_frac: float       = 0.20
    spine_source:      SpineSource = "left"
    cover_fit:         CoverFit    = "stretch"

    def __post_init__(self):
        """OOM Hardening Policy Validation"""
        max_dim = 8192
        if self.template_w > max_dim or self.template_h > max_dim:
            raise ValueError(
                f"Template resolution {self.template_w}x{self.template_h} "
                f"exceeds hard limit of {max_dim}px."
            )
        if self.spine_w > max_dim or self.spine_h > max_dim:
            raise ValueError("Spine resolution exceeds hard limit.")
        if self.cover_w > max_dim or self.cover_h > max_dim:
            raise ValueError("Cover resolution exceeds hard limit.")


@dataclass
class SpineLayout:
    """Logo placement on the spine strip (spine-space coordinates)."""
    game:   LogoSlot
    top:    LogoSlot
    bottom: LogoSlot

    logo_alpha: float = 0.85


@dataclass
class Profile:
    """
    Complete, self-contained profile.

    Loaded by the registry from a profile directory.  The ``root``
    attribute points to the directory so the engine can resolve
    ``template.png`` and ``assets/`` relative to it.
    """
    name:     str
    root:     Path
    geometry: ProfileGeometry
    layout:   SpineLayout

    @property
    def template_path(self) -> Path:
        return self.root / "template.png"


# ---------------------------------------------------------------------------
# Runtime options
# ---------------------------------------------------------------------------

@dataclass
class RenderOptions:
    """
    Rendering parameters supplied by the caller (CLI, API, …).
    Separated from the profile so that geometry stays immutable.
    """
    blur_radius:  int        = 20
    darken_alpha: int        = 180
    rgb_matrix:   str | None = None
    cover_fit:    CoverFit | None   = None   # overrides profile default
    spine_source: SpineSource | None = None  # overrides profile default
    no_rotate:    bool = False               # force rotate=0 on all slots
    # Logo control is handled by the caller (CLI) via logo_paths={} passed to
    # RenderPipeline — no field needed in the domain model (removed in Sprint 5).

    output_format:  OutFormat = "webp"
    skip_existing:  bool      = False
    workers:        int       = 4
    dry_run:        bool      = False


@dataclass
class CoverResult:
    """Outcome record for a single cover processed by the pipeline."""
    stem:    str
    status:  Literal["ok", "skip", "error", "dry"]
    elapsed: float
    error:   str = ""