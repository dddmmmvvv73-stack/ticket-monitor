// Тест документов предложения (Design/prototype/offer-doc.js). Запуск: node --test
const test = require("node:test");
const assert = require("node:assert/strict");
const { offerTotals, offerDocBody } = require("../Design/prototype/offer-doc.js");

const snap = {
  who: "Группа Рондо", period: "ноябрь 2026", created: "2026-10-26T16:00:00+03:00",
  econ: [["Гонорар", "1 500 000 ₽"]],
  rows: [
    { city: "Калининград", reg: "Калининградская область", dec: "yes", venue: "Янтарь-холл", seats: 1667, price: 5800, need: 2600, sales: 6768020, total: 3482162, profit: 3285858, be: 523.1, beShare: 0.31, status: "ok", margin: 1.23 },
    { city: "Курган", reg: "Курганская область", dec: "yes", venue: "Филармония", seats: 600, price: 3000, priceNote: "мало данных", need: 4000, sales: 1260000, total: 1500000, profit: -240000, be: 700, beShare: 1.1, status: "no", margin: -0.25 },
    { city: "Тула", reg: "Тульская область", dec: "maybe", venue: "", seats: 0, price: 4000, status: "nohall" }
  ]
};

test("итоги — только города с расчётом", () => {
  const t = offerTotals(snap.rows);
  assert.equal(t.n, 3); assert.equal(t.ok, 1); assert.equal(t.no, 1); assert.equal(t.profit, 3285858 - 240000);
});

test("артисту — только «подходит», без экономики; с флажком — и «на рассмотрении»", () => {
  const a = offerDocBody(snap, "artist");
  assert.ok(a.includes("Калининград") && a.includes("Курган") && !a.includes("Тула"));
  assert.ok(!a.includes("Прибыль") && !a.includes("5 800"));
  assert.ok(offerDocBody(snap, "artist", { maybe: true }).includes("Тула"));
});

test("руководителю — обе группы, риски, экранирование; страница ссылки — места под комментарии", () => {
  const b = offerDocBody(Object.assign({}, snap, { who: "<b>x</b>" }), "boss");
  assert.ok(b.includes("Подходит · 2") && b.includes("На рассмотрении · 1"));
  assert.ok(b.includes("Мало данных о ценах") && b.includes("Курган") && b.includes("не посчитано: Тула"));
  assert.ok(b.includes("&lt;b&gt;x&lt;/b&gt;") && !b.includes("<b>x</b>"));
  const s = offerDocBody(snap, "boss", { share: true });
  assert.ok(s.includes('data-mgr="Калининград"') && s.includes('data-mgr=""') && !s.includes("contenteditable"));
  assert.ok(s.includes('class="cc"') && !s.includes("<table"));   // на странице ссылки — карточки, не широкая таблица
});
