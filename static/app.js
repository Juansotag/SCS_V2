/* =============================================================
   app.js — Sabana Centro Sostenible · Dashboard Frontend
   ============================================================= */

// ------------------------------------------------------------------
// State
// ------------------------------------------------------------------
let allRows = [];
let geojsonLayer = null;
let selectedMunicipio = "";
let selectedDimension = "";
let selectedSubscore   = "";   // "" | "Especificidad" | "Vision_Regional" | "Impacto"
let selectedProyecto   = "";   // "" | ID_Proyecto value
let isRadarAggregated  = true; // true = overlaped, false = separate
let chartMunicipio, chartSub, chartDimension;
let radarCharts = {};   // id -> Chart instance
const map = L.map("map", { zoomControl: true }).setView([5.0, -74.0], 10);

// ------------------------------------------------------------------
// Base tile layer (dark)
// ------------------------------------------------------------------
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
  maxZoom: 18,
}).addTo(map);

// ------------------------------------------------------------------
// Colors
// ------------------------------------------------------------------
const SCORE_COLORS = [
  { min: 0,   max: 1,   fill: "#c8f0c8", opacity: 0.55 },
  { min: 1,   max: 2,   fill: "#70d16e", opacity: 0.65 },
  { min: 2,   max: 3,   fill: "#2ecc71", opacity: 0.70 },
  { min: 3,   max: 4,   fill: "#0e8a4a", opacity: 0.80 },
  { min: 4,   max: 5.1, fill: "#054d28", opacity: 0.90 },
];

function scoreColor(v) {
  for (const c of SCORE_COLORS) if (v >= c.min && v < c.max) return c;
  return SCORE_COLORS[0];
}

const CHART_COLORS = {
  Especificidad:  "#2ecc71",
  Vision_Regional:"#1abc9c",
  Impacto:        "#3498db",
  Promedio:       "#9b59b6",
};

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------
function scoreField() {
  return selectedSubscore || "Calificacion_Promedio";
}

function applyFilters(rows) {
  return rows.filter(r => {
    if (selectedMunicipio && r.Municipio  !== selectedMunicipio) return false;
    if (selectedDimension  && r.Dimension  !== selectedDimension)  return false;
    if (selectedProyecto   && r.ID_Proyecto !== selectedProyecto)  return false;
    return true;
  });
}

function groupByAvg(rows, groupKey, valueKey) {
  const acc = {};
  rows.forEach(r => {
    const k = r[groupKey] || "—";
    const v = parseFloat(r[valueKey]);
    if (!isNaN(v)) {
      acc[k] = acc[k] || { sum: 0, n: 0 };
      acc[k].sum += v;
      acc[k].n   += 1;
    }
  });
  return Object.entries(acc)
    .map(([k, { sum, n }]) => ({ label: k, value: +(sum / n).toFixed(2) }))
    .sort((a, b) => b.value - a.value);
}

function scoreBadge(v) {
  const val = parseFloat(v);
  if (isNaN(val)) return "<span style=\"color:#556070\">—</span>";
  if (val === 0) {
    return `<span class="score-badge" style="background:#1e2020;color:#6b7280">${val.toFixed(2)}</span>`;
  }
  // Interpolate hue: 1 → 0° (red), 5 → 120° (green)
  const clamped = Math.max(1, Math.min(5, val));
  const hue = ((clamped - 1) / 4) * 120;           // 0 to 120
  const sat = 70;
  const lit = 38;
  const bgAlpha = 0.18;
  const bg  = `hsla(${hue},${sat}%,${lit}%,${bgAlpha})`;
  const border = `hsl(${hue},${sat}%,${lit}%)`;
  const text   = `hsl(${hue},${sat}%,72%)`;
  return `<span class="score-badge" style="background:${bg};color:${text};border:1px solid ${border}44">${val.toFixed(2)}</span>`;
}

