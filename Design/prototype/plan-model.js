// Финансовая модель одной даты тура (раздел «Планирование», TOUR_PLANNER.md, раздел 3; решения пользователя 12.10.2026).
// Основа — Google Таблица пользователя «Калькулятор планирование сезона» (лист «Структура портфеля»), статьи — новые.
// Подключается в index.html до основного скрипта; тест — tests/plan-model.test.js (node --test).
//
// ▸ ФОРМУЛЫ — ТОЛЬКО ЗДЕСЬ. Страница берёт значения из справочников (проект, город, регион, площадка) и правок строки
//   тура и зовёт planCalc; сама ничего не считает.
//
// Постоянные издержки  = проектные (гонорар + % за безнал от гонорара + суточные × состав × дни (или суточные всего —
//                        per_diem_sum, когда состав и ставка неизвестны; подбор городов, решение пользователя 27.10) + авторские
//                        + московские расходы ÷ городов тура) + организационные (8 статей города) + аренда + логистика
//                        + реклама
// Переменные издержки  = сборы × (РАО/ВОИС + налог + комиссия касс + агентские), %
// Сборы                = вал × % от аншлага;  прибыль = сборы − переменные − постоянные
// Распоясовка (если задана) — пояса: цена × билетов = вал пояса; сборы пояса = вал × заполняемость пояса (пусто — общий
//                        % от аншлага); вал, мест и сборы даты — суммы по поясам (решение пользователя 12.10)
// Рентабельность продаж = прибыль ÷ сборы;  окупаемость затрат = прибыль ÷ итоговые расходы;  эффективность слота = прибыль ÷ вал
// ТБУ, билетов         = постоянные ÷ (средняя цена × (1 − переменные %))   — как в таблице
// Продать, чтобы заработать N = (постоянные + N) ÷ (средняя цена × (1 − переменные %)) билетов
var PLAN_DEFAULTS = {
  tax: 2,                                                    // налог, % от сборов
  classes: [["S", 600000], ["A", 500000], ["B", 400000], ["C", 250000]],   // ниже последнего — D (как в таблице)
  scenarios: [50, 70, 90],                                   // % от аншлага: осторожный / базовый / хороший
  base: 1,                                                   // какой сценарий — по умолчанию (базовый)
  weights: { fin: 0.25, comp: 0.25, ads: 0.15, attract: 0.15, market: 0.15, prep: 0.05 },   // итоговый балл (как в таблице)
  ban_months: 13,                                            // запрет повторного показа (как в таблице)
  target: 150000                                             // «продать, чтобы заработать»: желаемая прибыль по умолчанию (правится в карточке города)
};
var PLAN_ORG = [["transfer", "Трансфер"], ["hotel", "Проживание"], ["tech", "Технический райдер"], ["catering", "Кейтеринг на площадке"],
  ["loaders", "Грузчики"], ["security", "Охрана"], ["services", "Службы"], ["other", "Прочие расходы"]];
var PLAN_SCORES = [["comp", "Конкуренция", "5 — конкурентов нет, 1 — город перегружен похожими"], ["ads", "Рекламная эффективность бюджета", "Насколько реклама в городе окупается"],
  ["attract", "Привлекательность проекта", "Насколько проект интересен этому городу"], ["market", "Маркетинговая оценка", "Легко ли продаётся проект"],
  ["prep", "Простота подготовки", "Сколько сил уйдёт на организацию"]];

function planNum(v) { var n = typeof v === "number" ? v : parseFloat(String(v == null ? "" : v).replace(/\s/g, "").replace(",", ".")); return isFinite(n) ? n : 0; }

// Класс даты по прибыли и финансовая оценка 1–5 (S — 5 … D — 1)
function planClass(profit, cfg) {
  var cls = (cfg || PLAN_DEFAULTS).classes;
  for (var i = 0; i < cls.length; i++) if (profit >= cls[i][1]) return { cls: cls[i][0], score: 5 - i };
  return { cls: "D", score: 1 };
}

