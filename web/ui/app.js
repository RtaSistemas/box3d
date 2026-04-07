/**
 * app.js — Box3D Control Center
 * ================================
 * Pure Vanilla JS — no build steps, no frameworks.
 * Communicates exclusively with the FastAPI backend via Fetch + EventSource.
 *
 * Flow:
 *   boot()  →  fetchProfiles()  →  populate <select>
 *   path inputs onblur  →  POST /api/validate-path  →  visual feedback
 *   "Start Render" click  →  POST /api/render  →  open EventSource
 *   EventSource onmessage  →  update progress bar + log
 *   sentinel (done === -1)  →  close stream, show summary modal
 */

'use strict';

// ─── Element refs ──────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const profileSelect  = $('profile-select');
const profileInfo    = $('profile-info');
const inputCovers    = $('input-covers');
const inputOutput    = $('input-output');
const inputMarquees  = $('input-marquees');
const btnRender      = $('btn-render');
const btnLabel       = $('btn-label');

const cardIdle       = $('card-idle');
const cardProgress   = $('card-progress');
const progDone       = $('prog-done');
const progTotal      = $('prog-total');
const progPct        = $('prog-pct');
const progressBar    = $('progress-bar');
const logOutput      = $('log-output');
const logContainer   = $('log-container');

const summaryOverlay  = $('summary-overlay');
const summaryModal    = $('summary-modal');
const modalTitle      = $('modal-title');
const summaryStats    = $('summary-stats');
const summaryErrors   = $('summary-errors');
const summaryPreview  = $('summary-preview');
const previewImg      = $('preview-img');
const btnCloseModal   = $('btn-close-modal');
const btnOpenOutput   = $('btn-open-output');
const serverStatus    = $('server-status');

const rgbPicker       = $('opt-rgb-picker');
const rgbLabel        = $('rgb-label');
const btnResetRgb     = $('btn-reset-rgb');

// ─── State ─────────────────────────────────────────────────────────────────

let _rendering   = false;
let _evtSource   = null;
let _profilesMap = {};   // name → {template_w, template_h}

// ─── RGB colour picker ──────────────────────────────────────────────────────

/** Convert a CSS hex colour (#rrggbb) to normalised [r, g, b] floats (0–2 range). */
function _hexToRgbMatrix(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  return [r * 2, g * 2, b * 2];   // scale: white (#ffffff) → [2,2,2]; neutral → [1,1,1] (#808080)
}

/** Return the closest hex colour for a normalised rgb_matrix [r,g,b] (0–2 range). */
function _rgbMatrixToHex(matrix) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v / 2 * 255)));
  const r = clamp(matrix[0]).toString(16).padStart(2, '0');
  const g = clamp(matrix[1]).toString(16).padStart(2, '0');
  const b = clamp(matrix[2]).toString(16).padStart(2, '0');
  return `#${r}${g}${b}`;
}

function _updateRgbLabel() {
  const [r, g, b] = _hexToRgbMatrix(rgbPicker.value);
  rgbLabel.textContent = `${r.toFixed(2)}, ${g.toFixed(2)}, ${b.toFixed(2)}`;
}

/** Return null when the picker is at neutral (#808080 ≈ [1,1,1]) to avoid sending noise. */
function _getRgbMatrix() {
  const [r, g, b] = _hexToRgbMatrix(rgbPicker.value);
  const neutral = Math.abs(r - 1) < 0.02 && Math.abs(g - 1) < 0.02 && Math.abs(b - 1) < 0.02;
  return neutral ? null : [r, g, b];
}

rgbPicker.addEventListener('input', _updateRgbLabel);

btnResetRgb.addEventListener('click', () => {
  rgbPicker.value = '#808080';   // neutral: scale factors → [1, 1, 1]
  _updateRgbLabel();
});

// ─── Path inputs ────────────────────────────────────────────────────────────

const PATH_INPUTS = [
  { el: inputCovers,   required: true  },
  { el: inputOutput,   required: true  },
  { el: inputMarquees, required: false },
];

/**
 * Validate a single path input against the backend.
 * Optional inputs with an empty value are silently skipped.
 */
async function validatePathInput(entry) {
  const { el, required } = entry;
  const val = el.value.trim();

  // Remove previous state — hint lives as the next sibling of the input wrapper
  el.classList.remove('path-valid', 'path-invalid');
  const hint = el.closest('.field').querySelector('.path-hint');
  if (hint) hint.textContent = '';

  if (!val) {
    if (required) {
      el.classList.add('path-invalid');
      if (hint) hint.textContent = '✗ required';
    }
    _updateRenderButton();
    return;
  }

  try {
    const res  = await fetch('/api/validate-path', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ path: val }),
    });
    const data = await res.json();

    if (data.valid) {
      el.classList.add('path-valid');
      if (hint) hint.textContent = '✔ directory found';
    } else {
      el.classList.add('path-invalid');
      if (hint) hint.textContent = '✗ directory not found';
    }
  } catch {
    el.classList.add('path-invalid');
    if (hint) hint.textContent = '✗ server unreachable';
  }

  _updateRenderButton();
}

