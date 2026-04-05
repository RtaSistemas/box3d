"""
tests/visual/cases.py — Snapshot test case definitions
=======================================================
Shared between ``generate_baselines.py`` and ``test_render_snapshot.py``
so both use an identical parameter set.

Adding a new case here is enough to include it in both baseline generation
and regression testing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotCase:
    """Parameters for one deterministic render used in snapshot testing."""
    id:           str
    profile_name: str        = "mvs"
    blur_radius:  int        = 20
    darken_alpha: int        = 180
    rgb_matrix:   str | None = None
    no_rotate:    bool       = False
    with_logos:   bool       = True
    spine_source: str | None = None
    cover_fit:    str | None = None


# ---------------------------------------------------------------------------
# 6 representative cases — profile × modifier coverage
# ---------------------------------------------------------------------------

CASES: list[SnapshotCase] = [
    # Profiles
    SnapshotCase("mvs_default"),
    SnapshotCase("arcade_default",  profile_name="arcade"),
    SnapshotCase("dvd_default",     profile_name="dvd"),

    # Modifiers on MVS
    SnapshotCase("mvs_rgb_warm",
                 rgb_matrix="1.3 0 0  0 1.0 0  0 0 0.7"),
    SnapshotCase("mvs_no_rotate",   no_rotate=True),
    SnapshotCase("mvs_no_logos",    with_logos=False),
]
