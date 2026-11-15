/* Burn Calendar — harmonized MODIS + VIIRS hotspot calendar.
   Everything runs in the browser from static files produced by pipeline/harmonize.py.
   AI disclosure: written with assistance from Claude (Anthropic), an AI assistant. */
"use strict";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

// Ember ramp (light → dark, monotonic lightness, readable with colour-vision deficiencies)
const RAMP = ["#fbe9b7", "#f8cc7a", "#f2a24c", "#e17330", "#c24b1f", "#92301a", "#5c1e13"];
const ZERO = "#e4e7e2";
// Diverging: below normal (teal) ↔ above normal (ember)
const DIV = ["#1f6b72", "#5fa3a6", "#b7d6d3", "#eeeee9", "#f4c7a4", "#e07d4c", "#b23a1c", "#6b2010"];
const DIV_BREAKS = [0.25, 0.5, 0.8, 1.25, 2, 4, 8];   // ratio to the normal (median) month
const DIV_LABELS = ["< ¼×", "¼–½×", "½–0.8×", "≈ normal", "1.25–2×", "2–4×", "4–8×", "> 8×"];

const PRESETS = [
  { name: "All of Argentina", all: true },
  { name: "Paraná River Delta (Entre Ríos / Buenos Aires)", b: [-32.6, -34.3, -60.9, -58.4] },
  { name: "Córdoba hills (Sierras de Córdoba)", b: [-30.4, -32.6, -65.4, -63.9] },
  { name: "Dry Chaco (Santiago del Estero / Chaco / Formosa)", b: [-22.5, -28.5, -64.5, -58.5] },
  { name: "Northern Andean Patagonia (Río Negro / Chubut)", b: [-40.5, -43.5, -72.2, -70.5] },
  { name: "Corrientes wetlands (Iberá)", b: [-27.3, -29.6, -58.6, -56.0] },
  { name: "La Pampa caldén forest", b: [-35.5, -38.5, -66.0, -63.5] },
];

const state = {
  data: null, meta: null,
  sel: { all: true, name: "All of Argentina", poly: null, bbox: null },
  from: null, to: null,          // month indices (inclusive)
  baseFrom: 2003, baseTo: 2022,
  mode: "count",
  focus: null,                   // selected month index
  series: null,
};

/* ------------------------------------------------------------------ data */
async function gunzipResponse(resp) {
  const buf = new Uint8Array(await resp.arrayBuffer());
  if (buf[0] === 0x1f && buf[1] === 0x8b) {
    const ds = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Uint8Array(await new Response(ds).arrayBuffer());
  }
  return buf;   // server already removed the gzip layer
}

async function loadData() {
  const [metaR, gridR] = await Promise.all([fetch("data/meta.json"), fetch("data/grid.bin.gz")]);
  if (!metaR.ok || !gridR.ok) throw new Error("Data files are missing. Run pipeline/harmonize.py first.");
  const meta = await metaR.json();
  const bytes = await gunzipResponse(gridR);
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magic = String.fromCharCode(...bytes.slice(0, 4));
  if (magic !== "FCAL") throw new Error("Unexpected data format");
  const nL = dv.getUint16(6, true), n = dv.getUint32(8, true);
  const firstYear = dv.getInt16(12, true), firstMonth = dv.getUint8(14);
  const cell = dv.getFloat32(16, true);
  const recSize = 6 + 4 * nL;
  const cy = new Uint16Array(n), cx = new Uint16Array(n), m = new Uint16Array(n);
  const L = Array.from({ length: nL }, () => new Float32Array(n));
  let off = 20;
  for (let i = 0; i < n; i++, off += recSize) {
    cy[i] = dv.getUint16(off, true); cx[i] = dv.getUint16(off + 2, true); m[i] = dv.getUint16(off + 4, true);
    for (let k = 0; k < nL; k++) L[k][i] = dv.getFloat32(off + 6 + 4 * k, true);
  }
  // unique cells
  const key = new Map(); const rc = new Uint32Array(n); const ucy = [], ucx = [];
  for (let i = 0; i < n; i++) {
    const id = cy[i] * 4000 + cx[i];
    let u = key.get(id);
    if (u === undefined) { u = ucy.length; key.set(id, u); ucy.push(cy[i]); ucx.push(cx[i]); }
    rc[i] = u;
  }
  let nMonths = 0; for (let i = 0; i < n; i++) if (m[i] + 1 > nMonths) nMonths = m[i] + 1;
  const [ly, lm] = meta.last_month.split("-").map(Number);
  nMonths = Math.max(nMonths, (ly - firstYear) * 12 + lm - firstMonth + 1);
  return {
    n, cy, cx, m, harm: L[0], modis: L[1], viirs: L[2], rc,
    ucy: Uint16Array.from(ucy), ucx: Uint16Array.from(ucx),
    firstYear, firstMonth, cell, nMonths,
  };
}

const mYear = (i) => state.data.firstYear + Math.floor((state.data.firstMonth - 1 + i) / 12);
const mMonth = (i) => (state.data.firstMonth - 1 + i) % 12;          // 0..11
const mIndex = (y, mo) => (y - state.data.firstYear) * 12 + mo - (state.data.firstMonth - 1);
const mLabel = (i) => `${MONTHS_LONG[mMonth(i)]} ${mYear(i)}`;
const mValue = (i) => `${mYear(i)}-${String(mMonth(i) + 1).padStart(2, "0")}`;
const fmt = (v) => Math.round(v).toLocaleString("en-US");
const fmtPct = (r) => (r >= 2 ? `${r >= 10 ? Math.round(r) : r.toFixed(1)}×`
  : (r >= 1 ? "+" : "−") + Math.abs(Math.round((r - 1) * 100)) + "%");