// ------------------------------------------------------------------
// Chart factory
// ------------------------------------------------------------------
function makeBarChart(canvasId, labels, datasets, maxY = 5, horizontal = false) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      indexAxis: horizontal ? "y" : "x",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: datasets.length > 1,
          labels: { color: "#8b949e", font: { size: 11 }, boxWidth: 12 },
        },
        tooltip: {
          backgroundColor: "#1c2230",
          titleColor: "#e6edf3",
          bodyColor: "#8b949e",
          borderColor: "#30363d",
          borderWidth: 1,
          callbacks: {
            label: ctx => ` ${ctx.dataset.label || ""}: ${ctx.parsed[horizontal ? "x" : "y"].toFixed(2)}`
          }
        }
      },
      scales: {
        x: {
          ticks: { color: "#8b949e", font: { size: 10 }, maxRotation: 30 },
          grid:  { color: "#21262d" },
          max: horizontal ? maxY : undefined,
        },
        y: {
          ticks: { color: "#8b949e", font: { size: 10 } },
          grid:  { color: "#21262d" },
          max: horizontal ? undefined : maxY,
          min: 0,
        },
      },
    },
  });
}

// ------------------------------------------------------------------
// Update all 3 charts
// ------------------------------------------------------------------
function updateCharts(rows) {
  const field = scoreField();
  const label = selectedSubscore || "Promedio";

  // ---- Chart 1: avg by municipio ----
  const byMuni = groupByAvg(rows, "Municipio", field);
  if (chartMunicipio) chartMunicipio.destroy();
  chartMunicipio = makeBarChart(
    "chart-municipio",
    byMuni.map(d => d.label),
    [{
      label,
      data: byMuni.map(d => d.value),
      backgroundColor: byMuni.map(d => scoreColor(d.value).fill + "cc"),
      borderColor:     byMuni.map(d => scoreColor(d.value).fill),
      borderWidth: 1,
      borderRadius: 4,
    }],
    5, true
  );

  // ---- Chart 2: subcalificaciones grouped by municipio ----
  const munis2 = [...new Set(rows.map(r => r.Municipio).filter(Boolean))].slice(0, 20);
  const subsFields = ["Especificidad", "Vision_Regional", "Impacto"];
  const sub_datasets = subsFields.map(sub => ({
    label: sub.replace("_", " "),
    data: munis2.map(m => {
      const filtered = rows.filter(r => r.Municipio === m);
      const vals = filtered.map(r => parseFloat(r[sub])).filter(v => !isNaN(v));
      return vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2) : 0;
    }),
    backgroundColor: CHART_COLORS[sub] + "99",
    borderColor:     CHART_COLORS[sub],
    borderWidth: 1,
    borderRadius: 3,
  }));
  if (chartSub) chartSub.destroy();
  chartSub = makeBarChart("chart-subcalificaciones", munis2, sub_datasets, 5, false);

  // ---- Chart 3: by dimension ----
  const byDim = groupByAvg(rows, "Dimension", field);
  if (chartDimension) chartDimension.destroy();
  chartDimension = makeBarChart(
    "chart-dimension",
    byDim.map(d => d.label),
    [{
      label,
      data: byDim.map(d => d.value),
      backgroundColor: "#9b59b699",
      borderColor:     "#9b59b6",
      borderWidth: 1,
      borderRadius: 4,
    }],
    5, true
  );
}

