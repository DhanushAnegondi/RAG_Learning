// weatherwise site. The API speaks Celsius; this file converts for display only.
"use strict";
const $ = (id) => document.getElementById(id);
const state = { city: null, unit: "F", cities: [], outlook: null };

const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `request failed (${r.status})`);
  return body;
};
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// temperature and temperature-difference conversion
const T = (c) => (c == null ? null : state.unit === "F" ? c * 9 / 5 + 32 : c);
const D = (c) => (c == null ? null : state.unit === "F" ? c * 9 / 5 : c);
const f1 = (v) => (v == null ? "–" : v.toFixed(1));
const f0 = (v) => (v == null ? "–" : Math.round(v).toString());
const deg = () => `°${state.unit}`;
const signed = (v) => (v == null ? "–" : Math.abs(v) < 0.05 ? "0.0" : (v > 0 ? "+" : "") + v.toFixed(1));
const day = (iso, opt) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", opt);
const METHOD = {
  raw: "published forecast, kept as is", linear: "fixed correction", gbm: "boosted correction",
  drift: "recent-bias correction", ens_mean: "average of the weather models", blend: "blend of the weather models",
  decay: "season + fading anomaly", lstm: "season + LSTM", mix: "season + average of both", climatology: "seasonal average", persistence: "same as today",
};
const LEAD = (n) => (n === 1 ? "1 day before" : `${n} days before`);

