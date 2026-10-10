"""Export GWR results to a lightweight GeoJSON and write a Leaflet + Chart.js dashboard to dashboard/index.html.

View it with:  python -m http.server 8000 --directory dashboard   ->   http://localhost:8000
(The page fetches cook_county_data.geojson, so it must be served over HTTP, not opened as a file.)
"""

import json
import os
from pathlib import Path

# The user's shell exports miniconda's GDAL/PROJ paths, which break the wheels' bundled copies
for var in ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_DATA", "PROJ_LIB"):
    os.environ.pop(var, None)

import geopandas as gpd

ROOT = Path(__file__).resolve().parent
IN_PATH = ROOT / "data" / "cook_county_gwr_results.gpkg"
LAYER = "tracts_2022"
OUT_DIR = ROOT / "dashboard"
GEOJSON_PATH = OUT_DIR / "cook_county_data.geojson"
HTML_PATH = OUT_DIR / "index.html"

SIMPLIFY_M = 5  # geometry simplification tolerance in UTM meters (invisible at tract zoom levels)
COORD_PRECISION = 5  # ~1 m in lon/lat

# output property -> (source column, decimals)
PROPERTIES = {
    "geoid": ("GEOID", None),
    "name": ("NAMELSAD", None),
    "lst": ("lst_c", 2),
    "r2": ("gwr_local_r2", 3),
    "b_canopy": ("gwr_beta_tree_canopy_pct", 3),
    "t_canopy": ("gwr_t_tree_canopy_pct", 2),
    "sig_canopy": ("gwr_sig_tree_canopy_pct", None),
    "lisa": ("lisa_cluster", None),
    "canopy": ("tree_canopy_pct", 1),
    "imperv": ("impervious_pct", 1),
    "poverty": ("poverty_rate", 1),
    "income": ("median_income", 0),
    "minority": ("minority_rate", 1),
    "elderly": ("elderly_rate", 1),
    "renter": ("renter_rate", 1),
}


def export_geojson():
    gdf = gpd.read_file(IN_PATH, layer=LAYER)
    # The all-water Lake Michigan tract has no model results; leaving it out keeps the map honest
    gdf = gdf[gdf["gwr_local_r2"].notna()].copy()
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_M, preserve_topology=True)

    out = gpd.GeoDataFrame(geometry=gdf.geometry.to_crs(4326), index=gdf.index)
    for prop, (col, decimals) in PROPERTIES.items():
        out[prop] = gdf[col].round(decimals) if decimals is not None else gdf[col]
    out["sig_canopy"] = out["sig_canopy"].astype(bool)
    out["income"] = out["income"].astype(int)

    OUT_DIR.mkdir(exist_ok=True)
    GEOJSON_PATH.unlink(missing_ok=True)
    out.to_file(GEOJSON_PATH, driver="GeoJSON", COORDINATE_PRECISION=COORD_PRECISION, RFC7946="YES")
    size_mb = GEOJSON_PATH.stat().st_size / 1e6
    print(f"Exported {len(out)} tracts to {GEOJSON_PATH.relative_to(ROOT)} ({size_mb:.2f} MB)")
    return len(out)


def write_html(n_tracts):
    HTML_PATH.write_text(HTML.replace("__N_TRACTS__", f"{n_tracts:,}"), encoding="utf-8")
    print(f"Wrote {HTML_PATH.relative_to(ROOT)}")


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cook County Heat Vulnerability</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --accent: #2a78d6;
  --accent-wash: rgba(42, 120, 214, 0.10);
  --series-1: #2a78d6;
  --tract-line: rgba(255, 255, 255, 0.7);
  /* diverging blue <-> red, gray midpoint */
  --div-c3: #104281; --div-c2: #2a78d6; --div-c1: #9ec5f4; --div-0: #f0efec;
  --div-w1: #f6b8b3; --div-w2: #e34948; --div-w3: #a01c22;
  /* sequential blue */
  --seq-1: #b7d3f6; --seq-2: #86b6ef; --seq-3: #3987e5; --seq-4: #1c5cab; --seq-5: #0d366b;
  /* LISA clusters */
  --lisa-hh: #e34948; --lisa-hl: #eda100; --lisa-lh: #1baf7a; --lisa-ll: #2a78d6; --lisa-ns: #d4d3cc;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255, 255, 255, 0.10);
    --accent: #3987e5; --accent-wash: rgba(57, 135, 229, 0.16); --series-1: #3987e5;
    --tract-line: rgba(26, 26, 25, 0.7);
    --div-0: #383835;
    --lisa-hh: #e34948; --lisa-hl: #c98500; --lisa-lh: #199e70; --lisa-ll: #3987e5; --lisa-ns: #4a4a46;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255, 255, 255, 0.10);
  --accent: #3987e5; --accent-wash: rgba(57, 135, 229, 0.16); --series-1: #3987e5;
  --tract-line: rgba(26, 26, 25, 0.7);
  --div-0: #383835;
  --lisa-hh: #e34948; --lisa-hl: #c98500; --lisa-lh: #199e70; --lisa-ll: #3987e5; --lisa-ns: #4a4a46;
}

* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body {
  background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  display: flex; flex-direction: column;
}
header { padding: 14px 20px 12px; border-bottom: 1px solid var(--border); background: var(--surface); }
header h1 { margin: 0; font-size: 18px; font-weight: 650; letter-spacing: -0.01em; }
header p { margin: 2px 0 0; color: var(--ink-2); font-size: 13px; }

.layout { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 400px; }
.map-col { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.layer-bar {
  display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px;
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.layer-bar button {
  font: inherit; font-size: 13px; padding: 6px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: transparent; color: var(--ink-2);
}
.layer-bar button:hover { background: var(--accent-wash); color: var(--ink); }
.layer-bar button[aria-checked="true"] { background: var(--ink); color: var(--surface); border-color: var(--ink); }
.layer-bar button:focus-visible, .panel input:focus-visible, .legend input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
#map { flex: 1; min-height: 0; background: var(--page); }

.panel { min-width: 0; overflow-y: auto; background: var(--surface); border-left: 1px solid var(--border); padding: 16px 18px 24px; }
.search label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.search input {
  width: 100%; font: inherit; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--page); color: var(--ink);
}
.search .hint { font-size: 12px; color: var(--muted); min-height: 1.4em; margin-top: 4px; }

.empty { color: var(--ink-2); margin-top: 18px; }
.empty h2, .card h2 { font-size: 16px; margin: 18px 0 2px; font-weight: 650; }
.card .geoid { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0 6px; }
.stat { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.stat .k { font-size: 12px; color: var(--muted); }
.stat .v { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin-top: 2px; }
.stat .s { font-size: 12px; color: var(--ink-2); margin-top: 2px; }
.stat.wide { grid-column: 1 / -1; }
.cluster { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; display: inline-block; }
.note { font-size: 12px; color: var(--ink-2); }
.section-title { font-size: 13px; font-weight: 600; margin: 20px 0 2px; }
.chart-box { position: relative; height: 270px; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 8px; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 5px 4px; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; }
details summary { cursor: pointer; font-size: 12.5px; color: var(--ink-2); margin-top: 10px; }

.legend {
  background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; font: 12px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; min-width: 190px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.legend .title { font-weight: 600; margin-bottom: 6px; }
.legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; font-variant-numeric: tabular-nums; }
.legend .foot { color: var(--muted); margin-top: 6px; max-width: 220px; }
.legend label { display: flex; gap: 6px; align-items: center; margin-top: 6px; color: var(--ink-2); cursor: pointer; }
.leaflet-tooltip.tract-tip {
  background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); font: 12.5px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.leaflet-tooltip.tract-tip::before { display: none; }
/* OSM standard tiles, muted so they don't compete with the choropleth (CARTO basemaps now require an API key) */
.leaflet-tile-pane { filter: grayscale(1) brightness(1.06) contrast(0.82); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .leaflet-tile-pane { filter: grayscale(1) invert(1) brightness(0.82) contrast(0.85); }
}
:root[data-theme="dark"] .leaflet-tile-pane { filter: grayscale(1) invert(1) brightness(0.82) contrast(0.85); }
.leaflet-container { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.leaflet-control-attribution { background: var(--surface) !important; color: var(--muted) !important; }
.leaflet-control-attribution a { color: var(--ink-2) !important; }
.loading { position: absolute; inset: 0; display: grid; place-items: center; color: var(--ink-2); z-index: 500; pointer-events: none; }

@media (max-width: 860px) {
  body { height: auto; }
  .layout { grid-template-columns: minmax(0, 1fr); }
  .legend { min-width: 0; padding: 8px 10px; font-size: 11.5px; }
  .legend .foot { display: none; }
  #map { height: 62vh; flex: none; }
  .panel { border-left: none; border-top: 1px solid var(--border); padding: 16px; }
  header { padding: 12px 16px; }
  .layer-bar { padding: 8px 16px; }
}
</style>
</head>
<body>
<header>
  <h1>Cook County Heat Vulnerability</h1>
  <p>Summer 2022 land surface temperature, tree canopy and geographically weighted regression results for __N_TRACTS__ census tracts</p>
</header>
<main class="layout">
  <section class="map-col">
    <div class="layer-bar" role="radiogroup" aria-label="Map layer">
      <button role="radio" data-layer="lst" aria-checked="true">Land surface temperature</button>
      <button role="radio" data-layer="r2" aria-checked="false">GWR local R²</button>
      <button role="radio" data-layer="beta" aria-checked="false">Tree canopy effect (local β)</button>
      <button role="radio" data-layer="lisa" aria-checked="false">LISA heat hotspots</button>
    </div>
    <div id="map" style="position:relative"><div class="loading" id="loading">Loading tracts…</div></div>
  </section>
  <aside class="panel" aria-live="polite">
    <div class="search">
      <label for="search">Find a tract</label>
      <input id="search" list="tract-list" placeholder="GEOID, tract code or number, e.g. 2916" autocomplete="off">
      <datalist id="tract-list"></datalist>
      <div class="hint" id="search-hint"></div>
    </div>
    <div id="inspector">
      <div class="empty">
        <h2>Select a census tract</h2>
        <p>Click any tract on the map, or search above, to see its temperature, tree canopy, local regression results and how its vulnerability predictors compare with the Cook County average.</p>
        <div class="stats" id="county-stats"></div>
      </div>
    </div>
  </aside>
</main>

<script>
const DATA_URL = "cook_county_data.geojson";
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = (v, d = 1) => v == null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), d);

// Predictors summarized in the inspector chart (all tract-level; county stats are unweighted tract means)
const PREDICTORS = [
  { key: "lst", label: "Land surface temp.", unit: " °C", d: 1 },
  { key: "canopy", label: "Tree canopy", unit: "%", d: 1 },
  { key: "imperv", label: "Impervious surface", unit: "%", d: 1 },
  { key: "poverty", label: "Poverty rate", unit: "%", d: 1 },
  { key: "income", label: "Median income", unit: "", d: 0, money: true },
  { key: "minority", label: "Minority (non-white)", unit: "%", d: 1 },
  { key: "elderly", label: "Age 65+", unit: "%", d: 1 },
  { key: "renter", label: "Renter-occupied", unit: "%", d: 1 },
];
const LISA = {
  "High-High": { token: "--lisa-hh", label: "High-High (hotspot)" },
  "High-Low": { token: "--lisa-hl", label: "High-Low (hot outlier)" },
  "Low-High": { token: "--lisa-lh", label: "Low-High (cool outlier)" },
  "Low-Low": { token: "--lisa-ll", label: "Low-Low (coldspot)" },
  "Not Significant": { token: "--lisa-ns", label: "Not significant" },
};
const DIV = ["--div-c3", "--div-c2", "--div-c1", "--div-0", "--div-w1", "--div-w2", "--div-w3"];
const SEQ = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5"];

let features = [], stats = {}, layerKey = "lst", fadeInsig = true, selected = null, geo, map, tiles, legend, chart;

function computeStats() {
  for (const p of [...PREDICTORS, { key: "r2" }, { key: "b_canopy" }]) {
    const vals = features.map(f => f.properties[p.key]).filter(v => v != null);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (vals.length - 1));
    stats[p.key] = { mean, sd };
  }
}

