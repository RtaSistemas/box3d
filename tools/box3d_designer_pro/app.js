/**
 * app.js — Application bootstrap and wiring
 * Connects the canvas engine, profile I/O, and UI together.
 */

import { CanvasEngine }  from "./canvas.js";
import { exportProfile, importProfile, exportPython, downloadFile } from "./profile.js";

const $ = id => document.getElementById(id);

// ── State ────────────────────────────────────────────────────────────────
let engine = null;
let extras = {};   // non-geometry profile fields (spine_source, etc.)

// ── Init ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  engine = new CanvasEngine($("main-canvas"));

  // Wire canvas events → UI
  engine.on("select", updatePropsPanel);
  engine.on("change", (obj) => { updatePropsPanel(obj); refreshJson(); });
  engine.on("zoom",   (z)   => { $("zoom-display").textContent = `${Math.round(z * 100)}%`; });

  // Load placeholder template
  loadPlaceholderTemplate();

  // Wire all buttons
  wireUI();

  // Sections: open first ones by default
  document.querySelectorAll(".section").forEach((s, i) => { if (i < 3) s.classList.add("open"); });
  document.querySelectorAll(".section-title").forEach(t => {
    t.addEventListener("click", () => t.parentElement.classList.toggle("open"));
  });

  refreshJson();
});

// ── Template loading ──────────────────────────────────────────────────────
function loadPlaceholderTemplate() {
  // Draw a placeholder canvas
  const c = engine.el;
  c.width  = 703;
  c.height = 1000;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#12161e";
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.strokeStyle = "#1e2535";
  ctx.lineWidth = 2;
  ctx.strokeRect(2, 2, c.width-4, c.height-4);
  ctx.fillStyle  = "#1e2535";
  ctx.font       = "bold 22px 'Share Tech Mono', monospace";
  ctx.textAlign  = "center";
  ctx.fillText("Drop template PNG here", c.width/2, c.height/2 - 16);
  ctx.font = "14px 'Share Tech Mono', monospace";
  ctx.fillText("or use the Load Template button", c.width/2, c.height/2 + 16);
  engine.redraw();
}

function loadTemplateFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const img = new Image();
  img.onload = () => {
    engine.setTemplate(img);
    extras.tw = img.naturalWidth;
    extras.th = img.naturalHeight;
    showToast(`Template loaded: ${img.naturalWidth}×${img.naturalHeight}`);
    refreshJson();
  };
  img.src = URL.createObjectURL(file);
}

// ── UI Wiring ─────────────────────────────────────────────────────────────
function wireUI() {
  // Template loader
  $("btn-load-template").addEventListener("click", () => $("input-template").click());
  $("input-template").addEventListener("change", e => loadTemplateFile(e.target.files[0]));

  // Drag & drop on canvas area
  $("canvas-area").addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  $("canvas-area").addEventListener("drop", e => {
    e.preventDefault();
    const file = [...e.dataTransfer.files].find(f => f.type.startsWith("image/") || f.name.endsWith(".json"));
    if (file && file.name.endsWith(".json")) loadProfileFile(file);
    else if (file) loadTemplateFile(file);
  });

  // Add objects
  ["logo", "marquee", "spine", "cover"].forEach(type => {
    $(`btn-add-${type}`)?.addEventListener("click", () => {
      engine.addObject(type);
      refreshJson();
    });
  });

  // Remove
  $("btn-remove").addEventListener("click", () => { engine.removeSelected(); refreshJson(); });

  // Profile I/O
  $("btn-load-profile").addEventListener("click", () => $("input-profile").click());
  $("input-profile").addEventListener("change", e => loadProfileFile(e.target.files[0]));
  $("btn-export-json").addEventListener("click", doExportJson);
  $("btn-export-py").addEventListener("click",   doExportPython);
  $("btn-copy-json").addEventListener("click",   () => {
    navigator.clipboard.writeText($("json-preview").textContent);
    showToast("Copied to clipboard");
  });

  // Grid controls
  $("cb-show-grid").addEventListener("change",  e => { engine.showGrid  = e.target.checked; engine.redraw(); });
  $("cb-snap-grid").addEventListener("change",  e => { engine.snapToGrid = e.target.checked; });
  $("input-grid-size").addEventListener("input", e => {
    const v = parseInt(e.target.value);
    if (v > 0) { engine.gridSize = v; engine.redraw(); }
  });

  // Scanlines
  $("cb-scanlines")?.addEventListener("change", e => {
    document.body.classList.toggle("scanlines", e.target.checked);
  });

  // Zoom
  $("btn-zoom-in").addEventListener("click",  () => engine.setZoom(engine.zoom * 1.25));
  $("btn-zoom-out").addEventListener("click", () => engine.setZoom(engine.zoom * 0.8));
  $("btn-zoom-fit").addEventListener("click", () => {
    const area = $("canvas-area");
    engine.fitToScreen(area.clientWidth, area.clientHeight);
  });

  // Property inputs
  ["x","y","width","height"].forEach(key => {
    $(`prop-${key}`)?.addEventListener("input", e => {
      engine.setProperty(key, e.target.value);
      refreshJson();
    });
  });

  // Extras (spine_source etc.)
  $("sel-spine-source")?.addEventListener("change", e => { extras.spine_source = e.target.value; refreshJson(); });
  $("sel-cover-fit")?.addEventListener("change",    e => { extras.cover_fit    = e.target.value; refreshJson(); });
  $("inp-logo-alpha")?.addEventListener("input",    e => {
    extras.spine_layout = extras.spine_layout || {};
    extras.spine_layout.logo_alpha = parseFloat(e.target.value);
    refreshJson();
  });
}

