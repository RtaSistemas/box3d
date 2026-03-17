/**
 * canvas.js — Canvas editing engine
 * Manages layout objects, drag, resize, grid snapping, zoom, hit detection.
 */

export const COLORS = {
  logo:    { fill: "rgba(255,71,87,.25)",  stroke: "#ff4757" },
  marquee: { fill: "rgba(0,234,255,.2)",   stroke: "#00eaff" },
  spine:   { fill: "rgba(255,211,42,.2)",  stroke: "#ffd32a" },
  cover:   { fill: "rgba(46,213,115,.2)",  stroke: "#2ed573" },
};

const HANDLE_SIZE = 8;
const MIN_DIM     = 10;

export class CanvasEngine {
  constructor(canvasEl) {
    this.el      = canvasEl;
    this.ctx     = canvasEl.getContext("2d");
    this.objects = [];           // { type, x, y, w, h }
    this.selected = null;
    this.zoom    = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.gridSize  = 10;
    this.snapToGrid  = true;
    this.showGrid    = true;
    this.templateImg = null;
    this._drag  = null;         // { mode, startX, startY, origObj }

    this._bindEvents();
  }

  // ── Public API ──────────────────────────────────────────────────────

  setTemplate(img) {
    this.templateImg = img;
    this.el.width    = img.naturalWidth;
    this.el.height   = img.naturalHeight;
    this.redraw();
  }

  addObject(type) {
    const w = this.el.width  * .35 | 0;
    const h = this.el.height * .4  | 0;
    const x = ((this.el.width  - w) / 2 | 0);
    const y = ((this.el.height - h) / 2 | 0);
    const obj = { type, x, y, w, h };
    this.objects.push(obj);
    this.selected = obj;
    this.redraw();
    this._emit("select", obj);
    return obj;
  }

  removeSelected() {
    if (!this.selected) return;
    this.objects = this.objects.filter(o => o !== this.selected);
    this.selected = null;
    this.redraw();
    this._emit("select", null);
  }

  setZoom(z) {
    this.zoom = Math.max(.1, Math.min(4, z));
    this.el.style.transform = `scale(${this.zoom})`;
    this._emit("zoom", this.zoom);
  }

  fitToScreen(containerW, containerH) {
    const tw = this.el.width, th = this.el.height;
    const z  = Math.min((containerW - 40) / tw, (containerH - 40) / th, 1);
    this.setZoom(z);
  }

  setProperty(key, value) {
    if (!this.selected) return;
    const n = parseFloat(value);
    if (isNaN(n)) return;
    const map = { x:"x", y:"y", width:"w", height:"h" };
    if (map[key]) { this.selected[map[key]] = n; this.redraw(); this._emit("change", this.selected); }
  }

  // ── Redraw ───────────────────────────────────────────────────────────

  redraw() {
    const ctx = this.ctx;
    const W = this.el.width, H = this.el.height;
    ctx.clearRect(0, 0, W, H);

    // Template image
    if (this.templateImg) {
      ctx.drawImage(this.templateImg, 0, 0, W, H);
    } else {
      ctx.fillStyle = "#0b0e14";
      ctx.fillRect(0, 0, W, H);
    }

    // Grid
    if (this.showGrid) this._drawGrid(W, H);

    // Layout objects
    for (const obj of this.objects) {
      this._drawObject(obj, obj === this.selected);
    }
  }