function table(cols, rows, pick) {
  if (!rows.length) return '<p class="empty">Nothing here yet.</p>';
  const head = cols.map((c) => `<th>${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => "<tr>" + cols.map((c) => {
    const cls = pick && pick(r, c) ? ' class="pick"' : "";
    return `<td${cls}>${c.html ? c.html(r) : esc(c.get ? c.get(r) : r[c.key])}</td>`;
  }).join("") + "</tr>").join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// ---- line chart: SVG, one y axis, optional band, crosshair tooltip ----
function lineChart(el, { x, series, band, xLabel, yFmt, tipTitle }) {
  const W = 560, H = 260, m = { l: 40, r: 12, t: 10, b: 28 };
  const vals = series.flatMap((s) => s.y).concat(band ? band.lo.concat(band.hi) : []).filter((v) => v != null);
  if (!vals.length) { el.innerHTML = '<p class="empty">No data yet. Run “Update forecast”.</p>'; return; }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo || 1) * 0.08; lo -= pad; hi += pad;
  const px = (i) => m.l + (x.length === 1 ? 0 : (i / (x.length - 1)) * (W - m.l - m.r));
  const py = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const path = (ys) => {
    let d = "", pen = false;
    ys.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`; pen = true; });
    return d;
  };
  const step = (hi - lo) / 4;
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = lo + k * step;
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${py(v)}" y2="${py(v)}" stroke="var(--grid)"/>` +
      `<text x="${m.l - 6}" y="${py(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${yFmt(v)}</text>`;
  }
  const every = Math.max(1, Math.ceil(x.length / 6));
  x.forEach((lab, i) => {
    if (i % every === 0) g += `<text x="${px(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(xLabel(lab))}</text>`;
  });
  let bandPath = "";
  if (band) {
    const idx = x.map((_, i) => i).filter((i) => band.lo[i] != null);
    if (idx.length) {
      bandPath = `<path d="M${idx.map((i) => `${px(i).toFixed(1)},${py(band.hi[i]).toFixed(1)}`).join("L")}L${idx.reverse().map((i) => `${px(i).toFixed(1)},${py(band.lo[i]).toFixed(1)}`).join("L")}Z" fill="var(--band)" opacity="0.6"/>`;
    }
  }
  const lines = series.map((s) => `<path d="${path(s.y)}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>`).join("");
  const legend = (band ? `<span><i class="box" style="background:var(--band)"></i>${esc(band.name)}</span>` : "") +
    series.map((s) => `<span><i class="${s.dash ? "dash" : ""}" style="border-color:${s.color}"></i>${esc(s.name)}</span>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))}">${g}${bandPath}${lines}` +
    `<line class="cross" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" visibility="hidden"/>` +
    `<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg><div class="legend">${legend}</div>`;
  const svg = el.querySelector("svg"), cross = el.querySelector(".cross"), tip = $("tip");
  const move = (ev) => {
    const box = svg.getBoundingClientRect();
    const rel = ((ev.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(x.length - 1, Math.round(((rel - m.l) / (W - m.l - m.r)) * (x.length - 1))));
    cross.setAttribute("x1", px(i)); cross.setAttribute("x2", px(i)); cross.setAttribute("visibility", "visible");
    let html = `<b>${esc(tipTitle(x[i]))}</b>`;
    series.forEach((s) => { if (s.y[i] != null) html += `<br>${esc(s.name)}: ${yFmt(s.y[i], true)}`; });
    if (band && band.lo[i] != null) html += `<br>${esc(band.name)}: ${yFmt(band.lo[i], true)} to ${yFmt(band.hi[i], true)}`;
    tip.innerHTML = html; tip.hidden = false;
    tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 250) + "px";
    tip.style.top = ev.clientY + 14 + "px";
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
}
const yT = (v, long) => (long ? `${v.toFixed(1)}${deg()}` : `${Math.round(v)}°`);

// ---- Forecast tab ----
async function loadForecast() {
  const o = (state.outlook = await api(`/api/outlook?city=${state.city}`));
  const info = state.cities.find((c) => c.name === state.city);
  if (!o.days.length) {
    $("issued").textContent = "";
    $("week").innerHTML = '<p class="empty">No forecast for this city yet. Press “Update forecast” (takes a few minutes the first time).</p>';
    ["chart-tmax", "chart-tmin", "outlook-table"].forEach((id) => ($(id).innerHTML = ""));
    return;
  }
  const stale = info && info.today !== o.issued_on;
  $("issued").textContent = `Forecast made on ${day(o.issued_on, { weekday: "long", month: "long", day: "numeric" })}` +
    (stale ? ` — that is not today (${info.today}). Press “Update forecast”.` : ".");
  $("week").innerHTML = o.days.filter((d) => d.lead_days <= 7).map((d) => {
    const hi = d.tmax || {}, lo = d.tmin || {};
    return `<div class="card"><div class="day">${day(d.date, { weekday: "long" })}</div><div class="date">${day(d.date, { month: "short", day: "numeric" })}</div>` +
      `<div class="hi">${f0(T(hi.pred_c))}°</div><div class="rng">high, likely ${f0(T(hi.lo_c))}–${f0(T(hi.hi_c))}°</div>` +
      `<div class="lo">${f0(T(lo.pred_c))}°</div><div class="rng">low, likely ${f0(T(lo.lo_c))}–${f0(T(lo.hi_c))}°</div>` +
      `<div class="pub">Published: ${f0(T(hi.published_c))}° / ${f0(T(lo.published_c))}°<br><span class="chipm">${esc(METHOD[hi.method] || hi.method)}</span></div></div>`;
  }).join("");
  for (const v of ["tmax", "tmin"]) {
    lineChart($(`chart-${v}`), {
      x: o.days.map((d) => d.date),
      series: [
        { name: "weatherwise", color: "var(--ours)", y: o.days.map((d) => T(d[v]?.pred_c)) },
        { name: "published forecast", color: "var(--pub)", dash: true, y: o.days.map((d) => T(d[v]?.published_c)) },
      ],
      band: { name: "likely range (8 in 10)", lo: o.days.map((d) => T(d[v]?.lo_c)), hi: o.days.map((d) => T(d[v]?.hi_c)) },
      xLabel: (iso) => day(iso, { month: "short", day: "numeric" }), yFmt: yT,
      tipTitle: (iso) => day(iso, { weekday: "short", month: "short", day: "numeric" }),
    });
  }
  const cell = (k, v) => (d) => f1(T(d[v]?.[k]));
  $("outlook-table").innerHTML = table([
    { label: "Day", get: (d) => day(d.date, { weekday: "short", month: "short", day: "numeric" }) },
    { label: "Days ahead", key: "lead_days" },
    { label: `High ${deg()}`, get: cell("pred_c", "tmax") },
    { label: "Likely range", get: (d) => `${f1(T(d.tmax?.lo_c))} – ${f1(T(d.tmax?.hi_c))}` },
    { label: "Published high", get: cell("published_c", "tmax") },
    { label: `Low ${deg()}`, get: cell("pred_c", "tmin") },
    { label: "Likely range", get: (d) => `${f1(T(d.tmin?.lo_c))} – ${f1(T(d.tmin?.hi_c))}` },
    { label: "Published low", get: cell("published_c", "tmin") },
    { label: "How", get: (d) => METHOD[d.tmax?.method] || d.tmax?.method },
  ], o.days);
}

// ---- Check a day ----
const NAME = { tmax: "High", tmin: "Low" };
function renderChecks(dateIso, checks) {
  const box = $("check-result");
  if (!checks.length) {
    box.innerHTML = `<div class="verdict">Saved. No forecast is on file for ${esc(dateIso)} yet, so there is nothing to compare. Forecasts are kept from the day the site first ran for this city, plus a replay of the last 12 months.</div>`;
    return;
  }
  let html = "";
  for (const v of ["tmax", "tmin"]) {
    const rows = checks.filter((c) => c.variable === v);
    if (!rows.length) continue;
    const first = rows[0], miss = D(first.our_error_c), pubMiss = D(first.published_error_c);
    const verdict = first.inside_range ? '<span class="ok">inside the likely range</span>' : '<span class="miss">outside the likely range</span>';
    const better = pubMiss == null ? "" : Math.abs(miss) < Math.abs(pubMiss) - 0.05 ? " weatherwise was closer than the published forecast." :
      Math.abs(miss) > Math.abs(pubMiss) + 0.05 ? " The published forecast was closer." : " Same as the published forecast.";
    html += `<div class="verdict"><b>${NAME[v]} on ${day(dateIso, { weekday: "long", month: "long", day: "numeric" })}: you saw ${f1(T(first.observed_c))}${deg()}</b><br>` +
      `Forecast ${LEAD(first.lead_days)}: ${f1(T(first.pred_c))}${deg()} (likely ${f1(T(first.lo_c))}–${f1(T(first.hi_c))}). ` +
      `Off by ${f1(Math.abs(miss))}${deg()} (${miss > 0 ? "forecast too warm" : miss < 0 ? "forecast too cool" : "exact"}), ${verdict}.${better}` +
      (first.era5_c == null ? "" : ` The grid dataset the models learn from recorded ${f1(T(first.era5_c))}${deg()} that day.`) + "</div>";
    html += '<div class="scroll">' + table([
      { label: "Forecast made", get: (c) => LEAD(c.lead_days) },
      { label: "On", key: "issued_on" },
      { label: `weatherwise ${deg()}`, get: (c) => f1(T(c.pred_c)) },
      { label: "Likely range", get: (c) => `${f1(T(c.lo_c))} – ${f1(T(c.hi_c))}` },
      { label: "Our miss", get: (c) => signed(D(c.our_error_c)) },
      { label: "In range", html: (c) => (c.inside_range ? '<span class="ok">yes</span>' : '<span class="miss">no</span>') },
      { label: `Published ${deg()}`, get: (c) => f1(T(c.published_c)) },
      { label: "Published miss", get: (c) => signed(D(c.published_error_c)) },
      { label: "How", get: (c) => METHOD[c.method] || c.method },
      { label: "Kind", get: (c) => (c.kind === "live" ? "issued live" : "replay") },
    ], rows) + "</div>";
  }
  box.innerHTML = html + '<p class="hint">Miss = forecast minus what you saw. “Issued live” rows were forecast on that day and stored. “Replay” rows are what the models would have said, re-run on the last 12 months, which they were never trained on.</p>';
}
async function loadEntries() {
  const rows = await api(`/api/observations?city=${state.city}`);
  $("entries").innerHTML = table([
    { label: "Day", html: (r) => `<button class="linkbtn" data-show="${esc(r.date)}">${esc(day(r.date, { weekday: "short", year: "numeric", month: "short", day: "numeric" }))}</button>` },
    { label: `High ${deg()}`, get: (r) => f1(T(r.tmax_c)) },
    { label: `Low ${deg()}`, get: (r) => f1(T(r.tmin_c)) },
    { label: "Note", key: "note" },
    { label: "", html: (r) => `<button class="linkbtn" data-del="${esc(r.date)}">delete</button>` },
  ], rows);
}
$("entries").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.show) renderChecks(b.dataset.show, (await api(`/api/check?city=${state.city}&date=${b.dataset.show}`)).checks);
    if (b.dataset.del && confirm(`Delete your entry for ${b.dataset.del}?`)) {
      await api(`/api/observations?city=${state.city}&date=${b.dataset.del}`, { method: "DELETE" });
      $("check-result").innerHTML = "";
      loadEntries();
    }
  } catch (e) { $("entry-error").textContent = e.message; }
});
$("entry").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target), num = (k) => (f.get(k) === "" ? null : Number(f.get(k)));
  $("entry-error").textContent = "";
  try {
    const body = { city: state.city, date: f.get("date"), tmax: num("tmax"), tmin: num("tmin"), unit: f.get("unit"), note: f.get("note") || null };
    const res = await api("/api/observations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    renderChecks(body.date, res.checks);
    loadEntries();
  } catch (e) { $("entry-error").textContent = e.message; }
});

