/* OncoReady front end — vanilla JS, no external dependencies (works offline). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
let META = null;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const o = { headers: { "Content-Type": "application/json", "X-Actor": "clinician" }, ...opts };
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  const r = await fetch("/api" + path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-json */ }
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}
function toast(msg, bad) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " err" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3200);
}
const safe = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

/* ---------------------------------------------------------------- helpers */
const siteLabel = (k) => (META.sites[k] || {}).label || k;
const stageLabel = (v) => (v === null || v === undefined ? "Unknown" : ["0", "I", "II", "III", "IV"][v]);
const tierChip = (t) => `<span class="chip ${t}" title="${{ P1: "See within 48 h", P2: "See within 7 days", P3: "See within 14 days" }[t]}">${t}</span>`;
const bandTag = (b) => `<span class="tag ${b}">${{ ready: "Ready", nearly: "Nearly ready", not_ready: "Not ready" }[b]}</span>`;
const riskTag = (b, p) => (b ? `<span class="tag ${b}">${Math.round(p * 100)}% ${b}</span>` : "–");
const bar = (v, cls = "") => `<span class="bar ${cls}"><i style="width:${Math.max(0, Math.min(100, v))}%"></i></span>`;
const readCls = (v) => (v >= 85 ? "good" : v >= 60 ? "warn" : "crit");
const ACTION = { see_now: "Book earliest", parallel: "See now, test in parallel", book: "Book", book_conditional: "Book, chase items", prepare: "Prepare first" };
const STATUSLBL = { ok: "On target", watch: "Slightly late", delayed: "Late", critical: "Very late", unknown: "No data" };
const fmtDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "–");
const daysTxt = (d) => (d === null || d === undefined ? "–" : d + " d");

/* ---------------------------------------------------------------- journey rail (signature visual) */
const ORDER = ["symptom_onset", "first_contact", "biopsy", "pathology_report", "oncology_consult", "treatment_start"];
const NODE_LABEL = { symptom_onset: "Symptoms", first_contact: "First contact", biopsy: "Biopsy", pathology_report: "Diagnosis", oncology_consult: "Oncology consult", treatment_start: "Treatment" };
const PAIR = { "symptom_onset>first_contact": "symptom_to_contact", "first_contact>biopsy": "contact_to_biopsy", "biopsy>pathology_report": "biopsy_to_report", "pathology_report>oncology_consult": "report_to_consult" };

function rail(j, opt = {}) {
  const compact = !!opt.compact, W = opt.width || (compact ? 150 : 880), H = compact ? 12 : 96;
  const today = META.today;
  const nodes = ORDER.filter((k) => j.dates[k]).map((k) => ({ k, d: j.dates[k] }));
  if (!nodes.length) return compact ? `<svg class="rail" width="${W}" height="${H}"></svg>` : `<div class="empty">No journey dates recorded yet.</div>`;
  const ms = (d) => new Date(d + "T00:00:00").getTime();
  const last = nodes[nodes.length - 1];
  const ongoing = last.k !== "treatment_start";
  let t0 = ms(nodes[0].d), t1 = Math.max(ms(last.d), ongoing ? ms(today) : 0);
  if (t1 - t0 < 86400000 * 7) t1 = t0 + 86400000 * 7;
  const pad = compact ? 2 : 36, x = (d) => pad + ((ms(d) - t0) / (t1 - t0)) * (W - pad * 2);
  const ivByKey = Object.fromEntries(j.intervals.map((i) => [i.key, i]));
  let s = `<svg class="rail" width="${compact ? W : "100%"}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Patient journey timeline">`;
  const y = compact ? 6 : 44, th = compact ? 8 : 12;
  const seg = (a, b, cls, dashed) => {
    const xa = x(a), xb = Math.max(x(b), xa + 2);
    s += `<rect class="seg-${cls}" x="${xa}" y="${y - th / 2}" width="${xb - xa}" height="${th}" rx="3"${dashed ? ' opacity=".45"' : ""}><title>${a} to ${b}</title></rect>`;
  };
  for (let i = 0; i < nodes.length - 1; i++) {
    const key = PAIR[nodes[i].k + ">" + nodes[i + 1].k];
    const iv = key ? ivByKey[key] : null;
    seg(nodes[i].d, nodes[i + 1].d, iv && iv.status !== "unknown" ? iv.status : "unknown", false);
  }
  if (ongoing) {
    const oi = ivByKey.report_to_treatment;
    const st = last.k === "pathology_report" || last.k === "oncology_consult" ? (oi && oi.state === "ongoing" ? oi.status : "unknown") : "unknown";
    seg(last.d, today, st, true);
  }
  if (!compact) {
    nodes.forEach((n, i) => {
      const cx = x(n.d), up = i % 2 === 0, anc = cx < 90 ? "start" : cx > W - 90 ? "end" : "middle";
      s += `<circle cx="${cx}" cy="${y}" r="7" fill="#fff" stroke="#101a2b" stroke-width="2.2"/>`;
      s += `<text class="lab" x="${cx}" y="${up ? y - 18 : y + 30}" text-anchor="${anc}">${NODE_LABEL[n.k]}</text>`;
      s += `<text x="${cx}" y="${up ? y - 32 : y + 44}" text-anchor="${anc}">${fmtDate(n.d)}</text>`;
    });
    for (let i = 0; i < nodes.length - 1; i++) {
      const key = PAIR[nodes[i].k + ">" + nodes[i + 1].k], iv = key ? ivByKey[key] : null;
      const d = Math.round((ms(nodes[i + 1].d) - ms(nodes[i].d)) / 86400000);
      const mid = (x(nodes[i].d) + x(nodes[i + 1].d)) / 2;
      if (x(nodes[i + 1].d) - x(nodes[i].d) > 36) s += `<text x="${mid}" y="${y + 4}" text-anchor="middle" style="fill:#fff;font-weight:700;font-size:11px">${d}d${iv && iv.target ? "" : ""}</text>`;
    }
    if (ongoing) {
      const cx = x(today);
      s += `<line x1="${cx}" x2="${cx}" y1="${y - 20}" y2="${y + 20}" stroke="#101a2b" stroke-dasharray="3 3"/><text x="${cx}" y="${y + 34}" text-anchor="end" class="lab">Today</text>`;
    }
  }
  return s + "</svg>";
}

