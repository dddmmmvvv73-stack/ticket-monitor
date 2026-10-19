// Тест «Построения гастрольного маршрута» (Design/prototype/route-plan.js). Запуск: node --test
// Эталон — свободные даты площадок, которые прислал пользователь 16.10.2026 (февраль; с пропущенными запятыми).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { rpParse, rpRoutes, rpBridges, rpParseDays } = require("../Design/prototype/route-plan.js");

eval(fs.readFileSync(path.join(__dirname, "../Design/prototype/market-pop.js"), "utf8").replace("var MPOP", "global.MPOP"));
const P = global.MPOP;
const km = (a, b) => {   // по прямой × 1,3 — как на странице
  const p = P[a], q = P[b]; if (!p || !q) return null;
  const r = Math.PI / 180, x = (q[2] - p[2]) * r * Math.cos((p[1] + q[1]) / 2 * r), y = (q[1] - p[1]) * r;
  return Math.round(Math.round(Math.hypot(x, y) * 6371) * 1.3);
};
const text = fs.readFileSync(path.join(__dirname, "fixtures/venue-dates-feb.txt"), "utf8");
const p = rpParse(text, { cities: Object.keys(P), today: "2026-10-19" });
const row = (c) => p.rows.find((r) => r.city === c);

test("пропущенные запятые: «58» → 5, 8; «34» → 3, 4; «910» → 9, 10; «12» остаётся 12", () => {
  assert.deepEqual(row("Подольск").days, [1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15]);
  assert.deepEqual(row("Электросталь").days, [1, 2, 3, 4, 7, 8, 9, 10, 12, 14, 15]);
  assert.ok(row("Электросталь").fixes.includes("«910» → 9, 10"));
  assert.deepEqual(rpParseDays("1, 12, 1011, 5-7").days, [1, 5, 6, 7, 10, 11, 12]);
});

test("месяц из шапки, площадки, одна площадка у двух городов", () => {
  assert.equal(p.month, "2027-02");
  assert.equal(row("Кострома").venue, "КВЦ Губернский");
  assert.ok(p.issues.some((x) => /Лепсе.*Подольск и Выкса/.test(x)));
  assert.equal(p.rows.length, 5);
});

const R = rpRoutes(p.rows, { km, limit: 600, base: "Москва", month: "2027-02", top: 20 });

test("варианты без выходных: даты подряд, город — один раз, переезд ≤ 600 км; полные — первыми", () => {
  assert.ok(R.list.length > 0 && R.list.length <= 20);
  for (const v of R.list) {
    v.stops.forEach((s, i) => { if (i) assert.equal(s.day, v.stops[i - 1].day + 1); });
    assert.equal(new Set(v.stops.map((s) => s.city)).size, v.n);
    assert.ok(v.hops.every((h) => h <= 600));
    assert.equal(v.off, 0);
  }
  const ns = R.list.map((v) => v.n);
  assert.deepEqual(ns, [...ns].sort((a, b) => b - a));
});

test("Воронеж — Кострома (≈ 894 км) подряд не стоят; выезд из Москвы лимитом не ограничен", () => {
  for (const v of R.list) v.stops.forEach((s, i) => { if (i) assert.ok(!(new Set([s.city, v.stops[i - 1].city]).size === 2 && [s.city, v.stops[i - 1].city].sort().join() === "Воронеж,Кострома")); });
  const vrn = R.list.find((v) => v.stops[0].city === "Воронеж");
  if (vrn) assert.ok(vrn.fromBase > 600);
});

test("с выходными — длиннее или столько же, выходные посчитаны", () => {
  const G = rpRoutes(p.rows, { km, limit: 600, base: "Москва", month: "2027-02", gaps: 1, onlyOff: true });
  assert.ok(G.list.length > 0 && G.list.every((v) => v.off > 0));
  G.list.forEach((v) => v.stops.forEach((s, i) => { if (i) assert.ok(s.day - v.stops[i - 1].day <= 2); }));
});

test("город-связка для Воронеж — Кострома: до обоих концов ≤ 600 км", () => {
  const B = rpBridges(p.rows, { km, limit: 600, base: "Москва", candidates: Object.keys(P), pop: (c) => P[c][0] });
  const vk = B.find((b) => [b.a, b.b].sort().join() === "Воронеж,Кострома");
  assert.ok(vk && vk.cands.length > 0);
  assert.ok(vk.cands.every((c) => c.a <= 600 && c.b <= 600));
  assert.ok(vk.combos.length > 0 && vk.combos.every((c) => c.d2 - c.d1 >= 2 && c.d2 - c.d1 <= 4));
  assert.deepEqual([vk.combos[0].from, vk.combos[0].d1, vk.combos[0].to, vk.combos[0].d2], ["Воронеж", 3, "Кострома", 6]);
});
