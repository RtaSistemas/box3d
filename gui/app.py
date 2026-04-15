"""
gui/app.py — Box3D Desktop GUI
================================
CustomTkinter desktop application that wraps the Box3D rendering engine.

Provides the same functionality as the web Control Center without requiring
a browser or web server.  The RenderPipeline runs in a background thread;
progress events are bridged to the main thread via a ``queue.Queue`` polled
with ``after()``.

Run directly::

    python -m gui.app

Or via the installed entrypoint::

    box3d-gui
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

# ── Path bootstrap (works from both installed package and `python -m`) ────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cli.bootstrap import _DATA, _PROFILES          # noqa: E402
from core.models import RenderOptions                # noqa: E402
from core.pipeline import RenderPipeline             # noqa: E402
from core.registry import ProfileRegistry            # noqa: E402

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_VERSION = "2.1.0"

# Palette — mirrors the web Control Center for visual consistency
_BG      = "#0b0e14"
_PANEL   = "#12161e"
_PANEL2  = "#181d28"
_BORDER  = "#1e2535"
_ACCENT  = "#00eaff"
_ACCENT2 = "#ff2bd6"
_WARN    = "#ffb347"
_OK      = "#39ff7a"
_ERROR   = "#ff4757"
_TEXT    = "#c8d0e0"
_DIM     = "#5a6480"

_FONT_MONO = "Courier New" if platform.system() == "Windows" else "monospace"


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────

class App(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()

        self.title(f"BOX3D v{_VERSION} — Desktop")
        self.geometry("1300x800")
        self.minsize(960, 620)
        self.configure(fg_color=_BG)

        # ── Runtime state ────────────────────────────────────────────────────
        self._rendering        = False
        self._queue: queue.Queue[dict] = queue.Queue()
        self._profiles_map:   dict    = {}
        self._current_format  = "webp"
        self._last_output_dir: Path | None = None
        self._preview_ctk_img = None     # keep CTkImage reference alive

        self._build_ui()
        self._load_profiles()

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=290)
        self.grid_rowconfigure(0, weight=0)   # header
        self.grid_rowconfigure(1, weight=1)   # body

        self._build_header()
        self._build_config_panel()
        self._build_progress_panel()
        self._build_preview_panel()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, columnspan=3, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            hdr, text="BOX", font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT,
        ).grid(row=0, column=0, padx=(16, 0), pady=0)

        ctk.CTkLabel(
            hdr, text="3D",  font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT2,
        ).grid(row=0, column=1, padx=(0, 6), pady=0)

        ctk.CTkLabel(
            hdr, text=f"v{_VERSION}",
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            text_color=_DIM,
        ).grid(row=0, column=2, padx=0, pady=0, sticky="w")

        self._status_label = ctk.CTkLabel(
            hdr, text="● READY",
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            text_color=_OK,
        )
        self._status_label.grid(row=0, column=3, padx=16, pady=0, sticky="e")

    # ── Left config panel ─────────────────────────────────────────────────────

    def _build_config_panel(self) -> None:
        self._cfg = ctk.CTkScrollableFrame(
            self, fg_color=_PANEL, corner_radius=0, width=340,
        )
        self._cfg.grid(row=1, column=0, sticky="nsew")
        self._cfg.grid_columnconfigure(0, weight=1)

        r = 0

        # ── Profile ──────────────────────────────────────────────────────────
        r = self._heading(self._cfg, "▸ PROFILE", r)

        self._profile_var = ctk.StringVar(value="Loading…")
        self._profile_combo = ctk.CTkComboBox(
            self._cfg,
            variable=self._profile_var,
            values=[],
            command=self._on_profile_change,
            state="readonly",
            fg_color=_BG, button_color=_BORDER, border_color=_BORDER,
            text_color=_TEXT, dropdown_fg_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=12),
        )
        self._profile_combo.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 4))
        r += 1

        self._profile_info_lbl = ctk.CTkLabel(
            self._cfg, text="",
            font=ctk.CTkFont(family=_FONT_MONO, size=10), text_color=_DIM,
        )
        self._profile_info_lbl.grid(row=r, column=0, sticky="w", padx=14, pady=(0, 8))
        r += 1

        # ── Paths ─────────────────────────────────────────────────────────────
        r = self._heading(self._cfg, "▸ PATHS", r)

        self._covers_var   = ctk.StringVar(value=str(_DATA / "inputs" / "covers"))
        self._output_var   = ctk.StringVar(value=str(_DATA / "output" / "converted"))
        self._marquees_var = ctk.StringVar(value="")

        r = self._path_field(self._cfg, "Covers directory *", self._covers_var, r)
        r = self._path_field(self._cfg, "Output directory *", self._output_var, r)
        r = self._path_field(self._cfg, "Marquees directory (optional)", self._marquees_var, r)

        # ── Options ───────────────────────────────────────────────────────────
        r = self._heading(self._cfg, "▸ OPTIONS", r)

        # Numeric row: Workers / Blur / Darken
        num_frame = ctk.CTkFrame(self._cfg, fg_color="transparent")
        num_frame.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 8))
        num_frame.grid_columnconfigure((0, 1, 2), weight=1)
        r += 1

        self._workers_var = ctk.StringVar(value="4")
        self._blur_var    = ctk.StringVar(value="20")
        self._darken_var  = ctk.StringVar(value="180")

        for col, (lbl, var) in enumerate([
            ("Workers", self._workers_var),
            ("Blur",    self._blur_var),
            ("Darken",  self._darken_var),
        ]):
            f = ctk.CTkFrame(num_frame, fg_color="transparent")
            f.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(
                f, text=lbl, font=ctk.CTkFont(size=10), text_color=_DIM,
            ).pack(anchor="w")
            ctk.CTkEntry(
                f, textvariable=var, width=72,
                fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
                font=ctk.CTkFont(family=_FONT_MONO, size=12),
            ).pack(fill="x")

        # Select row: Cover fit / Spine source / Format
        sel_frame = ctk.CTkFrame(self._cfg, fg_color="transparent")
        sel_frame.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 8))
        sel_frame.grid_columnconfigure((0, 1, 2), weight=1)
        r += 1

        self._cover_fit_var    = ctk.StringVar(value="stretch")
        self._spine_source_var = ctk.StringVar(value="auto")
        self._format_var       = ctk.StringVar(value="webp")

        for col, (lbl, var, vals) in enumerate([
            ("Cover fit",    self._cover_fit_var,
             ["stretch", "fit", "crop"]),
            ("Spine source", self._spine_source_var,
             ["auto", "left", "right", "center"]),
            ("Format",       self._format_var,
             ["webp", "png"]),
        ]):
            f = ctk.CTkFrame(sel_frame, fg_color="transparent")
            f.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(
                f, text=lbl, font=ctk.CTkFont(size=10), text_color=_DIM,
            ).pack(anchor="w")
            ctk.CTkComboBox(
                f, variable=var, values=vals, width=88,
                state="readonly",
                fg_color=_BG, button_color=_BORDER, border_color=_BORDER,
                text_color=_TEXT, dropdown_fg_color=_PANEL2,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
            ).pack(fill="x")

        # ── RGB Tint ──────────────────────────────────────────────────────────
        r = self._heading(self._cfg, "▸ RGB TINT  (1.00 = neutral, max 5.00)", r)

        self._rgb_r = ctk.DoubleVar(value=1.0)
        self._rgb_g = ctk.DoubleVar(value=1.0)
        self._rgb_b = ctk.DoubleVar(value=1.0)

        rgb_frame = ctk.CTkFrame(self._cfg, fg_color=_PANEL2, corner_radius=6)
        rgb_frame.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 4))
        rgb_frame.grid_columnconfigure(1, weight=1)
        r += 1

        self._rgb_value_labels: dict[str, ctk.CTkLabel] = {}

        for i, (ch, var, color) in enumerate([
            ("R", self._rgb_r, "#ff6b6b"),
            ("G", self._rgb_g, "#6bff8a"),
            ("B", self._rgb_b, "#6bb8ff"),
        ]):
            ctk.CTkLabel(
                rgb_frame, text=ch, width=18,
                font=ctk.CTkFont(family=_FONT_MONO, size=12, weight="bold"),
                text_color=color,
            ).grid(row=i, column=0, padx=(10, 4), pady=5, sticky="w")

            ctk.CTkSlider(
                rgb_frame, variable=var,
                from_=0.0, to=5.0, number_of_steps=100,
                button_color=_ACCENT, button_hover_color=_ACCENT2,
                progress_color=_ACCENT, fg_color=_BORDER,
                command=lambda _, c=ch: self._on_rgb_slide(c),
            ).grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=5)

            val_lbl = ctk.CTkLabel(
                rgb_frame, text="1.00", width=42,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
                text_color=_DIM,
            )
            val_lbl.grid(row=i, column=2, padx=(0, 10), pady=5)
            self._rgb_value_labels[ch] = val_lbl

        ctk.CTkButton(
            self._cfg, text="↺ Reset to neutral",
            height=26, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            command=self._reset_rgb,
        ).grid(row=r, column=0, sticky="w", padx=12, pady=(0, 10))
        r += 1

        # ── Flags ─────────────────────────────────────────────────────────────
        r = self._heading(self._cfg, "▸ FLAGS", r)

        self._skip_var    = ctk.BooleanVar(value=False)
        self._dry_var     = ctk.BooleanVar(value=False)
        self._no_logos_var = ctk.BooleanVar(value=False)

        flags_frame = ctk.CTkFrame(self._cfg, fg_color="transparent")
        flags_frame.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 12))
        r += 1

        for text, var in [
            ("Skip existing", self._skip_var),
            ("Dry run",       self._dry_var),
            ("No logos",      self._no_logos_var),
        ]:
            ctk.CTkCheckBox(
                flags_frame, text=text, variable=var,
                checkbox_width=16, checkbox_height=16,
                checkmark_color=_BG, fg_color=_ACCENT,
                hover_color=_ACCENT2, border_color=_BORDER,
                text_color=_TEXT, font=ctk.CTkFont(size=12),
            ).pack(anchor="w", pady=3)

        # ── Render button ─────────────────────────────────────────────────────
        self._btn_render = ctk.CTkButton(
            self._cfg, text="▶  START RENDER",
            height=44, corner_radius=6,
            fg_color="transparent", border_color=_ACCENT, border_width=1,
            text_color=_ACCENT, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=13, weight="bold"),
            command=self._start_render,
        )
        self._btn_render.grid(row=r, column=0, sticky="ew", padx=12, pady=(4, 16))

    # ── Centre progress panel ─────────────────────────────────────────────────

    def _build_progress_panel(self) -> None:
        self._centre = ctk.CTkFrame(self, fg_color=_BG, corner_radius=0)
        self._centre.grid(row=1, column=1, sticky="nsew")
        self._centre.grid_columnconfigure(0, weight=1)
        self._centre.grid_rowconfigure(2, weight=1)

        # Progress meta + bar
        meta_card = ctk.CTkFrame(self._centre, fg_color=_PANEL2, corner_radius=6)
        meta_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        meta_card.grid_columnconfigure(1, weight=1)

        self._prog_meta_lbl = ctk.CTkLabel(
            meta_card, text="0 / —  ·  0%",
            font=ctk.CTkFont(family=_FONT_MONO, size=12), text_color=_DIM,
        )
        self._prog_meta_lbl.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        self._elapsed_lbl = ctk.CTkLabel(
            meta_card, text="",
            font=ctk.CTkFont(family=_FONT_MONO, size=11), text_color=_DIM,
        )
        self._elapsed_lbl.grid(row=0, column=2, padx=12, pady=8, sticky="e")

        self._progress_bar = ctk.CTkProgressBar(
            self._centre,
            progress_color=_ACCENT, fg_color=_PANEL2,
            corner_radius=20, height=10,
        )
        self._progress_bar.set(0)
        self._progress_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        # Log textbox
        self._log_box = ctk.CTkTextbox(
            self._centre,
            fg_color=_PANEL2, text_color=_DIM,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            corner_radius=6, wrap="none", state="disabled",
        )
        self._log_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    # ── Right preview panel ───────────────────────────────────────────────────

    def _build_preview_panel(self) -> None:
        self._right = ctk.CTkScrollableFrame(
            self, fg_color=_PANEL, corner_radius=0, width=290,
        )
        self._right.grid(row=1, column=2, sticky="nsew")
        self._right.grid_columnconfigure(0, weight=1)

        r = 0

        # Active profile info
        r = self._heading(self._right, "▸ ACTIVE PROFILE", r)

        self._prev_name_lbl = ctk.CTkLabel(
            self._right, text="—",
            font=ctk.CTkFont(family=_FONT_MONO, size=15, weight="bold"),
            text_color=_ACCENT,
        )
        self._prev_name_lbl.grid(row=r, column=0, sticky="w", padx=12, pady=(0, 2))
        r += 1

        self._prev_dims_lbl = ctk.CTkLabel(
            self._right, text="",
            font=ctk.CTkFont(family=_FONT_MONO, size=10), text_color=_DIM,
        )
        self._prev_dims_lbl.grid(row=r, column=0, sticky="w", padx=12, pady=(0, 10))
        r += 1

        # Profile template thumbnail
        self._tmpl_img_lbl = ctk.CTkLabel(self._right, text="")
        self._tmpl_img_lbl.grid(row=r, column=0, padx=12, pady=(0, 12))
        r += 1

        # Live preview
        r = self._heading(self._right, "▸ LAST RENDER", r)

        self._prev_idle_lbl = ctk.CTkLabel(
            self._right,
            text="No image yet.\nStart a render to see\na preview here.",
            font=ctk.CTkFont(size=11), text_color=_DIM, justify="center",
        )
        self._prev_idle_lbl.grid(row=r, column=0, padx=12, pady=20)
        r += 1

        self._prev_img_lbl = ctk.CTkLabel(self._right, text="")
        self._prev_img_lbl.grid(row=r, column=0, padx=12, pady=(0, 4))
        self._prev_img_lbl.grid_remove()
        r += 1

        self._prev_stem_lbl = ctk.CTkLabel(
            self._right, text="",
            font=ctk.CTkFont(family=_FONT_MONO, size=9), text_color=_DIM,
        )
        self._prev_stem_lbl.grid(row=r, column=0, padx=12, pady=(0, 12))
        r += 1

        # Open output folder
        ctk.CTkButton(
            self._right, text="📂  Open Output Folder",
            height=30, corner_radius=6,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            command=self._open_output_folder,
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 12))

    # =========================================================================
    # Layout helpers
    # =========================================================================

    def _heading(self, parent: ctk.CTkBaseClass, text: str, row: int) -> int:
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(family=_FONT_MONO, size=9),
            text_color=_DIM,
        ).grid(row=row, column=0, sticky="w", padx=12, pady=(10, 4))
        return row + 1

    def _path_field(
        self, parent: ctk.CTkBaseClass, label: str, var: ctk.StringVar, row: int
    ) -> int:
        ctk.CTkLabel(
            parent, text=label, font=ctk.CTkFont(size=10), text_color=_DIM,
        ).grid(row=row, column=0, sticky="w", padx=14, pady=(0, 2))
        row += 1

        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkEntry(
            frame, textvariable=var,
            fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            frame, text="📂", width=32, height=28,
            fg_color=_PANEL2, hover_color=_PANEL,
            border_color=_BORDER, border_width=1,
            text_color=_TEXT, font=ctk.CTkFont(size=13),
            command=lambda v=var: self._browse_dir(v),
        ).grid(row=0, column=1)

        return row

    # =========================================================================
    # Profiles
    # =========================================================================

    def _load_profiles(self) -> None:
        try:
            registry = ProfileRegistry(str(_PROFILES)).load()
            names = registry.names()
            self._profiles_map = {n: registry.get(n) for n in names}

            self._profile_combo.configure(values=names)
            if names:
                self._profile_var.set(names[0])
                self._on_profile_change(names[0])
            else:
                self._profile_var.set("No profiles found")
        except Exception as exc:
            self._log(f"⚠  Could not load profiles: {exc}")
            self._profile_var.set("Error loading profiles")

    def _on_profile_change(self, name: str) -> None:
        p = self._profiles_map.get(name)
        dims = f"{p.geometry.template_w} × {p.geometry.template_h} px" if p else ""

        self._profile_info_lbl.configure(text=dims)
        self._prev_name_lbl.configure(text=name or "—")
        self._prev_dims_lbl.configure(text=dims)

        # Show template thumbnail in the preview panel
        if p:
            self._load_template_thumbnail(p.template_path)

    def _load_template_thumbnail(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((256, 160), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._tmpl_img_lbl.configure(image=ctk_img)
            self._tmpl_img_lbl._ctk_image = ctk_img   # keep ref alive
        except Exception:
            pass

    # =========================================================================
    # RGB tint helpers
    # =========================================================================

    def _on_rgb_slide(self, channel: str) -> None:
        val = {"R": self._rgb_r, "G": self._rgb_g, "B": self._rgb_b}[channel].get()
        self._rgb_value_labels[channel].configure(text=f"{val:.2f}")

    def _reset_rgb(self) -> None:
        for ch, var in [("R", self._rgb_r), ("G", self._rgb_g), ("B", self._rgb_b)]:
            var.set(1.0)
            self._rgb_value_labels[ch].configure(text="1.00")

    def _get_rgb_matrix(self) -> str | None:
        r, g, b = self._rgb_r.get(), self._rgb_g.get(), self._rgb_b.get()
        neutral = abs(r - 1.0) < 0.01 and abs(g - 1.0) < 0.01 and abs(b - 1.0) < 0.01
        if neutral:
            return None
        return f"{r:.4f} 0 0  0 {g:.4f} 0  0 0 {b:.4f}"

    # =========================================================================
    # Filesystem helpers
    # =========================================================================

    def _browse_dir(self, var: ctk.StringVar) -> None:
        current = var.get()
        initial = current if Path(current).is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(initialdir=initial)
        if chosen:
            var.set(chosen)

    def _open_output_folder(self) -> None:
        path = self._last_output_dir or Path(self._output_var.get())
        if not path.is_dir():
            messagebox.showinfo("Info", f"Directory not found:\n{path}")
            return
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(str(path))                     # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Error", f"Cannot open folder:\n{exc}")

    # =========================================================================
    # Log helpers
    # =========================================================================

    def _log(self, text: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    # =========================================================================
    # Render
    # =========================================================================

    def _start_render(self) -> None:
        if self._rendering:
            return

        # ── Validate inputs ───────────────────────────────────────────────────
        profile_name = self._profile_var.get()
        if profile_name not in self._profiles_map:
            messagebox.showerror("Error", f"Profile '{profile_name}' not found.\nReload the application.")
            return

        covers_dir = Path(self._covers_var.get().strip())
        output_dir = Path(self._output_var.get().strip())

        if not covers_dir.is_dir():
            messagebox.showerror("Error", f"Covers directory does not exist:\n{covers_dir}")
            return
        if not self._output_var.get().strip():
            messagebox.showerror("Error", "Output directory cannot be empty.")
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        # ── Build options ─────────────────────────────────────────────────────
        try:
            workers = int(self._workers_var.get() or 4)
            blur    = int(self._blur_var.get() or 20)
            darken  = int(self._darken_var.get() or 180)
        except ValueError:
            messagebox.showerror("Error", "Workers, blur, and darken must be integers.")
            return

        spine_raw = self._spine_source_var.get()
        spine_src = None if spine_raw in ("", "auto") else spine_raw   # type: ignore[assignment]

        options = RenderOptions(
            blur_radius   = blur,
            darken_alpha  = darken,
            rgb_matrix    = self._get_rgb_matrix(),
            cover_fit     = self._cover_fit_var.get() or None,          # type: ignore[assignment]
            spine_source  = spine_src,
            output_format = self._format_var.get(),                      # type: ignore[assignment]
            skip_existing = self._skip_var.get(),
            workers       = workers,
            dry_run       = self._dry_var.get(),
        )

        marquees_raw = self._marquees_var.get().strip()
        marquees_dir = Path(marquees_raw) if marquees_raw else None

        # ── Update UI state ───────────────────────────────────────────────────
        self._rendering       = True
        self._current_format  = self._format_var.get()
        self._last_output_dir = output_dir

        self._btn_render.configure(
            state="disabled", text="⏳  RENDERING…",
            border_color=_WARN, text_color=_WARN,
        )
        self._status_label.configure(text="● RENDERING", text_color=_WARN)
        self._progress_bar.set(0)
        self._prog_meta_lbl.configure(text="0 / —  ·  0%")
        self._elapsed_lbl.configure(text="")
        self._clear_log()

        profile = self._profiles_map[profile_name]

        self._log(f"▶  Profile: {profile_name}  |  Covers: {covers_dir}")
        self._log("─" * 52)

        # ── Launch background thread ──────────────────────────────────────────
        threading.Thread(
            target=self._run_pipeline,
            args=(profile, covers_dir, output_dir, options,
                  marquees_dir, self._no_logos_var.get()),
            daemon=True,
        ).start()

        self.after(100, self._poll_queue)

    # ── Pipeline thread ───────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        profile,
        covers_dir: Path,
        output_dir: Path,
        options: RenderOptions,
        marquees_dir: Path | None,
        no_logos: bool,
    ) -> None:
        from core.models import CoverResult

        first_stem: str | None = None

        def on_progress(done: int, total: int, result: CoverResult) -> None:
            nonlocal first_stem
            if result.status == "ok" and first_stem is None:
                first_stem = result.stem
            self._queue.put({
                "type":    "progress",
                "done":    done,
                "total":   total,
                "stem":    result.stem,
                "status":  result.status,
                "elapsed": round(result.elapsed, 3),
            })

        try:
            pipeline = RenderPipeline(
                profile      = profile,
                covers_dir   = covers_dir,
                output_dir   = output_dir,
                options      = options,
                logo_paths   = {"top": None, "bottom": None},
                marquees_dir = marquees_dir or (profile.root / "assets"),
                no_logos     = no_logos,
            )
            report = pipeline.run(on_progress=on_progress)
        except Exception as exc:
            self._queue.put({"type": "fatal", "message": str(exc)})
            return

        self._queue.put({
            "type":            "done",
            "total":           report.total,
            "succeeded":       report.succeeded,
            "skipped":         report.skipped,
            "failed":          report.failed,
            "dry":             report.dry,
            "elapsed_time":    round(report.elapsed_time, 2),
            "breaker_tripped": report.breaker_tripped,
            "errors":          report.errors,
            "first_stem":      first_stem,
        })

    # ── Queue polling (runs in main thread via after()) ───────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                self._handle_event(self._queue.get_nowait())
        except queue.Empty:
            pass

        if self._rendering:
            self.after(100, self._poll_queue)

    def _handle_event(self, event: dict) -> None:
        etype = event["type"]

        if etype == "progress":
            done  = event["done"]
            total = event["total"]
            pct   = int(done / total * 100) if total else 0

            icon = {"ok": "✔", "skip": "⊘", "dry": "◌"}.get(event["status"], "✘")
            t    = f"  ({event['elapsed']}s)" if event["elapsed"] > 0 else ""
            self._log(f"{icon}  {event['stem']}{t}")

            self._prog_meta_lbl.configure(text=f"{done} / {total}  ·  {pct}%")
            self._progress_bar.set(done / total if total else 0)

            if event["status"] == "ok":
                self._update_live_preview(event["stem"])

        elif etype == "done":
            self._rendering = False
            self._btn_render.configure(
                state="normal", text="▶  START RENDER",
                border_color=_ACCENT, text_color=_ACCENT,
            )
            ok = event["failed"] == 0 and not event["breaker_tripped"]
            self._status_label.configure(
                text="● DONE" if ok else "● DONE (ERRORS)",
                text_color=_OK if ok else _ERROR,
            )
            self._progress_bar.set(1.0)
            self._log("─" * 52)
            self._log(
                f"■  Done — {event['succeeded']} ok  ·  "
                f"{event['failed']} errors  ·  {event['elapsed_time']}s"
            )
            if event["breaker_tripped"]:
                self._log("⚡ Circuit breaker tripped — batch aborted.")
            self._show_summary(event)

        elif etype == "fatal":
            self._rendering = False
            self._btn_render.configure(
                state="normal", text="▶  START RENDER",
                border_color=_ACCENT, text_color=_ACCENT,
            )
            self._status_label.configure(text="● ERROR", text_color=_ERROR)
            self._log(f"✘  Fatal error: {event['message']}")

    # =========================================================================
    # Live preview
    # =========================================================================

    def _update_live_preview(self, stem: str) -> None:
        output_dir = self._last_output_dir
        if output_dir is None:
            return
        # Try the current format first, then fall back to other supported exts
        for ext in (self._current_format, "webp", "png"):
            path = output_dir / f"{stem}.{ext}"
            if path.is_file():
                self._show_preview_image(path, stem)
                return

    def _show_preview_image(self, path: Path, stem: str = "") -> None:
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((260, 260), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._prev_img_lbl.configure(image=ctk_img)
            self._preview_ctk_img = ctk_img   # prevent GC
            self._prev_idle_lbl.grid_remove()
            self._prev_img_lbl.grid()
            if stem:
                self._prev_stem_lbl.configure(text=stem)
        except Exception:
            pass

    # =========================================================================
    # Summary dialog
    # =========================================================================

    def _show_summary(self, data: dict) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title("Render Complete")
        dlg.geometry("440x340")
        dlg.configure(fg_color=_PANEL)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.focus_set()
        dlg.lift()

        ok = data["failed"] == 0 and not data["breaker_tripped"]

        ctk.CTkLabel(
            dlg,
            text="✔  Render Complete" if ok else "✘  Finished With Errors",
            font=ctk.CTkFont(family=_FONT_MONO, size=14, weight="bold"),
            text_color=_OK if ok else _ERROR,
        ).pack(pady=(20, 10))

        # Stats grid
        stats = ctk.CTkFrame(dlg, fg_color=_PANEL2, corner_radius=6)
        stats.pack(fill="x", padx=20, pady=(0, 10))
        stats.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        for col, (label, value, color) in enumerate([
            ("Total",   data["total"],      _TEXT),
            ("OK",      data["succeeded"],  _OK),
            ("Skip",    data["skipped"],    _DIM),
            ("Errors",  data["failed"],     _ERROR if data["failed"] else _DIM),
            ("Dry",     data["dry"],        _DIM),
        ]):
            cell = ctk.CTkFrame(stats, fg_color="transparent")
            cell.grid(row=0, column=col, padx=6, pady=10, sticky="ew")
            ctk.CTkLabel(
                cell, text=label, font=ctk.CTkFont(size=9), text_color=_DIM,
            ).pack()
            ctk.CTkLabel(
                cell, text=str(value),
                font=ctk.CTkFont(family=_FONT_MONO, size=22, weight="bold"),
                text_color=color,
            ).pack()

        ctk.CTkLabel(
            dlg, text=f"Elapsed: {data['elapsed_time']}s",
            font=ctk.CTkFont(family=_FONT_MONO, size=11), text_color=_WARN,
        ).pack(pady=(0, 8))

        # Errors list
        if data.get("errors"):
            err_box = ctk.CTkTextbox(
                dlg, height=70, fg_color=_BG,
                text_color=_ERROR, font=ctk.CTkFont(family=_FONT_MONO, size=10),
            )
            err_box.pack(fill="x", padx=20, pady=(0, 10))
            for e in data["errors"]:
                err_box.insert("end", f"✘  {e}\n")
            err_box.configure(state="disabled")

        # Action row
        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row, text="📂  Open Output",
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=self._open_output_folder,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            btn_row, text="Close",
            fg_color=_ACCENT, text_color=_BG,
            hover_color=_ACCENT2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11, weight="bold"),
            command=dlg.destroy,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
