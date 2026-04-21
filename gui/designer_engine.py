"""
gui/designer_engine.py — Box3D Designer canvas engine
======================================================
Pure interaction logic for the visual profile geometry designer.
Manages objects, selection, drag/resize, zoom/pan, and canvas rendering.

Zero application state — two callbacks bridge engine ↔ UI:
    on_change_cb(obj)  — called when an object is moved/resized
    on_select_cb(obj)  — called when selection changes (obj may be None)
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    import tkinter as tk

from PIL import Image

try:
    from PIL import ImageTk
except ImportError as _itk_err:
    raise ImportError(
        "PIL.ImageTk is unavailable — tkinter may be missing from the bundle. "
        f"Original error: {_itk_err}"
    ) from _itk_err


@runtime_checkable
class CanvasProtocol(Protocol):
    """Structural interface satisfied by tkinter.Canvas (and test doubles)."""

    def create_image(self, x: float, y: float, **kwargs) -> int: ...
    def create_rectangle(self, x0: float, y0: float, x1: float, y1: float, **kwargs) -> int: ...
    def create_line(self, *coords, **kwargs) -> int: ...
    def create_polygon(self, *coords, **kwargs) -> int: ...
    def create_text(self, x: float, y: float, **kwargs) -> int: ...
    def delete(self, *args) -> None: ...
    def tag_bind(self, tag: str, sequence: str, func) -> None: ...
    def bind(self, sequence: str, func, add: bool = False) -> None: ...
    def winfo_width(self) -> int: ...
    def winfo_height(self) -> int: ...

from .constants import (
    _BG, _PANEL, _PANEL2, _BORDER, _TEXT, _DIM,
    _DSN_COLORS, _FONT_MONO, _HANDLE_SIZE, _MIN_DIM,
)


class DesignerEngine:
    """Interactive canvas engine for Box3D profile geometry design.

    All object coordinates are stored in *template space* (original image px).
    The canvas display applies zoom/pan transforms on every redraw.
    """

    def __init__(
        self,
        canvas: CanvasProtocol,
        on_change_cb: Callable | None = None,
        on_select_cb: Callable | None = None,
    ) -> None:
        self.canvas     = canvas
        self._on_change = on_change_cb or (lambda obj: None)
        self._on_select = on_select_cb or (lambda obj: None)

        self.objects:  list[dict]   = []
        self.selected: dict | None  = None

        self.zoom  = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.template_img: Image.Image | None      = None
        self._tpl_photo:   ImageTk.PhotoImage | None = None
        self._tpl_zoom:    float = -1.0

        self.template_w = 703
        self.template_h = 1000

        self.grid_size    = 10
        self.snap_to_grid = True
        self.show_grid    = True

        self._drag:      dict | None  = None
        self._panning    = False
        self._pan_start: tuple | None = None
        self._space_down = False

        self._bind_events()
        self.redraw()

    # ── Coordinate transforms ─────────────────────────────────────────────────

    def to_canvas(self, tx: float, ty: float) -> tuple[float, float]:
        """Template space → canvas pixel coords."""
        return tx * self.zoom + self.pan_x, ty * self.zoom + self.pan_y

    def to_template(self, cx: float, cy: float) -> tuple[float, float]:
        """Canvas pixel coords → template space."""
        return (cx - self.pan_x) / self.zoom, (cy - self.pan_y) / self.zoom

    def _snap(self, v: float) -> float:
        if self.snap_to_grid and self.grid_size > 0:
            return round(v / self.grid_size) * self.grid_size
        return v

    # ── Template ─────────────────────────────────────────────────────────────

    def set_template(self, pil_img: Image.Image) -> None:
        self.template_img = pil_img
        self.template_w   = pil_img.width
        self.template_h   = pil_img.height
        self._tpl_photo   = None
        self._tpl_zoom    = -1.0
        self.redraw()

    # ── Objects ───────────────────────────────────────────────────────────────

    def add_object(self, obj_type: str) -> dict | None:
        if any(o["type"] == obj_type for o in self.objects):
            return None
        w = max(_MIN_DIM, int(self.template_w * 0.35))
        h = max(_MIN_DIM, int(self.template_h * 0.40))
        obj: dict = {
            "type": obj_type,
            "x": (self.template_w - w) // 2,
            "y": (self.template_h - h) // 2,
            "w": w, "h": h,
        }
        self.objects.append(obj)
        self.selected = obj
        self.redraw()
        self._on_select(obj)
        return obj

    def remove_selected(self) -> None:
        if not self.selected:
            return
        self.objects  = [o for o in self.objects if o is not self.selected]
        self.selected = None
        self.redraw()
        self._on_select(None)

    def clear_all(self) -> None:
        self.objects.clear()
        self.selected = None
        self.redraw()
        self._on_select(None)

    # ── Zoom / Pan ────────────────────────────────────────────────────────────

    def set_zoom(
        self,
        z: float,
        origin_cx: float | None = None,
        origin_cy: float | None = None,
    ) -> None:
        prev      = self.zoom
        self.zoom = max(0.05, min(8.0, z))
        if origin_cx is not None and prev > 0:
            r          = self.zoom / prev
            self.pan_x = origin_cx - (origin_cx - self.pan_x) * r
            self.pan_y = origin_cy - (origin_cy - self.pan_y) * r
        self._tpl_photo = None          # invalidate cached photo
        self.redraw()

    def fit_to_screen(self) -> None:
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        z          = min(
            (cw - 40) / max(1, self.template_w),
            (ch - 40) / max(1, self.template_h),
            1.0,
        )
        self.zoom  = max(0.05, min(8.0, z))
        self.pan_x = round((cw - self.template_w * self.zoom) / 2)
        self.pan_y = round((ch - self.template_h * self.zoom) / 2)
        self._tpl_photo = None
        self.redraw()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._draw_template()
        if self.show_grid:
            self._draw_grid()
        for obj in self.objects:
            self._draw_object(obj, obj is self.selected)

    def _draw_template(self) -> None:
        if self.template_img is None:
            x1, y1 = self.to_canvas(0, 0)
            x2, y2 = self.to_canvas(self.template_w, self.template_h)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=_PANEL, outline=_BORDER, width=2)
            self.canvas.create_text(
                cx, cy - 14,
                text="Click  ◈ Load Template  to begin",
                fill=_DIM, font=(_FONT_MONO, 11),
            )
            return

        sw = max(1, int(self.template_w * self.zoom))
        sh = max(1, int(self.template_h * self.zoom))
        if self._tpl_photo is None or abs(self._tpl_zoom - self.zoom) > 1e-6:
            resized         = self.template_img.resize((sw, sh), Image.NEAREST)
            self._tpl_photo = ImageTk.PhotoImage(resized)
            self._tpl_zoom  = self.zoom
        self.canvas.create_image(
            int(self.pan_x), int(self.pan_y), anchor="nw", image=self._tpl_photo,
        )

    def _draw_grid(self) -> None:
        g = self.grid_size * self.zoom
        if g < 4:
            return
        cw = self.canvas.winfo_width() or 800
        ch = self.canvas.winfo_height() or 600
        x1, y1 = self.to_canvas(0, 0)
        x2, y2 = self.to_canvas(self.template_w, self.template_h)
        dx1 = max(x1, 0);  dy1 = max(y1, 0)
        dx2 = min(x2, cw); dy2 = min(y2, ch)
        gx = x1 + math.ceil((dx1 - x1) / g) * g
        while gx <= dx2:
            self.canvas.create_line(gx, dy1, gx, dy2, fill=_BORDER, width=1)
            gx += g
        gy = y1 + math.ceil((dy1 - y1) / g) * g
        while gy <= dy2:
            self.canvas.create_line(dx1, gy, dx2, gy, fill=_BORDER, width=1)
            gy += g

    def _draw_object(self, obj: dict, selected: bool) -> None:
        col  = _DSN_COLORS.get(obj["type"], {"fill": _PANEL2, "stroke": _TEXT})
        dash = () if selected else (4, 3)
        lw   = 2 if selected else 1

        if obj.get("quad"):
            q = obj["quad"]
            pts: list[float] = []
            for corner in (q["tl"], q["tr"], q["br"], q["bl"]):
                cx, cy = self.to_canvas(corner[0], corner[1])
                pts += [cx, cy]
            self.canvas.create_polygon(
                pts, fill=col["fill"], outline=col["stroke"], width=lw, dash=dash,
            )
            lx = sum(pts[i] for i in range(0, 8, 2)) / 4
            ly = sum(pts[i] for i in range(1, 8, 2)) / 4
            self.canvas.create_text(
                lx, ly, text=obj["type"].upper(),
                fill=col["stroke"], font=(_FONT_MONO, 9, "bold"),
            )
            if selected:
                hs = _HANDLE_SIZE / 2
                for corner in (q["tl"], q["tr"], q["br"], q["bl"]):
                    cx, cy = self.to_canvas(corner[0], corner[1])
                    self.canvas.create_rectangle(
                        cx - hs, cy - hs, cx + hs, cy + hs,
                        fill=col["stroke"], outline=_BG, width=1,
                    )
        else:
            x1, y1 = self.to_canvas(obj["x"],            obj["y"])
            x2, y2 = self.to_canvas(obj["x"] + obj["w"], obj["y"] + obj["h"])
            self.canvas.create_rectangle(
                x1, y1, x2, y2, fill=col["fill"], outline=col["stroke"], width=lw, dash=dash,
            )
            self.canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=obj["type"].upper(),
                fill=col["stroke"], font=(_FONT_MONO, 9, "bold"),
            )
            if selected:
                hs = _HANDLE_SIZE / 2
                for tx, ty in [
                    (obj["x"],            obj["y"]),
                    (obj["x"] + obj["w"], obj["y"]),
                    (obj["x"] + obj["w"], obj["y"] + obj["h"]),
                    (obj["x"],            obj["y"] + obj["h"]),
                ]:
                    cx, cy = self.to_canvas(tx, ty)
                    self.canvas.create_rectangle(
                        cx - hs, cy - hs, cx + hs, cy + hs,
                        fill=col["stroke"], outline=_BG, width=1,
                    )

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _hit_handle(self, obj: dict, tx: float, ty: float) -> str | None:
        hs = (_HANDLE_SIZE + 4) / 2 / self.zoom   # tolerance in template space
        if obj.get("quad"):
            corners = {k: obj["quad"][k] for k in ("tl", "tr", "br", "bl")}
        else:
            corners = {
                "tl": [obj["x"],            obj["y"]],
                "tr": [obj["x"] + obj["w"], obj["y"]],
                "br": [obj["x"] + obj["w"], obj["y"] + obj["h"]],
                "bl": [obj["x"],            obj["y"] + obj["h"]],
            }
        for name, (hx, hy) in corners.items():
            if abs(tx - hx) < hs and abs(ty - hy) < hs:
                return name
        return None

    @staticmethod
    def _point_in_poly(px: float, py: float, poly: list) -> bool:
        inside = False
        j = len(poly) - 1
        for i, (xi, yi) in enumerate(poly):
            xj, yj = poly[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def _hit_object(self, tx: float, ty: float) -> dict | None:
        for obj in reversed(self.objects):
            if obj.get("quad"):
                q = obj["quad"]
                if self._point_in_poly(tx, ty, [q["tl"], q["tr"], q["br"], q["bl"]]):
                    return obj
            elif (obj["x"] <= tx <= obj["x"] + obj["w"]
                  and obj["y"] <= ty <= obj["y"] + obj["h"]):
                return obj
        return None

    def _update_bbox(self, obj: dict) -> None:
        q = obj.get("quad")
        if not q:
            return
        xs = [q[k][0] for k in ("tl", "tr", "br", "bl")]
        ys = [q[k][1] for k in ("tl", "tr", "br", "bl")]
        obj["x"] = min(xs); obj["y"] = min(ys)
        obj["w"] = max(xs) - obj["x"]
        obj["h"] = max(ys) - obj["y"]

    def _ensure_quad(self, obj: dict) -> None:
        """Initialise a quad from bounding box if not already set (spine/cover only)."""
        if obj.get("quad") or obj["type"] not in ("cover", "spine"):
            return
        x, y, w, h = obj["x"], obj["y"], obj["w"], obj["h"]
        obj["quad"] = {
            "tl": [x,     y],
            "tr": [x + w, y],
            "br": [x + w, y + h],
            "bl": [x,     y + h],
        }

    # ── Mouse / keyboard events ───────────────────────────────────────────────

    def _bind_events(self) -> None:
        c = self.canvas
        c.configure(takefocus=True)
        c.bind("<ButtonPress-1>",    self._lmb_down)
        c.bind("<B1-Motion>",        self._lmb_move)
        c.bind("<ButtonRelease-1>",  self._lmb_up)
        c.bind("<ButtonPress-2>",    self._mmb_down)
        c.bind("<B2-Motion>",        self._mmb_move)
        c.bind("<ButtonRelease-2>",  self._mmb_up)
        c.bind("<MouseWheel>",       self._wheel)   # Windows / macOS
        c.bind("<Button-4>",         self._wheel)   # Linux scroll up
        c.bind("<Button-5>",         self._wheel)   # Linux scroll down
        c.bind("<KeyPress>",         self._key)
        c.bind("<KeyPress-space>",   lambda e: setattr(self, "_space_down", True))
        c.bind("<KeyRelease-space>", self._space_up)

    def _space_up(self, _e) -> None:
        self._space_down = False
        if not self._drag:
            self._panning   = False
            self._pan_start = None

    @staticmethod
    def _copy_obj(obj: dict) -> dict:
        c = dict(obj)
        if obj.get("quad"):
            c["quad"] = {k: list(v) for k, v in obj["quad"].items()}
        return c

    def _lmb_down(self, e) -> None:
        self.canvas.focus_set()
        cx, cy = float(e.x), float(e.y)
        tx, ty = self.to_template(cx, cy)

        if self._space_down:
            self._panning   = True
            self._pan_start = (cx, cy, self.pan_x, self.pan_y)
            return

        # Check corner handles first
        if self.selected:
            handle = self._hit_handle(self.selected, tx, ty)
            if handle:
                self._ensure_quad(self.selected)
                self._drag = {
                    "mode": "resize", "handle": handle,
                    "start_tx": tx, "start_ty": ty,
                    "orig": self._copy_obj(self.selected),
                }
                return

        hit = self._hit_object(tx, ty)
        if hit:
            self.selected = hit
            self._drag = {
                "mode": "move",
                "start_tx": tx, "start_ty": ty,
                "dx": tx - hit["x"], "dy": ty - hit["y"],
                "orig": self._copy_obj(hit),
            }
            self._on_select(hit)
        else:
            self.selected = None
            self._on_select(None)
        self.redraw()

    def _lmb_move(self, e) -> None:
        cx, cy = float(e.x), float(e.y)

        if self._panning and self._pan_start:
            sx, sy, spx, spy = self._pan_start
            self.pan_x = spx + (cx - sx)
            self.pan_y = spy + (cy - sy)
            self.redraw()
            return

        if not self._drag:
            return
        obj = self.selected
        if not obj or obj not in self.objects:
            self._drag = None
            return

        tx, ty = self.to_template(cx, cy)
        d = self._drag

        if d["mode"] == "move":
            if obj.get("quad"):
                dx = self._snap(tx - d["start_tx"])
                dy = self._snap(ty - d["start_ty"])
                oq = d["orig"]["quad"]
                obj["quad"] = {
                    k: [oq[k][0] + dx, oq[k][1] + dy]
                    for k in ("tl", "tr", "br", "bl")
                }
                self._update_bbox(obj)
            else:
                obj["x"] = self._snap(tx - d["dx"])
                obj["y"] = self._snap(ty - d["dy"])

        elif d["mode"] == "resize":
            snx, sny = self._snap(tx), self._snap(ty)
            h = d["handle"]
            if obj.get("quad"):
                obj["quad"][h] = [snx, sny]
                self._update_bbox(obj)
            else:
                o    = d["orig"]
                r, b = o["x"] + o["w"], o["y"] + o["h"]
                if h == "tl":
                    obj["w"] = max(_MIN_DIM, r - snx); obj["x"] = r - obj["w"]
                    obj["h"] = max(_MIN_DIM, b - sny); obj["y"] = b - obj["h"]
                elif h == "tr":
                    obj["w"] = max(_MIN_DIM, snx - o["x"])
                    obj["h"] = max(_MIN_DIM, b - sny); obj["y"] = b - obj["h"]
                elif h == "br":
                    obj["w"] = max(_MIN_DIM, snx - o["x"])
                    obj["h"] = max(_MIN_DIM, sny - o["y"])
                elif h == "bl":
                    obj["w"] = max(_MIN_DIM, r - snx); obj["x"] = r - obj["w"]
                    obj["h"] = max(_MIN_DIM, sny - o["y"])

        self.redraw()
        self._on_change(obj)

    def _lmb_up(self, _e) -> None:
        self._drag = None
        if self._panning and not self._space_down:
            self._panning   = False
            self._pan_start = None

    def _mmb_down(self, e) -> None:
        self._panning   = True
        self._pan_start = (float(e.x), float(e.y), self.pan_x, self.pan_y)

    def _mmb_move(self, e) -> None:
        if self._panning and self._pan_start:
            sx, sy, spx, spy = self._pan_start
            self.pan_x = spx + (e.x - sx)
            self.pan_y = spy + (e.y - sy)
            self.redraw()

    def _mmb_up(self, _e) -> None:
        self._panning   = False
        self._pan_start = None

    def _wheel(self, e) -> None:
        if e.num == 4 or (hasattr(e, "delta") and e.delta > 0):
            f = 1.1
        else:
            f = 1 / 1.1
        self.set_zoom(self.zoom * f, float(e.x), float(e.y))

    def _key(self, e) -> None:
        if not self.selected:
            return
        step = 10 if (e.state & 0x1) else 1
        obj  = self.selected
        dx = dy = 0
        if   e.keysym == "Left":                      dx = -step
        elif e.keysym == "Right":                     dx =  step
        elif e.keysym == "Up":                        dy = -step
        elif e.keysym == "Down":                      dy =  step
        elif e.keysym in ("Delete", "BackSpace"):
            self.remove_selected()
            return
        else:
            return
        if obj.get("quad"):
            for v in obj["quad"].values():
                v[0] += dx; v[1] += dy
            self._update_bbox(obj)
        else:
            obj["x"] += dx; obj["y"] += dy
        self.redraw()
        self._on_change(obj)

    # ── Profile I/O ──────────────────────────────────────────────────────────

    def import_profile(self, data: dict) -> None:
        """Load objects and template dimensions from a profile.json dict."""
        objects: list[dict] = []
        for qkey, skey, otype in (
            ("spine_quad", "spine", "spine"),
            ("cover_quad", "cover", "cover"),
        ):
            if data.get(qkey):
                q  = data[qkey]
                xs = [q[k][0] for k in ("tl", "tr", "br", "bl")]
                ys = [q[k][1] for k in ("tl", "tr", "br", "bl")]
                objects.append({
                    "type": otype,
                    "x": min(xs), "y": min(ys),
                    "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                    "quad": {k: list(v) for k, v in q.items()},
                })
            elif data.get(skey):
                s = data[skey]
                objects.append({
                    "type": otype, "x": 0, "y": 0,
                    "w": s["width"], "h": s["height"],
                })
        self.objects  = objects
        self.selected = None
        ts = data.get("template_size", {})
        if ts:
            self.template_w = ts.get("width",  self.template_w)
            self.template_h = ts.get("height", self.template_h)
        self.redraw()
        self._on_select(None)

    def build_profile(self, name: str, extras: dict) -> dict:
        """Build a profile.json-compatible dict from current canvas state."""
        find  = lambda t: next((o for o in self.objects if o["type"] == t), None)
        spine = find("spine")
        cover = find("cover")
        if not spine:
            raise ValueError("Profile must contain a spine object.")
        if not cover:
            raise ValueError("Profile must contain a cover object.")

        tw = extras.get("tw", self.template_w)
        th = extras.get("th", self.template_h)

        def sz(o: dict) -> dict:
            return {"width": round(o["w"]), "height": round(o["h"])}

        def mkq(o: dict) -> dict:
            x, y, w, h = round(o["x"]), round(o["y"]), round(o["w"]), round(o["h"])
            return {"tl": [x, y], "tr": [x+w, y], "br": [x+w, y+h], "bl": [x, y+h]}

        def rq(q: dict) -> dict:
            return {k: [round(v[0]), round(v[1])] for k, v in q.items()}

        sl = extras.get("spine_layout", {})

        def slot(key: str, fb: dict) -> dict:
            s = sl.get(key, {})
            return {
                "max_w":    s.get("max_w",    fb["max_w"]),
                "max_h":    s.get("max_h",    fb["max_h"]),
                "center_y": s.get("center_y", fb["center_y"]),
                "rotate":   s.get("rotate",   -90),
            }

        out: dict = {
            "name":          name,
            "template_size": {"width": tw, "height": th},
            "spine":         sz(spine),
            "cover":         sz(cover),
            "spine_quad":    rq(spine["quad"]) if spine.get("quad") else mkq(spine),
            "cover_quad":    rq(cover["quad"]) if cover.get("quad") else mkq(cover),
            "spine_source":      extras.get("spine_source",      "left"),
            "cover_fit":         extras.get("cover_fit",         "stretch"),
            "spine_source_frac": extras.get("spine_source_frac", 0.20),
            "spine_layout": {
                "game":   slot("game",   {"max_w": 80, "max_h": 320, "center_y": round(th * 0.50)}),
                "top":    slot("top",    {"max_w": 80, "max_h": 120, "center_y": round(th * 0.16)}),
                "bottom": slot("bottom", {"max_w": 80, "max_h": 80,  "center_y": round(th * 0.84)}),
                "logo_alpha": sl.get("logo_alpha", 0.85),
            },
        }
        if extras.get("description"):
            out["description"] = extras["description"]
        if extras.get("author") and extras["author"] != "box3d":
            out["author"] = extras["author"]
        return out
