const test = require('node:test');
const assert = require('node:assert/strict');
const { monthDays, shift, items } = require('../Design/prototype/work-calendar.js');

test('месяц начинается с понедельника; длинный месяц не теряет шестую неделю', () => {
  const days = monthDays('2026-03-21');
  assert.equal(days.length, 42);
  assert.equal(days[0], '2026-02-23');
  assert.equal(days.at(-1), '2026-04-05');
  assert.ok(days.includes('2026-03-31'));
  assert.equal(new Set(days).size, days.length);
});

test('високосный февраль и переход месяца с 31-го числа', () => {
  assert.ok(monthDays('2028-02-01').includes('2028-02-29'));
  assert.equal(shift('2028-01-31', 1), '2028-02-29');
  assert.equal(shift('2027-01-31', 1), '2027-02-28');
  assert.equal(shift('2026-12-31', 1), '2027-01-31');
  assert.equal(shift('2026-01-31', -1), '2025-12-31');
});

test('неделя не теряет дни на границе года и при переводе часов', () => {
  assert.deepEqual(monthDays('2027-01-01', true), ['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02', '2027-01-03']);
  assert.equal(shift('2026-03-27', 1, true), '2026-04-03');
  assert.equal(shift('2026-10-23', 1, true), '2026-10-30');
});

const work = {
  projects: { p1: { title: 'Первый проект', deadline: '2026-10-25' }, p2: { title: 'Второй проект' } },
  tasks: {
    t1: { text: 'Договор', due: '2026-10-21', project: 'p1', tags: ['tag1'], prio: 'high', status: 'work' },
    t2: { text: 'Афиша', due: '2026-10-21', project: 'p2', done: true },
    t3: { text: 'Без срока', project: 'p1' },
    t4: { text: 'Общая задача', due: '2026-10-22', tags: ['deleted'] }
  },
  tags: { tag1: { name: 'Документы', color: 'violet' } },
  shows: { s1: { project: 'p1', date: '2026-10-26', city: 'Тверь', name: 'Дворец культуры' } }
};

test('календарь соединяет задачи, дедлайны и гастроли, не создавая записей и не включая задачи без срока', () => {
  const before = JSON.stringify(work), list = items(work);
  assert.equal(list.length, 5);
  assert.deepEqual(list.map(e => e.key), ['task:t1', 'task:t2', 'task:t4', 'deadline:p1', 'show:s1']);
  assert.equal(list[0].color, 'violet');
  assert.equal(list[1].done, true);
  assert.equal(list[2].color, 'blue');
  assert.equal(JSON.stringify(work), before);
});

test('проект охватывает все типы записей; «без проекта» включает потерянную привязку', () => {
  assert.deepEqual(items(work, { project: 'p1' }).map(e => e.key), ['task:t1', 'deadline:p1', 'show:s1']);
  assert.deepEqual(items(work, { project: 'none' }).map(e => e.key), ['task:t4']);
  const orphan = { ...work, tasks: { lost: { text: 'Задача', due: '2026-10-21', project: 'deleted' } } };
  assert.deepEqual(items(orphan, { project: 'none' }).map(e => e.key), ['task:lost']);
  assert.deepEqual(items(work, { kind: 'show' }).map(e => e.key), ['show:s1']);
  assert.equal(items({}).length, 0);
});

test('статус, приоритет и теги отбирают задачи и работают вместе', () => {
  const keys = f => items(work, f, '2026-10-23').map(e => e.key);
  assert.deepEqual(keys({ project: 'p1', status: 'work', priority: 'high', tag: 'tag1' }), ['task:t1']);
  assert.deepEqual(keys({ status: 'done' }), ['task:t2']);
  assert.deepEqual(keys({ status: 'new' }), ['task:t4']);
  assert.deepEqual(keys({ priority: 'none' }), ['task:t2', 'task:t4']);
  assert.deepEqual(keys({ tag: 'none' }), ['task:t2']);
  assert.deepEqual(keys({ project: 'p1', status: 'done' }), []);
  assert.deepEqual(keys({ kind: 'deadline', status: 'work' }), []);
});

test('просроченные: только незавершённые до сегодняшнего дня; прежний wait соответствует «В работе»', () => {
  assert.deepEqual(items(work, { status: 'over' }, '2026-10-22').map(e => e.key), ['task:t1']);
  assert.deepEqual(items(work, { status: 'over' }, '2026-10-23').map(e => e.key), ['task:t1', 'task:t4']);
  const old = { tasks: { old: { text: 'Ранее ждала ответа', due: '2026-10-21', status: 'wait' } } };
  assert.deepEqual(items(old, { status: 'work' }).map(e => e.key), ['task:old']);
});