// ---- Scoreboard ----
async function loadScore() {
  const rows = await api(`/api/scoreboard?city=${state.city}`);
  const d1 = rows.find((r) => r.variable === "tmax" && r.lead_days === 1) || rows[0];
  $("score-tiles").innerHTML = !d1 ? "" : [
    [d1.n_checks, `days checked (${NAME[d1.variable].toLowerCase()}, ${LEAD(d1.lead_days)})`],
    [`${f1(D(d1.our_mae_same_days_c ?? d1.our_mae_c))}${deg()}`, "weatherwise average miss"],
    [`${f1(D(d1.published_mae_c))}${deg()}`, "published forecast average miss"],
    [`${Math.round(d1.share_inside_range * 100)}%`, "of your readings inside the likely range (aim: 80%)"],
  ].map(([n, l]) => `<div class="tile"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");
  $("score-table").innerHTML = rows.length ? table([
    { label: "", get: (r) => NAME[r.variable] },
    { label: "Forecast made", get: (r) => LEAD(r.lead_days) },
    { label: "Days checked", key: "n_checks" },
    { label: `Our avg miss ${deg()}`, get: (r) => f1(D(r.our_mae_c)) },
    { label: "Published avg miss", get: (r) => f1(D(r.published_mae_c)) },
    { label: "Ours, same days", get: (r) => f1(D(r.our_mae_same_days_c)) },
    { label: "Inside range", get: (r) => `${Math.round(r.share_inside_range * 100)}%` },
    { label: "Your reading vs grid data", get: (r) => signed(D(r.your_reading_minus_era5_c)) },
  ], rows) : '<p class="empty">No days checked yet. Go to “Check a day” and enter what you saw.</p>';
  $("score-note").textContent = rows.length ? "“Your reading vs grid data”: how much warmer (+) or cooler (−) your readings run than the grid dataset the models learn from. A steady gap is your location or thermometer, not a forecast error. With only a few days checked, these averages are still noisy." : "";
}

// ---- Track record ----
async function loadRecord() {
  const [board, hist, byLead] = await Promise.all([
    api(`/api/leaderboard?city=${state.city}`), api(`/api/history?city=${state.city}`), api(`/api/error-by-lead?city=${state.city}`),
  ]);
  const info = state.cities.find((c) => c.name === state.city) || {};
  $("record-hint").textContent = info.test_start
    ? `Every number here comes from days on or after ${info.test_start} (the held-out year). The models were built on earlier data and never saw these days.`
    : "No run yet for this city.";
  for (const v of ["tmax", "tmin"]) {
    const rows = board.filter((r) => r.variable === v);
    const leads = [...new Set(rows.map((r) => r.lead_days))].sort((a, b) => a - b);
    const at = (lead, pred) => { const r = rows.find((q) => q.lead_days === lead && pred(q)); return r ? D(r.test_mae_c) : null; };
    lineChart($(`mae-${v}`), {
      x: leads,
      series: [
        { name: "weatherwise", color: "var(--ours)", y: leads.map((n) => at(n, (q) => q.chosen)) },
        { name: "published forecast", color: "var(--pub)", dash: true, y: leads.map((n) => at(n, (q) => q.method === "raw")) },
      ],
      xLabel: (n) => `${n}d`, yFmt: (x, long) => (long ? `${x.toFixed(2)}${deg()}` : x.toFixed(1)),
      tipTitle: (n) => `${n} day${n > 1 ? "s" : ""} ahead`,
    });
  }
  const h = hist.filter((r) => r.variable === "tmax").slice(0, 120).reverse();
  lineChart($("hist-tmax"), {
    x: h.map((r) => r.date),
    series: [
      { name: "what happened (high)", color: "var(--ink)", y: h.map((r) => T(r.actual_c)) },
      { name: "weatherwise, day before", color: "var(--ours)", y: h.map((r) => T(r.pred_c)) },
      { name: "published, day before", color: "var(--pub)", dash: true, y: h.map((r) => T(r.published_c)) },
    ],
    xLabel: (iso) => day(iso, { month: "short", day: "numeric" }), yFmt: yT,
    tipTitle: (iso) => day(iso, { weekday: "short", month: "short", day: "numeric" }),
  });
  const methods = [...new Set(board.map((r) => r.method))];
  const order = ["raw", "linear", "gbm", "drift", "ens_mean", "blend", "decay", "lstm", "mix"].filter((m) => methods.includes(m));
  const keys = [...new Set(board.map((r) => `${r.variable}|${r.lead_days}`))];
  const grid = keys.map((k) => { const [variable, lead] = k.split("|"); return { variable, lead: +lead, cells: Object.fromEntries(board.filter((r) => r.variable === variable && r.lead_days === +lead).map((r) => [r.method, r])) }; });
  $("board").innerHTML = table([
    { label: "", get: (r) => NAME[r.variable] },
    { label: "Days ahead", get: (r) => r.lead },
    ...order.map((mth) => ({ label: METHOD[mth] || mth, method: mth, get: (r) => (r.cells[mth] ? D(r.cells[mth].test_mae_c).toFixed(2) : "") })),
    { label: "Range held", get: (r) => { const c = Object.values(r.cells).find((q) => q.chosen); return c && c.coverage_pct != null ? `${Math.round(c.coverage_pct)}%` : ""; } },
  ], grid, (r, c) => c.method && r.cells[c.method]?.chosen);
  $("by-lead").innerHTML = table([
    { label: "", get: (r) => NAME[r.variable] },
    { label: "Days ahead", key: "lead_days" },
    { label: "Days measured", key: "n_days" },
    { label: `Average miss ${deg()}`, get: (r) => D(r.mae_c).toFixed(2) },
    { label: "Leans (+ too warm)", get: (r) => signed(D(r.bias_c)) },
    { label: `Off by ${state.unit === "F" ? "3.6°F" : "2°C"}+`, get: (r) => `${Math.round(r.share_off_2c * 100)}%` },
    { label: `Off by ${state.unit === "F" ? "5.4°F" : "3°C"}+`, get: (r) => `${Math.round(r.share_off_3c * 100)}%` },
    { label: `Worst miss ${deg()}`, get: (r) => D(r.max_abs_error_c).toFixed(1) },
  ], byLead);
}

// ---- Data ----
async function loadData() {
  if (!$("tables").innerHTML) $("tables").innerHTML = '<p class="empty">Loading tables…</p>';
  const [quality, issues, tables] = await Promise.all([
    api(`/api/quality?city=${state.city}`), api(`/api/issues?city=${state.city}`), api("/api/tables"),
  ]);
  $("quality").innerHTML = table([
    { label: "Source", key: "source" }, { label: "Rows received", get: (r) => r.raw_rows.toLocaleString() },
    { label: "Usable days", get: (r) => r.usable_days.toLocaleString() }, { label: "From", key: "first_date" }, { label: "To", key: "last_date" },
    { label: "Rejected days", key: "rejected_days" }, { label: "Missing days", key: "missing_days" },
  ], quality);
  $("issues").innerHTML = issues.length ? table([
    { label: "Table", key: "source" }, { label: "Why rejected", key: "reason" }, { label: "Rows", key: "rejected_rows" },
    { label: "First", key: "first_seen" }, { label: "Last", key: "last_seen" },
  ], issues) : '<p class="empty">No rows rejected for this city: every value passed the cleaning rules.</p>';
  $("tables").innerHTML = tables.map((t) => `<details><summary><code>${esc(t.table)}</code> · ${t.row_count.toLocaleString()} rows</summary>` +
    `<p class="tbl-meta">${t.columns.map(([n, ty]) => `${esc(n)} <i>${esc(ty)}</i>`).join(" · ")}</p>` +
    `<div class="scroll">${table(t.columns.map(([n], i) => ({ label: n, get: (r) => r[i] })), t.sample)}</div></details>`).join("");
}

// ---- shell ----
const LOADERS = { forecast: loadForecast, check: loadEntries, score: loadScore, record: loadRecord, data: loadData };
let tab = "forecast";
async function show(name) {
  tab = name;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${name}`));
  try { await LOADERS[name](); } catch (e) { $("status").textContent = e.message; }
}
function setUnit(u) {
  state.unit = u;
  document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.unit === u));
  $("entry").elements.unit.value = u;
  try { localStorage.setItem("ww-unit", u); } catch { /* private window */ }
}
async function setCity(name) {
  state.city = name;
  const c = state.cities.find((q) => q.name === name);
  let saved = null;
  try { saved = localStorage.getItem("ww-unit"); } catch { /* private window */ }
  setUnit(saved || c.unit);
  const y = new Date(c.today + "T12:00:00Z"); y.setUTCDate(y.getUTCDate() - 1); // UTC both ways: no timezone shift
  $("entry").elements.date.value = y.toISOString().slice(0, 10);
  $("entry").elements.date.max = c.today;
  $("check-result").innerHTML = "";
  await show(tab);
}
async function pollRefresh() {
  const job = await api("/api/refresh");
  if (job.running) { $("status").textContent = `Updating ${job.city}: fetching data and re-training. This takes a few minutes…`; setTimeout(pollRefresh, 4000); return; }
  $("refresh").disabled = false;
  if (job.error) { $("status").textContent = `Update failed: ${job.error}`; return; }
  if (job.finished) { $("status").textContent = `Updated at ${job.finished.slice(11, 16)}.`; state.cities = await api("/api/cities"); show(tab); }
}
$("refresh").addEventListener("click", async () => {
  $("refresh").disabled = true;
  try { await api(`/api/refresh?city=${state.city}`, { method: "POST" }); } catch (e) { $("status").textContent = e.message; }
  pollRefresh();
});
document.querySelector(".tabs").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) show(b.dataset.tab); });
document.querySelector(".seg").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) { setUnit(b.dataset.unit); show(tab); } });
$("city").addEventListener("change", (ev) => setCity(ev.target.value));
(async () => {
  state.cities = await api("/api/cities");
  $("city").innerHTML = state.cities.map((c) => `<option value="${c.name}">${c.name[0].toUpperCase() + c.name.slice(1)}${c.has_forecast ? "" : " (no data yet)"}</option>`).join("");
  const first = state.cities.find((c) => c.has_forecast) || state.cities[0];
  $("city").value = first.name;
  await setCity(first.name);
  pollRefresh();
})();