function cellCenter(cy, cx) {
  const c = state.data.cell;
  return [cy * c - 90 + c / 2, cx * c - 180 + c / 2];
}

function pointInPoly(lat, lon, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i], [yj, xj] = poly[j];
    if (((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
}

function selectionMask() {
  const d = state.data; const U = d.ucy.length; const mask = new Uint8Array(U);
  if (state.sel.all) { mask.fill(1); return mask; }
  const [n, s, w, e] = state.sel.bbox;
  for (let u = 0; u < U; u++) {
    const [lat, lon] = cellCenter(d.ucy[u], d.ucx[u]);
    if (lat > n || lat < s || lon < w || lon > e) continue;
    if (!state.sel.poly || pointInPoly(lat, lon, state.sel.poly)) mask[u] = 1;
  }
  return mask;
}

function computeSeries() {
  const d = state.data, mask = selectionMask();
  const harm = new Float64Array(d.nMonths), modis = new Float64Array(d.nMonths), viirs = new Float64Array(d.nMonths);
  let cells = 0; for (const v of mask) cells += v;
  for (let i = 0; i < d.n; i++) {
    if (!mask[d.rc[i]]) continue;
    harm[d.m[i]] += d.harm[i]; modis[d.m[i]] += d.modis[i]; viirs[d.m[i]] += d.viirs[i];
  }
  state.series = { harm, modis, viirs, mask, cells };
}

/* normal = median of the same calendar month over the baseline years */
function normals() {
  const s = state.series.harm, out = [];
  for (let mo = 0; mo < 12; mo++) {
    const vals = [];
    for (let y = state.baseFrom; y <= state.baseTo; y++) {
      const i = mIndex(y, mo);
      if (i >= 0 && i < state.data.nMonths) vals.push(s[i]);
    }
    vals.sort((a, b) => a - b);
    out.push({ median: d3.quantileSorted(vals, 0.5) ?? 0, q25: d3.quantileSorted(vals, 0.25) ?? 0,
               q75: d3.quantileSorted(vals, 0.75) ?? 0, n: vals.length });
  }
  return out;
}

function sourceOf(i) {
  const v = mValue(i);
  for (const e of state.meta.eras) if (v >= e.from && v <= e.to) return e.source;
  return "";
}

/* ------------------------------------------------------------------ map */
let map, drawn, overlay;

function initMap() {
  map = L.map("map", { zoomSnap: 0.25, attributionControl: true }).setView([-38.5, -63.5], 3.5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 12, className: "basemap",
  }).addTo(map);
  drawn = new L.FeatureGroup().addTo(map);
  map.addControl(new L.Control.Draw({
    draw: { polyline: false, circle: false, circlemarker: false, marker: false,
            rectangle: { shapeOptions: { color: "#1d2a2f", weight: 2, fillOpacity: 0.04 } },
            polygon: { shapeOptions: { color: "#1d2a2f", weight: 2, fillOpacity: 0.04 } } },
    edit: { featureGroup: drawn, edit: false, remove: true },
  }));
  map.on(L.Draw.Event.CREATED, (e) => {
    drawn.clearLayers(); drawn.addLayer(e.layer);
    const ll = e.layer.getLatLngs()[0].map((p) => [p.lat, p.lng]);
    setSelection({ name: e.layerType === "rectangle" ? "Drawn rectangle" : "Drawn polygon", poly: ll });
  });
  map.on(L.Draw.Event.DELETED, () => setSelection({ all: true, name: "All of Argentina" }));
}

function drawSelectionShape() {
  drawn.clearLayers();
  if (state.sel.all) {   // back to the whole country
    map.fitBounds([[-55.1, -73.6], [-21.7, -53.6]], { padding: [10, 10] });
    return;
  }
  L.polygon(state.sel.poly, { color: "#1d2a2f", weight: 2, fillOpacity: 0.04 }).addTo(drawn);
  map.fitBounds(L.polygon(state.sel.poly).getBounds(), { padding: [20, 20], maxZoom: 8 });
}

/* hotspot density for the chosen dates, drawn as a Web-Mercator-correct image */
function drawOverlay() {
  const d = state.data, c = d.cell;
  let minY = 1e9, maxY = 0, minX = 1e9, maxX = 0;
  for (let u = 0; u < d.ucy.length; u++) {
    minY = Math.min(minY, d.ucy[u]); maxY = Math.max(maxY, d.ucy[u]);
    minX = Math.min(minX, d.ucx[u]); maxX = Math.max(maxX, d.ucx[u]);
  }
  const south = minY * c - 90, north = (maxY + 1) * c - 90, west = minX * c - 180, east = (maxX + 1) * c - 180;
  const W = maxX - minX + 1, H = Math.round((maxY - minY + 1) * 1.6);
  const sum = new Float64Array(d.ucy.length);
  for (let i = 0; i < d.n; i++) if (d.m[i] >= state.from && d.m[i] <= state.to) sum[d.rc[i]] += d.harm[i];
  const grid = new Float64Array(W * (maxY - minY + 1));
  for (let u = 0; u < d.ucy.length; u++) grid[(d.ucy[u] - minY) * W + (d.ucx[u] - minX)] = sum[u];
  const nz = Array.from(sum).filter((v) => v > 0).sort((a, b) => a - b);
  const breaks = [0.3, 0.5, 0.7, 0.82, 0.92, 0.97].map((q) => d3.quantileSorted(nz, q) || 1);
  const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const yN = merc(north), yS = merc(south);
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d"); const img = ctx.createImageData(W, H);
  const rgb = RAMP.map((h) => d3.rgb(h));
  for (let r = 0; r < H; r++) {
    const y = yN + (yS - yN) * (r + 0.5) / H;
    const lat = (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;
    const gy = Math.floor((lat + 90) / c) - minY;
    for (let x = 0; x < W; x++) {
      const v = gy >= 0 && gy <= maxY - minY ? grid[gy * W + x] : 0;
      if (v <= 0) continue;
      let k = 0; while (k < breaks.length && v > breaks[k]) k++;
      const p = (r * W + x) * 4, col = rgb[k];
      img.data[p] = col.r; img.data[p + 1] = col.g; img.data[p + 2] = col.b; img.data[p + 3] = 225;
    }
  }
  ctx.putImageData(img, 0, 0);
  if (overlay) map.removeLayer(overlay);
  overlay = L.imageOverlay(cv.toDataURL(), [[south, west], [north, east]],
    { className: "fire-overlay", interactive: false }).addTo(map);
  drawn.bringToFront();
}

/* ------------------------------------------------------------------ selection */
function setSelection(sel) {
  if (sel.all) {
    state.sel = { all: true, name: sel.name || "All of Argentina", poly: null, bbox: null };
  } else {
    const lats = sel.poly.map((p) => p[0]), lons = sel.poly.map((p) => p[1]);
    state.sel = { all: false, name: sel.name, poly: sel.poly,
                  bbox: [Math.max(...lats), Math.min(...lats), Math.min(...lons), Math.max(...lons)] };
    const [n, s, w, e] = state.sel.bbox;
    document.getElementById("bb-n").value = n.toFixed(2); document.getElementById("bb-s").value = s.toFixed(2);
    document.getElementById("bb-w").value = w.toFixed(2); document.getElementById("bb-e").value = e.toFixed(2);
  }
  if (!sel.fromDraw) drawSelectionShape();
  if (!sel.preset) document.getElementById("preset").value = "";
  state.focus = null;
  update();
}

function bboxPoly(n, s, w, e) { return [[n, w], [n, e], [s, e], [s, w]]; }

/* ------------------------------------------------------------------ rendering */
const tip = document.createElement("div"); tip.className = "tooltip"; tip.hidden = true;
document.body.appendChild(tip);
function showTip(ev, html) { tip.innerHTML = html; tip.hidden = false;
  tip.style.left = Math.min(ev.clientX + 12, innerWidth - 250) + "px"; tip.style.top = ev.clientY + 12 + "px"; }
function hideTip() { tip.hidden = true; }

function countBreaks(vals) {
  const nz = vals.filter((v) => v > 0).sort((a, b) => a - b);
  if (!nz.length) return [1, 2, 3, 4, 5, 6];
  const qs = [0.2, 0.4, 0.6, 0.75, 0.88, 0.96].map((q) => d3.quantileSorted(nz, q));
  const out = []; let last = 0;
  for (const q of qs) { let v = Math.max(Math.ceil(q), last + 1); out.push(v); last = v; }
  return out;
}
const classOf = (v, br) => { let k = 0; while (k < br.length && v > br[k]) k++; return k; };
const divClass = (r) => { let k = 0; while (k < DIV_BREAKS.length && r >= DIV_BREAKS[k]) k++; return k; };

function renderCalendar(norm) {
  const s = state.series.harm, host = document.getElementById("calendar");
  const y0 = mYear(state.from), y1 = mYear(state.to);
  const years = d3.range(y0, y1 + 1);
  const inRange = (i) => i >= state.from && i <= state.to && i < state.data.nMonths && i >= 0;
  const vals = []; for (let i = state.from; i <= state.to; i++) vals.push(s[i]);
  const br = countBreaks(vals);

  const cw = 44, ch = years.length > 20 ? 18 : 22, left = 62, top = 22, gap = 2, right = 150;
  const normalGap = 14;
  const W = left + 12 * (cw + gap) + right, H = top + years.length * (ch + gap) + normalGap + ch + 8;
  host.innerHTML = "";
  const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`)
    .attr("width", W).attr("height", H).attr("role", "img")
    .attr("aria-label", `Calendar of monthly hotspots for ${state.sel.name}, ${y0} to ${y1}`);
  svg.append("rect").attr("width", W).attr("height", H).attr("fill", "#f7f8f5");

  svg.selectAll("text.mh").data(MONTHS).join("text").attr("class", "mh")
    .attr("x", (d, i) => left + i * (cw + gap) + cw / 2).attr("y", 14).attr("text-anchor", "middle")
    .attr("font-size", 11).attr("fill", "#4c5a60").text((d) => d);

  const annual = years.map((y) => d3.sum(d3.range(12), (mo) => (inRange(mIndex(y, mo)) ? s[mIndex(y, mo)] : 0)));
  const aMax = d3.max(annual) || 1;
  const viirsStart = state.meta.eras.find((e) => e.source.startsWith("VIIRS")).from;

  years.forEach((y, r) => {
    const yy = top + r * (ch + gap);
    const era = `${y}-12` < viirsStart ? "MODIS" : "VIIRS";
    svg.append("rect").attr("x", left - 8).attr("y", yy).attr("width", 4).attr("height", ch)
      .attr("fill", era === "MODIS" ? "#9aa5a8" : "#1d2a2f");
    svg.append("text").attr("x", left - 14).attr("y", yy + ch / 2 + 4).attr("text-anchor", "end")
      .attr("font-size", 12).attr("fill", "#1d2a2f").text(y);
    for (let mo = 0; mo < 12; mo++) {
      const i = mIndex(y, mo), x = left + mo * (cw + gap);
      if (!inRange(i)) {
        svg.append("rect").attr("x", x).attr("y", yy).attr("width", cw).attr("height", ch)
          .attr("fill", "none").attr("stroke", "#d7dbd6").attr("stroke-dasharray", "2 2");
        continue;
      }
      const v = s[i], nm = norm[mo].median, ratio = nm > 0 ? v / nm : (v > 0 ? 99 : 1);
      const outage = state.meta.gaps && state.meta.gaps[mValue(i)];
      const fill = state.mode === "count" ? (v < 0.5 ? ZERO : RAMP[classOf(v, br)]) : DIV[divClass(ratio)];
      svg.append("rect").attr("class", "cell" + (state.focus === i ? " sel" : ""))
        .attr("x", x).attr("y", yy).attr("width", cw).attr("height", ch).attr("rx", 2)
        .attr("fill", fill).attr("tabindex", 0)
        .attr("aria-label", `${mLabel(i)}: ${fmt(v)} hotspots`)
        .on("mousemove", (ev) => showTip(ev, `<b>${mLabel(i)}</b><br>${fmt(v)} hotspots<br>` +
            (nm > 0 ? `${fmtPct(ratio)} vs normal (${fmt(nm)})` : "normal month: no hotspots") +
            (outage ? `<br>${outage.missing_days} of ${outage.days} days without ${outage.sensor} data; value scaled to the full month` : "")))
        .on("mouseleave", hideTip)
        .on("click", () => { state.focus = i; renderAll(false); })
        .on("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); state.focus = i; renderAll(false); } });
      if (outage && outage.missing_days >= 3) {
        svg.append("circle").attr("cx", x + cw - 5).attr("cy", yy + 5).attr("r", 2.5)
          .attr("fill", "#fff").attr("stroke", "#1d2a2f").attr("stroke-width", 1).attr("pointer-events", "none");
      }
    }
    const bw = (annual[r] / aMax) * (right - 70);
    const bx = left + 12 * (cw + gap) + 8;
    svg.append("rect").attr("x", bx).attr("y", yy + 3).attr("width", Math.max(bw, 0.5)).attr("height", ch - 6)
      .attr("fill", "#4c5a60");
    svg.append("text").attr("x", bx + bw + 5).attr("y", yy + ch / 2 + 4).attr("font-size", 11)
      .attr("fill", "#1d2a2f").text(fmt(annual[r]));
  });

  // normal row
  const ny = top + years.length * (ch + gap) + normalGap;
  svg.append("text").attr("x", left - 14).attr("y", ny + ch / 2 + 4).attr("text-anchor", "end")
    .attr("font-size", 12).attr("font-weight", 700).attr("fill", "#1d2a2f").text("Normal");
  norm.forEach((nmo, mo) => {
    const x = left + mo * (cw + gap);
    svg.append("rect").attr("x", x).attr("y", ny).attr("width", cw).attr("height", ch).attr("rx", 2)
      .attr("fill", state.mode === "count" ? (nmo.median < 0.5 ? ZERO : RAMP[classOf(nmo.median, br)]) : DIV[3])
      .attr("stroke", "#1d2a2f").attr("stroke-width", 1)
      .on("mousemove", (ev) => showTip(ev, `<b>Normal ${MONTHS_LONG[mo]}</b><br>median ${fmt(nmo.median)} hotspots<br>` +
          `middle half of years: ${fmt(nmo.q25)}–${fmt(nmo.q75)}<br>${state.baseFrom}–${state.baseTo}`))
      .on("mouseleave", hideTip);
  });
  svg.append("text").attr("x", left + 12 * (cw + gap) + 8).attr("y", 14).attr("font-size", 11)
    .attr("fill", "#4c5a60").text("Year total");

  // legend
  const lg = document.getElementById("calendar-legend");
  if (state.mode === "count") {
    const labels = [`1–${fmt(br[0])}`]; for (let k = 1; k < br.length; k++) labels.push(`${fmt(br[k - 1] + 1)}–${fmt(br[k])}`);
    labels.push(`> ${fmt(br[br.length - 1])}`);
    lg.innerHTML = `<span>Hotspots per month:</span><span class="sw"><i style="background:${ZERO}"></i>0</span>` +
      RAMP.map((c, k) => `<span class="sw"><i style="background:${c}"></i>${labels[k]}</span>`).join("");
  } else {
    lg.innerHTML = `<span>Compared with the normal month (${state.baseFrom}–${state.baseTo} median):</span>` +
      DIV.map((c, k) => `<span class="sw"><i style="background:${c}"></i>${DIV_LABELS[k]}</span>`).join("");
  }
  lg.innerHTML += `<span class="sw"><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="3" fill="#fff" stroke="#1d2a2f"/></svg>3+ days without satellite data (scaled)</span>` +
    `<span class="sw"><i style="background:#9aa5a8;width:4px"></i>MODIS observed</span>` +
    `<span class="sw"><i style="background:#1d2a2f;width:4px"></i>VIIRS converted to MODIS-equivalent</span>`;
}

function lastFullMonth() {
  const s = state.series.harm;
  let i = Math.min(state.to, state.data.nMonths - 1);
  return i;
}

function renderFigures(norm) {
  const s = state.series.harm;
  const total = d3.sum(d3.range(state.from, state.to + 1), (i) => s[i]);
  const focus = state.focus ?? lastFullMonth();
  const nm = norm[mMonth(focus)].median, r = nm > 0 ? s[focus] / nm : null;
  const maxMed = d3.max(norm, (d) => d.median) || 0;
  const season = norm.map((d, k) => (d.median >= maxMed * 0.5 && maxMed > 0 ? k : -1)).filter((k) => k >= 0);
  const seasonTxt = season.length ? seasonRange(season) : "—";
  const yrs = d3.range(mYear(state.from), mYear(state.to) + 1)
    .map((y) => ({ y, v: d3.sum(d3.range(12), (mo) => { const i = mIndex(y, mo);
      return i >= state.from && i <= state.to && i < state.data.nMonths ? s[i] : 0; }) }));
  const topY = yrs.reduce((a, b) => (b.v > a.v ? b : a), { y: "—", v: 0 });
  const cls = r === null ? "" : r >= 1.25 ? "up" : r <= 0.8 ? "down" : "";
  document.getElementById("figures").innerHTML = `
    <div class="figure"><div class="v">${fmt(total)}</div><div class="l">hotspots, ${mLabel(state.from)} – ${mLabel(state.to)}</div></div>
    <div class="figure ${cls}"><div class="v">${r === null ? (s[focus] > 0 ? "New" : "—") : fmtPct(r)}</div>
      <div class="l">${mLabel(focus)} vs a normal ${MONTHS_LONG[mMonth(focus)]} (${fmt(s[focus])} vs ${fmt(nm)})</div></div>
    <div class="figure"><div class="v">${seasonTxt}</div><div class="l">usual fire season (months at least half as active as the peak)</div></div>
    <div class="figure"><div class="v">${topY.y}</div><div class="l">most active year (${fmt(topY.v)} hotspots)</div></div>`;
}

function seasonRange(ks) {
  // group consecutive months, wrapping December→January
  const set = new Set(ks); const runs = []; const seen = new Set();
  for (const k of ks) {
    if (seen.has(k)) continue;
    let a = k; while (set.has((a + 11) % 12) && !seen.has((a + 11) % 12) && (a + 11) % 12 !== k) a = (a + 11) % 12;
    let b = a; seen.add(a); while (set.has((b + 1) % 12) && !seen.has((b + 1) % 12)) { b = (b + 1) % 12; seen.add(b); }
    runs.push(a === b ? MONTHS[a] : `${MONTHS[a]}–${MONTHS[b]}`);
  }
  return runs.join(", ");
}

function renderDetail(norm) {
  const s = state.series, i = state.focus ?? lastFullMonth(), mo = mMonth(i);
  const nm = norm[mo].median, v = s.harm[i];
  const same = d3.range(mYear(0), mYear(state.data.nMonths - 1) + 1).map((y) => mIndex(y, mo))
    .filter((k) => k >= 0 && k < state.data.nMonths && k !== i).map((k) => s.harm[k]);
  const rank = same.filter((x) => x > v).length + 1;
  const firstY = d3.range(mYear(0), mYear(0) + 2).find((y) => mIndex(y, mo) >= 0);
  const ratioTxt = nm > 0 ? `${(v / nm).toFixed(1)}× the normal ${MONTHS_LONG[mo]} (median ${fmt(nm)} in ${state.baseFrom}–${state.baseTo})`
                          : `in a month that normally has no hotspots here`;
  const src = sourceOf(i);
  const gap = state.meta.gaps && state.meta.gaps[mValue(i)];
  const raw = src.startsWith("VIIRS") ? `VIIRS detected ${fmt(s.viirs[i])} hotspots` : `MODIS detected ${fmt(s.modis[i])} hotspots`;
  document.getElementById("detail").innerHTML =
    `<p><strong>${mLabel(i)}: ${fmt(v)} hotspots</strong>, ${ratioTxt}. ` +
    `It ranks ${ordinal(rank)} of ${same.length + 1} ${MONTHS_LONG[mo]}s since ${firstY}. ` +
    `<span class="hint">Source: ${src} (${raw}).` +
    (gap ? ` ${gap.missing_days} of ${gap.days} days had no ${gap.sensor} data, so the month was scaled to its full length.` : "") +
    ` Click any month in the calendar to compare it.</span></p>`;
}
const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");

function renderSeason(norm) {
  const s = state.series.harm, i = state.focus ?? lastFullMonth(), y = mYear(i);
  const W = 460, H = 220, m = { t: 14, r: 10, b: 28, l: 44 };
  const yv = d3.range(12).map((mo) => { const k = mIndex(y, mo); return k >= 0 && k < state.data.nMonths ? s[k] : null; });
  const ymax = d3.max([...norm.map((d) => d.q75), ...yv.filter((v) => v !== null)]) || 1;
  const x = d3.scaleBand().domain(d3.range(12)).range([m.l, W - m.r]).padding(0.25);
  const yS = d3.scaleLinear().domain([0, ymax]).nice().range([H - m.b, m.t]);
  const host = document.getElementById("season"); host.innerHTML = "";
  const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", `Monthly hotspots in ${y} compared with the normal year`);
  svg.append("rect").attr("width", W).attr("height", H).attr("fill", "#f7f8f5");
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
    .call(d3.axisBottom(x).tickFormat((d) => MONTHS[d][0]).tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
    .call(d3.axisLeft(yS).ticks(5, "~s").tickSizeOuter(0));
  // band of the middle half of years
  svg.selectAll("rect.band").data(norm).join("rect").attr("x", (d, k) => x(k) - 3).attr("width", x.bandwidth() + 6)
    .attr("y", (d) => yS(d.q75)).attr("height", (d) => Math.max(1, yS(d.q25) - yS(d.q75))).attr("fill", "#d7dcd6");
  svg.selectAll("rect.bar").data(yv).join("rect").attr("x", (d, k) => x(k)).attr("width", x.bandwidth())
    .attr("y", (d) => yS(d ?? 0)).attr("height", (d) => yS(0) - yS(d ?? 0))
    .attr("fill", (d, k) => (d === null ? "none" : norm[k].median > 0 && d / norm[k].median >= 1.25 ? "#c24b1f" : "#4c5a60"));
  svg.selectAll("line.med").data(norm).join("line").attr("x1", (d, k) => x(k) - 3).attr("x2", (d, k) => x(k) + x.bandwidth() + 3)
    .attr("y1", (d) => yS(d.median)).attr("y2", (d) => yS(d.median)).attr("stroke", "#1d2a2f").attr("stroke-width", 2);
  svg.append("text").attr("x", W - m.r).attr("y", m.t + 2).attr("text-anchor", "end").attr("font-size", 11).attr("fill", "#1d2a2f")
    .text(`Bars: ${y} · line: normal (median) · grey: middle half of years`);
}

function renderAnnual() {
  const s = state.series.harm;
  const first = mYear(state.from), last = mYear(state.to);
  const data = d3.range(first, last + 1).map((y) => {
    let v = 0, full = true;
    for (let mo = 0; mo < 12; mo++) { const i = mIndex(y, mo);
      if (i < state.from || i > state.to || i >= state.data.nMonths || i < 0) { full = false; continue; } v += s[i]; }
    return { y, v, full };
  });
  const med = d3.median(data.filter((d) => d.full && d.y >= state.baseFrom && d.y <= state.baseTo), (d) => d.v) || 0;
  const W = 420, H = 220, m = { t: 14, r: 10, b: 28, l: 44 };
  const x = d3.scaleBand().domain(data.map((d) => d.y)).range([m.l, W - m.r]).padding(0.15);
  const yS = d3.scaleLinear().domain([0, d3.max(data, (d) => d.v) || 1]).nice().range([H - m.b, m.t]);
  const host = document.getElementById("annual"); host.innerHTML = "";
  const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", "Hotspots per year");
  svg.append("rect").attr("width", W).attr("height", H).attr("fill", "#f7f8f5");
  const every = Math.ceil(data.length / 9);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
    .call(d3.axisBottom(x).tickValues(data.map((d) => d.y).filter((y, k) => k % every === 0)).tickFormat((d) => `’${String(d).slice(2)}`).tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(yS).ticks(5, "~s").tickSizeOuter(0));
  svg.selectAll("rect.b").data(data).join("rect").attr("x", (d) => x(d.y)).attr("width", x.bandwidth())
    .attr("y", (d) => yS(d.v)).attr("height", (d) => yS(0) - yS(d.v))
    .attr("fill", (d) => (!d.full ? "#b9c0bd" : med && d.v >= 1.25 * med ? "#c24b1f" : "#4c5a60"))
    .style("cursor", "pointer")
    .on("mousemove", (ev, d) => showTip(ev, `<b>${d.y}</b><br>${fmt(d.v)} hotspots${d.full ? "" : " (partial year)"}` +
      (med ? `<br>${fmtPct(d.v / med)} vs median year` : "")))
    .on("mouseleave", hideTip)
    .on("click", (ev, d) => { const mo = state.focus !== null ? mMonth(state.focus) : 8;
      const i = mIndex(d.y, mo); if (i >= 0 && i < state.data.nMonths) { state.focus = i; renderAll(false); } });
  if (med) {
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", yS(med)).attr("y2", yS(med))
      .attr("stroke", "#1d2a2f").attr("stroke-dasharray", "4 3");
    svg.append("text").attr("x", m.l + 4).attr("y", m.t + 2).attr("font-size", 11)
      .attr("fill", "#1d2a2f").text(`dashed line: median year (${fmt(med)})`);
  }
}

function renderTop() {
  const s = state.series.harm;
  const items = d3.range(state.from, state.to + 1).filter((i) => i < state.data.nMonths)
    .map((i) => ({ i, v: s[i] })).sort((a, b) => b.v - a.v).slice(0, 8);
  document.getElementById("top-months").innerHTML = items.map((d) =>
    `<li><a href="#calendar" data-i="${d.i}">${mLabel(d.i)}</a><span>${fmt(d.v)}</span></li>`).join("");
  document.querySelectorAll("#top-months a").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); state.focus = +a.dataset.i; renderAll(false); }));
}

function renderMeta() {
  const s = state.series;
  const sel = state.sel.all ? "All mapped land in Argentina" :
    `${s.cells.toLocaleString("en-US")} grid cells of 0.1° · N ${state.sel.bbox[0].toFixed(2)}, S ${state.sel.bbox[1].toFixed(2)}, W ${state.sel.bbox[2].toFixed(2)}, E ${state.sel.bbox[3].toFixed(2)}`;
  document.getElementById("area-name").textContent = state.sel.name;
  document.getElementById("area-meta").textContent = sel;
}

function renderAll(redrawMap = true) {
  const norm = normals();
  renderMeta(); renderFigures(norm); renderCalendar(norm); renderDetail(norm); renderSeason(norm); renderAnnual(); renderTop();
  if (redrawMap) drawOverlay();
}

function update() { computeSeries(); renderAll(true); }

/* ------------------------------------------------------------------ method section */
function renderMethod() {
  const meta = state.meta;
  document.getElementById("eras").innerHTML = "<strong>Where each month comes from</strong>" +
    meta.eras.map((e) => `<div><span>${e.from} → ${e.to}</span><span>${e.source}</span></div>`).join("");
  const v = meta.validation;
  const scales = Object.keys(v);
  const methods = Object.keys(v[scales[0]]);
  let html = `<caption>Error when predicting a hidden year of MODIS from VIIRS (2012–2021)</caption>
    <tr><th>Method</th>${scales.map((s) => `<th>${s}</th>`).join("")}</tr>`;
  for (const m of methods) {
    html += `<tr class="${m === meta.method ? "best" : ""}"><td>${m}${m === meta.method ? " (used)" : ""}</td>` +
      scales.map((s) => `<td>${v[s][m].wape_pct}%</td>`).join("") + "</tr>";
  }
  html += `<tr><td colspan="${scales.length + 1}" class="hint" style="text-align:left">Weighted absolute error of monthly counts; lower is better.</td></tr>`;
  document.getElementById("validation").innerHTML = html;
}

/* ------------------------------------------------------------------ downloads */
function saveBlob(blob, name) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
const slug = () => state.sel.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function downloadMonthly() {
  const s = state.series, norm = normals();
  const rows = ["month,harmonized_hotspots_modis_equivalent,modis_observed,viirs_observed,source,normal_median,ratio_to_normal"];
  for (let i = state.from; i <= state.to && i < state.data.nMonths; i++) {
    const nm = norm[mMonth(i)].median;
    rows.push([mValue(i), s.harm[i].toFixed(1), Math.round(s.modis[i]), Math.round(s.viirs[i]),
      `"${sourceOf(i)}"`, nm.toFixed(1), nm > 0 ? (s.harm[i] / nm).toFixed(3) : ""].join(","));
  }
  saveBlob(new Blob([rows.join("\n")], { type: "text/csv" }), `burn-calendar_${slug()}_${mValue(state.from)}_${mValue(state.to)}.csv`);
}

async function downloadHotspots() {
  const btn = document.getElementById("dl-hotspots"), status = document.getElementById("dl-status");
  const tiles = state.meta.tiles.filter((t) => {
    if (state.sel.all) return true;
    const [n, s, w, e] = state.sel.bbox;
    return t.ty + 1 > s && t.ty < n && t.tx + 1 > w && t.tx < e;
  });
  const est = d3.sum(tiles, (t) => t.n);
  if (est > 1500000 && !confirm(`This area holds about ${fmt(est)} hotspots in total. The file may be large. Continue?`)) return;
  btn.disabled = true;
  const from = mValue(state.from), to = mValue(state.to);
  const out = ["latitude,longitude,acq_date,acq_time,instrument,satellite,daynight,confidence,frp"];
  let kept = 0;
  try {
    for (let k = 0; k < tiles.length; k++) {
      status.textContent = `Reading hotspots… ${k + 1} of ${tiles.length} map tiles`;
      const r = await fetch(`data/tiles/${tiles[k].file}`);
      const text = new TextDecoder().decode(await gunzipResponse(r));
      for (const line of text.split("\n")) {
        if (!line) continue;
        const c = line.split(",");
        const lat = +c[0], lon = +c[1], ym = c[2].slice(0, 7);
        if (ym < from || ym > to) continue;
        if (!state.sel.all) {
          const [n, s, w, e] = state.sel.bbox;
          if (lat > n || lat < s || lon < w || lon > e) continue;
          if (state.sel.poly && !pointInPoly(lat, lon, state.sel.poly)) continue;
        }
        const inst = c[4] === "SNPP" ? "VIIRS" : "MODIS";
        out.push([c[0], c[1], c[2], c[3], inst, c[4], c[5], c[6], c[7]].join(","));
        kept++;
      }
    }
    saveBlob(new Blob([out.join("\n")], { type: "text/csv" }), `hotspots_${slug()}_${from}_${to}.csv`);
    status.textContent = `${fmt(kept)} hotspots saved (raw detections from both sensors; not harmonized).`;
  } catch (err) {
    status.textContent = `Download failed: ${err.message}. Check your connection and try again.`;
  } finally { btn.disabled = false; }
}

function savePng(id) {
  const svgEl = document.querySelector(`#${id} svg`); if (!svgEl) return;
  const clone = svgEl.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.querySelectorAll("text").forEach((t) => t.setAttribute("font-family", "Archivo, Arial, sans-serif"));
  clone.querySelectorAll(".axis path, .axis line").forEach((l) => l.setAttribute("stroke", "#cfd4cf"));
  const vb = svgEl.viewBox.baseVal, scale = 2;
  // caption with area and dates
  const cap = document.createElementNS("http://www.w3.org/2000/svg", "text");
  cap.setAttribute("x", 4); cap.setAttribute("y", vb.height + 16); cap.setAttribute("font-size", 11);
  cap.setAttribute("font-family", "Arial, sans-serif"); cap.setAttribute("fill", "#4c5a60");
  cap.textContent = `${state.sel.name} · ${mValue(state.from)} to ${mValue(state.to)} · harmonized MODIS+VIIRS hotspots (NASA FIRMS)`;
  clone.setAttribute("viewBox", `0 0 ${vb.width} ${vb.height + 24}`);
  clone.setAttribute("width", vb.width); clone.setAttribute("height", vb.height + 24);
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", vb.width); bg.setAttribute("height", vb.height + 24); bg.setAttribute("fill", "#f7f8f5");
  clone.insertBefore(bg, clone.firstChild); clone.appendChild(cap);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
  const img = new Image();
  img.onload = () => {
    const cv = document.createElement("canvas"); cv.width = vb.width * scale; cv.height = (vb.height + 24) * scale;
    const ctx = cv.getContext("2d"); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0);
    cv.toBlob((b) => saveBlob(b, `${id}_${slug()}.png`)); URL.revokeObjectURL(url);
  };
  img.src = url;
}

/* ------------------------------------------------------------------ controls */
function initControls() {
  const d = state.data;
  const sel = document.getElementById("preset");
  PRESETS.forEach((p, k) => sel.insertAdjacentHTML("beforeend", `<option value="${k}">${p.name}</option>`));
  sel.addEventListener("change", () => {
    const p = PRESETS[+sel.value]; if (!p) return;
    if (p.all) setSelection({ all: true, name: p.name, preset: true });
    else { const [n, s, w, e] = p.b; setSelection({ name: p.name, poly: bboxPoly(n, s, w, e), preset: true }); }
  });
  document.getElementById("bb-apply").addEventListener("click", () => {
    const g = (id) => parseFloat(document.getElementById(id).value);
    const n = g("bb-n"), s = g("bb-s"), w = g("bb-w"), e = g("bb-e");
    const st = document.getElementById("dl-status");
    if ([n, s, w, e].some(Number.isNaN) || n <= s || e <= w) {
      st.textContent = "Enter all four coordinates, with North above South and East greater than West."; return;
    }
    st.textContent = "";
    setSelection({ name: `Box ${n.toFixed(2)}, ${w.toFixed(2)} to ${s.toFixed(2)}, ${e.toFixed(2)}`, poly: bboxPoly(n, s, w, e) });
  });

  const first = mValue(0), last = mValue(d.nMonths - 1);
  const fromI = document.getElementById("d-from"), toI = document.getElementById("d-to");
  fromI.min = toI.min = first; fromI.max = toI.max = last;
  state.from = Math.max(0, mIndex(2001, 0)); state.to = d.nMonths - 1;
  fromI.value = mValue(state.from); toI.value = mValue(state.to);
  const onDates = () => {
    const [fy, fm] = fromI.value.split("-").map(Number), [ty, tm] = toI.value.split("-").map(Number);
    if (!fy || !ty) return;
    let a = Math.max(0, mIndex(fy, fm - 1)), b = Math.min(d.nMonths - 1, mIndex(ty, tm - 1));
    if (a > b) [a, b] = [b, a];
    state.from = a; state.to = b; if (state.focus !== null && (state.focus < a || state.focus > b)) state.focus = null;
    renderAll(true);
  };
  fromI.addEventListener("change", onDates); toI.addEventListener("change", onDates);

  const bF = document.getElementById("b-from"), bT = document.getElementById("b-to");
  bF.value = state.baseFrom; bT.value = state.baseTo;
  const onBase = () => {
    let a = +bF.value, b = +bT.value; if (!a || !b) return; if (a > b) [a, b] = [b, a];
    state.baseFrom = a; state.baseTo = b; renderAll(false);
  };
  bF.addEventListener("change", onBase); bT.addEventListener("change", onBase);

  document.querySelectorAll(".toggle button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".toggle button").forEach((x) => x.setAttribute("aria-checked", x === b));
    state.mode = b.dataset.mode; renderAll(false);
  }));
  document.querySelectorAll("[data-png]").forEach((b) => b.addEventListener("click", () => savePng(b.dataset.png)));
  document.getElementById("dl-monthly").addEventListener("click", downloadMonthly);
  document.getElementById("dl-hotspots").addEventListener("click", downloadHotspots);
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  const loading = document.getElementById("loading");
  try {
    initMap();
    const [data, meta] = await Promise.all([loadData(), fetch("data/meta.json").then((r) => r.json())]);
    state.data = data; state.meta = meta;
    if (meta.repo) document.getElementById("repo-link").href = meta.repo;
    initControls(); renderMethod(); update();
    loading.hidden = true;
  } catch (err) {
    loading.textContent = `Could not load the data: ${err.message}`;
    console.error(err);
  }
})();
