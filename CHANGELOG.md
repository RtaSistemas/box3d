# Changelog

All notable changes to box3d are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added (Sprint 5.1)

- **Game logo fallback** — `_load_game_logo()` in `core/pipeline.py` now resolves
  the per-cover game logo in two stages: (1) `data/inputs/marquees/<stem>.*`, then
  (2) `profiles/<n>/assets/logo_game.*`. Falls back to `None` silently if both are
  absent. Three new tests verify priority, fallback, and the no-logo path.
- **Editable profiles/ next to the executable** — `_bootstrap_profiles()` in
  `cli/main.py` copies the built-in profiles from the bundle to `<exe-dir>/profiles/`
  on first run using `shutil.copytree`. On subsequent runs only new built-in profiles
  are added; existing ones are never overwritten, preserving user edits. The
  `--profiles-dir` default now points to this user-editable directory.
- **`instructions.txt` on first run** — `_bootstrap_instructions()` writes a
  comprehensive plain-text quick-start guide next to the executable the first time
  the binary is launched. The file is never overwritten. Covers: folder structure,
  file naming conventions, all render flags with defaults and examples, other
  commands, and steps to add a new profile.
- **`_PROFILES` module constant** — exposed alongside `_BUNDLE` and `_DATA` in
  `cli/main.py` for consistent path resolution across all bootstrap functions.

### Changed (Sprint 5.1)

- **README** — Architecture tree updated with per-file detail for profile `assets/`
  directories. "Standalone executable" section expanded to show `profiles/` and
  `instructions.txt` in the layout tree, with notes on editing profiles. "Creating a
  Profile" scaffold now lists all expected filenames and supported extensions. Profile
  JSON Schema corrected: `rotate` is documented as a per-slot integer field (degrees)
  replacing the erroneous `rotate_logos` bool; "Logo resolution order" section added.

---

## [2.0.0-rc1] — 2026-03

