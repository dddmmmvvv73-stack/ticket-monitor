const test = require('node:test');
const assert = require('node:assert/strict');
const N = require('../Design/prototype/work-notes.js');

const p = (...content) => ({ type: 'paragraph', content });
const t = (text) => ({ type: 'text', text });
const doc = {
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 1 }, content: [t('Райдер')] },
    p(t('Звук — '), { type: 'text', text: 'свой пульт', marks: [{ type: 'bold' }] }),
    { type: 'taskList', content: [
      { type: 'taskItem', attrs: { checked: true }, content: [p(t('Отправить райдер'))] },
      { type: 'taskItem', attrs: { checked: false }, content: [p(t('Согласовать свет'))] }
    ] },
    { type: 'callout', content: [p(t('Директор в отпуске до 28-го'))] },
    { type: 'table', content: [{ type: 'tableRow', content: [{ type: 'tableHeader', content: [p(t('Город'))] }, { type: 'tableCell', content: [p(t('Владимир'))] }] }] },
    { type: 'image', attrs: { src: '/api/work/file/n1-fdeadbeef.png', file: 'n1-fdeadbeef.png', alt: 'схема.png' } },
    { type: 'fileBlock', attrs: { file: 'n1-fcafebabe.pdf', name: 'договор.pdf', size: 1200 } },
    { type: 'horizontalRule' }
  ]
};

test('текст документа: блоки с новой строки, отметки не мешают, файл — именем', () => {
  assert.equal(N.docText(doc), 'Райдер\nЗвук — свой пульт\nОтправить райдер\nСогласовать свет\nДиректор в отпуске до 28-го\nГород\nВладимир\nдоговор.pdf');
  assert.equal(N.docText(null), '');
  assert.equal(N.docText({}), '');
  assert.ok(N.docText(doc, 5).length < N.docText(doc).length, 'превью — не весь текст');
});

test('значки карточки: чек-лист, картинки, файлы', () => {
  assert.deepEqual(N.docStats(doc), { checks: 2, done: 1, images: 1, files: 1 });
  assert.deepEqual(N.docStats({}), { checks: 0, done: 0, images: 0, files: 0 });
});

test('пустая заметка: только пустые абзацы; линия, таблица, пустой пункт чек-листа — уже не пусто', () => {
  assert.ok(N.docEmpty({}));
  assert.ok(N.docEmpty({ type: 'doc', content: [{ type: 'paragraph' }, p(t('   '))] }));
  assert.ok(!N.docEmpty({ type: 'doc', content: [{ type: 'horizontalRule' }] }));
  assert.ok(!N.docEmpty({ type: 'doc', content: [{ type: 'taskList', content: [{ type: 'taskItem', attrs: { checked: false }, content: [{ type: 'paragraph' }] }] }] }));
  assert.ok(!N.docEmpty({ type: 'doc', content: [{ type: 'image', attrs: { src: 'x' } }] }));
});

test('журнал задачи: новые сверху, при равном времени — по номеру; исходный список не меняется', () => {
  const log = [{ id: 'la', at: '2026-10-20T10:00', text: 'a' }, { id: 'lc', at: '2026-10-22T09:00', text: 'c' }, { id: 'lb', at: '2026-10-22T09:00', text: 'b' }];
  assert.deepEqual(N.logSorted(log).map((e) => e.id), ['lc', 'lb', 'la']);
  assert.equal(log[0].id, 'la');
  assert.deepEqual(N.logSorted(undefined), []);
});

test('время записи: сегодня, вчера (в том числе через границу года), дата, другой год', () => {
  assert.equal(N.stampText('2026-10-22T14:30', '2026-10-22'), 'сегодня, 14:30');
  assert.equal(N.stampText('2026-10-21T09:05', '2026-10-22'), 'вчера, 09:05');
  assert.equal(N.stampText('2025-12-31T23:59', '2026-01-01'), 'вчера, 23:59');
  assert.equal(N.stampText('2026-05-03T11:00', '2026-10-22'), '3 мая, 11:00');
  assert.equal(N.stampText('2025-10-18T11:00', '2026-10-22'), '18 окт 2025, 11:00');
  assert.equal(N.stampText('', '2026-10-22'), '');
});

test('задачи для выбора: только проекта; открытые по сроку, без срока после, готовые в конце', () => {
  const work = {
    projects: { p1: { title: 'Тур' }, p2: { title: 'Другой' } },
    tasks: {
      a: { text: 'Без срока', project: 'p1' }, b: { text: 'Позже', due: '2026-11-01', project: 'p1' },
      c: { text: 'Раньше', due: '2026-10-25', project: 'p1' }, d: { text: 'Сделано', due: '2026-10-01', project: 'p1', done: true },
      e: { text: 'Чужая', project: 'p2' }, f: { text: 'Ничья' }
    }
  };
  assert.deepEqual(N.taskOptions(work, 'p1').map((x) => x.id), ['c', 'b', 'a', 'd']);
  assert.equal(N.taskOptions(work, 'p1').find((x) => x.id === 'd').label, 'Сделано (готово)');
  const all = N.taskOptions(work, '');
  assert.equal(all.length, 6);
  assert.equal(all.find((x) => x.id === 'e').label, 'Чужая · Другой', 'без проекта в заметке — у задачи виден её проект');
});

test('адрес ссылки: сайт без схемы, почта, телефон; чужие схемы — нельзя', () => {
  assert.equal(N.normUrl('kassir.ru/vladimir'), 'https://kassir.ru/vladimir');
  assert.equal(N.normUrl('http://x.ru'), 'http://x.ru');
  assert.equal(N.normUrl('dk@mail.ru'), 'mailto:dk@mail.ru');
  assert.equal(N.normUrl('+7 (900) 123-45-67'), 'tel:+79001234567');
  assert.equal(N.normUrl('javascript:alert(1)'), '');
  assert.equal(N.normUrl('  '), '');
});

test('меню «/»: поиск по-русски и по-английски, «ё» = «е»', () => {
  assert.deepEqual(N.slashItems('чек'), ['todo']);
  assert.deepEqual(N.slashItems('h2'), ['h2']);
  assert.ok(N.slashItems('заголов').length === 3);
  assert.deepEqual(N.slashItems('табл'), ['table']);
  assert.equal(N.slashItems('').length, 13);
  assert.deepEqual(N.slashItems('ёжик'), []);
});

test('картинка или файл: по типу и по расширению', () => {
  assert.ok(N.isImage('скрин.PNG', ''));
  assert.ok(N.isImage('image', 'image/jpeg'));
  assert.ok(!N.isImage('договор.pdf', 'application/pdf'));
  assert.equal(N.sizeText(1536), '2 КБ');
  assert.equal(N.sizeText(2.5 * 1048576), '2,5 МБ');
});