/* ---------------------------------------------------------------- charts */
function hbars(rows, { max, target, fmt = (v) => v, cls } = {}) {
  const m = max || Math.max(1, ...rows.map((r) => r.value || 0), target || 0);
  return rows.map((r) => `<div class="hbar"><span>${esc(r.label)}</span><div class="track"><i style="width:${((r.value || 0) / m) * 100}%;${r.color ? "background:" + r.color : ""}"></i>${target ? `<u style="left:${(target / m) * 100}%" title="Target ${target}"></u>` : ""}</div><b class="right">${r.value === null || r.value === undefined ? "–" : esc(fmt(r.value))}</b></div>`).join("");
}
function lineChart(points, { w = 520, h = 190, target, yfmt = (v) => v } = {}) {
  if (!points.length) return `<div class="empty">Not enough data.</div>`;
  const pad = { l: 38, r: 12, t: 12, b: 26 }, mx = Math.max(...points.map((p) => p.y), target || 0) * 1.15 || 1;
  const X = (i) => pad.l + (points.length === 1 ? (w - pad.l - pad.r) / 2 : (i / (points.length - 1)) * (w - pad.l - pad.r));
  const Y = (v) => pad.t + (1 - v / mx) * (h - pad.t - pad.b);
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="Trend chart">`;
  for (let i = 0; i <= 4; i++) { const v = (mx / 4) * i; s += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="#e3e9f1"/><text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end" style="font-size:11px;fill:#566579">${yfmt(Math.round(v))}</text>`; }
  if (target) s += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(target)}" y2="${Y(target)}" stroke="#c2273d" stroke-dasharray="4 4"/><text x="${w - pad.r}" y="${Y(target) - 4}" text-anchor="end" style="font-size:11px;fill:#c2273d">target ${target} d</text>`;
  s += `<polyline fill="none" stroke="#0e6d78" stroke-width="2.4" points="${points.map((p, i) => X(i) + "," + Y(p.y)).join(" ")}"/>`;
  points.forEach((p, i) => { s += `<circle cx="${X(i)}" cy="${Y(p.y)}" r="3.8" fill="#0e6d78"><title>${esc(p.x)}: ${p.y}</title></circle><text x="${X(i)}" y="${h - 8}" text-anchor="middle" style="font-size:11px;fill:#566579">${esc(p.x.slice(2))}</text>`; });
  return s + "</svg>";
}

/* ---------------------------------------------------------------- modal */
function modal(html, onMount) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-bg" role="dialog" aria-modal="true"><div class="modal">${html}</div></div>`;
  const close = () => { root.innerHTML = ""; document.removeEventListener("keydown", esc_); };
  const esc_ = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", esc_);
  $(".modal-bg", root).addEventListener("mousedown", (e) => e.target.classList.contains("modal-bg") && close());
  onMount && onMount($(".modal", root), close);
  return close;
}

/* ---------------------------------------------------------------- router */
const routes = {};
function route() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [name, ...rest] = h.split("/");
  document.querySelectorAll("nav.side a").forEach((a) => a.classList.toggle("on", a.dataset.r === (name === "patient" ? "patients" : name)));
  const fn = routes[name] || routes.dashboard;
  view.innerHTML = `<div class="spin">Loading…</div>`;
  fn(...rest).catch((e) => { view.innerHTML = `<div class="empty">Something went wrong: ${esc(e.message)}</div>`; });
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
const synBanner = () => (META.synthetic_count > 0 ? `<div class="syn">The records shown include <b>${META.synthetic_count}</b> synthetic demo patients (MRN SYN-…). None are real people. Replace them under Settings &amp; data by importing your own CSV.</div>` : "");

/* ---------------------------------------------------------------- dashboard */
routes.dashboard = async () => {
  const d = await api("/dashboard");
  const t = d.totals;
  const miniRows = (rows) => rows.length ? `<table class="t"><tbody>${rows.map((r) => `<tr class="row" onclick="location.hash='#/patient/${r.id}'"><td>${tierChip(r.tier)}</td><td><b>${esc(r.name)}</b><div class="small muted">${siteLabel(r.site)}, stage ${stageLabel(r.stage)}, ${r.age}${r.sex}</div></td><td>${bandTag(r.band)}</td><td class="small">${ACTION[r.action]}</td><td class="small muted nowrap">${r.consult_date ? fmtDate(r.consult_date) : "Not booked"}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">Nothing here.</div>`;
  view.innerHTML = `${synBanner()}
  <div class="pagehead"><div><h1>Today</h1><p>${t.awaiting} referrals are waiting for a first oncology consultation.</p></div>
    <div class="actions"><a class="btn pri" href="#/planner">Plan today's clinic</a><a class="btn" href="#/patients">Open registry</a></div></div>
  <div class="kpis">
    <div class="kpi alert"><b>${d.tiers.P1 || 0}</b><span>need to be seen within 48 h</span></div>
    <div class="kpi"><b>${d.bands.not_ready || 0}</b><span>not ready: critical work-up missing</span></div>
    <div class="kpi"><b>${t.unscheduled}</b><span>have no consult date</span></div>
    <div class="kpi"><b>${t.avg_readiness ?? "–"}%</b><span>average record readiness</span></div>
    <div class="kpi"><b>${t.within_target_pct}%</b><span>treated within ${META.targets.report_to_treatment} d of diagnosis</span></div>
  </div>
  <div class="cols">
    <div>
      <section class="sec"><header><h2>Urgent queue</h2><a class="small" href="#/patients">All patients</a></header>${miniRows(d.urgent)}</section>
      <section class="sec"><header><h2>Next booked consultations</h2></header>${miniRows(d.upcoming)}</section>
    </div>
    <div>
      <section class="sec"><header><h2>Where journeys stall</h2></header>
        <p class="small muted" style="margin-top:0">Step with the largest overshoot against its target, one count per patient.</p>
        ${hbars(d.bottlenecks.map(([l, n]) => ({ label: l.replace("Pathology report", "Report").replace("oncology ", ""), value: n })), { fmt: (v) => v })}</section>
      <section class="sec"><header><h2>Most often missing before a consult</h2></header>
        ${hbars(d.missing.map(([l, n]) => ({ label: l.length > 34 ? l.slice(0, 33) + "…" : l, value: n })), { fmt: (v) => v })}</section>
    </div>
  </div>
  <section class="sec"><header><h2>Time from diagnosis to treatment</h2><span class="small muted">median days by month treatment started</span></header>
    <div class="cols even"><div>${lineChart(d.trend.map((x) => ({ x: x.month, y: x.median })), { target: META.targets.report_to_treatment })}</div>
    <div><table class="t"><thead><tr><th>Step</th><th class="num">Target</th><th class="num">Median</th><th class="num">90th pct</th><th class="num">Over target</th></tr></thead><tbody>
      ${d.intervals.map((i) => `<tr><td>${esc(i.label)}</td><td class="num">${i.target} d</td><td class="num">${daysTxt(i.median)}</td><td class="num">${daysTxt(i.p90)}</td><td class="num">${i.breach_pct ?? "–"}%</td></tr>`).join("")}</tbody></table></div></div>
  </section>`;
};

