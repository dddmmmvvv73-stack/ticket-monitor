// «Цели»: весь утверждённый Design/mockups/goals.html, с реальным хранилищем /api/work.
// Shadow DOM сохраняет CSS макета и изолирует его от существующих разделов сайта.
(function () {
"use strict";
const KEY = "ticketmonitor.goals.draft.v1";
const model = {db: null, work: null, base: {}, dirty: false, saving: false, error: ""};
const copy = x => JSON.parse(JSON.stringify(x));
const records = db => ({...Object.fromEntries(db.goals.map(({id, ...g}) => ["objectives/" + id, g])), "goalvision/vision": db.vision});
const clean = x => { if (!x) return null; const r = {...x}; delete r.upd; return r; };
const equal = (a,b) => JSON.stringify(clean(a)) === JSON.stringify(clean(b));
// model.db must not share nested arrays with model.base (server copy): otherwise edits change both and flush sees no difference.
async function request(body) {
  const r = await fetch("/api/work", body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {cache: "no-store"});
  const d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || "Не удалось сохранить цели"); return d;
}
function cacheDraft() { try { localStorage.setItem(KEY, JSON.stringify({db: model.db, base: model.base})); } catch (_) {} }
async function flush() {
  if (model.saving || !model.db) return;
  model.saving = true; model.error = "";
  try {
    while (model.dirty) {
      model.dirty = false;
      if (model.status) model.status();
      const wanted = copy(records(model.db));
      for (const key of new Set([...Object.keys(model.base), ...Object.keys(wanted)])) {
        if (equal(wanted[key], model.base[key])) continue;
        const [kind, id] = key.split("/");
        model.work = await request({op: wanted[key] ? "put" : "del", kind, id, data: wanted[key], expected: model.base[key] || null});
        window.WK = model.work;
        if (wanted[key]) model.base[key] = model.work[kind][id]; else delete model.base[key];
        cacheDraft();
      }
    }
    try { localStorage.removeItem(KEY); } catch (_) {}
  } catch (e) { model.dirty = true; model.error = "Не сохранено: " + e.message; cacheDraft(); }
  finally { model.saving = false; if (model.status) model.status(); }
}
window.addEventListener("beforeunload", e => { if (model.dirty || model.saving) { e.preventDefault(); e.returnValue = ""; } });
customElements.define("work-goals", class extends HTMLElement {
  connectedCallback() {
    const root = this.shadowRoot || this.attachShadow({mode: "open"});
    root.innerHTML = '<link rel="stylesheet" href="work-goals.css"><div id="save-state" role="status" aria-live="polite"></div><main id="main">Загрузка целей…</main><dialog id="dlg" aria-label="Цели"></dialog><div class="snack" id="snack" role="status"><span id="snack-t"></span><button id="snack-b" hidden>Вернуть</button></div>';
    const start = async () => {
      try {
        if (!model.db) {
          model.work = await request();
          model.db = {vision: clean((model.work.goalvision || {}).vision) || {text: "", horizon: String(new Date().getFullYear() + 3)}, goals: Object.entries(model.work.objectives || {}).map(([id,g]) => ({id,...copy(clean(g))}))};
          model.base = Object.fromEntries(Object.keys(records(model.db)).map(key => { const [k,id] = key.split("/"); return [key, model.work[k] && model.work[k][id] || null]; }));
          let draft; try { draft = JSON.parse(localStorage.getItem(KEY)); } catch (_) {}
          if (draft && draft.db && draft.base) { model.db = draft.db; model.base = draft.base; model.dirty = true; model.error = "Есть несохранённые изменения. Повторите сохранение; при конфликте скачайте изменения перед обновлением."; }
        } else if (!model.dirty && !model.saving) {
          model.work = await request();
          model.db = {vision: clean((model.work.goalvision || {}).vision) || {text: "", horizon: String(new Date().getFullYear() + 3)}, goals: Object.entries(model.work.objectives || {}).map(([id,g]) => ({id,...copy(clean(g))}))};
          model.base = Object.fromEntries(Object.keys(records(model.db)).map(key => { const [k,id] = key.split("/"); return [key, model.work[k] && model.work[k][id] || null]; }));
        }
        if (this.isConnected) mount(root);
      } catch (e) { root.querySelector("#main").textContent = "Не удалось загрузить цели: " + e.message; const b = document.createElement("button"); b.textContent = "Повторить"; b.onclick = start; root.querySelector("#main").appendChild(b); }
    };
    start();
  }
});
function mount(root) {

"use strict";
// ─────────────────────────────── утилиты
const $ = s => root.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const MONF = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const z2 = n => String(n).padStart(2, "0");
const iso = d => d.getFullYear() + "-" + z2(d.getMonth() + 1) + "-" + z2(d.getDate());
const D = s => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const TODAY = iso(new Date());
const addD = (s, n) => { const d = D(s); d.setDate(d.getDate() + n); return iso(d); };
const diff = (a, b) => Math.round((D(b) - D(a)) / 864e5);
const monday = s => { const d = D(s); d.setDate(d.getDate() - (d.getDay() + 6) % 7); return iso(d); };
const fd = s => { if (!s) return ""; const d = D(s); return d.getDate() + " " + MON[d.getMonth()] + (d.getFullYear() !== D(TODAY).getFullYear() ? " " + d.getFullYear() : ""); };
const plural = (n, a, b, c) => { n = Math.abs(n) % 100; const k = n % 10; return n > 10 && n < 20 ? c : k > 1 && k < 5 ? b : k === 1 ? a : c; };
const pl = (n, a, b, c) => n + " " + plural(n, a, b, c);
const pct = p => Math.round(p * 100);
const nf = (v, d = 0) => Number(v).toLocaleString("ru-RU", { maximumFractionDigits: d });
const isBool = kr => kr.unit === "да/нет";
function fv(v, unit) {
  if (unit === "да/нет") return v >= 1 ? "да" : "нет";
  if (unit === "₽") {
    const a = Math.abs(v);
    if (a >= 1e6) return nf(v / 1e6, 1) + " млн ₽";
    if (a >= 1e4) return nf(v / 1e3, 0) + " тыс. ₽";
    return nf(v) + " ₽";
  }
  if (unit === "%") return nf(v, 1) + " %";
  return nf(v, 1) + (unit ? " " + unit : "");
}
const INT_UNITS = new Set(["шт.", "раз", "дней", "человек"]);
const rnd = (v, unit) => INT_UNITS.has(unit) ? Math.round(v) : unit === "₽" ? Math.round(v / 1000) * 1000 : Math.round(v * 10) / 10;
function krPair(k) {
  if (isBool(k)) return fv(k.cur, k.unit);
  const cur = k.unit === "₽" || k.unit === "%" ? fv(k.cur, k.unit) : nf(k.cur, 1);
  return cur + (k.target < k.start ? " → " : " из ") + fv(k.target, k.unit);
}
const svgI = (p, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`;
const IC = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  dots: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  pencil: '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  chev: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  task: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m9 12 2 2 4-4"/>',
  home: '<path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  doc: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M9 15l2 2 4-4"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  note: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M8 13h8M8 17h5"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 16V9M12 16V5M17 16v-4"/>',
  map: '<path d="M14.1 6 9.9 4 3 7v13l6.9-3 4.2 2 6.9-3V3z"/><path d="M9.9 4v13M14.1 6v13"/>',
  ticket: '<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 17v2M13 11v2"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
  flag: '<path d="M4 22V4M4 4h13l-2 4 2 4H4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
  bulb: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2Z"/>',
};
const ic = (n, cls) => svgI(IC[n], cls);
function rand(seed) { let s = seed % 2147483647; if (s <= 0) s += 2147483646; return () => (s = s * 16807 % 2147483647) / 2147483647; }

// ─────────────────────────────── справочники
const SPH = [
  { id: "biz", name: "Бизнес", c: "#2f6fed" },
  { id: "money", name: "Деньги", c: "#d99a16" },
  { id: "art", name: "Артисты", c: "#8b7fc0" },
  { id: "team", name: "Команда", c: "#ec6a3f" },
  { id: "life", name: "Личное", c: "#2f9e6a" },
];
const sph = id => SPH.find(s => s.id === id) || SPH[0];
const ST = {
  ahead: "Опережает", on: "В графике", risk: "Под риском", off: "Отстаёт",
  ready: "Можно закрывать", late: "Срок прошёл", done: "Достигнута", drop: "В архиве",
};
const stCls = st => ({ ready: "on", late: "off" }[st] || st);
const CONF = { ok: ["Уверен, что успею", "темп устраивает", "on"], risk: ["Есть риски", "нужно поднажать", "risk"], bad: ["Под угрозой", "без изменений не успеть", "off"] };
const AUTO = {
  shows: "из «Работы»: прошедшие даты гастролей за срок цели",
  docs: "из «Документов»: подписанные договоры",
  projects: "из «Проектов»: проекты в завершённых статусах",
};
const UNITS = ["шт.", "₽", "%", "да/нет", "раз", "часов", "дней", "человек"];

// The server is authoritative; unsaved changes stay in memory and a recovery draft.
let DB = model.db;
function save() { model.dirty = true; cacheDraft(); flush(); showStatus(); }
const UI = model.ui || (model.ui = { view: "list", gid: null, tab: "ov", filter: "active", sphere: null, visEdit: false });
const G = id => DB.goals.find(g => g.id === id);

// ─────────────────────────────── расчёты
function krP(kr, v) {
  if (v == null) v = kr.cur;
  if (isBool(kr)) return v >= 1 ? 1 : 0;
  const s = kr.target - kr.start;
  return s ? clamp((v - kr.start) / s, 0, 1) : 1;
}
function gP(g, vals) {
  if (!g.krs.length) return 0;
  return g.krs.reduce((a, k) => a + krP(k, vals ? (vals[k.id] ?? k.start) : k.cur), 0) / g.krs.length;
}
function series(g) {
  const pts = [{ at: g.start, p: gP(g, {}) }];
  for (const c of g.checkins) pts.push({ at: c.at, p: gP(g, c.vals), c });
  const cur = gP(g), last = pts[pts.length - 1];
  if (Math.abs(last.p - cur) > 1e-9 && last.at < TODAY) pts.push({ at: TODAY, p: cur });
  return pts;
}
function valAt(g, kr, date) {
  let v = kr.start;
  for (const c of g.checkins) if (c.at <= date && c.vals[kr.id] != null) v = c.vals[kr.id];
  return v;
}
function stats(g) {
  const total = Math.max(1, diff(g.start, g.deadline));
  const el = clamp(diff(g.start, TODAY) / total, 0, 1);
  const p = gP(g), left = diff(TODAY, g.deadline), pts = series(g);
  const tail = pts.slice(-5);
  let slope = null;
  if (tail.length >= 2) {
    const xs = tail.map(t => diff(g.start, t.at)), ys = tail.map(t => t.p);
    const mx = xs.reduce((a, b) => a + b) / xs.length, my = ys.reduce((a, b) => a + b) / ys.length;
    let nu = 0, de = 0;
    xs.forEach((x, i) => { nu += (x - mx) * (ys[i] - my); de += (x - mx) ** 2; });
    if (de > 0) slope = nu / de;
  }
  const proj = slope != null ? clamp(p + slope * Math.max(0, left), 0, 1) : null;
  const eta = slope > 1e-6 && p < 1 ? addD(TODAY, Math.ceil((1 - p) / slope)) : null;
  let st;
  if (g.status === "done") st = "done";
  else if (g.status === "drop") st = "drop";
  else if (p >= 0.999) st = "ready";
  else if (left < 0) st = "late";
  else if (p - el >= 0.1) st = "ahead";
  else if (p - el >= -0.05) st = "on";
  else if (p - el >= -0.15) st = "risk";
  else st = "off";
  const need = left > 0 ? (1 - p) / left * 7 : null;
  return { p, el, gap: p - el, left, total, slope, proj, eta, st, pts, need, pace: slope != null ? slope * 7 : null };
}
const curWeek = () => monday(TODAY);
function weeks(n) { const a = []; for (let i = n - 1; i >= 0; i--) a.push(monday(addD(TODAY, -7 * i))); return a; }
function streak(h) {
  let s = 0; const cw = curWeek();
  for (let i = (h.log[cw] || 0) >= h.per ? 0 : 1; i < 60; i++) { const w = monday(addD(TODAY, -7 * i)); if ((h.log[w] || 0) >= h.per) s++; else break; }
  return s;
}
function adherence(h, n = 4) { // прошлые n недель, без текущей
  let a = 0, c = 0;
  for (let i = 1; i <= n; i++) { const w = monday(addD(TODAY, -7 * i)); if (h.log[w] == null) continue; a += Math.min(h.log[w], h.per) / h.per; c++; }
  return c ? a / c : null;
}
function stageStatus(s, i, g) {
  const n = s.steps.length, d = s.steps.filter(x => x.done).length;
  if (s.done || (n && d === n)) return "done";
  const firstOpen = g.stages.findIndex(x => !(x.done || (x.steps.length && x.steps.every(y => y.done))));
  if (s.due && s.due < TODAY) return "late";
  return i === firstOpen ? "cur" : "next";
}
function nextStep(g) {
  for (const s of g.stages) {
    const open = s.steps.filter(x => !x.done).sort((a, b) => (a.due || s.due || "9") < (b.due || s.due || "9") ? -1 : 1);
    if (open.length) return { step: open[0], stage: s };
  }
  return null;
}
function reviewStreak() {
  const wk = new Set(); DB.goals.forEach(g => g.checkins.forEach(c => wk.add(monday(c.at))));
  let s = 0;
  for (let i = wk.has(curWeek()) ? 0 : 1; i < 100; i++) { if (wk.has(monday(addD(TODAY, -7 * i)))) s++; else break; }
  return { s, thisWeek: wk.has(curWeek()) };
}
const active = () => DB.goals.filter(g => g.status === "active");
function niceStep(span) {
  const raw = Math.abs(span) / 40 || 1, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p; return Math.max(1, (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p);
}

// ─────────────────────────────── рисунки
function ring(p, e, size, sw, opt = {}) {
  const r = (size - sw) / 2 - 3, cx = size / 2, c = 2 * Math.PI * r, pc = clamp(p, 0, 1);
  let tick = "";
  if (e != null) {
    const a = e * 2 * Math.PI - Math.PI / 2, r1 = r - sw / 2 - 3, r2 = r + sw / 2 + 3;
    tick = `<line class="rg-tick" x1="${cx + r1 * Math.cos(a)}" y1="${cx + r1 * Math.sin(a)}" x2="${cx + r2 * Math.cos(a)}" y2="${cx + r2 * Math.sin(a)}"><title>План на сегодня — ${pct(e)} %</title></line>`;
  }
  const fs = opt.fs || size * 0.24;
  return `<svg class="ring" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="Прогресс ${pct(p)} %${e != null ? ", план " + pct(e) + " %" : ""}">
    <circle class="rg-bg" cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke-width="${sw}"/>
    <circle class="rg-fg" cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${c * pc} ${c}" transform="rotate(-90 ${cx} ${cx})"/>
    ${tick}
    <text x="${cx}" y="${cx + fs * (opt.sub ? 0.18 : 0.36)}" text-anchor="middle" font-size="${fs}">${pct(p)}<tspan font-size="${fs * 0.5}">%</tspan></text>
    ${opt.sub ? `<text class="rg-sub" x="${cx}" y="${cx + fs * 0.95}" text-anchor="middle" font-size="${Math.max(10, fs * 0.36)}">${opt.sub}</text>` : ""}
  </svg>`;
}
function krBar(kr, e) {
  return `<div class="bar thin"><i style="width:${pct(krP(kr))}%"></i>${e != null ? `<span class="tick" style="left:${pct(e)}%" title="План на сегодня"></span>` : ""}</div>`;
}
function burn(g, s, W = 640, H = 260, mini) {
  const pad = { l: mini ? 30 : 38, r: 14, t: 14, b: 26 }, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const total = Math.max(1, diff(g.start, g.deadline));
  const x = at => pad.l + clamp(diff(g.start, at) / total, 0, 1.05) * iw;
  const y = p => pad.t + (1 - clamp(p, 0, 1)) * ih;
  let o = `<defs><linearGradient id="gArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--st)" stop-opacity=".22"/><stop offset="1" stop-color="var(--st)" stop-opacity="0"/></linearGradient></defs>`;
  for (const v of [0, .25, .5, .75, 1]) o += `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${pad.l - 8}" y="${y(v) + 4}" text-anchor="end">${v * 100}</text>`;
  // месяцы
  const d0 = D(g.start); let m = new Date(d0.getFullYear(), d0.getMonth() + 1, 1);
  const months = [];
  while (iso(m) <= g.deadline) { months.push(iso(m)); m = new Date(m.getFullYear(), m.getMonth() + 1, 1); }
  const every = Math.ceil(months.length / (mini ? 4 : 8));
  months.forEach((mm, i) => { if (i % every) return; o += `<text class="ax" x="${x(mm)}" y="${H - 6}" text-anchor="middle">${MON[D(mm).getMonth()]}</text><line class="grid" x1="${x(mm)}" x2="${x(mm)}" y1="${H - pad.b}" y2="${H - pad.b + 4}"/>`; });
  o += `<line class="plan" x1="${x(g.start)}" y1="${y(0)}" x2="${x(g.deadline)}" y2="${y(1)}"/>`;
  const pts = s.pts;
  const line = pts.map(t => `${x(t.at).toFixed(1)},${y(t.p).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  o += `<polygon class="area" points="${x(pts[0].at)},${y(0)} ${line} ${x(last.at)},${y(0)}"/>`;
  o += `<polyline class="fact" points="${line}"/>`;
  if (s.proj != null && g.status === "active" && s.left > 0) {
    const endAt = s.eta && s.eta < g.deadline ? s.eta : g.deadline, endP = s.eta && s.eta < g.deadline ? 1 : s.proj;
    o += `<line class="fc" x1="${x(last.at)}" y1="${y(last.p)}" x2="${x(endAt)}" y2="${y(endP)}"/>`;
    if (!mini) o += `<text class="lbl" x="${x(endAt) - 4}" y="${y(endP) - 8}" text-anchor="end">прогноз ${pct(endP)} %</text>`;
  }
  if (TODAY > g.start && TODAY < g.deadline) {
    o += `<line class="today" x1="${x(TODAY)}" x2="${x(TODAY)}" y1="${pad.t}" y2="${H - pad.b}"/>`;
    if (!mini) o += `<text class="lbl" x="${x(TODAY) + 5}" y="${pad.t + 10}">сегодня</text>`;
  }
  if (!mini) pts.forEach(t => {
    if (!t.c) return;
    const col = { ok: "var(--ok)", risk: "var(--risk)", bad: "var(--off)" }[t.c.conf] || "var(--ink)";
    o += `<circle class="pt" cx="${x(t.at)}" cy="${y(t.p)}" r="4.5" fill="${col}"><title>${fd(t.at)}: ${pct(t.p)} % · ${CONF[t.c.conf][0]}${t.c.note ? " · " + esc(t.c.note) : ""}</title></circle>`;
  });
  o += `<circle cx="${x(last.at)}" cy="${y(last.p)}" r="${mini ? 4 : 6}" fill="var(--st)" stroke="#fff" stroke-width="2"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Прогресс по неделям: факт, план и прогноз">${o}</svg>`;
}
function weekGains(g, n = 10) {
  const pts = series(g), pAt = d => { let p = pts[0].p; for (const t of pts) if (t.at <= d) p = t.p; return p; };
  const out = [];
  for (const w of weeks(n)) { if (addD(w, 6) < g.start) continue; out.push({ w, g: pAt(addD(w, 6)) - pAt(addD(w, -1)) }); }
  return out;
}
function gainBars(arr) {
  const W = 560, H = 170, pad = { l: 8, r: 8, t: 22, b: 26 }, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const mx = Math.max(0.02, ...arr.map(a => Math.abs(a.g))), bw = iw / arr.length;
  const base = pad.t + ih;
  let o = `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${base}" y2="${base}"/>`;
  arr.forEach((a, i) => {
    const h = Math.abs(a.g) / mx * (ih - 4), xx = pad.l + i * bw + bw * 0.18, w = bw * 0.64;
    const cur = a.w === curWeek();
    o += `<rect x="${xx}" y="${a.g >= 0 ? base - Math.max(2, h) : base}" width="${w}" height="${Math.max(2, h)}" rx="5" fill="${a.g < 0 ? "var(--off)" : cur ? "rgba(20,20,20,.25)" : "var(--ink)"}"><title>${fd(a.w)}–${fd(addD(a.w, 6))}: ${a.g >= 0 ? "+" : ""}${nf(a.g * 100, 1)} п.п.</title></rect>`;
    if (Math.abs(a.g) >= 0.0005) o += `<text class="lbl" x="${xx + w / 2}" y="${(a.g >= 0 ? base - Math.max(2, h) : base) - 6}" text-anchor="middle">${a.g >= 0 ? "+" : ""}${nf(a.g * 100, 1)}</text>`;
    o += `<text class="ax" x="${xx + w / 2}" y="${H - 6}" text-anchor="middle">${D(a.w).getDate()} ${MON[D(a.w).getMonth()]}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Прирост прогресса по неделям">${o}</svg>`;
}

// ─────────────────────────────── экран: список целей
function render() {
  syncAuto();
  closePop();
  $("#main").innerHTML = UI.view === "goal" && G(UI.gid) ? renderGoal(G(UI.gid)) : renderList();
}
function renderList() {
  const act = active(), S = act.map(stats);
  const rv = reviewStreak();
  const avgP = S.length ? S.reduce((a, s) => a + s.p, 0) / S.length : 0;
  const avgE = S.length ? S.reduce((a, s) => a + s.el, 0) / S.length : 0;
  const cnt = k => S.filter(s => stCls(s.st) === k).length;
  const segs = [["ahead", cnt("ahead"), "var(--ahead)"], ["on", cnt("on"), "var(--ok)"], ["risk", cnt("risk"), "var(--risk)"], ["off", cnt("off"), "var(--off)"]].filter(s => s[1]);
  const near = act.slice().sort((a, b) => a.deadline < b.deadline ? -1 : 1)[0];
  // регулярные действия этой недели
  let hDone = 0, hAll = 0;
  act.forEach(g => g.habits.forEach(h => { hAll += h.per; hDone += Math.min(h.log[curWeek()] || 0, h.per); }));
  const doneN = DB.goals.filter(g => g.status === "done").length;

  const vis = UI.visEdit ? `
    <div class="vis-k">Видение</div>
    <div class="vis-edit">
      <textarea id="vis-text" aria-label="Чего я хочу добиться">${esc(DB.vision.text)}</textarea>
      <div class="row"><span class="hint" style="color:var(--dark-3)">к</span><input id="vis-h" value="${esc(DB.vision.horizon)}" aria-label="Год"><span class="hint" style="color:var(--dark-3)">году</span><span style="flex:1"></span>
      <button class="btn-ghost" data-a="vis-cancel">Отмена</button><button class="btn-w" data-a="vis-save">Сохранить</button></div>
    </div>` : `
    <div class="vis-k">${ic("spark")} Видение · к ${esc(DB.vision.horizon)} году<span style="flex:1"></span><button class="icon-btn" data-a="vis-edit" aria-label="Изменить видение" style="color:#fff">${ic("pencil")}</button></div>
    <p class="vis-t">${esc(DB.vision.text) || '<span style="color:var(--dark-3)">Опишите, чего хотите добиться через 3 года — одним абзацем.</span>'}</p>
    <div class="vis-foot"><span class="lbl">Ведут к этому:</span>${act.map(g => `<button class="vis-g" data-a="open" data-id="${g.id}"><span class="dotc" style="background:${sph(g.sphere).c}"></span><span>${esc(g.title)}</span></button>`).join("") || '<span class="lbl">пока ни одной цели</span>'}</div>`;

  const sum = `
    <div class="card-h"><h2>Сводка</h2><span class="sp"></span></div>
    <div class="sum-big"><b class="num">${pct(avgP)}<small>%</small></b><span>средний прогресс<br>план на сегодня — ${pct(avgE)} %</span></div>
    <div class="seg">${segs.map(s => `<i style="flex:${s[1]};background:${s[2]}" title="${ST[s[0]]}: ${s[1]}"></i>`).join("") || '<i style="flex:1;background:rgba(20,20,20,.12)"></i>'}</div>
    <div class="seg-leg">${segs.map(s => `<span><span class="dotc" style="background:${s[2]}"></span>${ST[s[0]]} — ${s[1]}</span>`).join("")}</div>
    <div class="sum-rows">
      <div class="sum-row"><span class="k">Недельный обзор</span><b>${rv.thisWeek ? "сделан · " : "ждёт · "}серия ${pl(rv.s, "неделя", "недели", "недель")}</b></div>
      <div class="sum-row"><span class="k">Регулярные действия на неделе</span><b class="num">${hDone} из ${hAll}</b></div>
      ${near ? `<div class="sum-row"><span class="k">Ближайший срок</span><button data-a="open" data-id="${near.id}">${fd(near.deadline)} · ${pl(diff(TODAY, near.deadline), "день", "дня", "дней")}</button></div>` : ""}
      <div class="sum-row"><span class="k">Достигнуто целей</span><button data-a="filter" data-f="done">${doneN}</button></div>
    </div>`;

  // фильтры и карточки
  const F = [["active", "Активные"], ["q", "На квартал"], ["y", "На год и дольше"], ["done", "Достигнутые"], ["drop", "Архив"]];
  const horizon = g => diff(g.start, g.deadline) <= 100 ? "q" : "y";
  let list = DB.goals.filter(g => {
    if (UI.sphere && g.sphere !== UI.sphere) return false;
    if (UI.filter === "active") return g.status === "active";
    if (UI.filter === "q" || UI.filter === "y") return g.status === "active" && horizon(g) === UI.filter;
    return g.status === UI.filter;
  });
  const order = { off: 0, late: 0, risk: 1, on: 2, ready: 2, ahead: 3, done: 4, drop: 5 };
  list = list.map(g => [g, stats(g)]).sort((a, b) => (order[a[1].st] - order[b[1].st]) || (a[0].deadline < b[0].deadline ? -1 : 1));
  const fcount = f => DB.goals.filter(g => (!UI.sphere || g.sphere === UI.sphere) && (f === "active" ? g.status === "active" : f === "q" || f === "y" ? g.status === "active" && horizon(g) === f : g.status === f)).length;
  const cards = list.map(([g, s]) => goalCard(g, s)).join("") + (UI.filter === "active" || UI.filter === "q" || UI.filter === "y" ? `<button class="gcard add" data-a="new"><span class="plus">${ic("plus")}</span>Новая цель</button>` : "");

  return `
    <header class="top">
      <div class="hello"><h1>Цели</h1><p>Чего хочу добиться — и как к этому идти</p></div>
      <div class="top-act">
        <button class="btn-glass" data-a="review">${ic("repeat")} Недельный обзор${rv.thisWeek ? "" : '<span class="dot"></span>'}</button>
        <button class="btn-create" data-a="new">${ic("plus")} Цель</button>
      </div>
    </header>
    <div class="lgrid">
      <section class="card dark vision a-vis" aria-label="Видение">${vis}</section>
      <section class="card yellow a-sum" aria-label="Сводка">${sum}</section>
      <div class="a-main">
        <div class="toolbar">
          <div class="seg-ctl" role="tablist">${F.map(([f, n]) => `<button class="${UI.filter === f ? "on" : ""}" data-a="filter" data-f="${f}">${n} <span style="opacity:.55">${fcount(f)}</span></button>`).join("")}</div>
          <span class="sp"></span>
          ${UI.sphere ? `<button class="chip on" data-a="sphere" data-s="${UI.sphere}">${sph(UI.sphere).name} ${ic("x")}</button>` : ""}
        </div>
        <div class="gcards">${cards || `<div class="empty">Здесь пока пусто</div>`}</div>
      </div>
      <aside class="a-side">
        ${weekCard(act)}
        ${sphereCard()}
      </aside>
    </div>`;
}
function goalCard(g, s) {
  const sp = sph(g.sphere), c = stCls(s.st), nx = nextStep(g);
  const left = s.left >= 0 ? "осталось " + pl(s.left, "день", "дня", "дней") : "срок прошёл " + fd(g.deadline);
  return `<button class="gcard c-${c}${g.status !== "active" ? " is-done" : ""}" style="--sc:${sp.c}" data-a="open" data-id="${g.id}">
    <div class="gc-top"><span class="gc-sph"><span class="dotc" style="background:${sp.c}"></span>${sp.name}</span><span class="sp"></span><span class="pill st-${c}">${ST[s.st]}</span></div>
    <h3 class="gc-title">${esc(g.title)}</h3>
    <div class="gc-mid">
      ${ring(s.p, g.status === "active" ? s.el : null, 92, 9)}
      <div class="gc-meta">
        <span>Срок <b>${fd(g.deadline)}</b></span>
        <span>${g.status === "done" ? "достигнута " + fd(g.doneAt) : g.status === "drop" ? "в архиве" : left}</span>
        ${g.status === "active" ? `<span>План на сегодня <b>${pct(s.el)} %</b></span>` : ""}
      </div>
    </div>
    <div class="gc-krs">${g.krs.slice(0, 3).map(k => `<div class="gc-kr"><div class="t"><span>${esc(k.title)}</span><span>${krPair(k)}</span></div>${krBar(k, g.status === "active" ? s.el : null)}</div>`).join("")}</div>
    ${g.status === "active" ? `<div class="gc-next">${ic("flag")}<span>${nx ? esc(nx.step.t) : "Следующий шаг не задан"}</span>${nx && (nx.step.due || nx.stage.due) ? `<small>${fd(nx.step.due || nx.stage.due)}</small>` : ""}</div>` : ""}
  </button>`;
}
function weekCard(act) {
  const cw = curWeek(), end = addD(cw, 6);
  const habits = [], steps = [];
  act.forEach(g => {
    g.habits.forEach(h => habits.push({ g, h }));
    g.stages.forEach(s => s.steps.forEach(st => {
      const due = st.due || s.due;
      if (due && due <= end && (!st.done || st.doneAt >= cw)) steps.push({ g, s, st, due });
    }));
  });
  steps.sort((a, b) => (a.st.done - b.st.done) || (a.due < b.due ? -1 : 1));
  let done = 0, all = 0;
  habits.forEach(({ h }) => { all += h.per; done += Math.min(h.log[cw] || 0, h.per); });
  steps.forEach(x => { all++; if (x.st.done) done++; });
  const hHtml = habits.map(({ g, h }) => {
    const v = h.log[cw] || 0;
    const ctl = h.per <= 7
      ? `<div class="hdots">${Array.from({ length: h.per }, (_, i) => `<button class="hdot${i < v ? " on" : ""}" data-a="hset" data-g="${g.id}" data-h="${h.id}" data-v="${i < v && i === v - 1 ? i : i + 1}" aria-label="${i + 1} из ${h.per}"></button>`).join("")}</div>`
      : `<div class="cnt"><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="-1" aria-label="Меньше">−</button><b>${v}/${h.per}</b><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="1" aria-label="Больше">+</button></div>`;
    return `<div class="wk-item"><span class="t">${esc(h.title)}</span><span class="g"><span class="dotc" style="background:${sph(g.sphere).c}"></span><span>${esc(g.title)}</span></span><span class="ctl">${ctl}</span></div>`;
  }).join("");
  const LIM = 5, shown = UI.wkAll ? steps : steps.slice(0, LIM);
  const sHtml = shown.map(({ g, s, st, due }) => `<div class="wk-step${st.done ? " done" : ""}"><button class="cb${st.done ? " on" : ""}" data-a="step" data-g="${g.id}" data-s="${s.id}" data-k="${st.id}" aria-label="Готово">${ic("check")}</button><span class="t">${esc(st.t)}</span><span class="g">${dueChip(due, st.done)}<span class="dotc" style="background:${sph(g.sphere).c}"></span><span class="gn">${esc(g.title)}</span></span></div>`).join("")
    + (steps.length > LIM ? `<button class="wk-more" data-a="wk-all">${UI.wkAll ? "Свернуть" : "Ещё " + (steps.length - LIM)}</button>` : "");
  return `<section class="card glass" aria-label="Эта неделя">
    <div class="card-h"><h2>Эта неделя</h2><span class="sp"></span><small>${fd(cw)} – ${fd(end)}</small></div>
    <div class="wk-sec"><span>Регулярно</span><span>${ic("repeat", "i")}</span></div>
    ${hHtml || '<p class="hint">Нет регулярных действий</p>'}
    <div class="wk-sec" style="margin-top:14px"><span>Шаги плана до ${fd(end)}</span></div>
    ${sHtml || '<p class="hint">Шагов со сроком на этой неделе нет</p>'}
    <div class="wk-foot"><span class="num">${done} из ${all}</span><div class="bar thin" style="--st:var(--green)"><i style="width:${all ? pct(done / all) : 0}%"></i></div></div>
  </section>`;
}
function dueChip(due, done) {
  if (!due) return "";
  const d = diff(TODAY, due);
  const cls = done ? "" : d < 0 ? "late" : d <= 2 ? "soon" : "";
  return `<span class="due ${cls}">${d === 0 ? "сегодня" : d === 1 ? "завтра" : d < 0 && !done ? "просрочено · " + fd(due) : fd(due)}</span>`;
}
function sphereCard() {
  const rows = SPH.map(s => {
    const gs = active().filter(g => g.sphere === s.id);
    const p = gs.length ? gs.reduce((a, g) => a + gP(g), 0) / gs.length : 0;
    return `<button class="sph-row${UI.sphere === s.id ? " on" : ""}" data-a="sphere" data-s="${s.id}"><span class="dotc" style="background:${s.c}"></span><span>${s.name}</span><span class="n">${gs.length ? pl(gs.length, "цель", "цели", "целей") + " · " + pct(p) + " %" : "нет целей"}</span><div class="bar" style="--st:${s.c}"><i style="width:${pct(p)}%"></i></div></button>`;
  }).join("");
  return `<section class="card glass" aria-label="Сферы"><div class="card-h"><h2>Баланс сфер</h2><span class="sp"></span></div>${rows}
    <p class="hint" style="margin:10px 4px 0">Нажмите сферу — останутся только её цели.</p></section>`;
}

// ─────────────────────────────── экран: цель
function renderGoal(g) {
  const s = stats(g), sp = sph(g.sphere), c = stCls(s.st);
  const TABS = [["ov", "Обзор"], ["plan", "План"], ["hab", "Регулярно"], ["an", "Аналитика"], ["log", "Журнал"]];
  const body = { ov: tabOverview, plan: tabPlan, hab: tabHabits, an: tabAnalytics, log: tabLog }[UI.tab](g, s);
  const left = s.left >= 0 ? pl(s.left, "день", "дня", "дней") : "срок прошёл";
  return `
    <section class="card dark hero c-${c}" style="--sc:${sp.c}">
      <div>
        <div class="h-top"><button class="circ" data-a="back" aria-label="Назад к целям">${ic("back")}</button><span class="h-sph"><span class="dotc" style="background:${sp.c}"></span>${sp.name}</span><span class="pill st-${c}">${ST[s.st]}</span></div>
        <h1>${esc(g.title)}</h1>
        ${g.why ? `<p class="h-why"><b>Зачем</b>${esc(g.why)}</p>` : ""}
        <div class="h-meta">
          <span class="h-tag">${ic("cal")}${fd(g.start)} → ${fd(g.deadline)}</span>
          <span class="h-tag">${ic("clock")}${g.status === "active" ? (s.left >= 0 ? "осталось " + left : left) : g.status === "done" ? "достигнута " + fd(g.doneAt) : "в архиве"}</span>
          ${g.projects.map(p => `<button class="h-tag" data-a="project" data-p="${esc(p)}">${ic("folder")}${esc(projectName(p))}</button>`).join("")}
        </div>
        ${g.status === "active" ? `<div class="h-time"><div class="bar thin" style="--st:#fff"><i style="width:${pct(s.el)}%;opacity:.35"></i><span class="tick" style="left:${pct(s.p)}%" title="Прогресс"></span></div>
          <div class="lab"><span>прошло ${pct(s.el)} % времени</span><span>сделано ${pct(s.p)} %</span></div></div>` : ""}
      </div>
      <div class="h-side">
        ${ring(s.p, g.status === "active" ? s.el : null, 168, 14, { sub: g.status === "active" ? "план " + pct(s.el) + " %" : "" })}
        <div class="h-act">
          ${g.status === "active" ? `<button class="btn-w" data-a="checkin" data-id="${g.id}" style="height:40px">${ic("pulse")} Отметить прогресс</button>` : `<button class="btn-w" data-a="restore" data-id="${g.id}" style="height:40px">Вернуть в работу</button>`}
          <button class="circ" data-a="gmenu" data-id="${g.id}" aria-label="Ещё">${ic("dots")}</button>
        </div>
      </div>
    </section>
    <div class="tabs" role="tablist">${TABS.map(([t, n]) => `<button class="chip${UI.tab === t ? " on" : ""}" role="tab" aria-selected="${UI.tab === t}" data-a="tab" data-t="${t}">${n}</button>`).join("")}</div>
    <div class="c-${c}">${body}</div>`;
}
function krBlock(g, s, k) {
  const e = g.status === "active" ? s.el : null;
  const cur = k.cur, ago = valAt(g, k, addD(TODAY, -28));
  const wks = Math.max(1, Math.min(4, diff(g.start, TODAY) / 7));
  const paceW = (cur - ago) / wks, needW = s.left > 0 ? (k.target - cur) / (s.left / 7) : 0;
  const expV = k.start + (k.target - k.start) * (e ?? 1);
  const behind = !isBool(k) && e != null && krP(k) < e - 0.05;
  const stats = isBool(k) ? `<span>${k.cur >= 1 ? "выполнено" : "ещё не выполнено"}</span>` :
    `<span>старт ${fv(k.start, k.unit)}</span>${e != null ? `<span class="${behind ? "bad" : "good"}">план на сегодня ${fv(rnd(expV, k.unit), k.unit)}</span>` : ""}
     ${g.status === "active" && krP(k) < 1 ? `<span>нужно ${needW >= 0 ? "+" : ""}${fv(Math.round(needW * 10) / 10, k.unit)} в неделю · сейчас ${paceW >= 0 ? "+" : ""}${fv(Math.round(paceW * 10) / 10, k.unit)}</span>` : ""}`;
  return `<button class="kr" data-a="${g.status === "active" ? "checkin" : "noop"}" data-id="${g.id}" title="${g.status === "active" ? "Отметить прогресс" : ""}">
    <span class="t"><span>${esc(k.title)}</span>${k.auto ? `<span class="auto" title="${AUTO[k.auto]}">авто</span>` : ""}</span>
    <span class="v"><b>${fv(k.cur, k.unit)}</b>${isBool(k) ? "" : (k.target < k.start ? " → " : " / ") + fv(k.target, k.unit)}</span>
    ${krBar(k, e)}
    <span class="s">${stats}</span>
  </button>`;
}
function tabOverview(g, s) {
  const steps = [];
  g.stages.forEach(st => st.steps.forEach(x => { if (!x.done) steps.push({ st, x, due: x.due || st.due }); }));
  steps.sort((a, b) => (a.due || "9") < (b.due || "9") ? -1 : 1);
  const cw = curWeek();
  return `<div class="ov">
    <div class="ov-col">
      <section class="card white">
        <div class="card-h"><h2>Ключевые результаты</h2><span class="sp"></span>${g.status === "active" ? `<button class="btn-dark" data-a="checkin" data-id="${g.id}">${ic("pulse")} Отметить</button>` : ""}</div>
        ${g.krs.map(k => krBlock(g, s, k)).join("") || '<p class="hint">Нет ключевых результатов — добавьте в «Изменить цель».</p>'}
        <p class="hint" style="margin:10px 2px 0">Черта на полосе — где результат должен быть сегодня, если идти ровно к сроку. Прогресс цели — среднее по результатам.</p>
      </section>
      <section class="card glass">
        <div class="card-h"><h3>Ближайшие шаги</h3><span class="sp"></span><button class="chip" data-a="tab" data-t="plan">Весь план ${ic("chev")}</button></div>
        ${steps.slice(0, 4).map(({ st, x, due }) => `<div class="wk-step"><button class="cb" data-a="step" data-g="${g.id}" data-s="${st.id}" data-k="${x.id}" aria-label="Готово">${ic("check")}</button><span class="t">${esc(x.t)}</span><span class="g">${dueChip(due)}<span class="gn">${esc(st.title)}</span></span></div>`).join("") || '<p class="hint">Все шаги сделаны — добавьте следующие в «Плане».</p>'}
      </section>
    </div>
    <div class="ov-col">
      <section class="card glass">
        <div class="card-h"><h3>Факт и план</h3><span class="sp"></span><button class="chip" data-a="tab" data-t="an">Аналитика ${ic("chev")}</button></div>
        <div class="chart">${burn(g, s, 460, 220, true)}</div>
        <div class="c-leg"><span><i></i>факт</span><span><i class="d"></i>план</span><span><i class="f"></i>прогноз</span></div>
        ${g.status === "active" ? `<div class="insight">${ic("bulb")}<span>${forecastText(g, s)}</span></div>` : ""}
      </section>
      ${g.habits.length ? `<section class="card glass">
        <div class="card-h"><h3>Регулярно на этой неделе</h3><span class="sp"></span><button class="chip" data-a="tab" data-t="hab">История ${ic("chev")}</button></div>
        ${g.habits.map(h => { const v = h.log[cw] || 0; return `<div class="wk-item"><span class="t">${esc(h.title)}</span><span class="g">${v >= h.per ? "выполнено" : "осталось " + (h.per - v)} · серия ${streak(h)} нед.</span><span class="ctl"><div class="cnt"><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="-1" aria-label="Меньше">−</button><b>${v}/${h.per}</b><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="1" aria-label="Больше">+</button></div></span></div>`; }).join("")}
      </section>` : ""}
    </div>
  </div>`;
}
function forecastText(g, s) {
  if (s.p >= 0.999) return "Все ключевые результаты достигнуты — можно отметить цель достигнутой (меню «•••»).";
  if (s.slope == null || s.slope <= 1e-6) return `Прогресса за последние отметки нет. Чтобы успеть к ${fd(g.deadline)}, нужно в среднем <b>+${nf(s.need * 100, 1)} п.п. в неделю</b>.`;
  const pace = nf(s.pace * 100, 1), need = nf(s.need * 100, 1);
  if (s.eta && s.eta <= g.deadline) return `При нынешнем темпе (+${pace} п.п. в неделю) цель будет достигнута <b>${fd(s.eta)}</b> — на ${pl(diff(s.eta, g.deadline), "день", "дня", "дней")} раньше срока.`;
  return `При нынешнем темпе (+${pace} п.п. в неделю) к ${fd(g.deadline)} будет <b>${pct(s.proj)} %</b>. Чтобы успеть, нужно <b>+${need} п.п. в неделю</b>${s.eta ? ` — иначе цель сдвинется примерно на ${fd(s.eta)}` : ""}.`;
}
function tabPlan(g) {
  let todayDone = false, o = "";
  g.stages.forEach((s, i) => {
    if (!todayDone && s.due && s.due >= TODAY && i > 0) { o += `<div class="today-mark"><span></span><span>Сегодня, ${fd(TODAY)}</span></div>`; todayDone = true; }
    if (!todayDone && i === 0 && s.due >= TODAY) todayDone = true;
    const ss = stageStatus(s, i, g), n = s.steps.length, d = s.steps.filter(x => x.done).length;
    const lab = { done: "готов", cur: "сейчас", late: "просрочен", next: "впереди" }[ss];
    const pc = { done: "st-on", cur: "st-done", late: "st-off", next: "st-drop" }[ss];
    o += `<div class="stg s-${ss}">
      <div class="stg-dot">${ss === "done" ? ic("check") : i + 1}</div>
      <div class="stg-card">
        <div class="stg-h"><input class="in" value="${esc(s.title)}" data-a2="stage-title" data-g="${g.id}" data-s="${s.id}" aria-label="Название этапа">
          <span class="pill ${pc}">${lab}</span>
          <input type="date" class="date-in" value="${s.due}" data-a2="stage-due" data-g="${g.id}" data-s="${s.id}" aria-label="Срок этапа">
          <button class="icon-btn sm" data-a="stage-del" data-g="${g.id}" data-s="${s.id}" aria-label="Удалить этап">${ic("trash")}</button></div>
        <div class="stg-meta"><span class="num">${d} из ${n}</span><div class="bar thin" style="--st:var(--green)"><i style="width:${n ? pct(d / n) : 0}%"></i></div></div>
        <ul class="steps">${s.steps.map(x => `<li class="${x.done ? "done" : ""}"><button class="cb${x.done ? " on" : ""}" data-a="step" data-g="${g.id}" data-s="${s.id}" data-k="${x.id}" aria-label="Готово">${ic("check")}</button><span class="tx">${esc(x.t)}</span>${dueChip(x.due, x.done)}
          <span class="act"><button class="icon-btn sm" data-a="totask" data-g="${g.id}" data-s="${s.id}" data-k="${x.id}" title="Сделать задачей в «Задачах»" aria-label="В задачи">${ic("task")}</button><button class="icon-btn sm" data-a="step-del" data-g="${g.id}" data-s="${s.id}" data-k="${x.id}" aria-label="Удалить шаг">${ic("x")}</button></span></li>`).join("")}</ul>
        <input class="add-in" placeholder="+ Шаг — напишите и нажмите Enter" data-a2="step-add" data-g="${g.id}" data-s="${s.id}" aria-label="Новый шаг">
      </div></div>`;
  });
  if (!todayDone && g.stages.length) o += `<div class="today-mark"><span></span><span>Сегодня, ${fd(TODAY)}</span></div>`;
  return `<section class="card glass">
    <div class="card-h"><h2>План реализации</h2><span class="sp"></span><small>этапы → шаги; сделанные шаги двигают этап</small></div>
    <div class="plan">${o}</div>
    <button class="stg-add" data-a="stage-add" data-g="${g.id}">${ic("plus")} Этап</button>
    <p class="hint" style="margin:14px 0 0">Значок «задача» у шага — в общей структуре шаг станет задачей в «Задачах» (со сроком, в календаре, с напоминанием) и будет связан с целью.</p>
  </section>`;
}
function tabHabits(g) {
  const W = weeks(8), cw = curWeek();
  const rows = g.habits.map(h => {
    const v = h.log[cw] || 0, ad = adherence(h);
    return `<div class="hb"><span class="nm">${esc(h.title)}<small>${h.per} в неделю</small></span>
      ${W.map(w => { const c = h.log[w]; const f = c == null ? 0 : Math.min(c, h.per) / h.per; return `<span class="hcell${f >= 1 ? " full" : ""}" title="${fd(w)}–${fd(addD(w, 6))}: ${c ?? 0} из ${h.per}"><i style="height:${pct(f)}%;${w === cw ? "opacity:.5" : ""}"></i></span>`; }).join("")}
      <span class="c"><span class="cnt"><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="-1" aria-label="Меньше">−</button><b>${v}/${h.per}</b><button data-a="hstep" data-g="${g.id}" data-h="${h.id}" data-d="1" aria-label="Больше">+</button></span></span>
      <span class="c">${streak(h)} нед.</span><span class="c ${ad == null ? "" : ad >= 0.9 ? "good" : ad >= 0.6 ? "warn" : "bad"}">${ad == null ? "—" : pct(ad) + " %"}</span></div>`;
  }).join("");
  const ins = leadLag(g);
  return `<section class="card glass">
    <div class="card-h"><h2>Регулярные действия</h2><span class="sp"></span><small>то, что делаю каждую неделю и что двигает результат</small></div>
    <div class="tbl-wrap">
      <div class="hb head"><span>Действие</span>${W.map(w => `<span>${D(w).getDate()}.${z2(D(w).getMonth() + 1)}</span>`).join("")}<span>Эта неделя</span><span>Серия</span><span>4 нед.</span></div>
      ${rows || '<p class="hint" style="padding:12px 0">Пока нет регулярных действий.</p>'}
    </div>
    <div class="hb-add"><input class="in-line" id="hb-t" placeholder="Например: «5 звонков агентам»" style="flex:1;min-width:200px" aria-label="Действие"><input class="in-line" id="hb-n" type="number" min="1" max="50" value="3" style="width:80px" aria-label="Раз в неделю"><span class="hint">раз в неделю</span><button class="btn-dark" data-a="habit-add" data-g="${g.id}">${ic("plus")} Добавить</button></div>
    ${ins ? `<div class="insight">${ic("bulb")}<span>${ins}</span></div>` : ""}
    <p class="hint" style="margin:14px 0 0">Результат (концерты, прибыль) виден поздно, а регулярные действия — каждую неделю. Если их выполнять, результат подтягивается — это и проверяет подсказка выше.</p>
  </section>`;
}
function leadLag(g) {
  if (!g.habits.length) return "";
  const gains = weekGains(g, 10).filter(a => a.w !== curWeek());
  const full = [], part = [];
  gains.forEach(a => {
    const ad = g.habits.reduce((x, h) => x + Math.min(h.log[a.w] || 0, h.per) / h.per, 0) / g.habits.length;
    (ad >= 0.999 ? full : part).push(a.g);
  });
  if (!full.length || !part.length) return "";
  const av = a => a.reduce((x, y) => x + y, 0) / a.length;
  const f = av(full) * 100, p = av(part) * 100;
  return `В недели, когда регулярные действия выполнены полностью (${full.length}), цель росла в среднем на <b>+${nf(f, 1)} п.п.</b>, в остальные (${part.length}) — на <b>+${nf(p, 1)} п.п.</b>${f > p ? " Регулярность работает." : " Связи пока не видно — возможно, действия стоит пересмотреть."}`;
}
function tabAnalytics(g, s) {
  const gains = weekGains(g, 10);
  const conf = g.checkins.slice(-12);
  const krRows = g.krs.map(k => {
    const ago = valAt(g, k, addD(TODAY, -28)), wks = Math.max(1, Math.min(4, diff(g.start, TODAY) / 7));
    const paceW = (k.cur - ago) / wks, needW = s.left > 0 ? (k.target - k.cur) / (s.left / 7) : 0;
    const expV = k.start + (k.target - k.start) * s.el;
    const proj = isBool(k) ? null : k.cur + paceW * Math.max(0, s.left) / 7;
    const ok = isBool(k) ? k.cur >= 1 : (k.target >= k.start ? proj >= k.target : proj <= k.target);
    return `<tr><td>${esc(k.title)}${k.auto ? ' <span class="auto">авто</span>' : ""}</td>
      <td>${fv(k.cur, k.unit)}</td><td>${fv(k.target, k.unit)}</td>
      <td>${isBool(k) ? "—" : fv(rnd(expV, k.unit), k.unit)}</td>
      <td>${isBool(k) || krP(k) >= 1 ? "—" : (needW >= 0 ? "+" : "") + fv(Math.round(needW * 10) / 10, k.unit)}</td>
      <td>${isBool(k) ? "—" : (paceW >= 0 ? "+" : "") + fv(Math.round(paceW * 10) / 10, k.unit)}</td>
      <td class="${ok ? "good" : "bad"}">${isBool(k) ? (k.cur >= 1 ? "сделано" : "не сделано") : fv(rnd(proj, k.unit), k.unit)}</td></tr>`;
  }).join("");
  const habAd = g.habits.map(h => adherence(h)).filter(x => x != null);
  const ha = habAd.length ? habAd.reduce((a, b) => a + b) / habAd.length : null;
  const stepsAll = g.stages.reduce((a, s2) => a + s2.steps.length, 0), stepsDone = g.stages.reduce((a, s2) => a + s2.steps.filter(x => x.done).length, 0);
  return `
    <div class="tiles4">
      <div class="tl dark"><small>Прогресс · план</small><b class="num">${pct(s.p)} % <span style="font-size:18px;color:var(--dark-3)">/ ${pct(s.el)} %</span></b><span>${s.gap >= 0 ? "впереди на " : "позади на "}${Math.abs(pct(s.gap))} п.п.</span></div>
      <div class="tl glass"><small>Прогноз к сроку</small><b class="num ${s.proj == null ? "" : s.proj >= 0.999 ? "good" : s.proj >= 0.85 ? "warn" : "bad"}">${s.proj == null ? "—" : pct(s.proj) + " %"}</b><span>${s.eta ? "100 % — " + fd(s.eta) : "по темпу последних отметок"}</span></div>
      <div class="tl glass"><small>Темп · нужно</small><b class="num">${s.pace == null ? "—" : "+" + nf(s.pace * 100, 1)} <span style="font-size:18px;color:var(--ink-3)">/ ${s.need == null ? "—" : "+" + nf(s.need * 100, 1)}</span></b><span>п.п. в неделю</span></div>
      <div class="tl glass"><small>Действия</small><b class="num">${ha == null ? "—" : pct(ha) + " %"}</b><span>регулярные за 4 нед. · шаги ${stepsDone}/${stepsAll}</span></div>
    </div>
    <div class="an-grid">
      <section class="card white an-wide">
        <div class="card-h"><h2>Факт, план и прогноз</h2><span class="sp"></span><small>прогресс цели, %</small></div>
        <div class="chart">${burn(g, s, 1000, 320)}</div>
        <div class="c-leg"><span><i></i>факт по отметкам (цвет точки — уверенность)</span><span><i class="d"></i>план: ровно от старта к сроку</span><span><i class="f"></i>прогноз по темпу последних 5 отметок</span></div>
        ${g.status === "active" ? `<div class="insight">${ic("bulb")}<span>${forecastText(g, s)}</span></div>` : ""}
      </section>
      <section class="card white an-wide">
        <div class="card-h"><h2>По ключевым результатам</h2></div>
        <div class="tbl-wrap"><table class="t"><thead><tr><th>Результат</th><th>Сейчас</th><th>Цель</th><th>План на сегодня</th><th>Нужно в неделю</th><th>Темп за 4 нед.</th><th>Прогноз к сроку</th></tr></thead><tbody>${krRows}</tbody></table></div>
      </section>
      <section class="card white">
        <div class="card-h"><h3>Прирост по неделям</h3><span class="sp"></span><small>п.п.</small></div>
        <div class="chart">${gainBars(gains)}</div>
      </section>
      <section class="card white">
        <div class="card-h"><h3>Уверенность по отметкам</h3></div>
        <div class="conf-row">${conf.map(c => `<i style="height:${{ ok: 100, risk: 62, bad: 30 }[c.conf]}%;background:${{ ok: "var(--ok)", risk: "var(--risk)", bad: "var(--off)" }[c.conf]}" title="${fd(c.at)} — ${CONF[c.conf][0]}"></i>`).join("") || '<span class="hint">Отметок ещё нет</span>'}</div>
        <div class="c-leg"><span><span class="dotc" style="background:var(--ok)"></span>уверен</span><span><span class="dotc" style="background:var(--risk)"></span>есть риски</span><span><span class="dotc" style="background:var(--off)"></span>под угрозой</span></div>
        ${leadLag(g) ? `<div class="insight">${ic("bulb")}<span>${leadLag(g)}</span></div>` : ""}
      </section>
    </div>`;
}
function tabLog(g) {
  const items = g.checkins.slice().reverse().map((c, i, arr) => {
    const prev = arr[i + 1], p = gP(g, c.vals), pp = prev ? gP(g, prev.vals) : 0;
    const ch = g.krs.map(k => { const a = prev ? (prev.vals[k.id] ?? k.start) : k.start, b = c.vals[k.id] ?? k.start; return a !== b ? `<span>${esc(k.title)}: ${fv(a, k.unit)} → ${fv(b, k.unit)}</span>` : ""; }).join("");
    const d = D(c.at);
    return `<div class="jr"><div class="jr-d"><b>${d.getDate()} ${MON[d.getMonth()]}</b>${d.getFullYear()}</div><div>
      <div class="jr-h"><span class="dp">${pct(p)} %</span><span class="${p - pp >= 0 ? "good" : "bad"}">${p - pp >= 0 ? "+" : ""}${nf((p - pp) * 100, 1)} п.п.</span><span class="pill st-${CONF[c.conf][2]}">${CONF[c.conf][0]}</span></div>
      ${ch ? `<div class="jr-ch">${ch}</div>` : ""}
      ${c.note ? `<div class="jr-n">${esc(c.note)}</div>` : ""}
      ${c.next ? `<div class="jr-nx">Главный шаг: <b>${esc(c.next)}</b></div>` : ""}
    </div></div>`;
  }).join("");
  return `<section class="card white">
    <div class="card-h"><h2>Журнал отметок</h2><span class="sp"></span>${g.status === "active" ? `<button class="btn-dark" data-a="checkin" data-id="${g.id}">${ic("pulse")} Отметить</button>` : ""}</div>
    ${items || '<p class="hint">Отметок пока нет. Первая — кнопкой «Отметить».</p>'}
    <div class="jr"><div class="jr-d"><b>${fd(g.start)}</b></div><div><div class="jr-h"><span class="dp">Цель поставлена</span></div></div></div>
  </section>`;
}

// ─────────────────────────────── окно: отметка прогресса и недельный обзор
let CI = null;
function openCheckin(ids, review) {
  CI = { queue: ids, i: 0, review, results: [] };
  loadCI();
  dlgOpen("", "");
  renderCI();
}
function loadCI() {
  const g = G(CI.queue[CI.i]), s = stats(g);
  CI.gid = g.id; CI.vals = {}; g.krs.forEach(k => CI.vals[k.id] = k.cur);
  const last = g.checkins[g.checkins.length - 1];
  CI.conf = last && last.at === TODAY ? last.conf : { ahead: "ok", on: "ok", risk: "risk", off: "bad" }[stCls(s.st)] || "ok";
  CI.note = last && last.at === TODAY ? last.note : ""; CI.next = ""; CI.before = s.p;
}
function renderCI() {
  const g = G(CI.gid), s = stats(g), tmp = gP(g, CI.vals);
  const d = $("#dlg"); d.className = "sm";
  const head = CI.review ? `Недельный обзор <span class="sub">· ${CI.i + 1} из ${CI.queue.length}</span>` : "Отметка прогресса";
  d.innerHTML = `<div class="dlg c-${stCls(s.st)}">
    <div class="dlg-h"><h2>${head}</h2><button class="icon-btn" data-a="close" aria-label="Закрыть">${ic("x")}</button></div>
    <div class="dlg-b">
      <div class="ci-top"><div id="ci-ring">${ring(tmp, s.el, 96, 9)}</div><div><h3>${esc(g.title)}</h3><p id="ci-cap">${capCI(g, s, tmp)}</p></div></div>
      ${g.krs.map(k => {
        const step = niceStep(k.target - k.start);
        const ctl = k.auto ? `<span class="auto" title="${AUTO[k.auto]}">считается само</span>`
          : isBool(k) ? `<div class="yn"><button class="${CI.vals[k.id] >= 1 ? "" : "on"}" data-a="ci-yn" data-k="${k.id}" data-v="0">Нет</button><button class="${CI.vals[k.id] >= 1 ? "on" : ""}" data-a="ci-yn" data-k="${k.id}" data-v="1">Да</button></div>`
          : `<div class="ci-ctl"><button data-a="ci-step" data-k="${k.id}" data-d="${-step}" aria-label="Меньше">−</button><input type="number" inputmode="decimal" value="${CI.vals[k.id]}" data-ci="${k.id}" aria-label="${esc(k.title)}"><button data-a="ci-step" data-k="${k.id}" data-d="${step}" aria-label="Больше">+</button></div>`;
        return `<div class="ci-kr"><span class="t">${esc(k.title)}<small>цель — ${fv(k.target, k.unit)}${k.auto ? " · " + AUTO[k.auto] : ""}</small></span>${ctl}<span class="ci-delta" id="cid-${k.id}">${deltaCI(k)}</span></div>`;
      }).join("")}
      <div class="fld" style="margin-top:18px"><span class="lb">Как оцениваете шансы успеть?</span>
        <div class="conf">${Object.entries(CONF).map(([k, v]) => `<button class="c-${v[2]}${CI.conf === k ? " on" : ""}" data-a="ci-conf" data-v="${k}"><b>${v[0]}</b><small>${v[1]}</small></button>`).join("")}</div></div>
      <div class="fld"><label for="ci-note">Что получилось и что мешает?</label><textarea class="fin" id="ci-note" rows="2" placeholder="Коротко — для журнала">${esc(CI.note)}</textarea></div>
      <div class="fld"><label for="ci-next">Главный шаг на следующую неделю</label><input class="fin" id="ci-next" value="${esc(CI.next)}" placeholder="Появится в плане — со сроком через неделю"></div>
    </div>
    <div class="dlg-f">${CI.review ? `<button class="btn-light" data-a="ci-skip">Пропустить</button>` : `<button class="btn-light" data-a="close">Отмена</button>`}<span class="sp"></span>
      <button class="btn-dark" data-a="ci-save">${CI.review && CI.i < CI.queue.length - 1 ? "Сохранить и дальше" : "Сохранить"}</button></div>
  </div>`;
}
function capCI(g, s, tmp) {
  const d = tmp - CI.before;
  return `было ${pct(CI.before)} % → станет <b>${pct(tmp)} %</b>${Math.abs(d) > 1e-4 ? ` (${d > 0 ? "+" : ""}${nf(d * 100, 1)} п.п.)` : ""} · план на сегодня ${pct(s.el)} %`;
}
function deltaCI(k) {
  const g = G(CI.gid), last = g.checkins[g.checkins.length - 1];
  const prev = last ? (last.vals[k.id] ?? k.start) : k.start, v = CI.vals[k.id];
  if (isBool(k)) return "";
  const d = v - prev;
  return `с прошлой отметки${last ? " (" + fd(last.at) + ")" : ""}: ${d >= 0 ? "+" : ""}${fv(d, k.unit)}`;
}
function refreshCI() {
  const g = G(CI.gid), s = stats(g), tmp = gP(g, CI.vals);
  $("#ci-ring").innerHTML = ring(tmp, s.el, 96, 9);
  $("#ci-cap").innerHTML = capCI(g, s, tmp);
  g.krs.forEach(k => { const el = root.getElementById("cid-" + k.id); if (el) el.textContent = deltaCI(k); });
}
function saveCI() {
  const g = G(CI.gid);
  CI.note = $("#ci-note").value; CI.next = $("#ci-next").value;
  const c = { at: TODAY, vals: { ...CI.vals }, conf: CI.conf, note: CI.note.trim(), next: CI.next.trim() };
  const i = g.checkins.findIndex(x => x.at === TODAY);
  if (i >= 0) g.checkins[i] = c; else g.checkins.push(c);
  g.krs.forEach(k => { if (!k.auto) k.cur = CI.vals[k.id]; });
  if (c.next) {
    let st = g.stages.find((s2, j) => stageStatus(s2, j, g) !== "done");
    if (!st) { st = { id: "st" + Date.now(), title: "Ближайшие шаги", due: g.deadline, steps: [] }; g.stages.push(st); }
    st.steps.push({ id: "s" + Date.now(), t: c.next, done: false, due: addD(TODAY, 7) });
  }
  save();
  CI.results.push({ g, before: CI.before, after: gP(g), conf: c.conf });
  nextCI();
}
function nextCI() {
  if (CI.review && CI.i < CI.queue.length - 1) { CI.i++; loadCI(); renderCI(); return; }
  if (CI.review) return reviewDone();
  closeDlg(); render(); snack("Отметка сохранена — график обновлён");
}
function reviewDone() {
  const rv = reviewStreak(), d = $("#dlg");
  const tot = CI.results.reduce((a, r) => a + (r.after - r.before), 0);
  d.innerHTML = `<div class="dlg"><div class="dlg-h"><h2>Неделя подведена</h2><button class="icon-btn" data-a="close" aria-label="Закрыть">${ic("x")}</button></div>
    <div class="dlg-b">
      <p class="hint" style="font-size:14px;margin:0 0 14px">Обновлено целей: <b>${CI.results.length}</b> · общий прирост ${tot >= 0 ? "+" : ""}${nf(tot * 100, 1)} п.п. · серия обзоров — <b>${pl(rv.s, "неделя", "недели", "недель")}</b></p>
      <div class="rv-list">${CI.results.map(r => { const s = stats(r.g); return `<div class="rv-i c-${stCls(s.st)}">${ring(s.p, s.el, 48, 5, { fs: 13 })}<div><span class="t">${esc(r.g.title)}</span><small>${pct(r.before)} % → ${pct(r.after)} % · ${CONF[r.conf][0].toLowerCase()}</small></div><span class="pill st-${stCls(s.st)}">${ST[s.st]}</span></div>`; }).join("") || '<p class="hint">Все цели пропущены.</p>'}</div>
    </div>
    <div class="dlg-f"><span class="sp"></span><button class="btn-dark" data-a="close">Готово</button></div></div>`;
  render();
}

// ─────────────────────────────── окно: новая цель / изменить (мастер из 4 шагов)
let WZ = null;
const WZ_STEPS = ["Цель", "Результаты", "План", "Действия"];
function openWizard(g) {
  const draft = g ? JSON.parse(JSON.stringify(g)) : {
    title: "", why: "", sphere: "biz", deadline: "", projects: [],
    krs: [{ id: "k1", title: "", unit: "шт.", start: 0, target: "" }], stages: [], habits: [], first: "",
  };
  draft.stages.forEach(s => s.text = s.steps.map(x => x.t).join("\n"));
  WZ = { step: 0, d: draft, edit: g ? g.id : null, err: "" };
  dlgOpen(); renderWZ();
}
function smart(d) {
  const words = (d.title || "").trim().split(/\s+/).filter(Boolean).length;
  const krOk = d.krs.filter(k => k.title.trim() && k.target !== "" && !isNaN(+k.target) && (k.unit === "да/нет" || +k.target !== +k.start)).length;
  return [
    ["S", "Конкретная", words >= 3, "формулировка из 3+ слов: что именно изменится"],
    ["M", "Измеримая", krOk > 0, "хотя бы один результат с числом «от → до»"],
    ["A", "Достижимая", d.krs.length <= 5 && d.krs.length > 0, "1–5 результатов — иначе теряется фокус"],
    ["R", "Значимая", (d.why || "").trim().length >= 10, "написано, зачем это вам"],
    ["T", "Со сроком", !!d.deadline && d.deadline > TODAY, "срок — дата в будущем"],
  ];
}
function renderWZ() {
  const d = WZ.d, sm = smart(d), dl = $("#dlg"); dl.className = "";
  const stepOk = [sm[0][2] && sm[4][2], sm[1][2], d.stages.length > 0, d.habits.length > 0 || !!(d.first || "").trim()];
  const body = [wz0, wz1, wz2, wz3][WZ.step](d);
  dl.innerHTML = `<div class="dlg">
    <div class="dlg-h"><h2>${WZ.edit ? "Изменить цель" : "Новая цель"}</h2><button class="icon-btn" data-a="close" aria-label="Закрыть">${ic("x")}</button></div>
    <div class="wz-steps">${WZ_STEPS.map((n, i) => `<button class="wz-st${i === WZ.step ? " on" : stepOk[i] ? " ok" : ""}" data-a="wz-go" data-i="${i}"><b>${stepOk[i] && i !== WZ.step ? "✓" : i + 1}</b>${n}</button>`).join("")}</div>
    <div class="dlg-b"><div class="wz-body"><div>${body}</div>
      <aside class="smart"><h4>Проверка SMART</h4><div id="wz-smart">${smartHtml(sm)}</div>
        <div class="sm-tip">${["Хорошая цель отвечает на «что изменится» и «зачем мне это». Срок — конец квартала или года.", "Результат — не дело, а измеримое изменение: не «звонить артистам», а «3 подписанных договора». 2–4 результата достаточно.", "3–6 этапов с датами. Шаги — конкретные действия на 1–3 дня. Кнопка «Разбить по месяцам» сделает каркас.", "Регулярное действие — то, что вы контролируете каждую неделю (звонки, встречи). Оно двигает результат."][WZ.step]}</div></aside>
    </div></div>
    <div class="dlg-f">${WZ.step ? `<button class="btn-light" data-a="wz-prev">${ic("back")} Назад</button>` : ""}<span class="err">${esc(WZ.err)}</span><span class="sp"></span>
      ${WZ.step < 3 ? `<button class="btn-light" data-a="wz-save">${WZ.edit ? "Сохранить" : "Создать сразу"}</button><button class="btn-dark" data-a="wz-next">Далее ${ic("chev")}</button>` : `<button class="btn-dark" data-a="wz-save">${WZ.edit ? "Сохранить" : "Создать цель"}</button>`}</div>
  </div>`;
}
function smartHtml(sm) { return sm.map(([l, n, ok, t]) => `<div class="sm-i${ok ? " ok" : ""}"><span class="ic">${ok ? "✓" : l}</span><span>${n}</span><small>${t}</small></div>`).join(""); }
function wz0(d) {
  const y = D(TODAY).getFullYear(), q = Math.floor(D(TODAY).getMonth() / 3);
  const qEnd = iso(new Date(y, q * 3 + 3, 0)), yEnd = y + "-12-31", h6 = addD(TODAY, 182);
  const wk = d.deadline ? Math.round(diff(TODAY, d.deadline) / 7) : null;
  return `
    <div class="fld"><label for="wz-title">Чего хочу добиться</label><textarea class="fin big" id="wz-title" rows="2" data-f="title" placeholder="Например: «Подписать трёх крупных артистов на 2027 год»">${esc(d.title)}</textarea></div>
    <div class="fld"><label for="wz-why">Зачем это мне</label><textarea class="fin" id="wz-why" rows="2" data-f="why" placeholder="Что изменится, когда достигну? Это будет перед глазами на странице цели.">${esc(d.why)}</textarea></div>
    <div class="fld"><span class="lb">Сфера</span><div class="chips">${SPH.map(s => `<button class="chip${d.sphere === s.id ? " on" : ""}" data-a="wz-sph" data-s="${s.id}"><span class="dotc" style="background:${s.c}"></span>${s.name}</button>`).join("")}</div></div>
    <div class="fld"><span class="lb">Срок</span><div class="chips">
      <button class="chip${d.deadline === qEnd ? " on" : ""}" data-a="wz-dl" data-v="${qEnd}">Конец квартала · ${fd(qEnd)}</button>
      <button class="chip${d.deadline === yEnd ? " on" : ""}" data-a="wz-dl" data-v="${yEnd}">Конец года</button>
      <button class="chip${d.deadline === h6 ? " on" : ""}" data-a="wz-dl" data-v="${h6}">Через полгода</button>
      <input type="date" class="date-in" style="height:32px" value="${d.deadline}" data-f="deadline" aria-label="Своя дата"></div>
      ${wk != null ? `<span class="hint">${wk > 0 ? "≈ " + pl(wk, "неделя", "недели", "недель") + " — это " + pl(wk, "недельная отметка", "недельные отметки", "недельных отметок") : "дата уже прошла"}</span>` : ""}</div>
    <div class="fld"><span class="lb">Связать с проектами (необязательно)</span><div class="chips">${Object.keys(model.work.projects || {}).map(p => `<button class="chip${d.projects.includes(p) ? " on" : ""}" data-a="wz-proj" data-p="${esc(p)}">${ic("folder")}${esc(projectName(p))}</button>`).join("")}</div></div>`;
}
function wz1(d) {
  const TPL = [["Провести концертов", "шт.", 0, 40], ["Чистая прибыль", "₽", 0, 5000000], ["Средняя заполняемость", "%", 60, 75], ["Подписано договоров", "шт.", 0, 3], ["Сделано", "да/нет", 0, 1]];
  return `
    <p class="hint" style="margin:0 0 12px;font-size:13.5px">Как поймём, что цель достигнута? Каждый результат — число «от → до». Прогресс цели — среднее по результатам.</p>
    <div class="krr head"><span>Результат</span><span>Сейчас</span><span>Цель</span><span>Единица</span><span></span></div>
    ${d.krs.map((k, i) => `<div class="krr">
      <input class="fin t" value="${esc(k.title)}" data-f="krs.${i}.title" placeholder="Например: подписано договоров" aria-label="Результат">
      <input class="fin" type="number" value="${k.start}" data-f="krs.${i}.start" data-num aria-label="Сейчас" ${k.unit === "да/нет" ? "disabled" : ""}>
      <input class="fin" type="number" value="${k.target}" data-f="krs.${i}.target" data-num aria-label="Цель" ${k.unit === "да/нет" ? "disabled" : ""}>
      <select class="fin u" data-f="krs.${i}.unit" data-re aria-label="Единица">${UNITS.map(u => `<option${u === k.unit ? " selected" : ""}>${u}</option>`).join("")}</select>
      <button class="icon-btn" data-a="wz-kr-del" data-i="${i}" aria-label="Удалить">${ic("x")}</button>
      <select class="fin kr-source" data-f="krs.${i}.auto" aria-label="Источник результата"><option value="">Вручную</option>${Object.keys(AUTO).map(a => `<option value="${a}"${k.auto === a ? " selected" : ""}>${AUTO[a]}</option>`).join("")}</select></div>`).join("")}
    <button class="add-row" data-a="wz-kr-add">${ic("plus")} Результат</button>
    <div class="fld" style="margin-top:18px"><span class="lb">Быстро добавить</span><div class="chips">${TPL.map((t, i) => `<button class="chip" data-a="wz-kr-tpl" data-i="${i}">+ ${t[0]}${t[1] === "да/нет" ? " (да/нет)" : ", " + t[1]}</button>`).join("")}</div></div>
    <div class="fld"><span class="lb">Автоматически из «Работы»</span><span class="hint">Выберите источник у результата. Считаются записи связанных проектов (или всех проектов, если связь не выбрана): ${Object.values(AUTO).join("; ")}.</span></div>`;
}
const WZ_TPL = [["Провести концертов", "шт.", 0, 40], ["Чистая прибыль", "₽", 0, 5000000], ["Средняя заполняемость", "%", 60, 75], ["Подписано договоров", "шт.", 0, 3], ["Сделано", "да/нет", 0, 1]];
function wz2(d) {
  return `
    <p class="hint" style="margin:0 0 12px;font-size:13.5px">План реализации — этапы со сроками, внутри — шаги (каждый с новой строки). Этапы видно на шкале, шаги — в «Этой неделе».</p>
    ${d.deadline ? `<div class="mini-tl">${d.stages.map(() => "<i></i>").join("") || '<i style="opacity:.15"></i>'}</div>` : ""}
    ${d.stages.map((s, i) => `<div class="stgr">
      <input class="fin" value="${esc(s.title)}" data-f="stages.${i}.title" placeholder="Этап ${i + 1}" aria-label="Этап">
      <input class="fin" type="date" value="${s.due}" data-f="stages.${i}.due" aria-label="Срок этапа">
      <button class="icon-btn" data-a="wz-st-del" data-i="${i}" aria-label="Удалить">${ic("x")}</button>
      <textarea class="fin" rows="2" data-f="stages.${i}.text" placeholder="Шаги — каждый с новой строки">${esc(s.text || "")}</textarea></div>`).join("")}
    <div class="chips"><button class="add-row" data-a="wz-st-add">${ic("plus")} Этап</button>
      <button class="add-row" data-a="wz-split" ${d.deadline ? "" : "disabled title='Сначала срок'"}>${ic("cal")} Разбить срок по месяцам</button></div>`;
}
function wz3(d) {
  return `
    <p class="hint" style="margin:0 0 12px;font-size:13.5px">Что будете делать регулярно, чтобы результат рос? Это то, что вы контролируете каждую неделю.</p>
    ${d.habits.map((h, i) => `<div class="hbr"><input class="fin" value="${esc(h.title)}" data-f="habits.${i}.title" placeholder="Например: звонки агентам" aria-label="Действие">
      <input class="fin" type="number" min="1" value="${h.per}" data-f="habits.${i}.per" data-num aria-label="Раз в неделю"><button class="icon-btn" data-a="wz-hb-del" data-i="${i}" aria-label="Удалить">${ic("x")}</button></div>`).join("")}
    ${d.habits.length ? '<p class="hint" style="margin:-2px 0 10px">число — сколько раз в неделю</p>' : ""}
    <button class="add-row" data-a="wz-hb-add">${ic("plus")} Регулярное действие</button>
    ${WZ.edit ? "" : `<div class="fld" style="margin-top:20px"><label for="wz-first">Первый шаг — что сделаю уже на этой неделе</label><input class="fin" id="wz-first" value="${esc(d.first || "")}" data-f="first" placeholder="Например: составить список из 30 артистов"></div>`}`;
}
function wzSet(path, val) {
  const ks = path.split("."); let o = WZ.d;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
  o[ks[ks.length - 1]] = val;
}
function wzSave() {
  const d = WZ.d, sm = smart(d);
  if (!d.title.trim()) { WZ.step = 0; WZ.err = "Напишите, чего хотите добиться"; return renderWZ(); }
  if (!d.deadline) { WZ.step = 0; WZ.err = "Укажите срок"; return renderWZ(); }
  if (d.deadline < (WZ.edit ? G(WZ.edit).start : TODAY)) { WZ.step = 0; WZ.err = "Срок не может быть раньше начала цели"; return renderWZ(); }
  if (d.krs.some(k => k.title.trim() && (!Number.isFinite(+k.start) || !Number.isFinite(+k.target) || (k.unit !== "да/нет" && (k.target === "" || +k.target === +k.start))))) { WZ.step = 1; WZ.err = "Укажите разные числовые значения начала и цели"; return renderWZ(); }
  const krs = d.krs.filter(k => k.title.trim()).map((k, i) => {
    const b = k.unit === "да/нет";
    const start = b ? 0 : +k.start || 0, target = b ? 1 : (k.target === "" ? start : +k.target);
    const old = WZ.edit ? G(WZ.edit).krs.find(x => x.id === k.id) : null;
    return { id: k.id || "k" + Date.now() + i, title: k.title.trim(), unit: k.auto ? "шт." : k.unit, start, target, cur: old ? old.cur : start, auto: k.auto || "" };
  });
  if (!krs.length) { WZ.step = 1; WZ.err = "Нужен хотя бы один измеримый результат"; return renderWZ(); }
  const oldG = WZ.edit ? G(WZ.edit) : null;
  const stages = d.stages.map((s, i) => {
    const old = oldG && oldG.stages.find(x => x.id === s.id);
    const steps = (s.text || "").split("\n").map(t => t.trim()).filter(Boolean).map((t, j) => {
      const was = old && old.steps.find(x => x.t === t);
      return was || { id: "s" + Date.now() + i + "-" + j, t, done: false, due: "" };
    });
    return { id: s.id || "st" + Date.now() + i, title: s.title.trim() || "Этап " + (i + 1), due: s.due || d.deadline, steps };
  });
  if (!WZ.edit && (d.first || "").trim()) {
    if (!stages.length) stages.push({ id: "st" + Date.now(), title: "Первые шаги", due: addD(TODAY, 14), steps: [] });
    stages[0].steps.unshift({ id: "s" + Date.now(), t: d.first.trim(), done: false, due: addD(monday(TODAY), 6) });
  }
  const habits = d.habits.filter(h => h.title.trim()).map((h, i) => ({ id: h.id || "h" + Date.now() + i, title: h.title.trim(), per: Math.max(1, +h.per || 1), log: h.log || {} }));
  if (WZ.edit) {
    Object.assign(oldG, { title: d.title.trim(), why: d.why.trim(), sphere: d.sphere, deadline: d.deadline, projects: d.projects, krs, stages, habits });
    save(); closeDlg(); render(); snack("Цель обновлена");
  } else {
    const g = { id: "g" + Date.now(), title: d.title.trim(), why: d.why.trim(), sphere: d.sphere, start: TODAY, deadline: d.deadline, status: "active", projects: d.projects, krs, stages, habits, checkins: [] };
    DB.goals.unshift(g); save(); closeDlg();
    UI.view = "goal"; UI.gid = g.id; UI.tab = "ov"; render(); window.scrollTo(0, 0);
    snack(sm.every(x => x[2]) ? "Цель создана — все пункты SMART выполнены" : "Цель создана");
  }
}

// ─────────────────────────────── окна, меню, сообщения
function dlgOpen() { const d = $("#dlg"); if (!d.open) d.showModal(); }
function closeDlg() { const d = $("#dlg"); if (d.open) d.close(); CI = null; WZ = null; }
$("#dlg").addEventListener("click", e => { if (e.target === e.currentTarget) { const r = e.currentTarget.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeDlg(); } });
$("#dlg").addEventListener("close", () => { CI = null; WZ = null; });
let snackT;
function snack(t, undo) {
  $("#snack-t").textContent = t;
  const b = $("#snack-b"); b.hidden = !undo; b.onclick = () => { undo(); $("#snack").classList.remove("on"); };
  $("#snack").classList.add("on"); clearTimeout(snackT); snackT = setTimeout(() => $("#snack").classList.remove("on"), undo ? 8000 : 3200);
}
function closePop() { root.querySelectorAll(".pop").forEach(p => p.remove()); }
function pop(anchor, items) {
  closePop();
  const p = document.createElement("div"); p.className = "pop";
  p.innerHTML = items.map(it => it === "-" ? "<hr>" : `<button class="${it[3] || ""}" data-a="${it[0]}" data-id="${it[2] || ""}">${ic(it[4] || "chev")}${it[1]}</button>`).join("");
  root.appendChild(p);
  const r = anchor.getBoundingClientRect(), w = p.offsetWidth;
  p.style.top = Math.min(r.bottom + 6, innerHeight - p.offsetHeight - 10) + "px";
  p.style.left = clamp(r.right - w, 10, innerWidth - w - 10) + "px";
}
function celebrate(g) {
  const d = $("#dlg"); d.className = "sm"; dlgOpen();
  d.innerHTML = `<div class="dlg"><div class="celebrate c-on"><div class="burst" style="display:inline-block">${ring(1, null, 150, 14)}</div>
    <h2>Цель достигнута</h2><p>«${esc(g.title)}» — в разделе «Достигнутые». История отметок и аналитика сохранятся.</p></div>
    <div class="dlg-f"><button class="btn-light" data-a="close">Закрыть</button><span class="sp"></span><button class="btn-dark" data-a="new">${ic("plus")} Следующая цель</button></div></div>`;
}

// ─────────────────────────────── действия
const A = {
  project: el => { S.view = "work"; wkpOpenPage(el.dataset.p); },
  noop: () => {},
  open: el => { closeDlg(); UI.view = "goal"; UI.gid = el.dataset.id; UI.tab = "ov"; render(); window.scrollTo(0, 0); },
  back: () => { UI.view = "list"; render(); window.scrollTo(0, 0); },
  tab: el => { UI.tab = el.dataset.t; render(); },
  filter: el => { UI.filter = el.dataset.f; render(); },
  sphere: el => { UI.sphere = UI.sphere === el.dataset.s ? null : el.dataset.s; render(); },
  "vis-edit": () => { UI.visEdit = true; render(); $("#vis-text").focus(); },
  "vis-cancel": () => { UI.visEdit = false; render(); },
  "vis-save": () => { DB.vision.text = $("#vis-text").value.trim(); DB.vision.horizon = $("#vis-h").value.trim() || DB.vision.horizon; UI.visEdit = false; save(); render(); snack("Видение сохранено"); },
  new: () => { closeDlg(); openWizard(null); },
  edit: el => openWizard(G(el.dataset.id)),
  checkin: el => openCheckin([el.dataset.id], false),
  review: () => { const a = active(); if (!a.length) return snack("Нет активных целей"); openCheckin(a.map(g => g.id), true); },
  gmenu: el => {
    const g = G(el.dataset.id);
    pop(el, g.status === "active"
      ? [["edit", "Изменить цель", g.id, "", "pencil"], ["done", "Отметить достигнутой", g.id, "", "check"], ["drop", "В архив", g.id, "", "archive"], "-", ["del", "Удалить", g.id, "danger", "trash"]]
      : [["edit", "Изменить цель", g.id, "", "pencil"], ["restore", "Вернуть в работу", g.id, "", "repeat"], "-", ["del", "Удалить", g.id, "danger", "trash"]]);
  },
  done: el => { const g = G(el.dataset.id); g.status = "done"; g.doneAt = TODAY; save(); render(); celebrate(g); },
  drop: el => { const g = G(el.dataset.id); g.status = "drop"; save(); render(); snack("Цель в архиве", () => { g.status = "active"; save(); render(); }); },
  restore: el => { const g = G(el.dataset.id); g.status = "active"; delete g.doneAt; save(); render(); snack("Цель снова в работе"); },
  del: el => {
    const i = DB.goals.findIndex(g => g.id === el.dataset.id), g = DB.goals[i];
    DB.goals.splice(i, 1); save(); UI.view = "list"; render();
    snack("Цель удалена", () => { DB.goals.splice(i, 0, g); save(); render(); });
  },
  step: async el => {
    const g = G(el.dataset.g), s = g.stages.find(x => x.id === el.dataset.s), st = s.steps.find(x => x.id === el.dataset.k);
    if (st.task && model.work.tasks[st.task]) {
      try { model.work = await request({op: "put", kind: "tasks", id: st.task, data: {...model.work.tasks[st.task], done: !st.done}}); window.WK = model.work; }
      catch (e) { snack(e.message); return; }
    }
    st.done = !st.done; st.doneAt = st.done ? TODAY : undefined; save(); render();
    if (st.done && s.steps.every(x => x.done)) snack("Этап «" + s.title + "» готов");
  },
  "step-del": el => {
    const g = G(el.dataset.g), s = g.stages.find(x => x.id === el.dataset.s), i = s.steps.findIndex(x => x.id === el.dataset.k), st = s.steps[i];
    s.steps.splice(i, 1); save(); render(); snack("Шаг удалён", () => { s.steps.splice(i, 0, st); save(); render(); });
  },
  totask: async el => {
    const g = G(el.dataset.g), step = g.stages.find(s => s.id === el.dataset.s).steps.find(x => x.id === el.dataset.k);
    if (step.task && model.work.tasks[step.task]) { S.view = "wktasks"; window.render(); wkOpenTask(step.task); return; }
    el.disabled = true;
    try {
      const id = "gt" + crypto.randomUUID().replaceAll("-", "").slice(0, 20);
      model.work = await request({op: "put", kind: "tasks", id, data: {text: step.t, due: step.due || g.deadline, project: g.projects.find(p => model.work.projects[p]) || "", done: step.done, desc: "Цель: " + g.title}});
      window.WK = model.work; step.task = id; save(); render(); snack("Задача создана в разделе «Задачи»");
    } catch (e) { snack(e.message); } finally { el.disabled = false; }
  },
  "stage-add": el => {
    const g = G(el.dataset.g), last = g.stages[g.stages.length - 1];
    g.stages.push({ id: "st" + Date.now(), title: "Новый этап", due: last && last.due > TODAY ? (addD(last.due, 30) < g.deadline ? addD(last.due, 30) : g.deadline) : g.deadline, steps: [] });
    save(); render(); const ins = root.querySelectorAll(".stg-h .in"); const x = ins[ins.length - 1]; if (x) { x.focus(); x.select(); }
  },
  "stage-del": el => {
    const g = G(el.dataset.g), i = g.stages.findIndex(x => x.id === el.dataset.s), s = g.stages[i];
    g.stages.splice(i, 1); save(); render(); snack("Этап удалён", () => { g.stages.splice(i, 0, s); save(); render(); });
  },
  hstep: el => { const g = G(el.dataset.g), h = g.habits.find(x => x.id === el.dataset.h), w = curWeek(); h.log[w] = clamp((h.log[w] || 0) + +el.dataset.d, 0, 99); save(); render(); },
  hset: el => { const g = G(el.dataset.g), h = g.habits.find(x => x.id === el.dataset.h); h.log[curWeek()] = +el.dataset.v; save(); render(); },
  "habit-add": el => {
    const t = $("#hb-t").value.trim(), n = Math.max(1, +$("#hb-n").value || 1);
    if (!t) return $("#hb-t").focus();
    G(el.dataset.g).habits.push({ id: "h" + Date.now(), title: t, per: n, log: {} }); save(); render();
  },
  close: () => closeDlg(),
  "wk-all": () => { UI.wkAll = !UI.wkAll; render(); },
  // отметка
  "ci-step": el => { const k = el.dataset.k; CI.vals[k] = Math.round(((+CI.vals[k] || 0) + +el.dataset.d) * 100) / 100; const inp = root.querySelector(`[data-ci="${k}"]`); if (inp) inp.value = CI.vals[k]; refreshCI(); },
  "ci-yn": el => { CI.vals[el.dataset.k] = +el.dataset.v; CI.note = $("#ci-note").value; CI.next = $("#ci-next").value; renderCI(); },
  "ci-conf": el => { CI.conf = el.dataset.v; root.querySelectorAll(".conf button").forEach(b => b.classList.toggle("on", b === el)); },
  "ci-save": () => saveCI(),
  "ci-skip": () => nextCI(),
  // мастер
  "wz-go": el => { WZ.step = +el.dataset.i; WZ.err = ""; renderWZ(); },
  "wz-next": () => { WZ.step = Math.min(3, WZ.step + 1); WZ.err = ""; renderWZ(); },
  "wz-prev": () => { WZ.step = Math.max(0, WZ.step - 1); WZ.err = ""; renderWZ(); },
  "wz-save": () => wzSave(),
  "wz-sph": el => { WZ.d.sphere = el.dataset.s; renderWZ(); },
  "wz-dl": el => { WZ.d.deadline = el.dataset.v; renderWZ(); },
  "wz-proj": el => { const p = el.dataset.p, a = WZ.d.projects; a.includes(p) ? a.splice(a.indexOf(p), 1) : a.push(p); renderWZ(); },
  "wz-kr-add": () => { WZ.d.krs.push({ id: "", title: "", unit: "шт.", start: 0, target: "" }); renderWZ(); const x = root.querySelectorAll(".krr .fin.t"); x[x.length - 1].focus(); },
  "wz-kr-del": el => { WZ.d.krs.splice(+el.dataset.i, 1); renderWZ(); },
  "wz-kr-tpl": el => { const t = WZ_TPL[+el.dataset.i]; const empty = WZ.d.krs.findIndex(k => !k.title.trim()); const k = { id: "", title: t[0], unit: t[1], start: t[2], target: t[3] }; if (empty >= 0) WZ.d.krs[empty] = k; else WZ.d.krs.push(k); renderWZ(); },
  "wz-st-add": () => { WZ.d.stages.push({ id: "", title: "", due: WZ.d.deadline || "", text: "", steps: [] }); renderWZ(); },
  "wz-st-del": el => { WZ.d.stages.splice(+el.dataset.i, 1); renderWZ(); },
  "wz-split": () => {
    const d = WZ.d; if (!d.deadline) return;
    const st = [], start = D(TODAY); let m = new Date(start.getFullYear(), start.getMonth() + 1, 0);
    while (iso(m) < d.deadline && st.length < 5) { if (diff(TODAY, iso(m)) >= 10) st.push(iso(m)); m = new Date(m.getFullYear(), m.getMonth() + 2, 0); }
    st.push(d.deadline);
    d.stages = st.map((due, i) => ({ id: "", title: i === st.length - 1 ? "Финиш: результат достигнут" : MONF[D(due).getMonth()][0].toUpperCase() + MONF[D(due).getMonth()].slice(1) + ": ", due, text: "", steps: [] }));
    renderWZ();
  },
  "wz-hb-add": () => { WZ.d.habits.push({ id: "", title: "", per: 3 }); renderWZ(); const x = root.querySelectorAll(".hbr .fin"); x[x.length - 2].focus(); },
  "wz-hb-del": el => { WZ.d.habits.splice(+el.dataset.i, 1); renderWZ(); },
};
root.addEventListener("click", e => {
  const el = e.target.closest("[data-a]");
  if (!e.target.closest(".pop") && !(el && el.dataset.a === "gmenu")) closePop();
  if (!el) return;
  const f = A[el.dataset.a]; if (f) { e.preventDefault(); f(el, e); }
});
root.addEventListener("input", e => {
  const t = e.target;
  if (t.dataset.f && WZ) {
    let v = t.value; if (t.hasAttribute("data-num")) v = v === "" ? "" : +v;
    wzSet(t.dataset.f, v); WZ.err = "";
    if (t.hasAttribute("data-re") || t.dataset.f === "deadline") renderWZ();
    else { const s = $("#wz-smart"); if (s) s.innerHTML = smartHtml(smart(WZ.d)); }
  }
  if (t.dataset.ci && CI) { CI.vals[t.dataset.ci] = t.value === "" ? 0 : +t.value; refreshCI(); }
});
root.addEventListener("change", e => {
  const t = e.target, a = t.dataset.a2; if (!a) return;
  const g = G(t.dataset.g), s = g && g.stages.find(x => x.id === t.dataset.s);
  if (a === "stage-title" && s) { s.title = t.value.trim() || s.title; save(); }
  if (a === "stage-due" && s && t.value) { s.due = t.value; g.stages.sort((x, y) => x.due < y.due ? -1 : 1); save(); render(); }
});
root.addEventListener("keydown", e => {
  const t = e.target;
  if (e.key === "Enter" && t.dataset.a2 === "step-add" && t.value.trim()) {
    const g = G(t.dataset.g), s = g.stages.find(x => x.id === t.dataset.s);
    s.steps.push({ id: "s" + Date.now(), t: t.value.trim(), done: false, due: "" }); save(); render();
    const inp = root.querySelector(`[data-a2="step-add"][data-s="${s.id}"]`); if (inp) inp.focus();
  }
  if (e.key === "Enter" && t.dataset.a2 === "stage-title") t.blur();
  if (e.key === "Enter" && t.id === "hb-t") A["habit-add"](root.querySelector('[data-a="habit-add"]'));
  if (e.key === "Escape") closePop();
});
model.paint = render;
model.status = showStatus;
function projectName(id) { return (model.work.projects[id] || {}).title || "Проект удалён"; }
function syncAuto() {
  DB.goals.forEach(g => {
    const owns = x => !g.projects.length || g.projects.includes(x.project);
    g.krs.forEach(k => {
      if (g.status !== "active") return;
      if (k.auto === "shows") k.cur = Object.values(model.work.shows || {}).filter(x => owns(x) && x.date >= g.start && x.date <= g.deadline && x.date < TODAY).length;
      if (k.auto === "docs") k.cur = Object.values(model.work.docs || {}).filter(x => owns(x) && x.kind === "Договор" && x.status === "signed").length;
      if (k.auto === "projects") k.cur = Object.entries(model.work.projects || {}).filter(([id,x]) => (!g.projects.length || g.projects.includes(id)) && (model.work.stages[x.stage] || {}).done).length;
    });
    g.stages.forEach(s => s.steps.forEach(x => { if (x.task && model.work.tasks[x.task]) x.done = !!model.work.tasks[x.task].done; }));
  });
}
function showStatus() {
  const el = $("#save-state");
  el.className = "save-state" + (model.error ? " error" : "");
  el.innerHTML = model.error ? esc(model.error) + ' <button id="retry-save">Повторить сохранение</button><button id="export-draft">Скачать изменения</button><button id="load-server">Загрузить сохранённое</button>' : model.dirty || model.saving ? "Сохранение…" : "Все изменения сохранены";
  if (model.error) {
    $("#retry-save").onclick = () => { model.error = ""; flush(); };
    $("#load-server").onclick = () => {
      if (!window.confirm("Несохранённые изменения будут заменены данными с сайта. Сначала скачайте их, если хотите сохранить. Продолжить?")) return;
      try { localStorage.removeItem(KEY); } catch (_) {}
      model.dirty = false; model.error = ""; model.db = null; model.ui = null; window.render();
    };
    $("#export-draft").onclick = () => { const a = document.createElement("a"), url = URL.createObjectURL(new Blob([JSON.stringify(DB, null, 2)], {type: "application/json"})); a.href = url; a.download = "goals-draft.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  }
}
render(); showStatus();

}
})();
