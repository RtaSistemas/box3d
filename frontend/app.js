/* PMAS — Frontend App (Vanilla JS + Apache ECharts) */

const API = "http://127.0.0.1:8000";

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const csvInput    = document.getElementById("csvInput");
const uploadZone  = document.getElementById("uploadZone");
const notification= document.getElementById("notification");
const cycleSelect = document.getElementById("cycleSelect");
const loadBtn     = document.getElementById("loadBtn");
const chartEl     = document.getElementById("chart");

const chart = echarts.init(chartEl, "dark");

// ---------------------------------------------------------------------------
// Notification helper
// ---------------------------------------------------------------------------
function notify(msg, type = "info") {
  notification.textContent = msg;
  notification.className = type;
  notification.style.display = "block";
  if (type === "success") setTimeout(() => { notification.style.display = "none"; }, 5000);
}

// ---------------------------------------------------------------------------
// Upload CSV
// ---------------------------------------------------------------------------
csvInput.addEventListener("change", async () => {
  const file = csvInput.files[0];
  if (!file) return;

  notify(`Enviando "${file.name}"…`, "info");

  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch(`${API}/api/upload-timesheet`, { method: "POST", body: form });
    const json = await res.json();

    if (!res.ok) {
      notify(`Erro: ${json.detail ?? res.statusText}`, "error");
      return;
    }

    let msg = `✔ ${json.records_inserted} registro(s) importado(s).`;
    if (json.quarantine_cycles_created > 0)
      msg += ` ⚠ ${json.quarantine_cycles_created} ciclo(s) de Quarentena criado(s) para datas órfãs.`;

    notify(msg, json.quarantine_cycles_created > 0 ? "info" : "success");
    await loadCycles();
  } catch (err) {
    notify(`Falha na conexão: ${err.message}`, "error");
  }
});

// Drag-and-drop support on the upload zone
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
// Load cycles into <select>
// ---------------------------------------------------------------------------
async function loadCycles() {
  try {
    const res  = await fetch(`${API}/api/cycles`);
    const list = await res.json();

    const prev = cycleSelect.value;
    cycleSelect.innerHTML = '<option value="">— Selecione um ciclo —</option>';

    list.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;

      const quarTag = c.is_quarantine ? " ⚠ [QUARENTENA]" : "";
      opt.textContent = `${c.name}${quarTag}`;
      if (c.is_quarantine) opt.style.color = "#fbbf24";

      cycleSelect.appendChild(opt);
    });

    // Restore previous selection if still available
    if (prev && [...cycleSelect.options].some((o) => o.value === prev))
      cycleSelect.value = prev;

    loadBtn.disabled = cycleSelect.options.length <= 1;
  } catch (err) {
    notify(`Não foi possível carregar ciclos: ${err.message}`, "error");
  }
}

cycleSelect.addEventListener("change", () => {
  loadBtn.disabled = !cycleSelect.value;
});

// ---------------------------------------------------------------------------
// Load dashboard data and render chart
// ---------------------------------------------------------------------------
loadBtn.addEventListener("click", async () => {
  const cycleId = cycleSelect.value;
  if (!cycleId) return;

  loadBtn.disabled = true;
  loadBtn.textContent = "Carregando…";

  try {
    const res  = await fetch(`${API}/api/dashboard/${cycleId}`);
    const json = await res.json();

    if (!res.ok) {
      notify(`Erro: ${json.detail ?? res.statusText}`, "error");
      return;
    }

    renderChart(json);
  } catch (err) {
    notify(`Falha ao carregar dashboard: ${err.message}`, "error");
  } finally {
    loadBtn.disabled = false;
    loadBtn.textContent = "Carregar Dashboard";
  }
});

// ---------------------------------------------------------------------------
// ECharts — horizontal stacked bar
// ---------------------------------------------------------------------------
function renderChart(payload) {
  const { cycle, data } = payload;

  const collaborators = data.map((r) => r.collaborator);
  const normalHours   = data.map((r) => r.normal_hours);
  const extraHours    = data.map((r) => r.extra_hours);
  const standbyHours  = data.map((r) => r.standby_hours);

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        let html = `<strong>${params[0].axisValue}</strong><br/>`;
        params.forEach((p) => {
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
    grid: { left: "22%", right: "5%", top: "12%", bottom: "5%", containLabel: false },
    xAxis: {
      type: "value",
      name: "Horas",
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8", formatter: (v) => `${v}h` },
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    yAxis: {
      type: "category",
      data: collaborators,
      axisLabel: { color: "#e2e8f0", fontSize: 12 },
      axisTick: { show: false },
    },
    series: [
      {
        name: "Horas Normais",
        type: "bar",
        stack: "total",
        data: normalHours,
        itemStyle: { color: "#3b82f6" },
        label: { show: false },
      },
      {
        name: "Horas Extras",
        type: "bar",
        stack: "total",
        data: extraHours,
        itemStyle: { color: "#f59e0b" },
      },
      {
        name: "Sobreaviso",
        type: "bar",
        stack: "total",
        data: standbyHours,
        itemStyle: { color: "#8b5cf6" },
      },
    ],
    title: {
      text: cycle.name + (cycle.is_quarantine ? "  ⚠ QUARENTENA" : ""),
      subtext: `${cycle.start_date}  →  ${cycle.end_date}`,
      textStyle: { color: "#f1f5f9", fontSize: 14 },
      subtextStyle: { color: "#64748b" },
      left: "center",
    },
  };

  chart.setOption(option, { notMerge: true });
}

// Resize chart with window
window.addEventListener("resize", () => chart.resize());

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
loadCycles();