/* ---------------------------------------------------------------- registry */
const reg = { q: "", site: "", tier: "", band: "", status: "awaiting_consult", sort: "priority", dir: "desc", offset: 0 };
routes.patients = async () => {
  view.innerHTML = `${synBanner()}<div class="pagehead"><div><h1>Referral registry</h1><p id="regcount"></p></div>
    <div class="actions"><button class="btn" id="b-exp">Export CSV</button><button class="btn" id="b-imp">Import CSV</button><button class="btn pri" id="b-new">Add patient</button></div></div>
    <div class="filters"><input id="f-q" type="search" placeholder="Search name, MRN, city" aria-label="Search" value="${esc(reg.q)}">
    <select id="f-site" aria-label="Cancer site"><option value="">All sites</option>${Object.keys(META.sites).map((k) => `<option value="${k}">${siteLabel(k)}</option>`).join("")}</select>
    <select id="f-tier" aria-label="Priority"><option value="">All priorities</option><option value="P1">P1 urgent</option><option value="P2">P2</option><option value="P3">P3</option></select>
    <select id="f-band" aria-label="Readiness"><option value="">Any readiness</option><option value="ready">Ready</option><option value="nearly">Nearly ready</option><option value="not_ready">Not ready</option></select>
    <select id="f-status" aria-label="Status"><option value="">Any status</option><option value="awaiting_consult">Awaiting consult</option><option value="in_treatment">In treatment</option></select></div>
    <div id="regtable"></div>`;
  for (const k of ["site", "tier", "band", "status"]) { const el = $("#f-" + k); el.value = reg[k]; el.onchange = () => { reg[k] = el.value; reg.offset = 0; load(); }; }
  let tm; $("#f-q").oninput = (e) => { clearTimeout(tm); tm = setTimeout(() => { reg.q = e.target.value; reg.offset = 0; load(); }, 250); };
  $("#b-new").onclick = () => patientForm();
  $("#b-exp").onclick = () => (location.href = "/api/export/patients.csv");
  $("#b-imp").onclick = importDialog;
  async function load() {
    const qs = new URLSearchParams({ q: reg.q, site: reg.site, tier: reg.tier, band: reg.band, status: reg.status, sort: reg.sort, dir: reg.dir, limit: 50, offset: reg.offset });
    const r = await api("/patients?" + qs);
    $("#regcount").textContent = `${r.total} patients match`;
    const th = (k, l, cls = "") => `<th class="sortable ${cls}" data-k="${k}" aria-sort="${reg.sort === k ? (reg.dir === "desc" ? "descending" : "ascending") : "none"}">${l}${reg.sort === k ? (reg.dir === "desc" ? " ▾" : " ▴") : ""}</th>`;
    $("#regtable").innerHTML = r.rows.length ? `<table class="t"><thead><tr>${th("priority", "Priority")}${th("name", "Patient")}${th("site", "Site")}${th("stage", "Stage")}${th("readiness", "Readiness")}${th("missing_critical", "Missing")}<th>Journey</th>${th("total_days", "Days", "num")}${th("risk", "Delay risk")}<th>Next step</th></tr></thead><tbody>
      ${r.rows.map((p) => `<tr class="row" data-id="${p.id}"><td>${tierChip(p.tier)} <span class="small muted">${p.priority}</span></td><td><b>${esc(p.name)}</b><div class="small muted">${esc(p.mrn)}, ${p.age}${p.sex}${p.red_flags ? ` <span class="flag">${p.red_flags} red flag${p.red_flags > 1 ? "s" : ""}</span>` : ""}</div></td>
      <td>${siteLabel(p.site)}</td><td>${stageLabel(p.stage)}</td><td>${bar(p.readiness, readCls(p.readiness))} <span class="small">${Math.round(p.readiness)}%</span></td>
      <td>${p.missing_critical ? `<span class="flag">${p.missing_critical} critical</span>` : p.missing ? `${p.missing} other` : '<span class="muted">none</span>'}</td>
      <td data-rail="${p.id}"></td><td class="num">${p.total_days ?? "–"}</td><td>${riskTag(p.risk_band, p.risk)}</td><td class="small">${ACTION[p.action]}</td></tr>`).join("")}</tbody></table>
      <div class="actions" style="margin-top:12px;justify-content:space-between"><span class="small muted">Showing ${r.offset ?? reg.offset + 1}–${Math.min(reg.offset + 50, r.total)} of ${r.total}</span><span><button class="btn sm" id="pg-prev" ${reg.offset ? "" : "disabled"}>Previous</button> <button class="btn sm" id="pg-next" ${reg.offset + 50 < r.total ? "" : "disabled"}>Next</button></span></div>` : `<div class="empty">No patients match. Clear a filter, or add a patient.</div>`;
    document.querySelectorAll("#regtable th.sortable").forEach((h) => (h.onclick = () => { const k = h.dataset.k; reg.dir = reg.sort === k && reg.dir === "desc" ? "asc" : "desc"; reg.sort = k; load(); }));
    document.querySelectorAll("#regtable tr.row").forEach((tr) => (tr.onclick = () => (location.hash = "#/patient/" + tr.dataset.id)));
    const pn = $("#pg-next"), pp = $("#pg-prev");
    if (pn) pn.onclick = () => { reg.offset += 50; load(); }; if (pp) pp.onclick = () => { reg.offset = Math.max(0, reg.offset - 50); load(); };
    r.rows.forEach((p) => { const c = document.querySelector(`[data-rail="${p.id}"]`); if (c) c.innerHTML = rail(p.rail, { compact: true }); });
  }
  await load();
};