// --- Layers: each returns { color(props), bins: [{token, label}], title, foot, value(props) } ---
function lstLayer() {
  const { mean, sd } = stats.lst;
  const edges = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map(k => mean + k * sd);
  const bins = DIV.map((token, i) => {
    const lo = edges[i - 1], hi = edges[i];
    const label = i === 0 ? `< ${fmt(hi)} °C` : i === DIV.length - 1 ? `≥ ${fmt(lo)} °C` : `${fmt(lo)} – ${fmt(hi)} °C`;
    return { token, label };
  });
  return {
    title: "Mean summer land surface temp.",
    bins, foot: `Centered on the county tract mean (${fmt(mean)} °C); classes are 1 SD (${fmt(sd)} °C) wide.`,
    color: p => css(DIV[binIndex(p.lst, edges)]),
    value: p => `${fmt(p.lst)} °C`,
  };
}
function r2Layer() {
  const edges = [0.5, 0.65, 0.8, 0.9];
  const labels = ["< 0.50", "0.50 – 0.65", "0.65 – 0.80", "0.80 – 0.90", "≥ 0.90"];
  return {
    title: "GWR local R²",
    bins: SEQ.map((token, i) => ({ token, label: labels[i] })),
    foot: "Share of LST variation explained by the local model (canopy, deprivation, impervious).",
    color: p => css(SEQ[binIndex(p.r2, edges)]),
    value: p => `Local R² ${fmt(p.r2, 2)}`,
  };
}
function betaLayer() {
  const edges = [-1.5, -0.75, -0.25, 0.25, 0.75, 1.5];
  const labels = ["< −1.5 (strong cooling)", "−1.5 – −0.75", "−0.75 – −0.25", "−0.25 – 0.25 (little effect)", "0.25 – 0.75", "0.75 – 1.5", "≥ 1.5 (warming)"];
  return {
    title: "Tree canopy effect on LST (local β)",
    bins: DIV.map((token, i) => ({ token, label: labels[i] })),
    foot: "Standardized local coefficient. Blue = more canopy goes with cooler surfaces here.",
    toggle: true,
    color: p => css(DIV[binIndex(p.b_canopy, edges)]),
    opacity: p => (fadeInsig && !p.sig_canopy ? 0.18 : 0.78),
    value: p => `β ${signed(p.b_canopy, 2)}${p.sig_canopy ? " · significant" : " · not significant"}`,
  };
}
function lisaLayer() {
  return {
    title: "LISA clusters of LST (p < 0.05)",
    bins: Object.values(LISA).map(c => ({ token: c.token, label: c.label })),
    foot: "Local Moran's I on summer LST with Queen contiguity, 999 permutations.",
    color: p => css(LISA[p.lisa]?.token ?? "--lisa-ns"),
    opacity: p => (p.lisa === "Not Significant" ? 0.35 : 0.8),
    value: p => LISA[p.lisa]?.label ?? "—",
  };
}
const LAYERS = { lst: lstLayer, r2: r2Layer, beta: betaLayer, lisa: lisaLayer };
const binIndex = (v, edges) => { let i = 0; while (i < edges.length && v >= edges[i]) i++; return i; };

