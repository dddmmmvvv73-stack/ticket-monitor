// Тест подбора городов (Design/prototype/city-pick.js). Запуск: node --test
// Примеры — артисты пользователя из прозвона 26.10 (гонорар, % сверху, состав) и цены нашей афиши.
const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../Design/prototype/plan-model.js");
Object.assign(global, model);   // в браузере plan-model.js и city-pick.js — общие скрипты страницы
const { PICK_DEFAULTS, PICK_ORG, pickTier, pickRider, pickQuantile, pickLevel, pickPrice, pickVenue, pickDec, pickInputs, pickCalc, pickTotals } = require("../Design/prototype/city-pick.js");

const near = (a, b, eps = 0.5) => assert.ok(Math.abs(a - b) <= eps, `${a} ≠ ${b}`);

test("нормы по вместимости и расстоянию", () => {
  assert.equal(pickTier(PICK_DEFAULTS.rent, 400), 80000);
  assert.equal(pickTier(PICK_DEFAULTS.rent, 1000), 150000);
  assert.equal(pickTier(PICK_DEFAULTS.rent, 7651), 500000);
  assert.equal(pickTier(PICK_DEFAULTS.travel, 2300), 25000);
});

test("райдер: от 1 млн — 500 тыс., меньше — половина гонорара, не меньше 100 тыс.", () => {
  assert.equal(pickRider(1500000), 500000);
  assert.equal(pickRider(1000000), 500000);
  assert.equal(pickRider(250000), 130000);   // 125 тыс. → округление до 10 тыс.
  assert.equal(pickRider(120000), 100000);
  assert.equal(pickRider(0), 0);
});

test("процентиль", () => {
  assert.equal(pickQuantile([4000, 2000, 3000, 5000], 0.75), 4250);
  assert.equal(pickQuantile([], 0.75), null);
});

test("цена города: свой город, мало данных — область, совсем нет — null", () => {
  const ev = (a, b) => ({ pmin: a, pmax: b });
  const city = [ev(2500, 5500), ev(2000, 7500), ev(3000, 4000), ev(2500, 6500)];   // середины 4000, 4750, 3500, 4500
  assert.deepEqual(pickPrice(city, []), { price: 4550, base: 4550, k: null, q: 0.75, n: 4, src: "city", conf: "mid" });   // 75-й процентиль 4562,5 → 4550
  const r = pickPrice([ev(2000, 4000)], [ev(1000, 3000), ev(2000, 4000), ev(3000, 5000)]);
  assert.equal(r.src, "region"); assert.equal(r.conf, "low"); assert.equal(r.nCity, 1); assert.equal(r.price, 3500);
  assert.equal(pickPrice([], []), null);
  assert.equal(pickPrice([ev(null, 3000)], []).price, 3000);   // одна цена — берём её, уверенность низкая
});

test("уровень артиста: его цены против рынка; цена города — медиана города × уровень", () => {
  const ev = (a, b) => ({ pmin: a, pmax: b });
  const market = Array.from({ length: 30 }, (_, i) => ev(1000 + i * 100, 4000 + i * 100));   // медиана середин 3 950
  const devyatova = [ev(2000, 4500), ev(1500, 3000), ev(1200, 3000), ev(2400, 4000)];        // середины 3250, 2250, 2100, 3200 → медиана 2725 → 2750
  const lv = pickLevel(devyatova, market);
  assert.equal(lv.k, 0.69); assert.equal(lv.n, 4); assert.equal(lv.price, 2750);
  assert.equal(pickLevel([ev(2000, 4000)], market), null);   // одна дата — уровня нет
  const city = [ev(2500, 5500), ev(2000, 7500), ev(3000, 4000), ev(2500, 6500)];               // середины 4000, 4750, 3500, 4500 → медиана 4250
  const r = pickPrice(city, [], PICK_DEFAULTS, lv.k);
  assert.equal(r.base, 4250); assert.equal(r.price, 2950); assert.equal(r.q, 0.5);           // 4250 × 0,69 = 2932,5 → 2950
});