/* ---------------------------------------------------------------- patient form */
function patientForm(existing) {
  const p = existing || { symptoms: [] };
  const sym = Object.entries(META.symptoms);
  modal(`<h2>${existing ? "Edit patient" : "Add patient"}</h2><form id="pf">
  <div class="fgrid">
   <label class="f span2"><span>Full name</span><input name="name" required value="${esc(p.name)}"></label>
   <label class="f"><span>Age</span><input name="age" type="number" min="0" max="120" value="${p.age ?? ""}"></label>
   <label class="f"><span>Sex</span><select name="sex"><option value="F">Female</option><option value="M">Male</option></select></label>
   <label class="f"><span>Cancer site</span><select name="site" required>${Object.keys(META.sites).map((k) => `<option value="${k}">${siteLabel(k)}</option>`).join("")}</select></label>
   <label class="f"><span>Clinical stage</span><select name="stage"><option value="">Not staged yet</option>${[1, 2, 3, 4].map((v) => `<option value="${v}">${stageLabel(v)}</option>`).join("")}</select></label>
   <label class="f"><span>ECOG (0–4)</span><select name="ecog"><option value="">Not recorded</option>${[0, 1, 2, 3, 4].map((v) => `<option value="${v}">${v}</option>`).join("")}</select></label>
   <label class="f"><span>Weight loss (%)</span><input name="weight_loss_pct" type="number" step="0.1" min="0" value="${p.weight_loss_pct ?? ""}"></label>
   <label class="f"><span>Haemoglobin (g/dL)</span><input name="hb" type="number" step="0.1" value="${p.hb ?? ""}"></label>
   <label class="f"><span>Symptom onset</span><input name="symptom_onset" type="date" value="${p.symptom_onset || ""}"></label>
   <label class="f"><span>Consult date (if booked)</span><input name="consult_date" type="date" value="${p.consult_date || ""}"></label>
   <label class="f"><span>Referring doctor</span><input name="referring_doctor" value="${esc(p.referring_doctor)}"></label>
   <label class="f"><span>City</span><input name="city" value="${esc(p.city)}"></label>
   <label class="f"><span>Distance from centre (km)</span><input name="distance_km" type="number" min="0" value="${p.distance_km ?? ""}"></label>
   <div class="span3"><span class="small muted" style="font-weight:550">Symptoms (red ones raise urgency)</span><div class="symgrid">${sym.map(([k, v]) => `<label class="${v.urgent ? "urg" : ""}"><input type="checkbox" name="sym" value="${k}" ${p.symptoms.includes(k) ? "checked" : ""}>${esc(v.label)}</label>`).join("")}</div></div>
   <label class="f span3"><span>Notes</span><textarea name="notes" rows="2">${esc(p.notes)}</textarea></label>
  </div><div class="actions" style="margin-top:16px;justify-content:flex-end"><button type="button" class="btn" id="pf-c">Cancel</button><button class="btn pri">${existing ? "Save changes" : "Add patient"}</button></div></form>`, (m, close) => {
    const f = $("#pf", m);
    f.sex.value = p.sex || "F"; f.site.value = p.site || "breast"; f.stage.value = p.stage ?? ""; f.ecog.value = p.ecog ?? "";
    $("#pf-c", m).onclick = close;
    f.onsubmit = safe(async (e) => {
      e.preventDefault();
      const fd = new FormData(f), body = {};
      for (const k of ["name", "age", "sex", "site", "stage", "ecog", "weight_loss_pct", "hb", "symptom_onset", "consult_date", "referring_doctor", "city", "distance_km", "notes"]) body[k] = fd.get(k);
      body.symptoms = fd.getAll("sym");
      if (existing) { await api("/patients/" + p.id, { method: "PUT", body }); toast("Changes saved"); close(); route(); }
      else { const r = await api("/patients", { method: "POST", body }); toast("Patient added"); close(); location.hash = "#/patient/" + r.id; }
    });
  });
}

function importDialog() {
  modal(`<h2>Import patients from CSV</h2><p class="muted">One row per patient. Dates become journey events, so readiness and delays are computed immediately. Rows with errors are skipped and listed.</p>
  <p><a href="/api/import/template.csv">Download the template</a></p><input type="file" id="csvf" accept=".csv,text/csv"><div id="imres" style="margin-top:12px"></div>
  <div class="actions" style="margin-top:16px;justify-content:flex-end"><button class="btn" id="im-c">Close</button><button class="btn pri" id="im-go">Import</button></div>`, (m, close) => {
    $("#im-c", m).onclick = close;
    $("#im-go", m).onclick = safe(async () => {
      const f = $("#csvf", m).files[0]; if (!f) return toast("Choose a CSV file first", true);
      const r = await fetch("/api/import", { method: "POST", headers: { "Content-Type": "text/csv" }, body: await f.text() }).then((x) => x.json());
      $("#imres", m).innerHTML = `<b>${r.imported} imported</b>, ${r.rejected} skipped.${(r.errors || []).map((e) => `<div class="small flag">Row ${e.row}: ${esc(e.error)}</div>`).join("")}`;
      if (r.imported) { META = await api("/meta"); toast(`${r.imported} patients imported`); }
    });
  });
}

