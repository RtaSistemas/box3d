/* PMAS — Frontend App (Vanilla JS + Apache ECharts) */

const API = "http://127.0.0.1:8000";

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const csvInput          = document.getElementById("csvInput");
const uploadZone        = document.getElementById("uploadZone");
const notification      = document.getElementById("notification");
const cycleSelect       = document.getElementById("cycleSelect");
const pepSelect         = document.getElementById("pepSelect");
const pepDescSelect     = document.getElementById("pepDescSelect");
const collaboratorSelect= document.getElementById("collaboratorSelect");
const loadBtn           = document.getElementById("loadBtn");
const clearBtn          = document.getElementById("clearBtn");
const activePills       = document.getElementById("activePills");
const statsRow          = document.getElementById("statsRow");
const chartTitle        = document.getElementById("chartTitle");

const chart = echarts.init(document.getElementById("chart"), "dark");

// In-memory pep data for cross-filtering descriptions
let pepData = [];

// ---------------------------------------------------------------------------
// Notification
// ---------------------------------------------------------------------------
function notify(msg, type = "info") {
  notification.textContent = msg;
  notification.className = type;
  notification.style.display = "block";
  if (type === "success") setTimeout(() => { notification.style.display = "none"; }, 6000);
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
csvInput.addEventListener("change", async () => {
  const file = csvInput.files[0];
  if (!file) return;
  notify(`Enviando "${file.name}"…`, "info");

  const form = new FormData();
  form.append("file", file);
  try {
    const res  = await fetch(`${API}/api/upload-timesheet`, { method: "POST", body: form });
    const json = await res.json();
    if (!res.ok) { notify(`Erro: ${json.detail ?? res.statusText}`, "error"); return; }

    let msg = `✔ ${json.records_inserted.toLocaleString("pt-BR")} registro(s) importado(s).`;
    if (json.quarantine_cycles_created > 0)
      msg += ` ⚠ ${json.quarantine_cycles_created} ciclo(s) de Quarentena criado(s) para datas órfãs.`;

    notify(msg, json.quarantine_cycles_created > 0 ? "info" : "success");
    await loadCycles();
  } catch (err) {
    notify(`Falha na conexão: ${err.message}`, "error");
  }
});

uploadZone.addEventListener("dragover", (e) => { e.preventDefault(); uploadZone.style.borderColor = "#3b82f6"; });
uploadZone.addEventListener("dragleave", () => { uploadZone.style.borderColor = ""; });
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.style.borderColor = "";
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    csvInput.files = dt.files;
    csvInput.dispatchEvent(new Event("change"));
  }
});

// ---------------------------------------------------------------------------
// Load reference data
// ---------------------------------------------------------------------------
async function loadCycles() {
  try {
    const list = await (await fetch(`${API}/api/cycles`)).json();
    const prev = cycleSelect.value;
    cycleSelect.innerHTML = '<option value="">— Selecione um ciclo —</option>';
    list.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name + (c.is_quarantine ? " ⚠" : "");
      if (c.is_quarantine) opt.style.color = "#fbbf24";
      cycleSelect.appendChild(opt);
    });
    if (prev && [...cycleSelect.options].some((o) => o.value === prev)) cycleSelect.value = prev;
    updateLoadBtn();
  } catch (err) {
    notify(`Erro ao carregar ciclos: ${err.message}`, "error");
  }
}

async function loadPeps() {
  const cycleId = cycleSelect.value;
  const collabId = collaboratorSelect.value;

  const params = new URLSearchParams();
  if (cycleId)  params.set("cycle_id",        cycleId);
  if (collabId) params.set("collaborator_id",  collabId);

  try {
    pepData = await (await fetch(`${API}/api/peps?${params}`)).json();

    const prevCode = pepSelect.value;
    const prevDesc = pepDescSelect.value;

    pepSelect.innerHTML = '<option value="">— Todos os PEPs —</option>';
    pepDescSelect.innerHTML = '<option value="">— Todas as descrições —</option>';

    pepData.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.code;
      opt.textContent = `${p.code}  (${p.total_records} reg.)`;
      pepSelect.appendChild(opt);
    });

    if (prevCode && [...pepSelect.options].some((o) => o.value === prevCode)) {
      pepSelect.value = prevCode;
      populatePepDescriptions(prevCode);
    }
    if (prevDesc && [...pepDescSelect.options].some((o) => o.value === prevDesc))
      pepDescSelect.value = prevDesc;

  } catch (err) {
    notify(`Erro ao carregar PEPs: ${err.message}`, "error");
  }
}

