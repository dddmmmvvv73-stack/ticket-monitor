// Реальная сверка афиши: пустое поле проекта не должно превращать занятые города в свободные.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Design/prototype/index.html', 'utf8');

function setup() {
  const ctx = {
    MR: [], MA: [], MR_CITY: {}, MK: {cities: ['Занят', 'Недавно', 'Давно', 'Свободен', 'Продюсер']},
    projKey: s => String(s || '').toLowerCase().trim(),
    canonPk: s => s === 'старое название' ? 'артист' : s,
    mRange: () => ['2026-11-11', '2027-11-11'], plCfg: () => ({ban_months: 13}),
    plLL: () => [55, 40], plKm: () => 10, dDiff: () => 0,
    plCityVenues: () => [], tbLogi: () => 'transfer', esc: String,
  };
  vm.createContext(ctx);
  for (const name of ['tbProjectKey', 'tbAfishaNotice', 'tbAnalyze']) {
    const code = source.match(new RegExp('function ' + name + '\\([^]*?\\n}'));
    // tbProjectKey — однострочная функция.
    vm.runInContext(name === 'tbProjectKey' ? source.match(/function tbProjectKey[^\n]+/)[0] : code[0], ctx);
  }
  return ctx;
}
const statuses = a => Object.fromEntries(Array.from(a.rows, r => [r.city, r.st]));

test('без поля проекта ищет точное название подбора; сохраняет сезон, 13 месяцев и приоритет продюсера', () => {
  const c = setup();
  c.MR = [{pk:'артист',city:'Занят',date:'2026-12-01'}, {pk:'артист',city:'Продюсер',date:'2026-12-02'},
    {pk:'другой артист',city:'Свободен',date:'2026-12-03'}, {pk:'артист',city:'Свободен',date:'2028-01-01'}];
  c.MA = [{pk:'артист',city:'Недавно',date:'2025-10-11'}, {pk:'артист',city:'Давно',date:'2025-10-10'}];
  const a = c.tbAnalyze({title:'Артист',rows:[{city:'Продюсер',status:'nodate'}]}, {});
  assert.equal(a.key,'артист'); assert.equal(a.nb,2);
  assert.deepEqual(statuses(a), {Занят:'base',Недавно:'recent',Давно:'free',Свободен:'free',Продюсер:'prod'});
  assert.match(c.tbAfishaNotice({title:'Артист'},a), /2 дат.*3 городов/);
});

test('явно выбранный проект имеет приоритет над названием, пробелы означают пустое поле', () => {
  const c = setup();
  assert.equal(c.tbProjectKey({title:'Артист',project:'Другой'}),'другой');
  assert.equal(c.tbProjectKey({title:'Артист',project:'   '}),'артист');
  c.MR = [{pk:'другой',city:'Занят',date:'2026-12-01'}];
  assert.equal(statuses(c.tbAnalyze({title:'Артист',project:'Другой'},{})).Занят,'base');
});

test('связанное прежнее название в архиве учитывается в запрете повтора', () => {
  const c = setup();
  c.MA = [{pk:'старое название',city:'Недавно',date:'2026-10-01'}];
  assert.equal(statuses(c.tbAnalyze({title:'Артист'},{})).Недавно,'recent');
});

test('нет совпадений: показывает проблему сверки; не подбирает похожего или другого артиста', () => {
  const c = setup();
  c.MR = [{pk:'артист трибьют',city:'Занят',date:'2026-12-01'}, {pk:'артист',city:'Свободен',date:'2026-12-01',offList:true}];
  const a = c.tbAnalyze({title:'Опечатка'},{});
  assert.equal(a.matched,0); assert.ok(a.rows.every(r => r.st === 'free'));
  assert.match(c.tbAfishaNotice({title:'Опечатка'},a), /не найден проект «Опечатка».*не может проверить/);
});

test('совпавшая афиша вне сезона отличается от отсутствия данных', () => {
  const c = setup();
  c.MR = [{pk:'артист',city:'Занят',date:'2028-01-01'}];
  const a = c.tbAnalyze({title:'Артист'},{});
  assert.equal(a.matched,1); assert.equal(a.nb,0);
  assert.doesNotMatch(c.tbAfishaNotice({title:'Артист'},a), /не найден/);
});