/* ---------------------------------------------------------------- patient workspace */
routes.patient = async (id) => {
  const d = await api("/patients/" + id);
  renderPatient(d);
};
function renderPatient(d) {
  const p = d.patient, ev = d.evaluation, rd = ev.readiness, pr = ev.priority, jr = ev.journey, rec = ev.recommendation;
  const groups = {};
  rd.items.forEach((i) => (groups[i.category] = groups[i.category] || []).push(i));
  const iv = jr.intervals;
  view.innerHTML = `${p.synthetic ? `<div class="syn">Synthetic demo patient. Not a real person.</div>` : ""}
  <div class="pagehead"><div><a class="small" href="#/patients">Back to registry</a><h1 style="margin-top:4px">${esc(p.name)} ${tierChip(pr.tier)}</h1>
    <p>${esc(p.mrn)}, ${p.age}${p.sex}, ${siteLabel(p.site)}, stage ${stageLabel(p.stage)}, ${p.ecog === null ? "ECOG not recorded" : "ECOG " + p.ecog}${p.referring_doctor ? ", referred by " + esc(p.referring_doctor) : ""}${p.city ? ", " + esc(p.city) : ""}</p></div>
    <div class="actions"><a class="btn pri" href="/patients/${p.id}/brief" target="_blank" rel="noopener">Open consultation brief</a><button class="btn" id="b-copy">Copy brief text</button><a class="btn" href="/api/patients/${p.id}/fhir.json" target="_blank" rel="noopener">FHIR export</a><button class="btn" id="b-edit">Edit</button><button class="btn danger" id="b-del">Delete</button></div></div>
  <div class="callout ${pr.tier}" style="margin-bottom:22px"><b>${esc(rec.text)}</b><div class="small muted">Priority ${pr.score}/100, ${pr.sla.toLowerCase()}. Record readiness ${rd.score}% (${rd.band.replace("_", " ")}).</div></div>
  <section class="sec"><header><h2>Patient journey</h2><span class="small muted">${jr.total_days !== null ? jr.total_days + " days from first symptom" + (jr.treated ? " to treatment start" : " so far") : ""}</span></header>
    <div style="overflow-x:auto">${rail(jr, { width: 880 })}</div>
    <table class="t" style="margin-top:6px"><thead><tr><th>Step</th><th class="num">Time taken</th><th class="num">Target</th><th>Status</th></tr></thead><tbody>
    ${iv.map((i) => `<tr><td>${esc(i.label)}</td><td class="num">${i.state === "ongoing" ? daysTxt(i.days) + " and counting" : i.state === "scheduled" ? daysTxt(i.days) + " (booked)" : daysTxt(i.days)}</td><td class="num">${i.target} d</td><td><span class="dot ${i.status}"></span>${i.state === "missing_date" ? "Date missing" : i.state === "inconsistent" ? "Dates out of order" : STATUSLBL[i.status]}</td></tr>`).join("")}</tbody></table>
    ${jr.safety.map((s) => `<div class="small ${s.severity === "high" ? "flag" : "muted"}" style="margin-top:6px">${s.severity === "high" ? "Safety check: " : "Note: "}${esc(s.text)}</div>`).join("")}
    <details style="margin-top:12px"><summary class="small" style="cursor:pointer">Recorded events (${d.events.length}) and add an event</summary>
      <table class="t"><tbody>${d.events.map((e) => `<tr><td>${fmtDate(e.date)}</td><td>${esc((META.events.find((x) => x.key === e.type) || {}).label || e.type)}</td><td class="muted">${esc(e.facility)}</td><td class="right"><button class="btn sm danger" data-del-ev="${e.id}">Remove</button></td></tr>`).join("")}</tbody></table>
      <form id="evf" class="actions" style="margin-top:8px"><select name="type" aria-label="Event type" style="width:auto">${META.events.map((e) => `<option value="${e.key}">${e.label}</option>`).join("")}</select><input type="date" name="date" required style="width:auto" aria-label="Event date"><input name="facility" placeholder="Facility (optional)" style="width:200px"><button class="btn pri sm">Add event</button></form></details>
  </section>
  <div class="cols">
    <section class="sec"><header><h2>Consultation readiness</h2><span><b>${rd.score}%</b> ${bar(rd.score, readCls(rd.score))}</span></header>
      ${Object.entries(groups).map(([g, items]) => `<div class="group"><h3>${esc(g)}</h3>${items.map((i) => `<div class="ck ${i.status === "pending" ? "missing" : ""} ${i.critical ? "crit" : ""}"><div class="lbl"><span class="nm">${esc(i.label)}${i.critical ? ' <span class="flag" title="Critical item">*</span>' : ""}</span><span class="own">${esc(i.owner_label)}${i.hint ? ", " + esc(i.hint) : ""}${i.received_date && i.status === "received" ? ", received " + fmtDate(i.received_date) : ""}</span></div>
        ${i.auto ? '<span class="small muted">Taken from ECOG field</span>' : `<span class="seg" role="group" aria-label="${esc(i.label)}">${["received", "pending", "na"].map((s) => `<button class="${s} ${i.status === s ? "on" : ""}" data-item="${i.key}" data-s="${s}" aria-pressed="${i.status === s}">${{ received: "Received", pending: "Pending", na: "Not needed" }[s]}</button>`).join("")}</span>`}</div>`).join("")}</div>`).join("")}
      <div class="small muted">* critical: the consultation cannot reach a treatment decision without it.</div></section>
    <div>
      ${ev.red_flags.length ? `<section class="sec"><header><h2>Red flags</h2></header><ul class="list">${ev.red_flags.map((r) => `<li class="flag">${esc(r.label)}</li>`).join("")}</ul></section>` : ""}
      <section class="sec"><header><h2>Why priority ${pr.tier}</h2></header>${pr.reasons.map((r) => `<div class="reason"><b>+${r.points}</b><span>${esc(r.text)}</span></div>`).join("")}</section>
      ${d.risk ? `<section class="sec"><header><h2>Risk of treatment delay</h2>${riskTag(d.risk.band, d.risk.probability)}</header><p class="small muted" style="margin-top:0">${esc(d.risk.label)}. Estimated from the cohort; use as a prompt to check, not a verdict.</p>
        <ul class="list">${d.risk.drivers.map((x) => `<li class="small">${esc(x.factor)} <span class="muted">${x.effect}</span></li>`).join("")}</ul></section>` : ""}
      <section class="sec"><header><h2>What this consult needs to settle</h2></header><ul class="list">${d.brief.questions.map((q) => `<li class="small">${esc(q)}</li>`).join("")}</ul></section>
      <section class="sec soft"><header><h2>Activity</h2></header>${d.audit.length ? d.audit.slice(0, 6).map((a) => `<div class="small"><span class="muted">${a.ts.replace("T", " ")}</span> ${esc(a.action.replace(/_/g, " "))} ${esc(a.detail || "")}</div>`).join("") : '<span class="small muted">No activity yet.</span>'}</section>
    </div>
  </div>`;
  $("#b-edit").onclick = () => patientForm(p);
  $("#b-del").onclick = () => modal(`<h2>Delete ${esc(p.name)}?</h2><p>This removes the patient, their journey events and checklist. It cannot be undone.</p><div class="actions" style="justify-content:flex-end"><button class="btn" id="d-c">Keep patient</button><button class="btn danger" id="d-y">Delete patient</button></div>`, (m, close) => { $("#d-c", m).onclick = close; $("#d-y", m).onclick = safe(async () => { await api("/patients/" + p.id, { method: "DELETE" }); close(); toast("Patient deleted"); location.hash = "#/patients"; }); });
  $("#b-copy").onclick = safe(async () => { const t = await fetch(`/api/patients/${p.id}/brief.txt`).then((r) => r.text()); try { await navigator.clipboard.writeText(t); toast("Brief copied"); } catch (e) { modal(`<h2>Brief text</h2><pre class="txt">${esc(t)}</pre><div class="actions" style="justify-content:flex-end"><button class="btn" id="x">Close</button></div>`, (m, c) => ($("#x", m).onclick = c)); } });
  document.querySelectorAll("[data-item]").forEach((b) => (b.onclick = safe(async () => { await api(`/patients/${p.id}/items`, { method: "POST", body: { key: b.dataset.item, status: b.dataset.s } }); const fresh = await api("/patients/" + p.id); renderPatient(fresh); toast("Checklist updated"); })));
  document.querySelectorAll("[data-del-ev]").forEach((b) => (b.onclick = safe(async () => { await api("/events/" + b.dataset.delEv, { method: "DELETE" }); renderPatient(await api("/patients/" + p.id)); toast("Event removed"); })));
  $("#evf").onsubmit = safe(async (e) => { e.preventDefault(); const fd = new FormData(e.target); await api(`/patients/${p.id}/events`, { method: "POST", body: Object.fromEntries(fd) }); renderPatient(await api("/patients/" + p.id)); toast("Event added"); });
}

