// Подбор городов для артиста (TOUR_PLANNER.md, «26.10 — Подбор городов»; решения пользователя 26.10.2026).
// Первое касание: известен гонорар (иногда % сверху и состав) — остальное по нормам, любое значение правится.
// По каждому городу: зал для расчёта, цена, которую город платит за похожие гастроли, нужная средняя цена билета
// (выйти в ноль) и прибыль при базовой заполняемости. Деньги считает planCalc (plan-model.js) — здесь только входы.
// Подключается в index.html после plan-model.js; тест — tests/city-pick.test.js (node --test).
// Объяснение для пользователя — CITY_PICK.md (правите формулы или нормы — правьте и его).
//
// Середина цены мероприятия = (мин. + макс.) / 2; выборка — гастроли того же формата в городе (афиша + архив),
// меньше PICK_DEFAULTS.minN — по области (уверенность «низкая»).
// Уровень артиста = медиана середин его дат ÷ медиана середин всех гастролей формата по стране (пользователь может вписать сам).
// Цена города   = артист в афише есть: медиана середин в городе × уровень артиста;
//                 нет: 75-й процентиль середин в городе (цены крупных концертов).
// Нужная цена   = постоянные ÷ (мест × заполняемость × (1 − переменные %))
// Запас         = цена города ÷ нужная цена − 1;  окупается — запас ≥ edge %, на грани — в пределах ± edge %, иначе нет.
var PICK_DEFAULTS = {
  fill: 70,                     // % от аншлага по умолчанию (решение 26.10)
  kassa: 10,                    // комиссия касс, % от сборов
  crew: 8,                      // состав на выезде, если неизвестен
  capMin: 300,                  // зал для расчёта — не меньше стольких мест
  capMax: 2500,                 // и не больше (если у артиста в афише мало залов; иначе — его самый большой зал)
  edge: 10,                     // ± % запаса — «на грани»
  big: 5000,                    // «крупный концерт» в городе — максимальная цена билета от стольких ₽
  minN: 3,                      // меньше мероприятий в городе — цена по области
  rider: { from: 1000000, sum: 500000, share: 0.5, min: 100000 },   // райдер на город: гонорар от 1 млн — 500 тыс. (слова пользователя), меньше — половина гонорара, не меньше 100 тыс.
  rent: [[500, 80000], [1000, 150000], [2000, 300000], [null, 500000]],    // аренда по вместимости зала (до N мест — ₽)
  ads: [[500, 80000], [1000, 150000], [2000, 250000], [null, 400000]],     // реклама по вместимости зала
  travel: [[700, 6000], [2000, 15000], [null, 25000]]                      // дорога туда и обратно на человека по расстоянию от Москвы, км
};

function pickTier(tiers, v) {
  for (var i = 0; i < tiers.length; i++) if (tiers[i][0] == null || v <= tiers[i][0]) return tiers[i][1];
  return tiers[tiers.length - 1][1];
}
function pickRider(fee, d) {
  var r = (d || PICK_DEFAULTS).rider, f = planNum(fee);
  if (!f) return 0;
  return f >= r.from ? r.sum : Math.max(r.min, Math.round(f * r.share / 10000) * 10000);
}
function pickQuantile(a, q) {
  if (!a.length) return null;
  var s = a.slice().sort(function (x, y) { return x - y; }), p = (s.length - 1) * q, i = Math.floor(p);
  return i + 1 < s.length ? s[i] + (s[i + 1] - s[i]) * (p - i) : s[i];
}
function pickMid(e) { var a = planNum(e.pmin), b = planNum(e.pmax); return a && b ? (a + b) / 2 : b || a || 0; }

function pickMids(l) { return (l || []).map(pickMid).filter(function (v) { return v > 0; }); }
function pickRound(v) { return Math.round(v / 50) * 50; }

// Уровень цен артиста против рынка: {k, n, price — его медиана, market — медиана по стране} или null (меньше двух дат с ценами)
function pickLevel(artistEv, allEv) {
  var a = pickMids(artistEv), m = pickMids(allEv);
  if (a.length < 2 || m.length < 20) return null;
  var pa = pickQuantile(a, 0.5), pm = pickQuantile(m, 0.5);
  return { k: Math.round(Math.max(0.4, Math.min(3, pa / pm)) * 100) / 100, n: a.length, price: pickRound(pa), market: pickRound(pm) };
}

// Цена, которую город платит: {price, base — медиана или процентиль города, k, n, src: "city" | "region", conf} или null.
// k — уровень артиста (число); без него — 75-й процентиль (крупные концерты города).
function pickPrice(cityEv, regionEv, d, k) {
  d = d || PICK_DEFAULTS;
  var c = pickMids(cityEv), g = pickMids(regionEv), q = k ? 0.5 : 0.75, m = k || 1;
  var out = function (l, src, conf, extra) { var b = pickQuantile(l, q); return Object.assign({ price: pickRound(b * m), base: pickRound(b), k: k || null, q: q, n: l.length, src: src, conf: conf }, extra || {}); };
  if (c.length >= d.minN) return out(c, "city", c.length >= 8 ? "high" : "mid");
  if (g.length >= d.minN) return out(g, "region", "low", { nCity: c.length });
  if (c.length) return out(c, "city", "low");
  return null;
}