  _drawGrid(W, H) {
    const ctx = this.ctx;
    const g   = this.gridSize;
    ctx.save();
    ctx.strokeStyle = "rgba(0,234,255,.06)";
    ctx.lineWidth   = .5;
    ctx.beginPath();
    for (let x = 0; x <= W; x += g) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = 0; y <= H; y += g) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
    ctx.restore();
  }

  _drawObject(obj, selected) {
    const ctx = this.ctx;
    const col = COLORS[obj.type] || { fill: "rgba(255,255,255,.15)", stroke: "#fff" };

    ctx.save();

    // Fill
    ctx.fillStyle = col.fill;
    ctx.fillRect(obj.x, obj.y, obj.w, obj.h);

    // Border
    ctx.strokeStyle = col.stroke;
    ctx.lineWidth   = selected ? 2 : 1;
    if (selected) ctx.setLineDash([]);
    else          ctx.setLineDash([4, 3]);
    ctx.strokeRect(obj.x + .5, obj.y + .5, obj.w - 1, obj.h - 1);
    ctx.setLineDash([]);

    // Label
    const label = obj.type.toUpperCase();
    ctx.fillStyle   = col.stroke;
    ctx.font        = `bold ${Math.min(13, obj.h * .18 | 0)}px 'Share Tech Mono', monospace`;
    ctx.textAlign   = "center";
    ctx.textBaseline = "middle";
    ctx.globalAlpha = .85;
    ctx.fillText(label, obj.x + obj.w / 2, obj.y + obj.h / 2);
    ctx.globalAlpha = 1;

    // Resize handles
    if (selected) {
      this._drawHandles(obj, col.stroke);
    }

    ctx.restore();
  }

  _drawHandles(obj, color) {
    const ctx = this.ctx;
    const s   = HANDLE_SIZE;
    const hs  = s / 2;
    const corners = [
      [obj.x,           obj.y],
      [obj.x + obj.w,   obj.y],
      [obj.x + obj.w,   obj.y + obj.h],
      [obj.x,           obj.y + obj.h],
    ];
    ctx.fillStyle   = color;
    ctx.strokeStyle = "#0b0e14";
    ctx.lineWidth   = 1.5;
    for (const [cx, cy] of corners) {
      ctx.fillRect(cx - hs, cy - hs, s, s);
      ctx.strokeRect(cx - hs, cy - hs, s, s);
    }
  }

  // ── Hit detection ────────────────────────────────────────────────────

  _hitHandle(obj, mx, my) {
    const s  = HANDLE_SIZE + 4;
    const hs = s / 2;
    const corners = [
      { name:"tl", x:obj.x,         y:obj.y         },
      { name:"tr", x:obj.x+obj.w,   y:obj.y         },
      { name:"br", x:obj.x+obj.w,   y:obj.y+obj.h   },
      { name:"bl", x:obj.x,         y:obj.y+obj.h   },
    ];
    return corners.find(c => Math.abs(mx - c.x) < hs && Math.abs(my - c.y) < hs) || null;
  }

  _hitObject(mx, my) {
    for (let i = this.objects.length - 1; i >= 0; i--) {
      const o = this.objects[i];
      if (mx >= o.x && mx <= o.x + o.w && my >= o.y && my <= o.y + o.h) return o;
    }
    return null;
  }

  // ── Events ───────────────────────────────────────────────────────────

  _toCanvas(e) {
    const rect = this.el.getBoundingClientRect();
    const scaleX = this.el.width  / rect.width;
    const scaleY = this.el.height / rect.height;
    return {
      x: (e.clientX - rect.left)  * scaleX,
      y: (e.clientY - rect.top)   * scaleY,
    };
  }

  _snap(v) {
    return this.snapToGrid ? Math.round(v / this.gridSize) * this.gridSize : v;
  }

  _bindEvents() {
    this.el.addEventListener("mousedown", e => {
      e.preventDefault();
      const { x: mx, y: my } = this._toCanvas(e);

      // Check handles on selected object first
      if (this.selected) {
        const handle = this._hitHandle(this.selected, mx, my);
        if (handle) {
          this._drag = { mode: "resize", handle: handle.name, startX: mx, startY: my, orig: { ...this.selected } };
          return;
        }
      }

      const hit = this._hitObject(mx, my);
      if (hit) {
        this.selected = hit;
        this._drag = { mode: "move", startX: mx - hit.x, startY: my - hit.y, orig: { ...hit } };
        this._emit("select", hit);
      } else {
        this.selected = null;
        this._emit("select", null);
      }
      this.redraw();
    });

    window.addEventListener("mousemove", e => {
      if (!this._drag) return;
      const { x: mx, y: my } = this._toCanvas(e);
      const d = this._drag;
      const obj = this.selected;

      if (d.mode === "move") {
        obj.x = this._snap(mx - d.startX);
        obj.y = this._snap(my - d.startY);
      } else if (d.mode === "resize") {
        const { orig } = d;
        const dx = this._snap(mx) - this._snap(d.orig.x + (d.handle.includes("r") ? d.orig.w : 0));
        const dy = this._snap(my) - this._snap(d.orig.y + (d.handle.includes("b") ? d.orig.h : 0));

        if (d.handle === "br") { obj.w = Math.max(MIN_DIM, orig.w + (mx - this._snap(orig.x + orig.w) + this._snap(mx) - mx)); }

        // Simpler direct approach
        const snap = this._snap.bind(this);
        if (d.handle === "tl") {
          const nx = snap(mx), ny = snap(my);
          obj.w = Math.max(MIN_DIM, orig.x + orig.w - nx);
          obj.h = Math.max(MIN_DIM, orig.y + orig.h - ny);
          obj.x = orig.x + orig.w - obj.w;
          obj.y = orig.y + orig.h - obj.h;
        } else if (d.handle === "tr") {
          obj.w = Math.max(MIN_DIM, snap(mx) - orig.x);
          const ny = snap(my);
          obj.h = Math.max(MIN_DIM, orig.y + orig.h - ny);
          obj.y = orig.y + orig.h - obj.h;
        } else if (d.handle === "br") {
          obj.w = Math.max(MIN_DIM, snap(mx) - orig.x);
          obj.h = Math.max(MIN_DIM, snap(my) - orig.y);
        } else if (d.handle === "bl") {
          const nx = snap(mx);
          obj.w = Math.max(MIN_DIM, orig.x + orig.w - nx);
          obj.x = orig.x + orig.w - obj.w;
          obj.h = Math.max(MIN_DIM, snap(my) - orig.y);
        }
      }

      this.redraw();
      this._emit("change", obj);
    });

    window.addEventListener("mouseup", () => { this._drag = null; });

    // Keyboard shortcuts
    window.addEventListener("keydown", e => {
      if (!this.selected) return;
      const step = e.shiftKey ? 10 : 1;
      const obj  = this.selected;
      if (e.key === "ArrowLeft")  { obj.x -= step; }
      else if (e.key === "ArrowRight") { obj.x += step; }
      else if (e.key === "ArrowUp")    { obj.y -= step; }
      else if (e.key === "ArrowDown")  { obj.y += step; }
      else if (e.key === "Delete" || e.key === "Backspace") { this.removeSelected(); return; }
      else return;
      e.preventDefault();
      this.redraw();
      this._emit("change", obj);
    });
  }

  // Simple event emitter
  _handlers = {};
  on(event, fn)         { (this._handlers[event] = this._handlers[event] || []).push(fn); }
  _emit(event, ...args) { (this._handlers[event] || []).forEach(fn => fn(...args)); }
}