test("зал для расчёта — самый большой в пределах «от–до»; цирк — только вписанный вручную", () => {
  const vs = [{ name: "Арена", cap: 7651 }, { name: "Филармония", cap: 1076 }, { name: "Клуб", cap: 150 }, { name: "?", cap: null }];
  assert.equal(pickVenue([{ name: "Цирк", cap: 1637 }, { name: "ДК", cap: 900 }], 300, 2500).name, "ДК");
  assert.equal(pickVenue([{ name: "Цирк", cap: 1637, src: "manual" }, { name: "ДК", cap: 900 }], 300, 2500).name, "Цирк");
  assert.equal(pickVenue(vs, 300, 2500).name, "Филармония");
  assert.equal(pickVenue(vs, 300, null).name, "Арена");
  assert.equal(pickVenue(vs, 2000, 5000), null);
});

test("Рондо, Новый Уренгой (576 мест): нормы, нужная цена, статус", () => {
  // гонорар 1,5 млн, состав неизвестен (8), 2 300 км от Москвы, цена города 6 500
  const inp = pickInputs({ fee: 1500000 }, { seats: 576, price: 6500, km: 2300 }, {});
  assert.equal(inp.x.org.tech, 500000); assert.equal(inp.src.rider, "norm");
  assert.equal(inp.x.rent, 150000); assert.equal(inp.x.ads, 150000);
  assert.equal(inp.x.logistics, 8 * 25000); assert.equal(inp.src.crew, "norm");
  const k = pickCalc(inp, PLAN_DEFAULTS);
  // постоянные: 1 500 000 + 500 000 + 150 000 + 200 000 + 150 000 = 2 500 000; переменные: налог 2 + кассы 10 = 12 %
  near(k.r.fixed, 2500000);
  near(k.need, 2500000 / (576 * 0.7 * 0.88), 0.01);   // ≈ 7 046 ₽
  assert.equal(k.status, "edge");   // 6 500 ÷ 7 046 − 1 ≈ −7,7 %
  near(k.r.sales, 6500 * 576 * 0.7, 0.01);
});

test("Дубцова: гонорар 1,2 млн + 13 % — % сверху от гонорара; правки города важнее норм", () => {
  const inp = pickInputs({ fee: 1200000, cashless: 13 }, { seats: 1000, price: 5000, km: 500, venueRent: 200000 }, { fill: 90, ads: 100000 });
  assert.equal(inp.src.rent, "venue"); assert.equal(inp.src.fill, "ovr"); assert.equal(inp.src.ads, "ovr");
  const k = pickCalc(inp, PLAN_DEFAULTS);
  near(k.r.project.cashless, 156000);
  near(k.r.fixed, 1200000 + 156000 + 500000 + 200000 + 8 * 6000 + 100000);
  assert.equal(k.status, "ok");
});

test("Девятова: гонорар 250 тыс., 6 человек — окупается в небольшом зале", () => {
  const inp = pickInputs({ fee: 250000, crew: 6 }, { seats: 400, price: 3000, km: 900 }, {});
  const k = pickCalc(inp, PLAN_DEFAULTS);
  near(k.r.fixed, 250000 + 130000 + 80000 + 6 * 15000 + 80000);
  assert.equal(k.status, "ok");
  assert.ok(k.r.profit > 0);
});

test("нет зала, нет цены, нет гонорара — свой статус", () => {
  assert.equal(pickCalc(pickInputs({ fee: 1e6 }, { price: 5000 }, {}), PLAN_DEFAULTS).status, "nohall");
  assert.equal(pickCalc(pickInputs({ fee: 1e6 }, { seats: 500 }, {}), PLAN_DEFAULTS).status, "noprice");
  assert.equal(pickCalc(pickInputs({}, { seats: 500, price: 5000 }, {}), PLAN_DEFAULTS).status, "nofee");
});

test("итог предложения: московские расходы делятся на число городов", () => {
  const a = pickCalc(pickInputs({ fee: 1e6, moscow: 300000 }, { seats: 1000, price: 5000, km: 500, cities: 3 }, {}), PLAN_DEFAULTS);
  near(a.r.project.moscow, 100000);
  const t = pickTotals([a, a]);
  assert.equal(t.n, 2); near(t.profit, a.r.profit * 2);
});

