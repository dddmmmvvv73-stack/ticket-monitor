// «Обзор» работы (Design/prototype/work-home.js): правила «Что горит», готовность проектов (пунктир «где должен быть»),
// «В фокусе». Сайтовые функции (wkDay, wkProjects, …) — простые заглушки поверх общего WK, как в index.html.
const test = require('node:test');
const assert = require('node:assert/strict');

const TODAY = '2026-10-26';
const add = (s, n) => { const d = new Date(s + 'T12:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const list = (k) => Object.keys(globalThis.WK[k] || {}).map((id) => Object.assign({ id }, globalThis.WK[k][id]));
Object.assign(globalThis, {
  S: { wk: {} },
  WK_PRIO_RANK: { high: 0, mid: 1, low: 2 },
  wkDay: (off) => add(TODAY, off || 0),
  wkStageDone: (st) => st === 'done',
  wkProjects: () => list('projects'),
  wkTasksOf: (pid) => list('tasks').filter((t) => pid == null || t.project === pid),
  wkDocsOf: (pid) => list('docs').filter((d) => pid == null || d.project === pid),
  wkShowsOf: (pid) => list('shows').filter((d) => d.project === pid),
  wkPname: (id) => (id && globalThis.WK.projects[id] ? globalThis.WK.projects[id].title : ''),
});
const home = require('../Design/prototype/work-home.js');

function setWork(w) { globalThis.WK = Object.assign({ projects: {}, tasks: {}, docs: {}, shows: {}, parties: {}, goals: {}, tags: {} }, w); }

test('«Что горит»: просрочено, сегодня, дедлайн за 7 дней, даты не в продаже, неоплаченный счёт, неподписанный договор', () => {
  setWork({
    projects: { p1: { title: 'Призрак', stage: 'talks', created: '2026-10-20', deadline: '2026-11-01' }, p2: { title: 'Завершённый', stage: 'done', deadline: '2026-10-28' } },
    tasks: { t1: { text: 'Райдер', project: 'p1', due: '2026-10-23' }, t2: { text: 'Позвонить', project: '', due: TODAY }, t3: { text: 'Готовая', project: 'p1', due: '2026-10-20', done: true } },
    shows: { s1: { project: 'p1', date: add(TODAY, 67), city: 'Надым' }, s2: { project: 'p1', date: add(TODAY, 69), city: 'Ноябрьск', sale: 'allowed' },
             s3: { project: 'p1', date: add(TODAY, 70), city: 'Сургут', sale: 'onsale' }, s4: { project: 'p1', date: add(TODAY, 120), city: 'Далеко' } },
    docs: { d1: { project: 'p1', kind: 'Счёт', party: 'ИП', amount: 600000, paid: 100000 }, d2: { project: 'p1', kind: 'Счёт', party: 'ИП', amount: 5, paid: 5 },
            d3: { project: 'p1', kind: 'Договор', party: 'ДК', status: 'wait' }, d4: { project: 'p1', kind: 'Договор', party: 'ЦМИ', status: 'signed' } },
  });
  const f = home.fire();
  assert.deepEqual(f.map((x) => x.k), ['Просрочено · 23 окт', 'Сегодня', 'Дедлайн готовности · 1 ноя', 'Не в продаже · через 67–69 дн.', 'Счёт не оплачен', 'Договоры не подписаны']);
  assert.equal(f[3].t, 'Надым, Ноябрьск');                    // «в продаже» и дальше 90 дней — не горят
  assert.equal(f[4].t.replace(/\s/g, ' '), 'ИП · 500 000 ₽');   // остаток по счёту (в числе — неразрывный пробел); оплаченный не горит
  assert.equal(f[5].t, 'ДК');                                  // подписанный договор не горит
  assert.ok(!f.some((x) => x.t === 'Завершённый'));           // завершённый проект — без дедлайна
});

test('готовность: пунктир — доля прошедшего времени от создания до дедлайна; ниже — «отстаёт»', () => {
  setWork({
    projects: { a: { title: 'Отстаёт', stage: 'talks', created: '2026-10-16', deadline: '2026-11-05' },   // 10 из 20 дней → план 50%
                b: { title: 'Впереди', stage: 'talks', created: '2026-10-16', deadline: '2026-11-05' },
                c: { title: 'Без дедлайна', stage: 'idea', created: '2026-10-20' },
                d: { title: 'Без задач', stage: 'talks', created: '2026-10-01', deadline: '2026-10-30' } },
    tasks: { a1: { project: 'a', text: '1', done: true, done_at: '2026-10-25' }, a2: { project: 'a', text: '2' }, a3: { project: 'a', text: '3' },
             b1: { project: 'b', text: '1', done: true, done_at: '2026-10-01' }, b2: { project: 'b', text: '2', done: true, done_at: '2026-10-25' }, c1: { project: 'c', text: '1' } },
  });
  const r = Object.fromEntries(home.ready().map((x) => [x.p.title, x]));
  assert.equal(r['Отстаёт'].plan, 50); assert.equal(r['Отстаёт'].pct, 33); assert.equal(r['Отстаёт'].behind, true);
  assert.equal(r['Впереди'].pct, 100); assert.equal(r['Впереди'].behind, false); assert.equal(r['Впереди'].week, 50);   // за 7 дней — одна из двух
  assert.equal(r['Без дедлайна'].plan, null); assert.equal(r['Без дедлайна'].behind, false);
  assert.equal(r['Без задач'].behind, false);                 // нечего отставать — не красим
});

test('план не выходит за 0–100%: дедлайн прошёл или проект создан позже сегодняшнего', () => {
  setWork({ projects: { a: { title: 'Прошёл', stage: 'talks', created: '2026-09-01', deadline: '2026-10-01' }, b: { title: 'Будущий', stage: 'talks', created: '2026-10-30', deadline: '2026-11-30' } },
            tasks: { a1: { project: 'a', text: 'x' }, b1: { project: 'b', text: 'y' } } });
  const r = Object.fromEntries(home.ready().map((x) => [x.p.title, x.plan]));
  assert.equal(r['Прошёл'], 100); assert.equal(r['Будущий'], 0);
});

test('«В фокусе»: сегодня — срок сегодня и прошедший; закреплённые; на неделе — следующие 7 дней; готовые не попадают', () => {
  setWork({ tasks: {
    t1: { text: 'Просрочена', due: '2026-10-20', prio: 'low' }, t2: { text: 'Сегодня важная', due: TODAY, prio: 'high' }, t3: { text: 'Сегодня', due: TODAY, prio: 'mid' },
    t4: { text: 'Через 3 дня', due: add(TODAY, 3), pin: true }, t5: { text: 'Через 8 дней', due: add(TODAY, 8) }, t6: { text: 'Готова', due: TODAY, done: true, pin: true },
    t7: { text: 'Без срока', pin: true } } });
  assert.deepEqual(home.focusList('today').map((t) => t.text), ['Просрочена', 'Сегодня важная', 'Сегодня']);
  assert.deepEqual(home.focusList('week').map((t) => t.text), ['Через 3 дня']);
  assert.deepEqual(home.focusList('pin').map((t) => t.text), ['Через 3 дня', 'Без срока']);
});

test('цели месяца — только выбранного месяца, по порядку', () => {
  setWork({ goals: { g1: { month: '2026-10', text: 'Вторая', order: 2 }, g2: { month: '2026-10', text: 'Первая', order: 1 }, g3: { month: '2026-11', text: 'Ноябрь', order: 1 } } });
  assert.deepEqual(home.goals('2026-10').map((g) => g.text), ['Первая', 'Вторая']);
  assert.deepEqual(home.goals('2026-12'), []);
});