/** Enable the render button only when required paths are valid. */
function _updateRenderButton() {
  if (_rendering) return;
  const ok = PATH_INPUTS
    .filter(e => e.required)
    .every(e => e.el.classList.contains('path-valid'));
  btnRender.disabled = !ok;
}

// ─── Folder buttons ─────────────────────────────────────────────────────────

document.querySelectorAll('.btn-folder').forEach(btn => {
  btn.addEventListener('click', async () => {
    const inputId = btn.dataset.for;
    const input   = $(inputId);
    const path    = input ? input.value.trim() : null;
    try {
      await fetch('/api/open-folder', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ path: path || null }),
      });
    } catch { /* silently ignore — OS may not support it */ }
  });
});

// ─── Profile loading ────────────────────────────────────────────────────────

async function fetchProfiles() {
  try {
    const res  = await fetch('/api/profiles');
    const data = await res.json();

    if (!data.profiles || data.profiles.length === 0) {
      profileSelect.innerHTML = '<option value="">No profiles found</option>';
      return;
    }

    profileSelect.innerHTML = '';
    data.profiles.forEach(p => {
      _profilesMap[p.name] = p;
      const opt = document.createElement('option');
      opt.value       = p.name;
      opt.textContent = p.name;
      profileSelect.appendChild(opt);
    });

    _onProfileChange();

    // Mark server as online
    serverStatus.textContent = '● API ONLINE';
    serverStatus.className   = 'badge badge-ok';

  } catch {
    profileSelect.innerHTML  = '<option value="">Cannot reach server</option>';
    serverStatus.textContent = '● API OFFLINE';
    serverStatus.className   = 'badge badge-error';
  }
}

function _onProfileChange() {
  const name = profileSelect.value;
  const p    = _profilesMap[name];
  profileInfo.textContent = p
    ? `${p.template_w} × ${p.template_h} px`
    : '';
}

// ─── Render ─────────────────────────────────────────────────────────────────

function _buildPayload() {
  return {
    profile:       profileSelect.value,
    covers_dir:    inputCovers.value.trim(),
    output_dir:    inputOutput.value.trim(),
    marquees_dir:  inputMarquees.value.trim() || null,
    workers:       parseInt($('opt-workers').value, 10) || 4,
    blur_radius:   parseInt($('opt-blur').value,    10) || 20,
    darken_alpha:  parseInt($('opt-darken').value,  10) || 180,
    cover_fit:     $('opt-cover-fit').value || null,
    spine_source:  $('opt-spine-source').value || null,
    output_format: $('opt-format').value,
    skip_existing: $('opt-skip').checked,
    dry_run:       $('opt-dry').checked,
    no_logos:      $('opt-no-logos').checked,
    rgb_matrix:    _getRgbMatrix(),
  };
}

async function startRender() {
  if (_rendering) return;

  _setRendering(true);
  _resetProgress();
  _showProgressPanel();

  const payload = _buildPayload();

  // ── POST /api/render ────────────────────────────────────────────
  let startResp;
  try {
    const res = await fetch('/api/render', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    startResp = await res.json();

    if (startResp.status !== 'started') {
      throw new Error(startResp.detail || 'Unknown error');
    }
  } catch (err) {
    _appendLog(`✘ Failed to start render: ${err.message}`);
    _setRendering(false);
    return;
  }

  _appendLog(`▶  Profile: ${payload.profile}  |  Covers: ${payload.covers_dir}`);
  _appendLog('─'.repeat(52));

  // ── EventSource /api/progress ───────────────────────────────────
  _evtSource = new EventSource('/api/progress');

  _evtSource.onmessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); }
    catch { return; }

    // ── Sentinel — render finished ──────────────────────────────
    if (data.done === -1) {
      _evtSource.close();
      _evtSource = null;
      _setRendering(false);

      // Force bar to 100% on success
      if (data.failed === 0 && !data.breaker_tripped) {
        _setProgress(data.total, data.total);
      }

      _appendLog('─'.repeat(52));
      _appendLog(
        `■  Done — ${data.succeeded} ok · ${data.failed} errors · ${data.elapsed_time}s`
      );
      _showSummary(data, payload.output_format);
      return;
    }

    // ── Per-cover progress event ────────────────────────────────
    const icon    = data.status === 'ok'   ? '✔'
                  : data.status === 'skip' ? '⊘'
                  : data.status === 'dry'  ? '◌'
                  :                          '✘';
    const elapsed = data.elapsed > 0 ? `  (${data.elapsed}s)` : '';

    _appendLog(`${icon}  ${data.stem}${elapsed}`);
    _setProgress(data.done, data.total);
  };

  _evtSource.onerror = () => {
    if (_evtSource) {
      _appendLog('✘ Connection to server lost.');
      _evtSource.close();
      _evtSource = null;
      _setRendering(false);
    }
  };
}