function styleFor(layer) {
  return f => {
    const isSel = selected && f.properties.geoid === selected.properties.geoid;
    return {
      fillColor: layer.color(f.properties),
      fillOpacity: layer.opacity ? layer.opacity(f.properties) : 0.78,
      color: isSel ? css("--ink") : css("--tract-line"),
      weight: isSel ? 2.5 : 0.5,
    };
  };
}

function render() {
  const layer = LAYERS[layerKey]();
  geo.setStyle(styleFor(layer));
  if (selected) selected.layer.bringToFront();
  geo.eachLayer(l => l.setTooltipContent(tipHtml(l.feature.properties, layer)));
  legend.update(layer);
}

function tipHtml(p, layer) {
  return `<strong>${p.name}</strong><br>${layer.value(p)}`;
}

// --- Inspector ---
function inspect(f) {
  selected = f ? { properties: f.properties, layer: f.layer } : null;
  render();
  const p = f.properties;
  history.replaceState(null, "", `${location.search}#${p.geoid}`);
  const lisa = LISA[p.lisa];
  const slopeC = p.b_canopy * stats.lst.sd / stats.canopy.sd;  // back-transform standardized β to °C per canopy point
  const lstDiff = p.lst - stats.lst.mean;
  document.getElementById("inspector").innerHTML = `
    <div class="card">
      <h2>${p.name}</h2>
      <div class="geoid">GEOID ${p.geoid}</div>
      <div class="stats">
        <div class="stat"><div class="k">Land surface temp.</div><div class="v">${fmt(p.lst)} °C</div>
          <div class="s">${signed(lstDiff, 1)} °C vs county avg</div></div>
        <div class="stat"><div class="k">Tree canopy</div><div class="v">${fmt(p.canopy)}%</div>
          <div class="s">County avg ${fmt(stats.canopy.mean)}%</div></div>
        <div class="stat"><div class="k">Local β, tree canopy</div><div class="v">${signed(p.b_canopy, 2)}</div>
          <div class="s">${p.sig_canopy ? "Significant" : "Not significant"} (t = ${fmt(p.t_canopy, 2)})</div></div>
        <div class="stat"><div class="k">Local R²</div><div class="v">${fmt(p.r2, 2)}</div>
          <div class="s">County avg ${fmt(stats.r2.mean, 2)}</div></div>
        <div class="stat wide"><div class="k">LISA heat cluster</div>
          <div class="v" style="font-size:16px"><span class="cluster"><span class="swatch" style="background:${css(lisa?.token ?? "--lisa-ns")}"></span>${lisa?.label ?? "—"}</span></div></div>
      </div>
      <p class="note">${p.sig_canopy
        ? `Locally, each extra percentage point of tree canopy goes with <strong>${signed(slopeC, 2)} °C</strong> of surface
           temperature, holding deprivation and impervious surface constant (standardized β ${signed(p.b_canopy, 2)}).`
        : `The local tree canopy effect here (${signed(slopeC, 2)} °C per canopy point) is not statistically
           significant after correcting for multiple testing.`}</p>
      <div class="section-title">Vulnerability predictors vs. Cook County average</div>
      <div class="note">Standard deviations from the county tract average (0 = average)</div>
      <div class="chart-box"><canvas id="chart" role="img" aria-label="Bar chart of this tract's predictors in standard deviations from the Cook County average"></canvas></div>
      <details open><summary>Table view</summary>
        <table><thead><tr><th>Predictor</th><th>This tract</th><th>County avg</th></tr></thead>
        <tbody>${PREDICTORS.map(d => `<tr><td>${d.label}</td><td>${val(d, p[d.key])}</td><td>${val(d, stats[d.key].mean)}</td></tr>`).join("")}</tbody></table>
      </details>
    </div>`;
  drawChart(p);
}

