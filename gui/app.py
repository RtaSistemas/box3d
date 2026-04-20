"""
gui/app.py — Box3D Desktop GUI entry point
===========================================
Thin shell: window chrome, header (with inline tab nav), and two content frames.

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
from gui.constants import (                                 # noqa: E402
    _VERSION, _BG, _PANEL, _PANEL2, _ACCENT, _ACCENT2, _OK, _DIM, _FONT_MONO,
)
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
    # Header — BOX3D title + version + inline tab nav + status
    # =========================================================================

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        # col 0-1: logo  col 2: version  col 3: nav  col 4 (weight): spacer  col 5: status
        hdr.grid_columnconfigure(4, weight=1)

        # ── Logo ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            hdr, text="BOX",
            font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT,
        ).grid(row=0, column=0, padx=(16, 0), pady=0)

        ctk.CTkLabel(
            hdr, text="3D",
            font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT2,
        ).grid(row=0, column=1, padx=(0, 10), pady=0)

        ctk.CTkLabel(
            hdr, text=f"v{_VERSION}",
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            text_color=_DIM,
        ).grid(row=0, column=2, padx=(0, 24), pady=0)

        # ── Tab nav buttons ───────────────────────────────────────────────────
        nav = ctk.CTkFrame(hdr, fg_color="transparent")
        nav.grid(row=0, column=3, sticky="ns")

        self._btn_ctrl = ctk.CTkButton(
            nav, text="CONTROL",
            width=96, height=52, corner_radius=0,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=0,
            text_color=_ACCENT,
            font=ctk.CTkFont(family=_FONT_MONO, size=11, weight="bold"),
            command=lambda: self._switch_tab("Control"),
        )
        self._btn_ctrl.pack(side="left")

        self._btn_dsgn = ctk.CTkButton(
            nav, text="DESIGNER PRO",
            width=118, height=52, corner_radius=0,
            fg_color="transparent", hover_color=_PANEL2,
            border_width=0,
            text_color=_DIM,
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            command=lambda: self._switch_tab("Designer"),
        )
        self._btn_dsgn.pack(side="left")

        # col 4 spacer (weight=1 above) keeps status pinned right
        ctk.CTkFrame(hdr, fg_color="transparent").grid(row=0, column=4, sticky="ew")

        # ── Status label ─────────────────────────────────────────────────────
        self._status_label = ctk.CTkLabel(
            hdr, text="● READY",
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            text_color=_OK,
        )
        self._status_label.grid(row=0, column=5, padx=16, sticky="e")

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
            self._btn_ctrl.configure(
                text_color=_ACCENT,
                font=ctk.CTkFont(family=_FONT_MONO, size=11, weight="bold"),
            )
            self._btn_dsgn.configure(
                text_color=_DIM,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
            )
        else:
            self._dsgn_frame.grid()
            self._ctrl_frame.grid_remove()
            self._btn_dsgn.configure(
                text_color=_ACCENT,
                font=ctk.CTkFont(family=_FONT_MONO, size=11, weight="bold"),
            )
            self._btn_ctrl.configure(
                text_color=_DIM,
                font=ctk.CTkFont(family=_FONT_MONO, size=11),
            )

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
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
