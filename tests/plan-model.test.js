// Тест финансовой модели (Design/prototype/plan-model.js). Запуск: node --test
// Эталон — строки листа «Структура портфеля» Google Таблицы пользователя (12.10.2026): те же входы — те же цифры.
const test = require("node:test");
const assert = require("node:assert/strict");
const { PLAN_DEFAULTS, planCalc, planClass, planScore, planBanned, planNum } = require("../Design/prototype/plan-model.js");

const near = (a, b, eps = 0.5) => assert.ok(Math.abs(a - b) <= eps, `${a} ≠ ${b}`);

// В таблице: постоянные = себестоимость + аренда + реклама + затраты; переменные = % (там 0 + 0 + 11 %).
// Здесь «себестоимость» — гонорар, затраты региона — логистика, 11 % — налог (остальные ставки 0).
const cfg11 = { ...PLAN_DEFAULTS, tax: 11 };

test("Синяя птица, Новый Уренгой (КСЦ «Газодобытчик») — как в таблице", () => {
  const r = planCalc({ gross: 1582000, seats: 576, fill: 95, fee: 500000, rent: 100000, ads: 105000, logistics: 80000, cities: 1 }, cfg11);
  near(r.fixed, 785000);
  near(r.revenue, 1337581);           // ВЫРУЧКА
  near(r.profit, 552581);             // ПРИБЫЛЬ
  near(r.avg, 2746.527778, 1e-3);     // СР. ЦЕНА БИЛЕТА
  near(r.beTickets, 321.1409253, 1e-3);   // ТБУ БИЛ.
  near(r.beRub, 882022.4719, 1e-2);       // ТБУ
  near(r.beShare, 0.5575363286, 1e-6);    // % ТБУ
  near(r.eff, 0.3492926675, 1e-6);        // % ЭФФЕКТИВНОСТЬ СЛОТА
  assert.equal(r.cls, "A");
});

test("Строчка-пример (Новый Уренгой, ГДК Октябрь) — переменные 32 %, убыток, класс D", () => {
  // РАО/ВОИС/агентские 11 % + агентский 10 % + 11 %
  const r = planCalc({ gross: 1464100, seats: 383, fill: 73.97266666666666, fee: 650000, rent: 120000, ads: 200000, logistics: 96000,
    rao_on: true, rao: 11, agent: 10, cities: 1 }, cfg11);
  near(r.fixed, 1066000);
  near(r.varPct, 32, 1e-9);
  near(r.revenue, 736462.9926, 1e-2);
  near(r.profit, -329537.0074, 1e-2);
  near(r.beTickets, 410.0873052, 1e-3);
  assert.equal(r.cls, "D");
});

test("Статьи проекта: безнал от гонорара, суточные × состав × дни, московские ÷ городов, организационные", () => {
  const r = planCalc({ gross: 1000000, seats: 500, fill: 100, fee: 300000, cashless: 7, per_diem: 2000, crew: 8, days: 2, author: 15000,
    moscow: 200000, cities: 5, org: { transfer: 10000, hotel: 40000, tech: 30000, catering: 5000, loaders: 6000, security: 4000, services: 3000, other: 2000 },
    rent: 90000, logistics: 70000, ads: 60000, kassa: 8, agent: 0 });
  assert.equal(r.project.cashless, 21000);
  assert.equal(r.project.per_diem, 32000);
  assert.equal(r.project.moscow, 40000);
  assert.equal(r.project.total, 300000 + 21000 + 32000 + 15000 + 40000);
  assert.equal(r.org, 100000);
  assert.equal(r.fixed, 408000 + 100000 + 90000 + 70000 + 60000);
  assert.equal(r.varPct, 10);              // налог 2 + касса 8 (РАО/ВОИС выключен)
  assert.equal(r.variable, 100000);
  assert.equal(r.profit, 1000000 - 100000 - 728000);
});

test("РАО/ВОИС учитывается, только если включён у проекта", () => {
  assert.equal(planCalc({ gross: 100, seats: 1, fill: 100, rao: 5 }).varPct, 2);
  assert.equal(planCalc({ gross: 100, seats: 1, fill: 100, rao: 5, rao_on: true }).varPct, 7);
});

test("Классы и финансовая оценка — пороги таблицы", () => {
  assert.deepEqual(planClass(600000), { cls: "S", score: 5 });
  assert.deepEqual(planClass(500000), { cls: "A", score: 4 });
  assert.deepEqual(planClass(400000), { cls: "B", score: 3 });
  assert.deepEqual(planClass(250000), { cls: "C", score: 2 });
  assert.deepEqual(planClass(249999), { cls: "D", score: 1 });
  assert.deepEqual(planClass(-1), { cls: "D", score: 1 });
});

test("Итоговый балл: веса таблицы, неоценённое не тянет вниз", () => {
  assert.equal(planScore(5, { comp: 5, ads: 5, attract: 5, market: 5, prep: 5 }), 5);
  assert.equal(planScore(1, {}), 1);
  // пример из «Гастрольных планов»: фин 1, реклама 3, привлекательность 2, маркетинг 2, подготовка 3, конкуренция 1
  assert.equal(planScore(1, { comp: 1, ads: 3, attract: 2, market: 2, prep: 3 }), 1.7);
});

test("Запрет повторного показа — 13 месяцев", () => {
  assert.equal(planBanned("2026-04-21", "2027-05-01"), true);
  assert.equal(planBanned("2026-04-21", "2027-05-22"), false);
  assert.equal(planBanned("", "2027-05-01"), false);
  assert.equal(planBanned("2025-09", "2026-11"), false);
});

test("Числа из ввода: пробелы и запятая", () => {
  assert.equal(planNum("1 500 000"), 1500000);
  assert.equal(planNum("2,5"), 2.5);
  assert.equal(planNum(""), 0);
  assert.equal(planNum("abc"), 0);
});

test("Без мест и вала — ТБУ нет, деления на ноль нет", () => {
  const r = planCalc({ fee: 100000 });
  assert.equal(r.beTickets, null);
  assert.equal(r.eff, null);
  assert.equal(r.profit, -100000);
});