// ─── Progress helpers ────────────────────────────────────────────────────────

function _resetProgress() {
  logOutput.textContent  = '';
  progressBar.style.width = '0%';
  progDone.textContent   = '0';
  progTotal.textContent  = '—';
  progPct.textContent    = '0%';
}

function _setProgress(done, total) {
  const pct = total > 0 ? Math.round(done / total * 100) : 0;
  progressBar.style.width = `${pct}%`;
  progDone.textContent    = done;
  progTotal.textContent   = total;
  progPct.textContent     = `${pct}%`;
}

function _appendLog(line) {
  logOutput.textContent += line + '\n';
  // Auto-scroll to bottom
  logContainer.scrollTop = logContainer.scrollHeight;
}

function _showProgressPanel() {
  cardIdle.classList.add('hidden');
  cardProgress.classList.remove('hidden');
}

// ─── Form lock/unlock ────────────────────────────────────────────────────────

function _setRendering(state) {
  _rendering = state;

  // Disable/enable all inputs
  const fields = document.querySelectorAll(
    '#config-panel input, #config-panel select'
  );
  fields.forEach(el => { el.disabled = state; });

  if (state) {
    btnRender.classList.add('rendering');
    btnRender.disabled    = true;
    btnLabel.textContent  = '⏳ RENDERING…';
  } else {
    btnRender.classList.remove('rendering');
    btnLabel.textContent = '▶ START RENDER';
    _updateRenderButton();
  }
}

// ─── Summary modal ────────────────────────────────────────────────────────────

function _showSummary(data) {
  const hasFails = data.failed > 0 || data.breaker_tripped;

  modalTitle.textContent = hasFails ? 'Render Finished With Errors' : 'Render Complete';
  modalTitle.className   = hasFails ? 'modal-title failed' : 'modal-title';

  // ── Preview image ───────────────────────────────────────────────
  const fmt  = data.output_format || 'webp';
  const stem = data.first_stem;
  if (stem && data.succeeded > 0) {
    previewImg.src = `/api/preview/${encodeURIComponent(stem)}.${fmt}`;
    previewImg.alt = stem;
    summaryPreview.classList.remove('hidden');
  } else {
    summaryPreview.classList.add('hidden');
    previewImg.src = '';
  }

  summaryStats.innerHTML = `
    ${_stat('Total',       data.total,        'dim')}
    ${_stat('Succeeded',   data.succeeded,    'ok')}
    ${_stat('Skipped',     data.skipped,      'dim')}
    ${_stat('Errors',      data.failed,       data.failed  > 0 ? 'error' : 'dim')}
    ${_stat('Dry-run',     data.dry,          'dim')}
    ${_stat('Time',        `${data.elapsed_time}s`, 'warn')}
  `;

  if (data.breaker_tripped) {
    summaryStats.innerHTML += _stat('Circuit Breaker', 'TRIPPED', 'error');
  }

  if (data.errors && data.errors.length > 0) {
    summaryErrors.classList.remove('hidden');
    summaryErrors.innerHTML = data.errors
      .map(e => `<p>✘ ${_esc(e)}</p>`)
      .join('');
  } else {
    summaryErrors.classList.add('hidden');
  }

  summaryOverlay.classList.remove('hidden');
}

function _stat(label, value, cls) {
  return `
    <div class="stat-item">
      <div class="stat-label">${label}</div>
      <div class="stat-value ${cls}">${value}</div>
    </div>`;
}

function _esc(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── Event bindings ──────────────────────────────────────────────────────────

PATH_INPUTS.forEach(entry => {
  entry.el.addEventListener('blur', () => validatePathInput(entry));
});

profileSelect.addEventListener('change', _onProfileChange);

btnRender.addEventListener('click', startRender);

btnCloseModal.addEventListener('click', () => {
  summaryOverlay.classList.add('hidden');
});

btnOpenOutput.addEventListener('click', async () => {
  try {
    await fetch('/api/open-folder', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ path: null }),   // null → use last output dir
    });
  } catch { /* silently ignore */ }
});

// Close modal on overlay click
summaryOverlay.addEventListener('click', (e) => {
  if (e.target === summaryOverlay) summaryOverlay.classList.add('hidden');
});

// ─── Boot ────────────────────────────────────────────────────────────────────

_updateRgbLabel();   // initialise label from picker default (#808080 → neutral)
fetchProfiles();