/* ---------------------------------------------------------------- planner */
routes.planner = async () => {
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  view.innerHTML = `${synBanner()}<div class="pagehead"><div><h1>Clinic planner</h1><p>Builds a session from the waiting list: urgent patients first, then ready patients, then the rest. Anyone not ready gets a prep task for the right owner.</p></div></div>
  <form id="pl" class="filters" style="align-items:flex-end">
    <label class="f">Clinic date<input type="date" name="date" value="${tomorrow}" style="width:auto"></label>
    <label class="f">Start<input type="time" name="start" value="09:00" style="width:auto"></label>
    <label class="f">End<input type="time" name="end" value="13:00" style="width:auto"></label>
    <label class="f">Doctors<input type="number" name="doctors" min="1" max="8" value="2" style="width:80px"></label>
    <label class="f">Standard slot (min)<input type="number" name="new_min" min="10" max="90" value="30" style="width:90px"></label>
    <label class="f">Complex slot (min)<input type="number" name="complex_min" min="15" max="120" value="45" style="width:90px"></label>
    <label class="f">Site<select name="site" style="width:auto"><option value="">All sites</option>${Object.keys(META.sites).map((k) => `<option value="${k}">${siteLabel(k)}</option>`).join("")}</select></label>
    <button class="btn pri">Build schedule</button></form>
  <div id="plout"><div class="empty">Choose a date and press Build schedule.</div></div>`;
  let last = null;
  $("#pl").onsubmit = safe(async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const body = { start: f.start, end: f.end, doctors: +f.doctors, new_min: +f.new_min, complex_min: +f.complex_min, only_date: f.date, site: f.site };
    const r = await api("/planner", { method: "POST", body });
    last = { r, date: f.date };
    const k = r.kpis;
    const docs = {};
    r.schedule.forEach((s) => (docs[s.doctor] = docs[s.doctor] || []).push(s));
    $("#plout").innerHTML = `<div class="kpis"><div class="kpi"><b>${k.booked}</b><span>patients booked from ${r.candidates} waiting</span></div><div class="kpi alert"><b>${k.urgent_booked}</b><span>urgent (P1) seen</span></div><div class="kpi"><b>${k.conditional}</b><span>seen before work-up is complete</span></div><div class="kpi"><b>${k.utilisation}%</b><span>of session time used</span></div><div class="kpi"><b>${k.waitlisted}</b><span>left on the waiting list</span></div></div>
    <section class="sec"><header><h2>Schedule for ${fmtDate(f.date)}</h2><button class="btn pri sm" id="commit">Confirm bookings</button></header>
      <div class="slots" style="--n:${Math.min(4, Object.keys(docs).length || 1)}">${Object.entries(docs).map(([d, rows]) => `<div><h3 style="margin-bottom:4px">Doctor ${d}</h3>${rows.map((s) => `<div class="slot" data-id="${s.id}"><div><div class="time">${s.start}</div><div class="small muted">${s.minutes} min</div></div><div>${tierChip(s.tier)} <b>${esc(s.name)}</b><div><span class="tagp ${s.tag}">${{ ready: "Ready", conditional: "Chase items first", parallel_workup: "Test in parallel" }[s.tag]}</span> <span class="small muted">${s.n_missing} item${s.n_missing === 1 ? "" : "s"} outstanding</span></div></div></div>`).join("") || '<div class="empty">No slots filled.</div>'}</div>`).join("") || '<div class="empty">No patients to schedule for these filters.</div>'}</div></section>
    <div class="cols even"><section class="sec"><header><h2>Prep tasks before the clinic</h2><span class="small muted">${k.task_count} tasks</span></header>
      ${Object.entries(r.tasks).map(([o, ts]) => `<details><summary style="cursor:pointer;padding:5px 0"><b>${esc(o)}</b> <span class="muted small">${ts.length} item${ts.length === 1 ? "" : "s"}</span></summary><ul class="list">${ts.map((t) => `<li class="small"><a href="#/patient/${t.patient_id}">${esc(t.patient)}</a>: ${esc(t.item)}${t.critical ? ' <span class="flag">critical</span>' : ""}</li>`).join("")}</ul></details>`).join("") || '<div class="empty">Everyone booked is fully prepared.</div>'}</section>
      <section class="sec"><header><h2>Waiting list</h2><span class="small muted">${r.waitlist.length} not placed</span></header>
      <table class="t"><tbody>${r.waitlist.slice(0, 15).map((w) => `<tr class="row" onclick="location.hash='#/patient/${w.id}'"><td>${tierChip(w.tier)}</td><td>${esc(w.name)}</td><td>${bandTag(w.band)}</td></tr>`).join("") || '<tr><td class="muted">Everyone fits in this session.</td></tr>'}</tbody></table>${r.waitlist.length > 15 ? `<div class="small muted" style="margin-top:6px">…and ${r.waitlist.length - 15} more. Add a doctor or extend the session.</div>` : ""}</section></div>`;
    document.querySelectorAll(".slot").forEach((s) => (s.onclick = () => (location.hash = "#/patient/" + s.dataset.id)));
    const c = $("#commit");
    if (c) c.onclick = safe(async () => { const x = await api("/planner/commit", { method: "POST", body: { date: last.date, patient_ids: last.r.schedule.map((s) => s.id) } }); toast(`${x.updated} consultations booked for ${fmtDate(last.date)}`); });
  });
};