// Расчёт одной даты. x — уже собранные входные значения (справочник или правка строки):
//   gross, seats, fill (%), fee, cashless (%), per_diem, crew, days, author, rao_on, rao (%), moscow, cities,
//   org {transfer…other}, rent, logistics, ads, kassa (%), agent (%); cfg — параметры (налог, классы).
function planCalc(x, cfg) {
  cfg = cfg || PLAN_DEFAULTS;
  var n = planNum, gross = n(x.gross), seats = n(x.seats), fill = n(x.fill) / 100, sales, zones = null;
  if (x.zones && x.zones.length) {   // распоясовка: вал, места и сборы — по поясам
    gross = 0; seats = 0; sales = 0;
    zones = x.zones.map(function (z) {
      var zg = n(z.price) * n(z.seats), zf = z.fill != null && z.fill !== "" ? n(z.fill) / 100 : fill;
      gross += zg; seats += n(z.seats); sales += zg * zf;
      return { name: z.name || "", price: n(z.price), seats: n(z.seats), gross: zg, fill: zf * 100, own: z.fill != null && z.fill !== "", sales: zg * zf };
    });
  } else sales = gross * fill;
  var avg = seats > 0 ? gross / seats : 0;
  var varPct = (x.rao_on ? n(x.rao) : 0) + n(cfg.tax) + n(x.kassa) + n(x.agent);
  var v = varPct / 100;
  var cities = Math.max(1, n(x.cities) || 1);
  var project = {
    fee: n(x.fee), cashless: n(x.fee) * n(x.cashless) / 100,
    per_diem: x.per_diem_sum != null && x.per_diem_sum !== "" ? n(x.per_diem_sum) : n(x.per_diem) * n(x.crew) * Math.max(0, n(x.days)),
    author: n(x.author), moscow: n(x.moscow) / cities
  };
  project.total = project.fee + project.cashless + project.per_diem + project.author + project.moscow;
  var org = 0; PLAN_ORG.forEach(function (o) { org += n((x.org || {})[o[0]]); });
  var fixed = project.total + org + n(x.rent) + n(x.logistics) + n(x.ads);
  var variable = sales * v;
  var revenue = sales - variable;            // выручка после переменных (как «ВЫРУЧКА» в таблице)
  var profit = revenue - fixed;
  var net = avg * (1 - v);                   // сколько остаётся с одного билета после переменных
  var beTickets = net > 0 ? fixed / net : null;
  var target = x.target != null && x.target !== "" ? n(x.target) : n(cfg.target != null ? cfg.target : PLAN_DEFAULTS.target);
  var tgTickets = net > 0 ? (fixed + target) / net : null;
  var cl = planClass(profit, cfg);
  return {
    gross: gross, seats: seats, zones: zones, fillEff: gross > 0 ? sales / gross * 100 : n(x.fill),
    avg: avg, sales: sales, varPct: varPct, variable: variable, project: project, org: org, rent: n(x.rent), logistics: n(x.logistics), ads: n(x.ads),
    fixed: fixed, total: fixed + variable, revenue: revenue, profit: profit,
    beTickets: beTickets, beRub: beTickets == null ? null : beTickets * avg, beShare: beTickets == null || !seats ? null : beTickets / seats,
    target: target, tgTickets: tgTickets, tgRub: tgTickets == null ? null : tgTickets * avg, tgShare: tgTickets == null || !seats ? null : tgTickets / seats,
    eff: gross > 0 ? profit / gross : null, ros: sales > 0 ? profit / sales : null, roi: fixed + variable > 0 ? profit / (fixed + variable) : null,
    cls: cl.cls, finScore: cl.score
  };
}

// Итоговый балл кандидата: финансовая оценка + ручные оценки 1–5 с весами. Нет оценки — вес не учитывается.
function planScore(finScore, scores, cfg) {
  var w = (cfg || PLAN_DEFAULTS).weights, sum = 0, ws = 0;
  var add = function (val, wt) { if (val >= 1 && val <= 5) { sum += val * wt; ws += wt; } };
  add(finScore, w.fin);
  PLAN_SCORES.forEach(function (s) { add(planNum((scores || {})[s[0]]), w[s[0]]); });
  return ws ? Math.round(sum / ws * 10) / 10 : null;
}

// Запрет повторного показа: с последнего показа в городе прошло меньше ban_months месяцев до даты тура
function planBanned(lastShow, date, cfg) {
  if (!lastShow || !/^\d{4}-\d{2}/.test(lastShow)) return false;
  var m = (cfg || PLAN_DEFAULTS).ban_months, a = new Date(lastShow + (lastShow.length === 7 ? "-01" : "") + "T12:00:00Z");
  a.setUTCMonth(a.getUTCMonth() + m);
  var d = date && /^\d{4}-\d{2}/.test(date) ? new Date(date + (date.length === 7 ? "-01" : "") + "T12:00:00Z") : new Date();
  return a > d;
}

// ---------- Аналитика тура (запрос пользователя 13.10: какие статьи крупнее, что сильнее влияет на маржу, доли расходов)
// Статьи расходов одной даты: сумма статей = r.total (постоянные + переменные). Группы — для долей расходов.
var PLAN_GROUPS = [["project", "Гонорар и проект", "#1d6fae"], ["perdiem", "Суточные", "#6fa7d6"], ["org", "Организационные", "#7c3aed"], ["rent", "Аренда", "#ea580c"],
  ["logistics", "Логистика", "#0891b2"], ["ads", "Реклама", "#db2777"], ["variable", "Налог и комиссии", "#a16207"]];
