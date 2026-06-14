"""
gui/app.py — Box3D Desktop GUI entry point
===========================================
Thin shell: window chrome, header (with inline tab nav + font scale controls),
and two content frames.

    Control  → gui/control_tab.py  (ControlTab)
    Designer → gui/designer_tab.py (DesignerTab)

Run directly::

    python -m gui.app

Or via the installed entrypoint::

    box3d-gui
"""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

# ── Path bootstrap (works from both installed package and `python -m`) ────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cli.bootstrap import (                                 # noqa: E402
    _bootstrap_data_dir, _bootstrap_instructions,
)
from gui.config import load_config, save_config             # noqa: E402
from gui.constants import (                                 # noqa: E402
    _VERSION, _BG, _PANEL, _PANEL2, _ACCENT, _ACCENT2, _OK, _DIM,
)
from gui import fonts                                       # noqa: E402
from gui.fonts import F                                     # noqa: E402
from gui.control_tab  import ControlTab                     # noqa: E402
from gui.designer_tab import DesignerTab                    # noqa: E402

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    """Main application window — header with inline tab switcher, no CTkTabview."""

    def __init__(self) -> None:
        super().__init__()

        self.title(f"BOX3D v{_VERSION} — Desktop")
        self.geometry("1360x820")
        self.minsize(980, 640)
        self.configure(fg_color=_BG)

        self.grid_rowconfigure(0, weight=0)   # header
        self.grid_rowconfigure(1, weight=1)   # content
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_content()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    # Header — BOX3D title + version + inline tab nav + font scale + status
    # =========================================================================

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_rowconfigure(0, weight=1)
        # col 5 expands to push right-side controls to the edge
        hdr.grid_columnconfigure(5, weight=1)

        # ── Logo ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            hdr, text="BOX",
            font=F(20, "bold"),
            text_color=_ACCENT,
        ).grid(row=0, column=0, padx=(16, 0))

        ctk.CTkLabel(
            hdr, text="3D",
            font=F(20, "bold"),
            text_color=_ACCENT2,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkLabel(
            hdr, text=f"v{_VERSION}",
            font=F(10),
            text_color=_DIM,
        ).grid(row=0, column=2, padx=(0, 20))

        # ── Tab nav buttons ───────────────────────────────────────────────────
        # Store the two font objects so _switch_tab can reuse them without
        # creating new CTkFont instances on every tab switch (avoids registry growth).
        self._font_nav_active = F(11, "bold")
        self._font_nav_dim    = F(11)

        self._btn_ctrl = ctk.CTkButton(
            hdr, text="CONTROL",
            width=96, height=52, corner_radius=0,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=0,
            text_color=_ACCENT,
            font=self._font_nav_active,
            command=lambda: self._switch_tab("Control"),
        )
        self._btn_ctrl.grid(row=0, column=3)

        self._btn_dsgn = ctk.CTkButton(
            hdr, text="DESIGNER PRO",
            width=118, height=52, corner_radius=0,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=0,
            text_color=_DIM,
            font=self._font_nav_dim,
            command=lambda: self._switch_tab("Designer"),
        )
        self._btn_dsgn.grid(row=0, column=4)

        # col 5 spacer
        ctk.CTkFrame(hdr, fg_color="transparent", width=0).grid(row=0, column=5, sticky="ew")

        # ── Font scale controls ───────────────────────────────────────────────
        self._scale_label = ctk.CTkLabel(
            hdr, text=f"{fonts.scale_pct()}%",
            font=F(10),
            text_color=_DIM,
            width=36,
        )

        ctk.CTkButton(
            hdr, text="A-",
            width=28, height=28, corner_radius=4,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=1, border_color=_DIM,
            text_color=_DIM,
            font=F(10),
            command=self._font_decrease,
        ).grid(row=0, column=6, padx=(0, 2))

        self._scale_label.grid(row=0, column=7, padx=2)

        ctk.CTkButton(
            hdr, text="A+",
            width=28, height=28, corner_radius=4,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=1, border_color=_DIM,
            text_color=_DIM,
            font=F(11),
            command=self._font_increase,
        ).grid(row=0, column=8, padx=(2, 12))

        # ── Status label ──────────────────────────────────────────────────────
        self._status_label = ctk.CTkLabel(
            hdr, text="● READY",
            font=F(11),
            text_color=_OK,
        )
        self._status_label.grid(row=0, column=9, padx=16)

    # =========================================================================
    # Content area — two frames, one visible at a time
    # =========================================================================

    def _build_content(self) -> None:
        content = ctk.CTkFrame(self, fg_color=_BG, corner_radius=0)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._ctrl_frame = ctk.CTkFrame(content, fg_color=_BG, corner_radius=0)
        self._ctrl_frame.grid(row=0, column=0, sticky="nsew")

        self._dsgn_frame = ctk.CTkFrame(content, fg_color=_BG, corner_radius=0)
        self._dsgn_frame.grid(row=0, column=0, sticky="nsew")
        self._dsgn_frame.grid_remove()

        self._control_tab  = ControlTab(
            self._ctrl_frame, on_status_change=self._update_status,
        )
        self._designer_tab = DesignerTab(
            self._dsgn_frame, on_install_cb=self.reload_and_select_profile,
        )

        self._active_tab = "Control"

    # =========================================================================
    # Tab switching
    # =========================================================================

    def _switch_tab(self, name: str) -> None:
        self._active_tab = name
        if name == "Control":
            self._ctrl_frame.grid()
            self._dsgn_frame.grid_remove()
            self._btn_ctrl.configure(text_color=_ACCENT, font=self._font_nav_active)
            self._btn_dsgn.configure(text_color=_DIM,    font=self._font_nav_dim)
        else:
            self._dsgn_frame.grid()
            self._ctrl_frame.grid_remove()
            self._btn_dsgn.configure(text_color=_ACCENT, font=self._font_nav_active)
            self._btn_ctrl.configure(text_color=_DIM,    font=self._font_nav_dim)

    # =========================================================================
    # Font scale
    # =========================================================================

    def _font_increase(self) -> None:
        new = fonts.step_up()
        fonts.set_scale(new)
        self._scale_label.configure(text=f"{fonts.scale_pct()}%")
        self._persist_scale()

    def _font_decrease(self) -> None:
        new = fonts.step_down()
        fonts.set_scale(new)
        self._scale_label.configure(text=f"{fonts.scale_pct()}%")
        self._persist_scale()

    def _persist_scale(self) -> None:
        cfg = load_config()
        cfg["font_scale"] = fonts.get_scale()
        save_config(cfg)

    # =========================================================================
    # Callbacks
    # =========================================================================

    def _update_status(self, text: str, color: str) -> None:
        self._status_label.configure(text=text, text_color=color)

    def reload_and_select_profile(self, name: str) -> None:
        """Called by DesignerTab after installing a profile: reload + switch tab."""
        self._control_tab.reload_profiles(select=name)
        self._switch_tab("Control")

    def _on_close(self) -> None:
        self._control_tab.save_config()
        self._designer_tab.save_config()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _bootstrap_data_dir()
    _bootstrap_instructions()
    cfg = load_config()
    fonts.init_scale(cfg.get("font_scale", 1.0))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
