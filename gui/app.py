"""
gui/app.py — Box3D Desktop GUI entry point
===========================================
Thin shell: window chrome, header, CTkTabview with two tabs.

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

from .constants import (                                    # noqa: E402
    _VERSION, _BG, _PANEL, _ACCENT, _ACCENT2, _OK, _DIM, _FONT_MONO,
)
from .control_tab  import ControlTab                        # noqa: E402
from .designer_tab import DesignerTab                       # noqa: E402

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    """Main application window with Control and Designer tabs."""

    def __init__(self) -> None:
        super().__init__()

        self.title(f"BOX3D v{_VERSION} — Desktop")
        self.geometry("1360x820")
        self.minsize(980, 640)
        self.configure(fg_color=_BG)

        self.grid_rowconfigure(0, weight=0)   # header
        self.grid_rowconfigure(1, weight=1)   # tabs
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_tabs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    # Header
    # =========================================================================

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            hdr, text="BOX",
            font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT,
        ).grid(row=0, column=0, padx=(16, 0))

        ctk.CTkLabel(
            hdr, text="3D",
            font=ctk.CTkFont(family=_FONT_MONO, size=20, weight="bold"),
            text_color=_ACCENT2,
        ).grid(row=0, column=1, padx=(0, 6))

        ctk.CTkLabel(
            hdr, text=f"v{_VERSION}",
            font=ctk.CTkFont(family=_FONT_MONO, size=10),
            text_color=_DIM,
        ).grid(row=0, column=2, sticky="w")

        self._status_label = ctk.CTkLabel(
            hdr, text="● READY",
            font=ctk.CTkFont(family=_FONT_MONO, size=11),
            text_color=_OK,
        )
        self._status_label.grid(row=0, column=3, padx=16, sticky="e")

    # =========================================================================
    # Tabs
    # =========================================================================

    def _build_tabs(self) -> None:
        tabs = ctk.CTkTabview(
            self,
            fg_color=_BG,
            segmented_button_fg_color=_PANEL,
            segmented_button_selected_color=_ACCENT,
            segmented_button_selected_hover_color=_ACCENT2,
            segmented_button_unselected_color=_PANEL,
            segmented_button_unselected_hover_color=_PANEL,
            text_color=_DIM,
            text_color_disabled=_DIM,
            corner_radius=0,
            border_width=0,
        )
        tabs.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        tabs.add("Control")
        tabs.add("Designer")

        self._control_tab = ControlTab(tabs.tab("Control"), on_status_change=self._update_status)
        DesignerTab(tabs.tab("Designer"))

    # =========================================================================
    # Status callback (used by ControlTab)
    # =========================================================================

    def _update_status(self, text: str, color: str) -> None:
        self._status_label.configure(text=text, text_color=color)

    def _on_close(self) -> None:
        self._control_tab.save_config()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
