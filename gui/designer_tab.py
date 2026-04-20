"""
gui/designer_tab.py — Box3D Designer Pro tab
=============================================
Visual profile geometry designer: template loading, quad-corner placement,
spine-slot configuration, profile import/export, and live JSON preview.
"""
from __future__ import annotations

import json
import re
import shutil
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
import customtkinter as ctk
from PIL import Image, ImageFilter

from .constants import (
    _BG, _PANEL, _PANEL2, _BORDER,
    _ACCENT, _ACCENT2, _ERROR, _TEXT, _DIM,
    _FONT_MONO, _DSN_SWATCH,
)
from .designer_engine import DesignerEngine


class DesignerTab:
    """Designer Pro tab — builds its UI inside the given *parent* frame."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_install_cb: Callable[[str], None] | None = None,
    ) -> None:
        self._parent       = parent
        self._engine: DesignerEngine | None = None
        self._cur_obj: dict | None          = None
        self._updating_ui  = False
        self._template_path: Path | None    = None
        self._on_install   = on_install_cb or (lambda name: None)
        self._canvas_bg_var: ctk.StringVar  = ctk.StringVar(value=_PANEL2)

        # 3-column layout: left | canvas | right
        parent.grid_columnconfigure(0, weight=0, minsize=235)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(2, weight=0, minsize=265)
        parent.grid_rowconfigure(0, weight=1)

        self._build_left_panel(parent)
        self._build_canvas(parent)
        self._build_right_panel(parent)
        parent.after(200, self._restore_config)

    # =========================================================================
    # Left panel
    # =========================================================================

    def _build_left_panel(self, parent: ctk.CTkFrame) -> None:
        left = ctk.CTkScrollableFrame(
            parent, fg_color=_PANEL, corner_radius=0, width=235,
        )
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        r = 0

        # ── Template ─────────────────────────────────────────────────────────
        r = self._heading(left, "▸ TEMPLATE", r)
        ctk.CTkButton(
            left, text="◈ Load Template Image",
            height=30, corner_radius=6,
            fg_color="transparent", border_color=_ACCENT, border_width=1,
            text_color=_ACCENT, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=self._load_template,
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 4))
        r += 1

        self._tpl_info_lbl = ctk.CTkLabel(
            left, text="No template loaded.",
            font=ctk.CTkFont(family=_FONT_MONO, size=9), text_color=_DIM,
        )
        self._tpl_info_lbl.grid(row=r, column=0, sticky="w", padx=14, pady=(0, 4))
        r += 1

        ctk.CTkButton(
            left, text="✦ Fix Template Alpha",
            height=26, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            command=self._fix_template_alpha,
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 8))
        r += 1

        # ── Objects ───────────────────────────────────────────────────────────
        r = self._heading(left, "▸ OBJECTS", r)

        for obj_type in ("spine", "cover", "logo", "marquee"):
            color = _DSN_SWATCH.get(obj_type, _TEXT)
            ctk.CTkButton(
                left, text=f"＋ {obj_type.capitalize()}",
                height=28, corner_radius=4,
                fg_color="transparent", border_color=color, border_width=1,
                text_color=color, hover_color=_PANEL2,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
                command=lambda t=obj_type: self._add_object(t),
            ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 3))
            r += 1

        ctk.CTkButton(
            left, text="✕ Remove Selected",
            height=28, corner_radius=4,
            fg_color="transparent", border_color=_ERROR, border_width=1,
            text_color=_ERROR, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=lambda: self._engine and self._engine.remove_selected(),
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 8))
        r += 1

        self._obj_list_lbl = ctk.CTkLabel(
            left, text="—",
            font=ctk.CTkFont(family=_FONT_MONO, size=10), text_color=_DIM,
            justify="left", anchor="w",
        )
        self._obj_list_lbl.grid(row=r, column=0, sticky="ew", padx=14, pady=(0, 10))
        r += 1

        # ── Profile I/O ───────────────────────────────────────────────────────
        r = self._heading(left, "▸ PROFILE I/O", r)

        for lbl_text, var_name in [("Name", "_name_var"), ("Description", "_desc_var")]:
            ctk.CTkLabel(
                left, text=lbl_text, font=ctk.CTkFont(size=10), text_color=_DIM,
            ).grid(row=r, column=0, sticky="w", padx=14)
            r += 1
            var = ctk.StringVar(value=("my_profile" if var_name == "_name_var" else ""))
            setattr(self, var_name, var)
            ctk.CTkEntry(
                left, textvariable=var,
                fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
            ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 6))
            r += 1

        io_btns = ctk.CTkFrame(left, fg_color="transparent")
        io_btns.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 10))
        io_btns.grid_columnconfigure((0, 1), weight=1)
        r += 1

        ctk.CTkButton(
            io_btns, text="⬇ Import",
            height=28, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=self._import_profile,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))

        ctk.CTkButton(
            io_btns, text="⬆ Export",
            height=28, corner_radius=4,
            fg_color="transparent", border_color=_ACCENT, border_width=1,
            text_color=_ACCENT, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=self._export_profile,
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        ctk.CTkButton(
            io_btns, text="▶ Usar no Control",
            height=30, corner_radius=4,
            fg_color="transparent", border_color=_ACCENT2, border_width=1,
            text_color=_ACCENT2, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=self._install_profile,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # ── Render settings ───────────────────────────────────────────────────
        r = self._heading(left, "▸ RENDER SETTINGS", r)

        for lbl, attr, choices, dflt in [
            ("Spine source", "_spine_src_var",  ["left", "right", "center"], "left"),
            ("Cover fit",    "_cover_fit_var",  ["stretch", "fit", "crop"],  "stretch"),
        ]:
            ctk.CTkLabel(left, text=lbl, font=ctk.CTkFont(size=10), text_color=_DIM,
                         ).grid(row=r, column=0, sticky="w", padx=14)
            r += 1
            var = ctk.StringVar(value=dflt)
            setattr(self, attr, var)
            ctk.CTkComboBox(
                left, variable=var, values=choices, state="readonly",
                fg_color=_BG, button_color=_BORDER, border_color=_BORDER,
                text_color=_TEXT, dropdown_fg_color=_PANEL2,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
            ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 6))
            r += 1

        ctk.CTkLabel(
            left, text="Spine frac (0.0–1.0)",
            font=ctk.CTkFont(size=10), text_color=_DIM,
        ).grid(row=r, column=0, sticky="w", padx=14)
        r += 1
        self._spine_frac_var = ctk.StringVar(value="0.20")
        ctk.CTkEntry(
            left, textvariable=self._spine_frac_var,
            fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 10))
        r += 1

        # ── Grid & Snap ───────────────────────────────────────────────────────
        r = self._heading(left, "▸ GRID & SNAP", r)

        self._show_grid_var = ctk.BooleanVar(value=True)
        self._snap_var      = ctk.BooleanVar(value=True)

        for text, var, cmd in [
            ("Show grid",    self._show_grid_var, self._toggle_grid),
            ("Snap to grid", self._snap_var,      self._toggle_snap),
        ]:
            ctk.CTkCheckBox(
                left, text=text, variable=var,
                checkbox_width=16, checkbox_height=16,
                checkmark_color=_BG, fg_color=_ACCENT,
                hover_color=_ACCENT2, border_color=_BORDER,
                text_color=_TEXT, font=ctk.CTkFont(size=11),
                command=cmd,
            ).grid(row=r, column=0, sticky="w", padx=14, pady=(0, 4))
            r += 1

        gs_row = ctk.CTkFrame(left, fg_color="transparent")
        gs_row.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 10))
        gs_row.grid_columnconfigure(1, weight=1)
        r += 1
        ctk.CTkLabel(gs_row, text="Grid size:",
                     font=ctk.CTkFont(size=10), text_color=_DIM,
                     ).grid(row=0, column=0, padx=(0, 6))
        self._grid_size_var = ctk.StringVar(value="10")
        ctk.CTkEntry(
            gs_row, textvariable=self._grid_size_var, width=60,
            fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
        ).grid(row=0, column=1, sticky="w")
        self._grid_size_var.trace_add("write", self._apply_grid_size)

        # ── Canvas background color ───────────────────────────────────────────
        r = self._heading(left, "▸ CANVAS BG", r)

        bg_row = ctk.CTkFrame(left, fg_color="transparent")
        bg_row.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 12))
        bg_row.grid_columnconfigure(1, weight=1)
        r += 1

        self._bg_swatch = ctk.CTkButton(
            bg_row, text="", width=28, height=28, corner_radius=4,
            fg_color=_PANEL2, hover_color=_PANEL2,
            command=self._pick_canvas_bg,
        )
        self._bg_swatch.grid(row=0, column=0, padx=(0, 8))

        ctk.CTkLabel(
            bg_row, text="Background",
            font=ctk.CTkFont(size=10), text_color=_DIM,
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkButton(
            bg_row, text="◉ Pick",
            height=28, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            command=self._pick_canvas_bg,
        ).grid(row=0, column=2, padx=(8, 0))

        # ── Zoom ──────────────────────────────────────────────────────────────
        r = self._heading(left, "▸ ZOOM", r)

        ctk.CTkButton(
            left, text="⊡ Fit to Screen",
            height=28, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=lambda: self._engine and self._engine.fit_to_screen(),
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 4))
        r += 1

        zoom_row = ctk.CTkFrame(left, fg_color="transparent")
        zoom_row.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 12))
        zoom_row.grid_columnconfigure((0, 1, 2), weight=1)

        for col, (lbl, z) in enumerate([("50%", 0.5), ("100%", 1.0), ("200%", 2.0)]):
            ctk.CTkButton(
                zoom_row, text=lbl, height=26, corner_radius=4,
                fg_color="transparent", border_color=_BORDER, border_width=1,
                text_color=_DIM, hover_color=_PANEL2,
                font=ctk.CTkFont(family=_FONT_MONO, size=10),
                command=lambda z=z: self._set_zoom(z),
            ).grid(row=0, column=col, padx=2, sticky="ew")

    # =========================================================================
    # Canvas
    # =========================================================================

    def _build_canvas(self, parent: ctk.CTkFrame) -> None:
        cframe = ctk.CTkFrame(parent, fg_color=_PANEL2, corner_radius=0)
        cframe.grid(row=0, column=1, sticky="nsew")
        cframe.grid_columnconfigure(0, weight=1)
        cframe.grid_rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            cframe, bg=self._canvas_bg_var.get(),
            highlightthickness=0, bd=0, cursor="crosshair",
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._engine = DesignerEngine(
            self._canvas,
            on_change_cb=self._on_change,
            on_select_cb=self._on_select,
        )
        parent.after(150, self._engine.fit_to_screen)

    # =========================================================================
    # Right panel
    # =========================================================================

    def _build_right_panel(self, parent: ctk.CTkFrame) -> None:
        right = ctk.CTkScrollableFrame(
            parent, fg_color=_PANEL, corner_radius=0, width=265,
        )
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        r = 0

        # ── Selection label ───────────────────────────────────────────────────
        r = self._heading(right, "▸ SELECTION", r)
        self._sel_lbl = ctk.CTkLabel(
            right, text="Click an object to select it.",
            font=ctk.CTkFont(family=_FONT_MONO, size=10), text_color=_DIM,
            justify="left", anchor="w",
        )
        self._sel_lbl.grid(row=r, column=0, sticky="ew", padx=14, pady=(0, 8))
        r += 1

        # ── Properties (X / Y / W / H) ────────────────────────────────────────
        self._props_frame = ctk.CTkFrame(right, fg_color="transparent")
        self._props_frame.grid(row=r, column=0, sticky="ew")
        self._props_frame.grid_remove()
        self._props_frame.grid_columnconfigure((0, 1), weight=1)
        r += 1

        self._prop_vars: dict[str, ctk.StringVar] = {}
        for i, (label, key) in enumerate([("X", "x"), ("Y", "y"), ("W", "w"), ("H", "h")]):
            ri, ci = divmod(i, 2)
            px = (12, 4) if ci == 0 else (4, 12)
            f = ctk.CTkFrame(self._props_frame, fg_color="transparent")
            f.grid(row=ri, column=ci, sticky="ew", padx=px, pady=(0, 6))
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=10), text_color=_DIM).pack(anchor="w")
            var = ctk.StringVar(value="0")
            self._prop_vars[key] = var
            ctk.CTkEntry(
                f, textvariable=var,
                fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
                font=ctk.CTkFont(family=_FONT_MONO, size=12),
            ).pack(fill="x")
            var.trace_add("write", lambda *_, k=key: self._on_prop_change(k))

        # ── Quad corners ──────────────────────────────────────────────────────
        self._quad_section = ctk.CTkFrame(right, fg_color="transparent")
        self._quad_section.grid(row=r, column=0, sticky="ew")
        self._quad_section.grid_remove()
        self._quad_section.grid_columnconfigure((0, 1), weight=1)
        r += 1

        ctk.CTkLabel(
            self._quad_section, text="▸ QUAD CORNERS",
            font=ctk.CTkFont(family=_FONT_MONO, size=9), text_color=_DIM,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))

        self._quad_vars: dict[str, dict[str, ctk.StringVar]] = {
            c: {} for c in ("tl", "tr", "bl", "br")
        }
        for corner, row_i, col_i in [("tl", 0, 0), ("tr", 0, 1), ("bl", 1, 0), ("br", 1, 1)]:
            px = (12, 4) if col_i == 0 else (4, 12)
            f = ctk.CTkFrame(self._quad_section, fg_color=_PANEL2, corner_radius=4)
            f.grid(row=1 + row_i, column=col_i, sticky="ew", padx=px, pady=(0, 4))
            ctk.CTkLabel(
                f, text=corner.upper(),
                font=ctk.CTkFont(family=_FONT_MONO, size=9, weight="bold"), text_color=_DIM,
            ).pack(anchor="w", padx=6, pady=(4, 0))
            xy = ctk.CTkFrame(f, fg_color="transparent")
            xy.pack(fill="x", padx=4, pady=(0, 4))
            xy.grid_columnconfigure((0, 1), weight=1)
            for ci, axis in enumerate(("x", "y")):
                ctk.CTkLabel(xy, text=axis, font=ctk.CTkFont(size=9), text_color=_DIM,
                             ).grid(row=0, column=ci, padx=2)
                var = ctk.StringVar(value="0")
                self._quad_vars[corner][axis] = var
                ctk.CTkEntry(
                    xy, textvariable=var, width=46,
                    fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
                    font=ctk.CTkFont(family=_FONT_MONO, size=11),
                ).grid(row=1, column=ci, padx=2, sticky="ew")
                var.trace_add("write", lambda *_, c=corner, a=axis: self._on_quad_change(c, a))

        # ── Spine layout slots ────────────────────────────────────────────────
        self._slots_section = ctk.CTkFrame(right, fg_color="transparent")
        self._slots_section.grid(row=r, column=0, sticky="ew")
        self._slots_section.grid_remove()
        self._slots_section.grid_columnconfigure(0, weight=1)
        r += 1

        ctk.CTkLabel(
            self._slots_section, text="▸ SPINE LAYOUT",
            font=ctk.CTkFont(family=_FONT_MONO, size=9), text_color=_DIM,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self._slot_vars: dict[str, dict[str, ctk.StringVar]] = {
            s: {} for s in ("game", "top", "bottom")
        }
        self._logo_alpha_var = ctk.StringVar(value="0.85")

        defaults = {"game": ("80","320","500","-90"), "top": ("80","120","160","-90"), "bottom": ("80","80","840","-90")}
        for si, slot in enumerate(("game", "top", "bottom")):
            ctk.CTkLabel(
                self._slots_section, text=f"  {slot.upper()}",
                font=ctk.CTkFont(family=_FONT_MONO, size=10, weight="bold"), text_color=_DIM,
            ).grid(row=1 + si * 2, column=0, sticky="w", padx=14)
            inner = ctk.CTkFrame(self._slots_section, fg_color=_PANEL2, corner_radius=4)
            inner.grid(row=2 + si * 2, column=0, sticky="ew", padx=12, pady=(0, 8))
            inner.grid_columnconfigure((0, 1, 2, 3), weight=1)
            dw, dh, dy, dr = defaults[slot]
            for ci, (flbl, fkey, dflt) in enumerate([
                ("max_w", "max_w", dw), ("max_h", "max_h", dh),
                ("ctr_y", "center_y", dy), ("rot",  "rotate", dr),
            ]):
                cf = ctk.CTkFrame(inner, fg_color="transparent")
                cf.grid(row=0, column=ci, padx=4, pady=6, sticky="ew")
                ctk.CTkLabel(cf, text=flbl, font=ctk.CTkFont(size=8), text_color=_DIM).pack(anchor="w")
                var = ctk.StringVar(value=dflt)
                self._slot_vars[slot][fkey] = var
                ctk.CTkEntry(
                    cf, textvariable=var,
                    fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
                    font=ctk.CTkFont(family=_FONT_MONO, size=10),
                ).pack(fill="x")

        alpha_row = ctk.CTkFrame(self._slots_section, fg_color="transparent")
        alpha_row.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 10))
        alpha_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            alpha_row, text="Logo alpha:",
            font=ctk.CTkFont(size=10), text_color=_DIM,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkEntry(
            alpha_row, textvariable=self._logo_alpha_var, width=60,
            fg_color=_BG, border_color=_BORDER, text_color=_TEXT,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
        ).grid(row=0, column=1, sticky="w")

        # ── JSON preview ──────────────────────────────────────────────────────
        r = self._heading(right, "▸ JSON PREVIEW", r)

        ctk.CTkButton(
            right, text="↻ Refresh JSON",
            height=26, corner_radius=4,
            fg_color="transparent", border_color=_BORDER, border_width=1,
            text_color=_DIM, hover_color=_PANEL2,
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            command=self._update_json_preview,
        ).grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 6))
        r += 1

        self._json_box = ctk.CTkTextbox(
            right, height=220,
            fg_color=_PANEL2, text_color=_DIM,
            font=ctk.CTkFont(family=_FONT_MONO, size=9),
            corner_radius=4, wrap="none", state="disabled",
        )
        self._json_box.grid(row=r, column=0, sticky="ew", padx=12, pady=(0, 12))

    # =========================================================================
    # Layout helper
    # =========================================================================

    def _heading(self, parent: ctk.CTkBaseClass, text: str, row: int) -> int:
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(family=_FONT_MONO, size=9), text_color=_DIM,
        ).grid(row=row, column=0, sticky="w", padx=12, pady=(10, 4))
        return row + 1

    # =========================================================================
    # Engine callbacks
    # =========================================================================

    def _on_select(self, obj: dict | None) -> None:
        self._cur_obj = obj
        if obj is None:
            self._sel_lbl.configure(text="Click an object to select it.")
            self._props_frame.grid_remove()
            self._quad_section.grid_remove()
            self._slots_section.grid_remove()
        else:
            self._sel_lbl.configure(text=f"Selected: {obj['type'].upper()}")
            self._props_frame.grid()
            self._refresh_props(obj)
            if obj["type"] in ("spine", "cover"):
                self._quad_section.grid()
                self._refresh_quad(obj)
            else:
                self._quad_section.grid_remove()
            if obj["type"] == "spine":
                self._slots_section.grid()
            else:
                self._slots_section.grid_remove()
        self._update_obj_list()

    def _on_change(self, obj: dict) -> None:
        if obj is self._cur_obj:
            self._refresh_props(obj)
            if obj.get("quad"):
                self._refresh_quad(obj)

    # =========================================================================
    # UI ↔ engine sync
    # =========================================================================

    def _refresh_props(self, obj: dict) -> None:
        self._updating_ui = True
        try:
            for k in ("x", "y", "w", "h"):
                self._prop_vars[k].set(str(round(obj.get(k, 0))))
        finally:
            self._updating_ui = False

    def _refresh_quad(self, obj: dict) -> None:
        q = obj.get("quad")
        if not q:
            return
        self._updating_ui = True
        try:
            for corner, axes in self._quad_vars.items():
                pt = q.get(corner, [0, 0])
                axes["x"].set(str(round(pt[0])))
                axes["y"].set(str(round(pt[1])))
        finally:
            self._updating_ui = False

    def _on_prop_change(self, key: str) -> None:
        if self._updating_ui or not self._cur_obj or not self._engine:
            return
        try:
            val = float(self._prop_vars[key].get())
        except ValueError:
            return
        self._cur_obj[key] = val
        self._engine.redraw()

    def _on_quad_change(self, corner: str, axis: str) -> None:
        if self._updating_ui or not self._cur_obj or not self._engine:
            return
        q = self._cur_obj.get("quad")
        if not q:
            return
        try:
            val = float(self._quad_vars[corner][axis].get())
        except ValueError:
            return
        q[corner][0 if axis == "x" else 1] = val
        self._engine._update_bbox(self._cur_obj)
        self._engine.redraw()

    def _update_obj_list(self) -> None:
        if not self._engine or not self._engine.objects:
            self._obj_list_lbl.configure(text="—")
            return
        lines = []
        for obj in self._engine.objects:
            marker = "▶" if obj is self._cur_obj else "  "
            lines.append(f"{marker} {obj['type']}")
        self._obj_list_lbl.configure(text="\n".join(lines))

    # =========================================================================
    # Left panel actions
    # =========================================================================

    def _add_object(self, obj_type: str) -> None:
        if not self._engine:
            return
        if self._engine.add_object(obj_type) is None:
            messagebox.showwarning(
                "Already exists",
                f"A '{obj_type}' object already exists.\nRemove it first.",
            )
        self._update_obj_list()

    def _load_template(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Template Image",
            filetypes=[("Image files", "*.png *.webp *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
            self._template_path = Path(path)
            if self._engine:
                self._engine.set_template(img)
                self._engine.fit_to_screen()
            self._tpl_info_lbl.configure(text=f"{Path(path).name}  ({img.width}×{img.height})")
        except Exception as exc:
            messagebox.showerror("Error", f"Cannot load image:\n{exc}")

    def _fix_template_alpha(self) -> None:
        """Anti-alias the loaded template's alpha channel in-place via PIL."""
        if not self._template_path or not self._template_path.is_file():
            messagebox.showwarning("Fix Alpha", "Load a template image first.")
            return
        if self._template_path.suffix.lower() != ".png":
            messagebox.showwarning("Fix Alpha", "Only PNG templates can be fixed in-place.")
            return
        try:
            img = Image.open(self._template_path).convert("RGBA")
            r, g, b, a = img.split()
            a_arr    = np.array(a, dtype=np.float32)
            a_binary = (a_arr > 128).astype(np.float32) * 255.0
            a_clean  = Image.fromarray(a_binary.astype(np.uint8), "L")
            a_smooth = a_clean.filter(ImageFilter.GaussianBlur(radius=1.5))
            fixed    = Image.merge("RGBA", (r, g, b, a_smooth))
            fixed.save(str(self._template_path), "PNG", optimize=False)
            if self._engine:
                self._engine.set_template(fixed)
            self._tpl_info_lbl.configure(
                text=f"{self._template_path.name}  ({fixed.width}×{fixed.height})  ✦ alpha fixed"
            )
            messagebox.showinfo("Fix Alpha", "Alpha channel anti-aliased and saved.")
        except Exception as exc:
            messagebox.showerror("Fix Alpha", f"Failed:\n{exc}")

    def _toggle_grid(self) -> None:
        if self._engine:
            self._engine.show_grid = self._show_grid_var.get()
            self._engine.redraw()

    def _toggle_snap(self) -> None:
        if self._engine:
            self._engine.snap_to_grid = self._snap_var.get()

    def _apply_grid_size(self, *_) -> None:
        if not self._engine:
            return
        try:
            self._engine.grid_size = max(1, int(self._grid_size_var.get()))
            self._engine.redraw()
        except ValueError:
            pass

    def _set_zoom(self, z: float) -> None:
        if self._engine:
            cw = self._canvas.winfo_width() / 2
            ch = self._canvas.winfo_height() / 2
            self._engine.set_zoom(z, cw, ch)

    # =========================================================================
    # Profile I/O
    # =========================================================================

    def _import_profile(self) -> None:
        path = filedialog.askopenfilename(
            title="Import Profile JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if self._engine:
                self._engine.import_profile(data)
            self._name_var.set(data.get("name", Path(path).stem))
            self._desc_var.set(data.get("description", ""))
            self._spine_src_var.set(data.get("spine_source", "left"))
            self._cover_fit_var.set(data.get("cover_fit", "stretch"))
            self._spine_frac_var.set(str(data.get("spine_source_frac", 0.20)))
            sl = data.get("spine_layout", {})
            self._logo_alpha_var.set(str(sl.get("logo_alpha", 0.85)))
            dh_map = {"game": "320", "top": "120", "bottom": "80"}
            dy_map = {"game": "500", "top": "160", "bottom": "840"}
            for slot in ("game", "top", "bottom"):
                s  = sl.get(slot, {})
                sv = self._slot_vars[slot]
                sv["max_w"].set(str(s.get("max_w", 80)))
                sv["max_h"].set(str(s.get("max_h", int(dh_map[slot]))))
                sv["center_y"].set(str(s.get("center_y", int(dy_map[slot]))))
                sv["rotate"].set(str(s.get("rotate", -90)))
            self._update_obj_list()
            self._update_json_preview()
        except Exception as exc:
            messagebox.showerror("Import Error", f"Cannot load profile:\n{exc}")

    def _export_profile(self) -> None:
        if not self._engine:
            return
        try:
            extras = self._gather_extras()
            data   = self._engine.build_profile(
                self._name_var.get().strip() or "profile", extras,
            )
        except ValueError as exc:
            messagebox.showerror("Export Error", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Export Error", f"Cannot build profile:\n{exc}")
            return

        path = filedialog.asksaveasfilename(
            title="Export Profile JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"{data['name']}.json",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            messagebox.showinfo("Exported", f"Profile saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", f"Cannot write file:\n{exc}")

    def _gather_extras(self) -> dict:
        def _flt(var: ctk.StringVar, d: float) -> float:
            try:
                return float(var.get())
            except ValueError:
                return d

        def _int(var: ctk.StringVar, d: int) -> int:
            try:
                return int(var.get())
            except ValueError:
                return d

        sl: dict = {}
        for slot in ("game", "top", "bottom"):
            sv = self._slot_vars[slot]
            sl[slot] = {
                "max_w":    _int(sv["max_w"],    80),
                "max_h":    _int(sv["max_h"],    320),
                "center_y": _int(sv["center_y"], 500),
                "rotate":   _int(sv["rotate"],   -90),
            }
        sl["logo_alpha"] = _flt(self._logo_alpha_var, 0.85)

        return {
            "tw":                self._engine.template_w if self._engine else 703,
            "th":                self._engine.template_h if self._engine else 1000,
            "spine_source":      self._spine_src_var.get(),
            "cover_fit":         self._cover_fit_var.get(),
            "spine_source_frac": _flt(self._spine_frac_var, 0.20),
            "spine_layout":      sl,
            "description":       self._desc_var.get().strip(),
        }

    # =========================================================================
    # Canvas background color
    # =========================================================================

    def _pick_canvas_bg(self) -> None:
        from tkinter import colorchooser
        result = colorchooser.askcolor(
            color=self._canvas_bg_var.get(),
            title="Canvas Background Color",
        )
        if result and result[1]:
            self._apply_canvas_bg(result[1])

    def _apply_canvas_bg(self, color: str) -> None:
        try:
            self._canvas_bg_var.set(color)
            self._canvas.configure(bg=color)
            if self._engine:
                self._engine.redraw()
            if hasattr(self, "_bg_swatch"):
                self._bg_swatch.configure(fg_color=color, hover_color=color)
        except Exception:
            pass

    # =========================================================================
    # Config persistence (issue #27 — Designer side)
    # =========================================================================

    def _restore_config(self) -> None:
        from gui.config import load_config
        cfg = load_config()
        if not cfg:
            return
        if color := cfg.get("dsn_canvas_bg"):
            self._apply_canvas_bg(color)
        for key, var in [
            ("dsn_spine_source", self._spine_src_var),
            ("dsn_cover_fit",    self._cover_fit_var),
            ("dsn_spine_frac",   self._spine_frac_var),
            ("dsn_grid_size",    self._grid_size_var),
            ("dsn_name",         self._name_var),
            ("dsn_desc",         self._desc_var),
        ]:
            if (v := cfg.get(key)) is not None:
                var.set(str(v))
        if (v := cfg.get("dsn_show_grid")) is not None:
            self._show_grid_var.set(bool(v))
            self._toggle_grid()
        if (v := cfg.get("dsn_snap")) is not None:
            self._snap_var.set(bool(v))
            self._toggle_snap()

    def save_config(self) -> None:
        """Merge Designer settings into the shared config file."""
        from gui.config import load_config, save_config as _write
        cfg = load_config()
        cfg.update({
            "dsn_canvas_bg":    self._canvas_bg_var.get(),
            "dsn_spine_source": self._spine_src_var.get(),
            "dsn_cover_fit":    self._cover_fit_var.get(),
            "dsn_spine_frac":   self._spine_frac_var.get(),
            "dsn_show_grid":    self._show_grid_var.get(),
            "dsn_snap":         self._snap_var.get(),
            "dsn_grid_size":    self._grid_size_var.get(),
            "dsn_name":         self._name_var.get(),
            "dsn_desc":         self._desc_var.get(),
        })
        _write(cfg)

    # =========================================================================
    # Profile install (issue #33)
    # =========================================================================

    def _install_profile(self) -> None:
        """Install the current profile into profiles/ and reload the Control tab."""
        from cli.bootstrap import _PROFILES

        if not self._engine:
            return

        name = self._name_var.get().strip() or "profile"
        if not re.match(r"^[a-zA-Z0-9_-]+$", name):
            messagebox.showerror(
                "Nome inválido",
                f"O nome '{name}' é inválido.\n"
                "Use apenas letras, números, underscores e hífens.",
            )
            return

        types = {o["type"] for o in self._engine.objects}
        if "spine" not in types or "cover" not in types:
            messagebox.showerror(
                "Profile incompleto",
                "O profile precisa ter pelo menos um objeto spine e um cover.",
            )
            return

        try:
            extras = self._gather_extras()
            data   = self._engine.build_profile(name, extras)
        except Exception as exc:
            messagebox.showerror("Erro ao gerar profile", str(exc))
            return

        profile_dir = _PROFILES / name
        if profile_dir.exists():
            if not messagebox.askyesno(
                "Sobrescrever?",
                f"O profile '{name}' já existe.\nDeseja sobrescrever?",
            ):
                return

        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "profile.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
            )
        except Exception as exc:
            messagebox.showerror("Erro ao instalar", f"Não foi possível salvar o profile:\n{exc}")
            return

        if self._template_path and self._template_path.is_file():
            try:
                shutil.copy2(self._template_path, profile_dir / "template.png")
            except Exception as exc:
                messagebox.showwarning("Aviso", f"Não foi possível copiar o template:\n{exc}")
        else:
            messagebox.showwarning(
                "Sem template",
                f"Profile instalado sem template.png.\n"
                f"Copie um template.png para profiles/{name}/ antes de renderizar.",
            )

        self._on_install(name)

    def _update_json_preview(self) -> None:
        if not self._engine:
            return
        try:
            data = self._engine.build_profile(
                self._name_var.get().strip() or "profile", self._gather_extras(),
            )
            text = json.dumps(data, indent=2, ensure_ascii=False)
        except ValueError as exc:
            text = f"# {exc}"
        except Exception as exc:
            text = f"# Error: {exc}"

        self._json_box.configure(state="normal")
        self._json_box.delete("1.0", "end")
        self._json_box.insert("1.0", text)
        self._json_box.configure(state="disabled")