function planItems(r, x, cfg) {
  var n = planNum, s = r.sales, out = [];
  var add = function (id, label, group, sum) { if (sum) out.push({ id: id, label: label, group: group, sum: sum }); };
  add("fee", "Гонорар", "project", r.project.fee); add("cashless", "% за безнал", "project", r.project.cashless);
  add("author", "Авторские", "project", r.project.author); add("moscow", "Московские расходы", "project", r.project.moscow);
  add("per_diem", "Суточные", "perdiem", r.project.per_diem);
  PLAN_ORG.forEach(function (o) { add(o[0], o[1], "org", n((x.org || {})[o[0]])); });
  add("rent", "Аренда", "rent", r.rent); add("logistics", "Логистика", "logistics", r.logistics); add("ads", "Реклама", "ads", r.ads);
  add("tax", "Налог", "variable", s * n(cfg.tax) / 100); add("kassa", "Комиссия касс", "variable", s * n(x.kassa) / 100);
  if (x.rao_on) add("rao", "РАО/ВОИС", "variable", s * n(x.rao) / 100);
  add("agent", "Агентские", "variable", s * n(x.agent) / 100);
  return out;
}
// Сдвиг одного фактора даты (решение пользователя: в рублях и процентах): заполняемость и комиссия касс — ± п.п.;
// цена билета — ± ₽ за билет; статьи (гонорар, аренда, реклама, логистика, организационные, суточные) — ± ₽ на город.
var PLAN_FACTORS = [["fill", "Заполняемость", "pp"], ["price", "Средняя цена билета", "rub_t"], ["fee", "Гонорар", "rub"], ["rent", "Аренда", "rub"],
  ["ads", "Реклама", "rub"], ["logistics", "Логистика", "rub"], ["org", "Организационные", "rub"], ["per_diem", "Суточные", "rub"], ["kassa", "Комиссия касс", "pp"]];
function planShift(x, f, d) {
  var n = planNum, y = JSON.parse(JSON.stringify(x));
  if (f === "fill") {
    y.fill = Math.max(0, Math.min(100, n(y.fill) + d));
    if (y.zones) y.zones.forEach(function (z) { if (z.fill != null && z.fill !== "") z.fill = Math.max(0, Math.min(100, n(z.fill) + d)); });
  } else if (f === "price") {
    if (y.zones && y.zones.length) y.zones.forEach(function (z) { z.price = Math.max(0, n(z.price) + d); });
    else y.gross = Math.max(0, n(y.gross) + d * n(y.seats));
  } else if (f === "org") {   // рост — в «прочие»; снижение — всех организационных статей поровну в долях (не ниже нуля)
    y.org = y.org || {};
    var tot = 0; Object.keys(y.org).forEach(function (k) { tot += n(y.org[k]); });
    if (d >= 0) y.org.other = n(y.org.other) + d;
    else if (tot > 0) { var kf = Math.max(0, tot + d) / tot; Object.keys(y.org).forEach(function (k) { y.org[k] = n(y.org[k]) * kf; }); }
  }
  else if (f === "per_diem") {
    if (y.per_diem_sum != null && y.per_diem_sum !== "") y.per_diem_sum = Math.max(0, n(y.per_diem_sum) + d);   // суточные всего — сдвиг суммы
    else { var k = n(y.crew) * Math.max(1, n(y.days)); if (k > 0) y.per_diem = Math.max(0, n(y.per_diem) + d / k); }
  }
  else y[f] = Math.max(0, n(y[f]) + d);
  return y;
}
// Чувствительность тура: прибыль и маржа при сдвиге каждого фактора вверх и вниз (по всем датам сразу).
// steps: {pp — п.п. заполняемости, rub_t — ₽ на билет, rub — ₽ на город, kassa — п.п. комиссии}. Самый влиятельный — первым.
function planSensitivity(xs, cfg, steps) {
  var tot = function (list) { var p = 0, s = 0; list.forEach(function (x) { var r = planCalc(x, cfg); p += r.profit; s += r.sales; }); return { p: p, s: s, m: s > 0 ? p / s : null }; };
  var base = tot(xs), out = [];
  PLAN_FACTORS.forEach(function (f) {
    var st = f[0] === "kassa" ? steps.kassa : f[2] === "pp" ? steps.pp : f[2] === "rub_t" ? steps.rub_t : steps.rub;
    if (!st) return;
    var up = tot(xs.map(function (x) { return planShift(x, f[0], st); })), dn = tot(xs.map(function (x) { return planShift(x, f[0], -st); }));
    out.push({ id: f[0], label: f[1], unit: f[0] === "kassa" ? "pp" : f[2], step: st, up: up.p - base.p, down: dn.p - base.p,
      upM: up.m != null && base.m != null ? (up.m - base.m) * 100 : null, downM: dn.m != null && base.m != null ? (dn.m - base.m) * 100 : null });
  });
  out = out.filter(function (o) { return o.up || o.down; });
  out.sort(function (a, b) { return Math.max(Math.abs(b.up), Math.abs(b.down)) - Math.max(Math.abs(a.up), Math.abs(a.down)); });
  return { base: base, factors: out };
}

if (typeof module !== "undefined") module.exports = { PLAN_DEFAULTS: PLAN_DEFAULTS, PLAN_ORG: PLAN_ORG, PLAN_SCORES: PLAN_SCORES, PLAN_GROUPS: PLAN_GROUPS, PLAN_FACTORS: PLAN_FACTORS,
  planNum: planNum, planClass: planClass, planCalc: planCalc, planScore: planScore, planBanned: planBanned, planItems: planItems, planShift: planShift, planSensitivity: planSensitivity };
