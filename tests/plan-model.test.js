// Тест финансовой модели (Design/prototype/plan-model.js). Запуск: node --test
// Эталон — строки листа «Структура портфеля» Google Таблицы пользователя (12.10.2026): те же входы — те же цифры.
const test = require("node:test");
const assert = require("node:assert/strict");
const { PLAN_DEFAULTS, planCalc, planClass, planScore, planBanned, planNum, planItems, planShift, planSensitivity } = require("../Design/prototype/plan-model.js");

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

test("Распоясовка: вал, места и сборы — по поясам; пустая заполняемость пояса — общий %", () => {
  const zones = [{ name: "VIP", price: 6000, seats: 40, fill: 60 }, { name: "Партер", price: 4500, seats: 180 }, { name: "Балкон", price: 2500, seats: 156, fill: 95 }];
  const r = planCalc({ zones, fill: 80, gross: 999, seats: 1 });   // вал и места площадки не используются
  assert.equal(r.gross, 240000 + 810000 + 390000);
  assert.equal(r.seats, 376);
  near(r.sales, 240000 * 0.6 + 810000 * 0.8 + 390000 * 0.95, 1e-6);
  near(r.avg, 1440000 / 376, 1e-9);
  near(r.fillEff, r.sales / r.gross * 100, 1e-9);
  assert.equal(r.zones[1].own, false);
  assert.equal(r.zones[1].fill, 80);
});

test("Рентабельность продаж и окупаемость затрат", () => {
  const r = planCalc({ gross: 1000000, seats: 500, fill: 100, fee: 600000 });
  // сборы 1 000 000, переменные 2 % = 20 000, постоянные 600 000 → прибыль 380 000
  assert.equal(r.profit, 380000);
  near(r.ros, 0.38, 1e-12);
  near(r.roi, 380000 / 620000, 1e-12);
  assert.equal(planCalc({ fee: 1 }).ros, null);
});

test("Продать, чтобы заработать N: (постоянные + N) ÷ чистая цена билета", () => {
  const r = planCalc({ gross: 1000000, seats: 500, fill: 100, fee: 600000 });   // ср. цена 2 000, после 2 % — 1 960
  near(r.tgTickets, (600000 + 150000) / 1960, 1e-9);        // по умолчанию 150 000
  near(r.tgRub, r.tgTickets * 2000, 1e-6);
  near(r.tgShare, r.tgTickets / 500, 1e-12);
  const r2 = planCalc({ gross: 1000000, seats: 500, fill: 100, fee: 600000, target: 0 });
  near(r2.tgTickets, r2.beTickets, 1e-9);                   // цель 0 — та же точка безубыточности
});

// ---------- Аналитика тура: статьи, сдвиги, чувствительность
const xA = { gross: 1000000, seats: 500, fill: 70, fee: 200000, cashless: 10, per_diem: 2000, crew: 5, days: 2, author: 10000, moscow: 30000, cities: 3,
  org: { transfer: 15000, hotel: 40000 }, rent: 80000, logistics: 50000, ads: 60000, kassa: 8, agent: 5, rao_on: true, rao: 4 };

test("статьи расходов в сумме — все расходы даты", () => {
  const r = planCalc(xA, PLAN_DEFAULTS), items = planItems(r, xA, PLAN_DEFAULTS);
  near(items.reduce((a, i) => a + i.sum, 0), r.total, 0.01);
  near(items.find((i) => i.id === "kassa").sum, r.sales * 0.08, 0.01);
  near(items.find((i) => i.id === "per_diem").sum, 2000 * 5 * 2);
});

test("сдвиги: заполняемость в п.п., цена — ₽ на билет, статья — ₽ на город", () => {
  assert.equal(planShift(xA, "fill", 5).fill, 75);
  assert.equal(planShift(xA, "price", 100).gross, 1000000 + 100 * 500);
  assert.equal(planShift(xA, "rent", -10000).rent, 70000);
  assert.equal(planShift(xA, "org", 5000).org.other, 5000);
  const down = planShift(xA, "org", -11000).org;   // 55 000 → 44 000: статьи в тех же долях
  near(down.transfer + down.hotel, 44000, 0.01); near(down.transfer / down.hotel, 15000 / 40000, 1e-9);
  near(planCalc(planShift(xA, "per_diem", 10000), PLAN_DEFAULTS).project.per_diem, 20000 + 10000);
  assert.equal(xA.fill, 70);   // исходные данные не меняются
});

test("чувствительность: рост аренды на 10 000 ₽ в 2 городах — прибыль −20 000 ₽; самый влиятельный — первым", () => {
  const s = planSensitivity([xA, { ...xA, rent: 50000 }], PLAN_DEFAULTS, { pp: 5, rub_t: 100, rub: 10000, kassa: 1 });
  const rent = s.factors.find((f) => f.id === "rent");
  near(rent.up, -20000); near(rent.down, 20000);
  const m = (f) => Math.max(Math.abs(f.up), Math.abs(f.down));
  assert.ok(s.factors.every((f, i) => i === 0 || m(s.factors[i - 1]) >= m(f)));
});