/* ---------------------------------------------------------------- analytics */
routes.analytics = async () => {
  const d = await api("/analytics");
  const tgt = META.targets.report_to_treatment;
  view.innerHTML = `${synBanner()}<div class="pagehead"><div><h1>Journey analytics</h1><p>Where delay comes from across the whole cohort.</p></div></div>
  <section class="sec"><header><h2>By cancer site</h2></header><table class="t"><thead><tr><th>Site</th><th class="num">Patients</th><th>Average readiness</th><th class="num">Ready</th><th class="num">Median diagnosis to treatment</th><th class="num">Over ${tgt} d</th><th class="num">With red flags</th></tr></thead><tbody>
  ${d.sites.map((s) => `<tr><td><b>${esc(s.label)}</b></td><td class="num">${s.n}</td><td>${bar(s.readiness, readCls(s.readiness))} ${s.readiness}%</td><td class="num">${s.ready_pct}%</td><td class="num">${daysTxt(s.median_dx_to_tx)}</td><td class="num">${s.over_target_pct ?? "–"}%</td><td class="num">${s.red_flag_pct}%</td></tr>`).join("")}</tbody></table></section>
  <div class="cols even"><section class="sec"><header><h2>Distance from the centre</h2><span class="small muted">median days, diagnosis to treatment</span></header>${hbars(d.distance.map((x) => ({ label: `${x.bin} (n=${x.n})`, value: x.median })), { target: tgt, fmt: (v) => v + " d" })}</section>
  <section class="sec"><header><h2>Number of facilities visited</h2><span class="small muted">median days, diagnosis to treatment</span></header>${hbars(d.hops.map((x) => ({ label: `${x.hops} facilit${x.hops === "1" ? "y" : "ies"} (n=${x.n})`, value: x.median })), { target: tgt, fmt: (v) => v + " d" })}</section></div>
  <p class="small muted">The black tick marks the ${tgt}-day target. Patterns reflect whichever data is loaded; with the demo cohort they come from the generator's assumptions, not from real patients.</p>`;
};

/* ---------------------------------------------------------------- model */
routes.model = async () => {
  const d = await api("/model"), m = d.metrics;
  if (!m) { view.innerHTML = `<div class="pagehead"><h1>Delay-risk model</h1></div><div class="empty">No model trained yet.<br><button class="btn pri" id="tr" style="margin-top:10px">Train model</button></div>`; $("#tr").onclick = safe(async () => { await api("/model/train", { method: "POST" }); route(); }); return; }
  const b = m.logistic_regression, g = m.gradient_boosting;
  view.innerHTML = `${synBanner()}<div class="pagehead"><div><h1>Delay-risk model</h1><p>Predicts whether diagnosis to treatment will exceed ${d.label_days} days, using only what is known at the consultation.</p></div><div class="actions"><button class="btn pri" id="tr">Retrain on current data</button></div></div>
  <div class="syn" style="background:#fdecef;border-color:#f3b9c4;color:#7a1626"><b>Read this first.</b> ${esc(m.caveat)} Trained on: <b>${esc(m.trained_on)}</b> data. Do not use scores clinically until retrained on real data and validated.</div>
  <div class="kpis"><div class="kpi"><b>${m.n_total}</b><span>treated patients used (${m.n_train} train, ${m.n_test} test)</span></div><div class="kpi"><b>${Math.round(m.prevalence * 100)}%</b><span>were delayed beyond ${d.label_days} d</span></div><div class="kpi"><b>${b.auc}</b><span>test AUC, logistic (served)</span></div><div class="kpi"><b>${g.auc}</b><span>test AUC, gradient boosting</span></div><div class="kpi"><b>${m.cv_auc_logistic[0]}</b><span>5-fold CV AUC (±${m.cv_auc_logistic[1]})</span></div></div>
  <div class="cols even"><section class="sec"><header><h2>Held-out test performance</h2></header><table class="t"><thead><tr><th></th><th class="num">AUC</th><th class="num">Accuracy</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">Brier</th></tr></thead><tbody>
    <tr><td>Logistic regression</td><td class="num">${b.auc}</td><td class="num">${b.accuracy}</td><td class="num">${b.precision}</td><td class="num">${b.recall}</td><td class="num">${b.brier}</td></tr>
    <tr><td>Gradient boosting</td><td class="num">${g.auc}</td><td class="num">${g.accuracy}</td><td class="num">${g.precision}</td><td class="num">${g.recall}</td><td class="num">${g.brier}</td></tr>
    <tr><td>Rule: consult wait over target</td><td class="num">–</td><td class="num">${m.baseline_rule_wait_over_target.accuracy}</td><td class="num">${m.baseline_rule_wait_over_target.precision}</td><td class="num">${m.baseline_rule_wait_over_target.recall}</td><td class="num">–</td></tr>
    <tr><td>Always predict "on time"</td><td class="num">0.5</td><td class="num">${m.majority_class_accuracy}</td><td class="num">–</td><td class="num">0</td><td class="num">–</td></tr></tbody></table>
    <p class="small muted">Threshold 0.5. Accuracy alone flatters the model when most patients are on time, so judge it by AUC, recall and calibration.</p></section>
  <section class="sec"><header><h2>Calibration</h2></header><table class="t"><thead><tr><th>Predicted range</th><th class="num">Patients</th><th class="num">Mean predicted</th><th class="num">Actually delayed</th></tr></thead><tbody>${m.calibration.map((c) => `<tr><td>${c.bin}</td><td class="num">${c.n}</td><td class="num">${Math.round(c.predicted * 100)}%</td><td class="num">${Math.round(c.observed * 100)}%</td></tr>`).join("")}</tbody></table></section></div>
  <section class="sec"><header><h2>What drives the prediction</h2><span class="small muted">standardised logistic coefficients</span></header>${hbars(m.top_coefficients.map(([n, c]) => ({ label: n, value: Math.abs(c), color: c > 0 ? "#c2273d" : "#1f8a70" })), { fmt: (v) => v.toFixed(2) })}<p class="small muted">Red raises risk, green lowers it.</p></section>`;
  $("#tr").onclick = safe(async () => { $("#tr").disabled = true; $("#tr").textContent = "Training…"; await api("/model/train", { method: "POST" }); toast("Model retrained"); route(); });
};