// Зал для расчёта: самый большой из залов с известной вместимостью в пределах «от–до»; цирк, стадион, дельфинарий —
// только если вписаны вручную
var PICK_NOT_HALL = /цирк|дельфинари|стадион|ипподром|аквапарк|каток/i;
function pickVenue(venues, capMin, capMax) {
  var lo = planNum(capMin), hi = planNum(capMax);
  var ok = (venues || []).filter(function (v) { return v.cap && v.cap >= lo && (!hi || v.cap <= hi) && (v.src === "manual" || !PICK_NOT_HALL.test(v.name)); });
  ok.sort(function (a, b) { return b.cap - a.cap; });
  return ok[0] || null;
}

// Входы planCalc для города. econ — экономика проекта (гонорар, % сверху, состав…); c — город: {seats, venueRent, price,
// km — от Москвы, cities — городов в предложении}; o — правки города. src — откуда каждое значение: ovr | econ | venue | norm.
function pickInputs(econ, c, o, d) {
  d = d || PICK_DEFAULTS; econ = econ || {}; o = o || {};
  var n = planNum, src = {}, has = function (v) { return v != null && v !== ""; };
  var pick = function (f, list) { for (var i = 0; i < list.length; i++) if (has(list[i][0])) { src[f] = list[i][1]; return n(list[i][0]); } src[f] = "none"; return 0; };
  var crew = pick("crew", [[econ.crew, "econ"], [d.crew, "norm"]]);
  var seats = pick("seats", [[o.seats, "ovr"], [c.seats, "venue"]]);
  var price = pick("price", [[o.price, "ovr"], [c.price, "city"]]);
  var fill = pick("fill", [[o.fill, "ovr"], [econ.fill, "econ"], [d.fill, "norm"]]);
  var rider = pick("rider", [[o.rider, "ovr"], [econ.rider, "econ"], [pickRider(econ.fee, d) || null, "norm"]]);
  var rent = pick("rent", [[o.rent, "ovr"], [c.venueRent, "venue"], [seats ? pickTier(d.rent, seats) : null, "norm"]]);
  var ads = pick("ads", [[o.ads, "ovr"], [econ.ads, "econ"], [seats ? pickTier(d.ads, seats) : null, "norm"]]);
  var logistics = pick("logistics", [[o.logistics, "ovr"], [c.km != null ? crew * pickTier(d.travel, c.km) : null, "norm"]]);
  var kassa = pick("kassa", [[econ.kassa, "econ"], [d.kassa, "norm"]]);
  return { src: src, x: { gross: price * seats, seats: seats, fill: fill, fee: n(econ.fee), cashless: n(econ.cashless), per_diem: n(econ.per_diem), crew: crew, days: 1,
    author: n(econ.author), rao_on: n(econ.rao) > 0, rao: n(econ.rao), moscow: n(econ.moscow), cities: Math.max(1, n(c.cities) || 1),
    org: { tech: rider }, rent: rent, logistics: logistics, ads: ads, kassa: kassa, agent: 0 } };
}

// Расчёт города: planCalc по цене города + нужная цена, запас и статус (ok | edge | no | nohall | noprice | nofee)
function pickCalc(inp, cfg, d) {
  d = d || PICK_DEFAULTS;
  var x = inp.x, r = planCalc(x, cfg), f = planNum(x.fill) / 100, v = r.varPct / 100;
  var need = x.seats > 0 && f > 0 && v < 1 ? r.fixed / (x.seats * f * (1 - v)) : null;
  var price = x.seats > 0 ? x.gross / x.seats : 0, margin = need && price ? price / need - 1 : null, e = d.edge / 100;
  var status = !x.fee ? "nofee" : !x.seats ? "nohall" : !price ? "noprice" : margin >= e ? "ok" : margin >= -e ? "edge" : "no";
  return { r: r, need: need, price: price, margin: margin, status: status };
}

// Итог предложения: сумма по городам (московские расходы уже поделены на число городов через x.cities)
function pickTotals(calcs) {
  var t = { n: 0, sales: 0, total: 0, profit: 0, ok: 0, edge: 0, no: 0 };
  calcs.forEach(function (k) { t.n++; t.sales += k.r.sales; t.total += k.r.total; t.profit += k.r.profit; if (t[k.status] != null) t[k.status]++; });
  return t;
}

if (typeof module !== "undefined") module.exports = { PICK_DEFAULTS: PICK_DEFAULTS, pickTier: pickTier, pickRider: pickRider, pickQuantile: pickQuantile, pickMid: pickMid,
  pickLevel: pickLevel, pickPrice: pickPrice, pickVenue: pickVenue, pickInputs: pickInputs, pickCalc: pickCalc, pickTotals: pickTotals };