// ------------------------------------------------------------------
// Update table (todos los proyectos filtrados)
// ------------------------------------------------------------------
function updateTable(rows) {
  const field = scoreField();
  const sorted = [...rows]
    .filter(r => !isNaN(parseFloat(r[field])))
    .sort((a, b) => parseFloat(b[field]) - parseFloat(a[field]));

  const muniLabel  = selectedMunicipio || "Todos los municipios";
  const dimLabel   = selectedDimension  || "Todas las dimensiones";
  const projLabel  = selectedProyecto   ? ` · ${selectedProyecto}` : "";
  document.getElementById("table-scope-label").textContent =
    `${muniLabel} · ${dimLabel}${projLabel} — ${sorted.length} proyectos`;

  const tbody = document.getElementById("top-table-body");
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="16" class="empty-row">Sin datos para los filtros seleccionados.</td></tr>`;
    return;
  }
  tbody.innerHTML = buildTableHTML(sorted);
}

// ------------------------------------------------------------------
// Build table HTML rows (shared between mini and full table)
// ------------------------------------------------------------------
function buildTableHTML(sorted) {
  const field = scoreField();
  let html = "";
  sorted.forEach((r, i) => {
    const products = (r.Productos || "—").split(";").map(s => s.trim()).filter(Boolean);
    const codes    = (r.Codigos_MGA || "—").split(",").map(s => s.trim()).filter(Boolean);
    const numRows  = Math.max(products.length, codes.length, 1);

    for (let j = 0; j < numRows; j++) {
      html += "<tr>";
      if (j === 0) {
        const rs = numRows > 1 ? ` rowspan="${numRows}"` : "";
        html += `<td${rs}>${i + 1}</td>`;
        html += `<td${rs}>${r.Municipio || "—"}</td>`;
        html += `<td${rs}><span style="font-size:11px;color:#8b949e">${r.Dimension || "—"}</span></td>`;
        html += `<td${rs} style="font-family:monospace;color:#1abc9c">${r.ID_Proyecto || "—"}</td>`;
        html += `<td${rs} style="max-width:180px">${r.Nombre_Proyecto || "—"}</td>`;
      }
      const code = codes[j] || "";
      const dane = String(r.Codigo_DANE || "").trim();
      if (code && dane) {
        html += `<td style="font-family:monospace;font-size:11px"><a href="/sispt/${dane}?highlight=${encodeURIComponent(code)}" target="_blank" style="color:#1abc9c;text-decoration:none;border-bottom:1px dashed #1abc9c55" title="Ver en SisPT de ${r.Municipio || dane}">${code}</a></td>`;
      } else {
        html += `<td style="font-family:monospace;font-size:11px;color:#1abc9c">${code}</td>`;
      }
      html += `<td style="max-width:240px;font-size:11.5px;color:#adb5bd">${products[j] || ""}</td>`;

      const fin = (r.Finanzas && code) ? r.Finanzas[code] : undefined;
      const f24 = fin ? (fin['2024']||"—") : "—";
      const f25 = fin ? (fin['2025']||"—") : "—";
      const f26 = fin ? (fin['2026']||"—") : "—";
      const f27 = fin ? (fin['2027']||"—") : "—";

      html += `<td style="font-size:10.5px;color:#e6edf3">${f24}</td>`;
      html += `<td style="font-size:10.5px;color:#e6edf3">${f25}</td>`;
      html += `<td style="font-size:10.5px;color:#e6edf3">${f26}</td>`;
      html += `<td style="font-size:10.5px;color:#e6edf3">${f27}</td>`;

      if (j === 0) {
        const rs = numRows > 1 ? ` rowspan="${numRows}"` : "";
        html += `<td${rs}>${scoreBadge(r.Especificidad)}</td>`;
        html += `<td${rs}>${scoreBadge(r.Vision_Regional)}</td>`;
        html += `<td${rs}>${scoreBadge(r.Impacto)}</td>`;
        html += `<td${rs}>${scoreBadge(r.Calificacion_Promedio)}</td>`;
        html += `<td${rs} style="max-width:260px;font-size:11.5px;color:#adb5bd">${r.Justificacion || "—"}</td>`;
      }
      html += "</tr>";
    }
  });
  return html;
}

// ------------------------------------------------------------------
// Update full-table modal (all filtered rows)
// ------------------------------------------------------------------
function updateFullTable(rows) {
  const field = scoreField();
  const sorted = [...rows]
    .filter(r => !isNaN(parseFloat(r[field])))
    .sort((a, b) => parseFloat(b[field]) - parseFloat(a[field]));

  const muniLabel  = selectedMunicipio || "Todos los municipios";
  const dimLabel   = selectedDimension  || "Todas las dimensiones";
  const projLabel  = selectedProyecto   ? ` · ${selectedProyecto}` : "";
  const countLabel = ` · ${sorted.length} registros`;
  document.getElementById("modal-scope-label").textContent =
    `${muniLabel} · ${dimLabel}${projLabel}${countLabel}`;

  const tbody = document.getElementById("full-table-body");
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="16" class="empty-row">Sin datos para los filtros seleccionados.</td></tr>`;
    return;
  }
  tbody.innerHTML = buildTableHTML(sorted);
}
// ------------------------------------------------------------------
// Update map layer colors
// ------------------------------------------------------------------
function updateMapColors(rows) {
  if (!geojsonLayer) return;
  const field = scoreField();
  const muniMap = {};
  rows.forEach(r => {
    const dane = String(r.Codigo_DANE || "").trim();
    const v = parseFloat(r[field]);
    if (dane && !isNaN(v)) {
      muniMap[dane] = muniMap[dane] || { sum: 0, n: 0 };
      muniMap[dane].sum += v;
      muniMap[dane].n   += 1;
    }
  });

  geojsonLayer.eachLayer(layer => {
    const dane = String(layer.feature.properties.MpCodigo || "");
    const entry = muniMap[dane];
    const avg   = entry ? entry.sum / entry.n : 0;
    const c     = scoreColor(avg);
    const isSelected = selectedMunicipio && layer.feature.properties.MpNombre === selectedMunicipio;
    layer.setStyle({
      fillColor:   c.fill,
      fillOpacity: c.opacity,
      color:       isSelected ? "#fff" : "#333",
      weight:      isSelected ? 2.5 : 0.8,
    });
  });
}