function populatePepDescriptions(code) {
  const entry = pepData.find((p) => p.code === code);
  const prevDesc = pepDescSelect.value;
  pepDescSelect.innerHTML = '<option value="">— Todas as descrições —</option>';
  if (entry) {
    entry.descriptions.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      pepDescSelect.appendChild(opt);
    });
  }
  if (prevDesc && [...pepDescSelect.options].some((o) => o.value === prevDesc))
    pepDescSelect.value = prevDesc;
}

async function loadCollaborators() {
  const cycleId  = cycleSelect.value;
  const pepCode  = pepSelect.value;
  const pepDesc  = pepDescSelect.value;

  const params = new URLSearchParams();
  if (cycleId)  params.set("cycle_id",         cycleId);
  if (pepCode)  params.set("pep_code",          pepCode);
  if (pepDesc)  params.set("pep_description",   pepDesc);

  try {
    const prev = collaboratorSelect.value;
    const list = await (await fetch(`${API}/api/collaborators?${params}`)).json();
    collaboratorSelect.innerHTML = '<option value="">— Todos —</option>';
    list.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      collaboratorSelect.appendChild(opt);
    });
    if (prev && [...collaboratorSelect.options].some((o) => o.value === prev))
      collaboratorSelect.value = prev;
  } catch (err) {
    notify(`Erro ao carregar colaboradores: ${err.message}`, "error");
  }
}

// ---------------------------------------------------------------------------
// Event wiring — cascading dropdowns
// ---------------------------------------------------------------------------
cycleSelect.addEventListener("change", async () => {
  updateLoadBtn();
  await Promise.all([loadPeps(), loadCollaborators()]);
});

pepSelect.addEventListener("change", () => {
  populatePepDescriptions(pepSelect.value);
  loadCollaborators();
});

pepDescSelect.addEventListener("change", () => {
  loadCollaborators();
});

collaboratorSelect.addEventListener("change", () => {
  loadPeps();
});

function updateLoadBtn() {
  loadBtn.disabled = !cycleSelect.value;
}

// ---------------------------------------------------------------------------
// Load dashboard
// ---------------------------------------------------------------------------
loadBtn.addEventListener("click", async () => {
  const cycleId  = cycleSelect.value;
  if (!cycleId) return;

  const pepCode  = pepSelect.value;
  const pepDesc  = pepDescSelect.value;
  const collabId = collaboratorSelect.value;

  const params = new URLSearchParams();
  if (pepCode)  params.set("pep_code",        pepCode);
  if (pepDesc)  params.set("pep_description", pepDesc);
  if (collabId) params.set("collaborator_id", collabId);

  loadBtn.disabled = true;
  loadBtn.textContent = "Carregando…";

  try {
    const res  = await fetch(`${API}/api/dashboard/${cycleId}?${params}`);
    const json = await res.json();
    if (!res.ok) { notify(`Erro: ${json.detail ?? res.statusText}`, "error"); return; }
    renderDashboard(json);
    renderPills(json);
  } catch (err) {
    notify(`Falha ao carregar dashboard: ${err.message}`, "error");
  } finally {
    loadBtn.disabled = false;
    loadBtn.textContent = "Carregar";
  }
});

clearBtn.addEventListener("click", () => {
  pepSelect.value = "";
  pepDescSelect.value = "";
  collaboratorSelect.value = "";
  activePills.innerHTML = "";
  populatePepDescriptions("");
  loadCollaborators();
});