const val = (d, v) => d.money ? "$" + fmt(v, 0) : fmt(v, d.d) + d.unit;

function drawChart(p) {
  if (chart) chart.destroy();
  const z = PREDICTORS.map(d => (p[d.key] - stats[d.key].mean) / stats[d.key].sd);
  const ink2 = css("--ink-2"), muted = css("--muted"), grid = css("--grid"), axis = css("--axis");
  chart = new Chart(document.getElementById("chart"), {
    type: "bar",
    data: {
      labels: PREDICTORS.map(d => d.label),
      datasets: [{ data: z.map(v => Math.max(-3, Math.min(3, v))), backgroundColor: css("--series-1"),
                   borderRadius: 4, borderSkipped: false, barThickness: 14 }],
    },
    options: {
      indexAxis: "y", maintainAspectRatio: false, animation: { duration: 250 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: ink2,
          borderColor: css("--border"), borderWidth: 1, padding: 10, displayColors: false,
          callbacks: {
            label: ctx => {
              const d = PREDICTORS[ctx.dataIndex];
              return [`This tract: ${val(d, p[d.key])}`, `County avg: ${val(d, stats[d.key].mean)}`, `${signed(z[ctx.dataIndex], 2)} SD`];
            },
          },
        },
      },
      scales: {
        x: {
          min: -3, max: 3, ticks: { stepSize: 1, color: muted, callback: v => (v > 0 ? "+" : "") + v },
          grid: { color: c => (c.tick.value === 0 ? axis : grid), lineWidth: c => (c.tick.value === 0 ? 1.5 : 1) },
          border: { display: false },
        },
        y: { ticks: { color: ink2, font: { size: 12 } }, grid: { display: false }, border: { display: false } },
      },
    },
  });
}

function countySummary() {
  const n = features.length;
  const hh = features.filter(f => f.properties.lisa === "High-High").length;
  const sig = features.filter(f => f.properties.sig_canopy && f.properties.b_canopy < 0).length;
  document.getElementById("county-stats").innerHTML = `
    <div class="stat"><div class="k">Mean summer LST</div><div class="v">${fmt(stats.lst.mean)} °C</div></div>
    <div class="stat"><div class="k">Mean tree canopy</div><div class="v">${fmt(stats.canopy.mean)}%</div></div>
    <div class="stat"><div class="k">Heat hotspot tracts</div><div class="v">${hh}</div><div class="s">${fmt(100 * hh / n, 0)}% of ${n.toLocaleString()} tracts</div></div>
    <div class="stat"><div class="k">Significant canopy cooling</div><div class="v">${sig}</div><div class="s">tracts with significant negative β</div></div>`;
}