// ------------------------------------------------------------------
// Refresh everything
// ------------------------------------------------------------------
function refresh() {
  const rows = applyFilters(allRows);
  updateCharts(rows);
  updateTable(rows);
  updateMapColors(applyFilters(allRows));
  buildRadarCharts(rows);
}

// ------------------------------------------------------------------
// Radar / spider charts (one per dimension)
// ------------------------------------------------------------------
const MUNI_PALETTE = [
  "#2ecc71", "#3498db", "#9b59b6", "#e67e22",
  "#e74c3c", "#1abc9c", "#f39c12", "#d35400",
  "#c0392b", "#8e44ad", "#16a085", "#2980b9",
];

function buildRadarCharts(rows) {
  const grid = document.getElementById("radar-grid");
  const field = scoreField();

  // Axes = unique dimensions present in data
  const dims  = [...new Set(allRows.map(r => r.Dimension).filter(Boolean))].sort();
  // Datasets = unique municipalities present in filtered rows
  const munis = [...new Set(rows.map(r => r.Municipio).filter(Boolean))].sort();

  if (!dims.length) { grid.innerHTML = ""; return; }

  // Build datasets — one per municipality
  const datasets = munis.map((muni, i) => {
    const color = MUNI_PALETTE[i % MUNI_PALETTE.length];
    const isHighlighted = !selectedMunicipio || selectedMunicipio === muni;
    const data = dims.map(dim => {
      const vals = rows
        .filter(r => r.Municipio === muni && r.Dimension === dim)
        .map(r => parseFloat(r[field]))
        .filter(v => !isNaN(v));
      return vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2) : null;
    });
    return {
      label: muni,
      data,
      spanGaps: true,
      borderColor:          color,
      backgroundColor:      color + (isHighlighted ? "25" : "06"),
      pointBackgroundColor: color,
      pointRadius:   isHighlighted ? 5 : 2,
      borderWidth:   isHighlighted ? 2.5 : 1,
      borderDash:    isHighlighted ? [] : [5, 5],
      _color_solid: color,
    };
  });

  const makeOptions = (dsList) => ({
    type: "radar",
    data: { labels: dims, datasets: dsList },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#1c2230",
          titleColor: "#e6edf3",
          bodyColor:  "#8b949e",
          borderColor: "#30363d",
          borderWidth: 1,
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.r != null ? ctx.parsed.r.toFixed(2) : '—'}`,
          },
        },
      },
      scales: {
        r: {
          min: 0,
          max: 5,
          ticks: { stepSize: 1, color: "#556070", font: { size: 9 }, backdropColor: "transparent" },
          grid: { color: "#21262d" },
          angleLines: { color: "#30363d" },
          pointLabels: { color: "#adb5bd", font: { size: window.innerWidth < 800 ? 9 : 11, weight: "500" } },
        },
      },
    },
  });

  if (isRadarAggregated) {
    if (!document.getElementById("radar-main")) {
      grid.innerHTML = `
        <div class="radar-card radar-card-single" style="width:100%">
          <div class="radar-card-title">Calificación por dimensión · cada línea = un municipio</div>
          <div class="radar-wrap-large"><canvas id="radar-main"></canvas></div>
          <div class="radar-legend" id="radar-legend"></div>
        </div>`;
    }

    if (radarCharts["main"]) {
      radarCharts["main"].data.labels   = dims;
      radarCharts["main"].data.datasets = datasets;
      radarCharts["main"].update("none");
    } else {
      const ctx = document.getElementById("radar-main").getContext("2d");
      radarCharts["main"] = new Chart(ctx, makeOptions(datasets));
    }

    const legend = document.getElementById("radar-legend");
    if (legend) {
      legend.innerHTML = datasets.map(d => {
        const active = !selectedMunicipio || selectedMunicipio === d.label;
        return `<span class="radar-leg-item${active ? "" : " radar-leg-dim"}" style="--c:${d._color_solid}">${d.label}</span>`;
      }).join("");
    }

  } else {
    // Segregated view
    const ids = datasets.map(d => `radar-sep-${d.label.replace(/\s+/g,'')}`);
    
    // Check if DOM has these elements
    const hasAll = ids.every(id => document.getElementById(id));
    if (!hasAll) {
      grid.innerHTML = datasets.map((d, i) => `
        <div class="radar-card" style="flex: 1 1 300px; min-height: 350px;">
          <div class="radar-card-title" style="color:${d._color_solid}">${d.label}</div>
          <div class="radar-wrap" style="height:300px"><canvas id="${ids[i]}"></canvas></div>
        </div>`).join("");
      radarCharts = {}; // reset to bind to new canvases
    }

    datasets.forEach((ds, i) => {
      const id = ids[i];
      // modify dataset to look nice when alone
      const singleDs = { ...ds, backgroundColor: ds._color_solid + "25", borderWidth: 2, borderDash: [] };
      if (radarCharts[id]) {
        radarCharts[id].data.labels = dims;
        radarCharts[id].data.datasets = [singleDs];
        radarCharts[id].update("none");
      } else {
        const ctx = document.getElementById(id).getContext("2d");
        radarCharts[id] = new Chart(ctx, makeOptions([singleDs]));
      }
    });
  }
}

// ------------------------------------------------------------------
// Load GeoJSON & data
// ------------------------------------------------------------------
async function loadGeoJSON() {
  const res  = await fetch("/api/geojson");
  const data = await res.json();

  geojsonLayer = L.geoJSON(data, {
    style: { fillColor: "#2ecc7133", fillOpacity: 0.4, color: "#333", weight: 0.8 },
    onEachFeature(feature, layer) {
      const name = feature.properties.MpNombre;
      const dane = feature.properties.MpCodigo;
      layer.on("click", () => {
        if (selectedMunicipio === name) {
          selectedMunicipio = "";
          document.getElementById("filter-municipio").value = "";
        } else {
          selectedMunicipio = name;
          document.getElementById("filter-municipio").value = name;
        }
        refresh();
      });
      layer.on("mouseover", function(e) {
        const rows = allRows.filter(r => String(r.Codigo_DANE).trim() === String(dane));
        const avg = rows.length
          ? (rows.reduce((a, r) => a + parseFloat(r.Calificacion_Promedio || 0), 0) / rows.length).toFixed(2)
          : "Sin datos";
        const esp = rows.length
          ? (rows.reduce((a, r) => a + parseFloat(r.Especificidad || 0), 0) / rows.length).toFixed(2)
          : "—";
        const vis = rows.length
          ? (rows.reduce((a, r) => a + parseFloat(r.Vision_Regional || 0), 0) / rows.length).toFixed(2)
          : "—";
        const imp = rows.length
          ? (rows.reduce((a, r) => a + parseFloat(r.Impacto || 0), 0) / rows.length).toFixed(2)
          : "—";
        layer.bindPopup(`
          <div class="popup-title">${name}</div>
          <div class="popup-row"><span class="popup-label">Promedio:</span><span>${avg}</span></div>
          <div class="popup-row"><span class="popup-label">Especificidad:</span><span>${esp}</span></div>
          <div class="popup-row"><span class="popup-label">Visión Regional:</span><span>${vis}</span></div>
          <div class="popup-row"><span class="popup-label">Impacto:</span><span>${imp}</span></div>
          <div style="margin-top:6px;font-size:11px;color:#8b949e">Clic para filtrar</div>
        `).openPopup(e.latlng);
      });
      layer.on("mouseout", () => layer.closePopup());
    },
  }).addTo(map);

  map.fitBounds(geojsonLayer.getBounds(), { padding: [10, 10] });
}

async function loadData() {
  const res  = await fetch("/api/data");
  const data = await res.json();
  allRows = data.rows || [];

  // Populate municipality filter from data
  const muniSel = document.getElementById("filter-municipio");
  (data.municipalities || []).forEach(m => {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    muniSel.appendChild(opt);
  });

  // Populate dimension filter
  const dimSel = document.getElementById("filter-dimension");
  (data.dimensions || []).forEach(d => {
    const opt = document.createElement("option");
    opt.value = d; opt.textContent = d;
    dimSel.appendChild(opt);
  });

  // Populate proyecto filter
  const projSel = document.getElementById("filter-proyecto");
  (data.projects || []).forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.id} – ${p.nombre}`;
    projSel.appendChild(opt);
  });

  // Update badge
  document.getElementById("last-updated").textContent =
    `${allRows.length} registros · ${data.municipalities.length} municipios · ${(data.projects||[]).length} proyectos`;

  refresh();
}