// ---------------------------------------------------------------------------
// Active filter pills
// ---------------------------------------------------------------------------
function renderPills(payload) {
  activePills.innerHTML = "";
  const f = payload.filters;

  const add = (label, clearFn) => {
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.innerHTML = `${label} <button title="Remover filtro">×</button>`;
    pill.querySelector("button").onclick = () => { clearFn(); loadBtn.click(); };
    activePills.appendChild(pill);
  };

  if (f.pep_code)        add(`PEP: ${f.pep_code}`,           () => { pepSelect.value = ""; populatePepDescriptions(""); });
  if (f.pep_description) add(`Desc: ${f.pep_description}`,   () => { pepDescSelect.value = ""; });
  if (f.collaborator_id) {
    const name = collaboratorSelect.options[collaboratorSelect.selectedIndex]?.text || f.collaborator_id;
    add(`Colaborador: ${name}`, () => { collaboratorSelect.value = ""; });
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------
function renderDashboard(payload) {
  const { cycle, data } = payload;

  // Stats
  let totalNormal = 0, totalExtra = 0, totalStandby = 0;
  data.forEach((r) => { totalNormal += r.normal_hours; totalExtra += r.extra_hours; totalStandby += r.standby_hours; });
  const grandTotal = totalNormal + totalExtra + totalStandby;

  document.getElementById("statNormal").textContent  = fmt(totalNormal);
  document.getElementById("statExtra").textContent   = fmt(totalExtra);
  document.getElementById("statStandby").textContent = fmt(totalStandby);
  document.getElementById("statTotal").textContent   = fmt(grandTotal);
  document.getElementById("statCollabs").textContent = data.length;
  statsRow.style.display = "grid";

  // Chart title
  const filters = payload.filters;
  let sub = cycle.name;
  if (filters.pep_code)        sub += `  |  PEP: ${filters.pep_code}`;
  if (filters.pep_description) sub += `  →  ${filters.pep_description}`;
  chartTitle.textContent = sub;

  // ECharts
  const collaborators = data.map((r) => r.collaborator);
  const normalH   = data.map((r) => r.normal_hours);
  const extraH    = data.map((r) => r.extra_hours);
  const standbyH  = data.map((r) => r.standby_hours);

  const maxItems = 40;
  const truncated = collaborators.length > maxItems;
  const colSlice  = truncated ? collaborators.slice(0, maxItems) : collaborators;

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        let html = `<strong>${params[0].axisValue}</strong><br/>`;
        params.forEach((p) => {
          if (p.value > 0)
            html += `${p.marker} ${p.seriesName}: <strong>${p.value.toFixed(2)}h</strong><br/>`;
        });
        return html;
      },
    },
    legend: {
      data: ["Horas Normais", "Horas Extras", "Sobreaviso"],
      textStyle: { color: "#cbd5e1" },
      top: 0,
    },
    grid: { left: "28%", right: "6%", top: "10%", bottom: "5%", containLabel: false },
    xAxis: {
      type: "value",
      name: "Horas",
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8", formatter: (v) => `${v}h` },
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    yAxis: {
      type: "category",
      data: colSlice,
      axisLabel: { color: "#e2e8f0", fontSize: 11, overflow: "truncate", width: 200 },
      axisTick: { show: false },
    },
    series: [
      { name: "Horas Normais", type: "bar", stack: "total", data: truncated ? normalH.slice(0, maxItems)  : normalH,  itemStyle: { color: "#3b82f6" } },
      { name: "Horas Extras",  type: "bar", stack: "total", data: truncated ? extraH.slice(0, maxItems)   : extraH,   itemStyle: { color: "#f59e0b" } },
      { name: "Sobreaviso",    type: "bar", stack: "total", data: truncated ? standbyH.slice(0, maxItems) : standbyH, itemStyle: { color: "#8b5cf6" } },
    ],
    title: {
      text: cycle.is_quarantine ? `${cycle.name}  ⚠ QUARENTENA` : cycle.name,
      subtext: `${cycle.start_date}  →  ${cycle.end_date}${truncated ? `   (top ${maxItems} de ${collaborators.length})` : ""}`,
      textStyle: { color: "#f1f5f9", fontSize: 13 },
      subtextStyle: { color: "#64748b" },
      left: "center",
    },
  };

  chart.setOption(option, { notMerge: true });
}

function fmt(h) {
  return h >= 1000
    ? (h / 1000).toFixed(1) + "k"
    : h.toFixed(1);
}

window.addEventListener("resize", () => chart.resize());

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
loadCycles();