test("решение по городу: dec; старое «вычеркнут» — «не подходит»", () => {
  assert.equal(pickDec({ dec: "yes" }), "yes");
  assert.equal(pickDec({ x: true }), "no");
  assert.equal(pickDec({ x: true, dec: "maybe" }), "maybe");
  assert.equal(pickDec(null), "");
});

test("правки города: гонорар, %, состав, кассы, агентские, РАО — важнее экономики артиста", () => {
  const inp = pickInputs({ fee: 1500000, cashless: 13, crew: 10 }, { seats: 1000, price: 5000, km: 500 },
    { fee: 1200000, cashless: 0, crew: 6, kassa: 8, agent: 5, rao: 4 });
  const x = inp.x;
  assert.equal(x.fee, 1200000); assert.equal(x.cashless, 0); assert.equal(x.crew, 6); assert.equal(x.logistics, 6 * 6000);
  assert.equal(x.kassa, 8); assert.equal(x.agent, 5); assert.equal(x.rao, 4); assert.equal(x.rao_on, true);
  assert.equal(inp.src.fee, "ovr"); assert.equal(inp.src.cashless, "ovr");
  assert.equal(x.org.tech, 500000);   // райдер — по гонорару города (1,2 млн → 500 тыс.)
  const k = pickCalc(inp, PLAN_DEFAULTS);
  near(k.r.varPct, 2 + 8 + 5 + 4);
});

test("статьи расходов вместо райдера: сумма статей, райдер не учитывается", () => {
  const inp = pickInputs({ fee: 1000000 }, { seats: 800, price: 5000, km: 300 }, { rider: 700000, org: { hotel: 120000, transfer: 40000, tech: "" } });
  assert.deepEqual(inp.x.org, { hotel: 120000, transfer: 40000 });
  assert.equal(inp.src.rider, "org");
  const k = pickCalc(inp, PLAN_DEFAULTS);
  near(k.r.org, 160000);
});

test("распоясовка: места, средняя цена, заполняемость — по поясам; нужная цена — от итогов поясов", () => {
  const zones = [{ name: "Партер", price: 6000, seats: 400 }, { name: "Балкон", price: 3000, seats: 200, fill: 50 }];
  const inp = pickInputs({ fee: 1000000 }, { seats: 900, price: 4000, km: 300 }, { zmode: true, zones: zones, fill: 80 });
  assert.equal(inp.src.price, "zones");
  const k = pickCalc(inp, PLAN_DEFAULTS);
  near(k.r.seats, 600); near(k.r.gross, 3000000); near(k.price, 5000);
  near(k.r.sales, 6000 * 400 * 0.8 + 3000 * 200 * 0.5);   // 2 220 000
  near(k.need, k.r.fixed / (600 * (k.r.fillEff / 100) * 0.88), 0.01);
});

test("суточные всего: вместо ставки × состав; правка города важнее экономики, ставка города — важнее суммы экономики", () => {
  const c = { seats: 800, price: 5000, km: 500 };
  const a = pickCalc(pickInputs({ fee: 1e6, per_diem: 3000, per_diem_sum: 50000 }, c, {}), PLAN_DEFAULTS);
  near(a.r.project.per_diem, 50000);
  const b = pickCalc(pickInputs({ fee: 1e6, per_diem_sum: 50000 }, c, { per_diem_sum: 20000 }), PLAN_DEFAULTS);
  near(b.r.project.per_diem, 20000);
  const d = pickCalc(pickInputs({ fee: 1e6, per_diem_sum: 50000 }, c, { per_diem: 2000, crew: 5 }), PLAN_DEFAULTS);
  near(d.r.project.per_diem, 10000);
  const t = pickCalc(pickInputs({ fee: 1e6 }, c, { target: 300000 }), PLAN_DEFAULTS);
  near(t.r.target, 300000);
});

test("статьи подбора (список пользователя 27.10): все 11 в сумме, в том числе новые — реквизит, гладильщица, сканировка, администратор", () => {
  assert.equal(PICK_ORG.length, 11);
  const org = {}; PICK_ORG.forEach(([k], i) => { org[k] = 1000 * (i + 1); });
  const k = pickCalc(pickInputs({ fee: 1e6 }, { seats: 800, price: 5000, km: 300 }, { org }), PLAN_DEFAULTS);
  near(k.r.org, 1000 * (11 * 12 / 2));
});