// ------------------------------------------------------------------
// Filter event listeners
// ------------------------------------------------------------------
document.getElementById("filter-dimension").addEventListener("change", e => {
  selectedDimension = e.target.value;
  refresh();
});
document.getElementById("filter-subscore").addEventListener("change", e => {
  selectedSubscore = e.target.value;
  refresh();
});
document.getElementById("filter-municipio").addEventListener("change", e => {
  selectedMunicipio = e.target.value;
  refresh();
});
document.getElementById("btn-reset").addEventListener("click", () => {
  selectedMunicipio = "";
  selectedDimension = "";
  selectedSubscore  = "";
  selectedProyecto  = "";
  document.getElementById("filter-municipio").value  = "";
  document.getElementById("filter-dimension").value  = "";
  document.getElementById("filter-subscore").value   = "";
  document.getElementById("filter-proyecto").value   = "";
  refresh();
});

document.getElementById("radar-toggle").addEventListener("click", () => {
  isRadarAggregated = !isRadarAggregated;
  document.getElementById("radar-toggle").textContent = isRadarAggregated ? "Separar Municipios" : "Unir Municipios";
  
  // Destroy old charts to clean up memory
  Object.values(radarCharts).forEach(c => c.destroy());
  radarCharts = {};
  
  refresh();
});

// Filter: proyecto
document.getElementById("filter-proyecto").addEventListener("change", e => {
  selectedProyecto = e.target.value;
  refresh();
});

// Modal: Ampliar / Cerrar
function openTableModal() {
  const rows = applyFilters(allRows);
  updateFullTable(rows);
  const modal = document.getElementById("table-modal");
  modal.style.display = "flex";
  document.body.style.overflow = "hidden";
}
function closeTableModal() {
  document.getElementById("table-modal").style.display = "none";
  document.body.style.overflow = "";
}

document.getElementById("btn-expand-table").addEventListener("click", openTableModal);
document.getElementById("btn-close-modal").addEventListener("click", closeTableModal);
document.getElementById("table-modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeTableModal();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeTableModal();
});

// ------------------------------------------------------------------
// Boot
// ------------------------------------------------------------------
(async () => {
  await Promise.all([loadGeoJSON(), loadData()]);
})();
