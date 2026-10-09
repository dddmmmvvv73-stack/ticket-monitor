// Тест определения типа проекта по шестиугольному профилю (Design/prototype/project-rating.js).
// Запуск: node --test   (Node находит *.test.js сам)
const test = require("node:test");
const assert = require("node:assert/strict");
const { PT_CONFIG, ptTypeOf, ptValid, ptLabel, ptRadar } = require("../Design/prototype/project-rating.js");

test("конфиг: 6 осей, 6 эталонов, значения 0–3, порог задан", () => {
  assert.equal(PT_CONFIG.axes.length, 6);
  assert.equal(PT_CONFIG.types.length, 6);
  for (const t of PT_CONFIG.types) assert.ok(ptValid(t.v), t.name);
  assert.ok(PT_CONFIG.between > 0);
});

test("каждый эталон определяется сам собой, без «между»", () => {
  for (const t of PT_CONFIG.types) {
    const r = ptTypeOf(t.v);
    assert.equal(r.name, t.name);
    assert.equal(r.d1, 0);
    assert.equal(r.between, null, t.name);
  }
});

test("профиль рядом с эталоном — тот же тип", () => {
  assert.equal(ptTypeOf([3, 3, 3, 1, 1, 2]).name, "Популярный артист");       // ядро фанатов чуть ниже
  assert.equal(ptTypeOf([1, 2, 1, 3, 2, 1]).name, "Новый с потенциалом");      // потенциал чуть ниже
  assert.equal(ptTypeOf([0, 1, 0, 0, 0, 0]).name, "Мёртвый проект");
});

test("близко к двум эталонам — «между X и Y» (по порогу из конфига)", () => {
  const cfg = { between: 0.6, types: [{ name: "А", v: [0, 0, 0, 0, 0, 0] }, { name: "Б", v: [2, 0, 0, 0, 0, 0] }, { name: "В", v: [3, 3, 3, 3, 3, 3] }] };
  const mid = ptTypeOf([1, 0, 0, 0, 0, 0], cfg);   // до А и до Б — одинаково
  assert.ok(mid.between, "должно быть «между»");
  assert.deepEqual([mid.name, mid.between].sort(), ["А", "Б"]);
  assert.match(ptLabel(mid), /^между «/);
  const near = ptTypeOf([0, 0, 0, 0, 0, 0], cfg);   // ровно А, Б дальше на 2 — без «между»
  assert.equal(near.name, "А");
  assert.equal(near.between, null);
  const strict = ptTypeOf([1, 0, 0, 0, 0, 0], Object.assign({}, cfg, { between: 0 }));   // порог 0 — «между» не бывает
  assert.equal(strict.between, null);
});

test("кривой профиль — нет типа", () => {
  for (const bad of [null, [], [1, 2, 3], [1, 2, 3, 4, 0, 0], [1, 1, 1, 1, 1, 1.5], [-1, 0, 0, 0, 0, 0]]) assert.equal(ptTypeOf(bad), null);
  assert.equal(ptLabel(null), "не оценён");
});

test("рисунок: 3 кольца, многоугольник профиля, прошлый — пунктиром", () => {
  const svg = ptRadar([3, 2, 1, 0, 1, 2], { prev: [1, 1, 1, 1, 1, 1] });
  assert.equal((svg.match(/<polygon/g) || []).length, 3 + 1 + 1);
  assert.match(svg, /stroke-dasharray/);
  assert.equal((ptRadar(null).match(/<polygon/g) || []).length, 3);   // без оценки — только кольца
});