/* ---------------------------------------------------------------- audit + settings */
routes.audit = async () => {
  const r = await api("/audit?limit=300");
  view.innerHTML = `<div class="pagehead"><div><h1>Audit log</h1><p>Every change and export, newest first.</p></div></div><table class="t"><thead><tr><th>Time</th><th>Who</th><th>Action</th><th>Patient</th><th>Detail</th></tr></thead><tbody>${r.rows.map((a) => `<tr><td class="nowrap small">${a.ts.replace("T", " ")}</td><td>${esc(a.actor)}</td><td>${esc(a.action.replace(/_/g, " "))}</td><td>${a.patient_id ? `<a href="#/patient/${a.patient_id}">#${a.patient_id}</a>` : ""}</td><td class="small muted">${esc(a.detail || "")}</td></tr>`).join("")}</tbody></table>`;
};
routes.settings = async () => {
  const s = await api("/settings");
  view.innerHTML = `${synBanner()}<div class="pagehead"><div><h1>Settings &amp; data</h1></div></div>
  <section class="sec"><header><h2>Time targets for each journey step</h2></header><p class="muted small" style="margin-top:0">Defaults are starting points. Set them to your institution's protocol; every score and delay flag recalculates.</p>
   <form id="tg" class="fgrid" style="max-width:760px">${Object.entries(META.intervals).map(([k, v]) => `<label class="f"><span>${esc(v.label)} (days)</span><input type="number" min="1" max="365" name="${k}" value="${s.targets[k]}"></label>`).join("")}<div style="align-self:end"><button class="btn pri">Save targets</button> <button type="button" class="btn" id="tg-r">Reset to defaults</button></div></form></section>
  <section class="sec"><header><h2>Data</h2></header><div class="actions"><button class="btn" id="imp">Import patients from CSV</button><a class="btn" href="/api/export/patients.csv">Export registry CSV</a><button class="btn" id="seed">Regenerate demo cohort</button><button class="btn danger" id="reset">Remove all patients</button></div>
  <p class="small muted">Demo data is synthetic. Public datasets such as Kaggle could not be downloaded from this environment, so for real use import your own records.</p></section>`;
  $("#tg").onsubmit = safe(async (e) => { e.preventDefault(); const b = Object.fromEntries(new FormData(e.target)); const r = await api("/settings/targets", { method: "PUT", body: b }); META.targets = r.targets; toast("Targets saved"); });
  $("#tg-r").onclick = safe(async () => { const r = await api("/settings/targets", { method: "PUT", body: s.defaults }); META.targets = r.targets; toast("Defaults restored"); route(); });
  $("#imp").onclick = importDialog;
  $("#seed").onclick = () => modal(`<h2>Regenerate demo cohort?</h2><p>Adds 700 new synthetic patients and retrains the model. Existing patients stay.</p><div class="actions" style="justify-content:flex-end"><button class="btn" id="c">Cancel</button><button class="btn pri" id="y">Generate</button></div>`, (m, close) => { $("#c", m).onclick = close; $("#y", m).onclick = safe(async () => { $("#y", m).disabled = true; $("#y", m).textContent = "Generating…"; await api("/seed", { method: "POST", body: { n: 700, seed: Math.floor(Math.random() * 1e6) } }); META = await api("/meta"); close(); toast("Demo cohort added"); route(); }); });
  $("#reset").onclick = () => modal(`<h2>Remove every patient?</h2><p>All patients, events and the audit log are deleted. This cannot be undone.</p><div class="actions" style="justify-content:flex-end"><button class="btn" id="c">Cancel</button><button class="btn danger" id="y">Remove all</button></div>`, (m, close) => { $("#c", m).onclick = close; $("#y", m).onclick = safe(async () => { await api("/reset", { method: "POST" }); META = await api("/meta"); close(); toast("All patients removed"); route(); }); });
};

/* ---------------------------------------------------------------- boot */
(async () => { try { META = await api("/meta"); route(); } catch (e) { view.innerHTML = `<div class="empty">Cannot reach the OncoReady server: ${esc(e.message)}</div>`; } })();