// --- Map setup ---

function buildLegend() {
  const ctl = L.control({ position: "bottomright" });
  ctl.onAdd = () => {
    const div = L.DomUtil.create("div", "legend");
    L.DomEvent.disableClickPropagation(div);
    ctl.div = div;
    return div;
  };
  ctl.update = layer => {
    ctl.div.innerHTML = `<div class="title">${layer.title}</div>` +
      layer.bins.map(b => `<div class="row"><span class="swatch" style="background:${css(b.token)}"></span>${b.label}</div>`).join("") +
      (layer.toggle ? `<label><input type="checkbox" id="fade" ${fadeInsig ? "checked" : ""}> Fade non-significant tracts</label>` : "") +
      `<div class="foot">${layer.foot}</div>`;
    const box = ctl.div.querySelector("#fade");
    if (box) box.addEventListener("change", e => { fadeInsig = e.target.checked; render(); });
  };
  return ctl;
}

function selectByQuery(q) {
  q = q.trim().toLowerCase().replace(/^census tract\s*/, "");
  const hint = document.getElementById("search-hint");
  if (!q) { hint.textContent = ""; return; }
  const f = features.find(f => f.properties.geoid === q || f.properties.geoid.slice(5) === q.padStart(6, "0") ||
                                f.properties.name.toLowerCase() === `census tract ${q}`);
  if (!f) { hint.textContent = `No Cook County tract matches “${q}”.`; return; }
  hint.textContent = "";
  map.fitBounds(f.layer.getBounds(), { maxZoom: 13, padding: [40, 40] });
  inspect(f);
}

async function init() {
  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([41.84, -87.75], 10);
  // Leaflet measures the container once; re-measure whenever the flex/grid layout resizes it
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("map"));
  tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    render(); if (selected) inspect(selected);
  });

  const data = await (await fetch(DATA_URL)).json();
  features = data.features;
  computeStats();

  geo = L.geoJSON(data, {
    onEachFeature: (f, layer) => {
      f.layer = layer;
      layer.bindTooltip("", { sticky: true, className: "tract-tip", direction: "top", offset: [0, -8] });
      layer.on("click", () => inspect(f));
      layer.on("mouseover", () => layer.setStyle({ weight: 2, color: css("--ink") }));
      layer.on("mouseout", () => geo.resetStyle(layer) || render());
    },
  }).addTo(map);
  geo.options.style = styleFor(LAYERS[layerKey]());
  map.invalidateSize();
  map.fitBounds(geo.getBounds(), { padding: [10, 10] });

  legend = buildLegend().addTo(map);
  render();
  countySummary();
  document.getElementById("loading").remove();

  document.getElementById("tract-list").innerHTML =
    features.map(f => `<option value="${f.properties.geoid}">${f.properties.name}</option>`).join("");
  const search = document.getElementById("search");
  search.addEventListener("change", () => selectByQuery(search.value));
  search.addEventListener("keydown", e => { if (e.key === "Enter") selectByQuery(search.value); });

  const buttons = document.querySelectorAll(".layer-bar button");
  const setLayer = key => {
    if (!LAYERS[key]) return;
    buttons.forEach(b => b.setAttribute("aria-checked", b.dataset.layer === key));
    layerKey = key;
    geo.options.style = styleFor(LAYERS[layerKey]());
    render();
    const url = new URL(location.href);
    url.searchParams.set("layer", key);
    history.replaceState(null, "", url);
  };
  buttons.forEach(btn => btn.addEventListener("click", () => setLayer(btn.dataset.layer)));
  setLayer(new URLSearchParams(location.search).get("layer") || "lst");

  const fromHash = location.hash.slice(1);
  if (fromHash) selectByQuery(fromHash);
}

init().catch(err => {
  document.getElementById("loading").textContent =
    `Could not load ${DATA_URL} (${err.message}). Serve this folder over HTTP: python -m http.server 8000`;
});
</script>
</body>
</html>
"""


def main():
    n = export_geojson()
    write_html(n)
    print("View with: python -m http.server 8000 --directory dashboard  ->  http://localhost:8000")


if __name__ == "__main__":
    main()