// ── Properties panel ─────────────────────────────────────────────────────
function updatePropsPanel(obj) {
  const noSel = !obj;
  $("props-title").textContent = obj ? `▸ ${obj.type.toUpperCase()}` : "▸ SELECT AN OBJECT";

  ["x","y","width","height"].forEach(key => {
    const el = $(`prop-${key}`);
    if (!el) return;
    el.disabled = noSel;
    el.value    = obj ? Math.round(obj[key === "width" ? "w" : key === "height" ? "h" : key]) : "";
  });

  // Object list highlight
  document.querySelectorAll(".obj-item").forEach(el => {
    el.classList.toggle("active", obj && el.dataset.type === obj.type);
  });
}

// ── JSON refresh ─────────────────────────────────────────────────────────
function refreshJson() {
  const name    = $("profile-name-input").value || "untitled";
  const profile = exportProfile(name, engine.objects, engine.templateImg, extras);
  $("json-preview").textContent = JSON.stringify(profile, null, 2);
}

// ── Export ───────────────────────────────────────────────────────────────
function doExportJson() {
  const name    = $("profile-name-input").value || "untitled";
  const profile = exportProfile(name, engine.objects, engine.templateImg, extras);
  downloadFile(JSON.stringify(profile, null, 2), `${name}_profile.json`, "application/json");
  showToast("profile.json exported");
}

function doExportPython() {
  const name    = $("profile-name-input").value || "untitled";
  const profile = exportProfile(name, engine.objects, engine.templateImg, extras);
  downloadFile(exportPython(profile), `${name}_profile.py`, "text/plain");
  showToast("profile.py exported");
}

// ── Profile import ────────────────────────────────────────────────────────
function loadProfileFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const json = JSON.parse(e.target.result);
      const { objects, extras: ex } = importProfile(json);
      engine.objects  = objects;
      engine.selected = null;
      extras = ex;
      if (json.name) $("profile-name-input").value = json.name;
      // Sync controls
      if ($("sel-spine-source") && ex.spine_source) $("sel-spine-source").value = ex.spine_source;
      if ($("sel-cover-fit")    && ex.cover_fit)    $("sel-cover-fit").value    = ex.cover_fit;
      engine.redraw();
      updatePropsPanel(null);
      refreshJson();
      showToast(`Profile "${json.name}" loaded`);
    } catch (err) {
      showToast("Error: invalid JSON — " + err.message, true);
    }
  };
  reader.readAsText(file);
}

// ── Toast ─────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, error = false) {
  let t = $("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    Object.assign(t.style, {
      position:"fixed", bottom:"1.5rem", left:"50%", transform:"translateX(-50%)",
      fontFamily:"var(--font-mono)", fontSize:".8rem", padding:".45rem 1rem",
      borderRadius:"4px", zIndex:9998, transition:"opacity .3s", pointerEvents:"none",
    });
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.background = error ? "rgba(255,43,214,.15)" : "rgba(0,234,255,.12)";
  t.style.border      = `1px solid ${error ? "var(--accent2)" : "var(--accent)"}`;
  t.style.color       = error ? "var(--accent2)" : "var(--accent)";
  t.style.opacity = "1";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.style.opacity = "0"; }, 2800);
}
