// Тест разбора списка продюсера (Design/prototype/tour-parse.js). Запуск: node --test
// Эталон — список, который прислал пользователь 13.10.2026 («Призрак Оперы»): как есть, с пометками чата и вторым спектаклем.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { tpParse } = require("../Design/prototype/tour-parse.js");

global.MPOP = undefined;
eval(fs.readFileSync(path.join(__dirname, "../Design/prototype/market-pop.js"), "utf8").replace("var MPOP", "global.MPOP"));
const text = fs.readFileSync(path.join(__dirname, "fixtures/producer-list-phantom.txt"), "utf8");
const r = tpParse(text, { cities: Object.keys(global.MPOP), today: "2026-10-13" });
const by = (city, date) => r.rows.find((x) => x.city === city && (!date || x.date === date));

test("название и даты без года — ближайший будущий год", () => {
  assert.equal(r.title, "Призрак Оперы");
  assert.equal(by("Тольятти").date, "2027-02-01");
  assert.equal(by("Тамбов").date, "2027-02-08");
});

test("статусы: под вопросом, без даты, переезд", () => {
  assert.equal(by("Вологда").status, "maybe");
  assert.equal(by("Салехард").status, "maybe");
  assert.equal(by("Старый Оскол").status, "nodate");
  assert.equal(by("Ярославль").status, "transit");
});

test("другой спектакль того же продюсера", () => {
  const s = r.rows.filter((x) => x.city === "Сургут");
  assert.deepEqual(s.map((x) => [x.status, x.time]), [["other", "15:00"], ["ok", "19:00"]]);
  assert.equal(s[0].other, "Летучая Мышь");
});

test("опечатка и район", () => {
  assert.equal(by("Сергиев Посад").fix, "опечатка");
  assert.equal(by("Новосибирск", "2027-01-20").fix, "район");
});

test("заметки без города и служебные строки чата", () => {
  assert.ok(!r.rows.some((x) => /PM/.test(x.line)));
  const notes = r.rows.filter((x) => x.status === "note").map((x) => x.line);
  assert.ok(notes.includes("Апрель Казахстан"));
  assert.ok(notes.includes("2-3 марта - Достроить."));
  assert.equal(by("Краснодар").note, "второй состав");
});

test("все выступления распознаны", () => {
  const shows = r.rows.filter((x) => x.status === "ok" || x.status === "maybe");
  assert.equal(shows.length, 31);   // 9 в феврале, 11 в январе, 9 в марте, 2 — второй состав
  assert.ok(shows.every((x) => x.city && x.date));
});

test("форматы дат: 15.10, 16/10, «Самара — 17 октября»", () => {
  const t = tpParse("15.10 Самара\nСаратов — 17 октября\nЭнгельс 16/10", { cities: ["Самара", "Саратов", "Энгельс"], today: "2026-10-13" });
  assert.deepEqual(t.rows.map((x) => [x.city, x.date, x.status]), [["Самара", "2026-10-15", "ok"], ["Саратов", "2026-10-17", "ok"], ["Энгельс", "2026-10-16", "ok"]]);
});
