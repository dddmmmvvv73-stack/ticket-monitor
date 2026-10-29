const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../Design/prototype/work-processes.js');
test('воронка v2: резерв и отказ вне воронки, «перезвонить» — по дате шага', () => {
  const rows = [{stage:'found'}, {stage:'ready',next_at:'2026-10-28'}, {stage:'approve'}, {stage:'booking',next_at:'2026-10-01'},
    {stage:'reserve',next_at:'2026-10-29'}, {stage:'declined',next_at:'2026-10-01'}, {stage:'discuss',next_at:'2026-11-01'}];
  assert.deepEqual(P.counts(rows,'2026-10-29'), {total:5,due:1,ready:1,approve:1,booking:1,reserve:1,declined:1});
  assert.ok(P.due({stage:'reserve',next_at:'2026-10-29'},'2026-10-29'));   // резерв: «вернуться к вопросу»
  assert.ok(!P.due({stage:'booking',next_at:'2026-10-01'},'2026-10-29') && !P.due({stage:'declined',next_at:'2026-10-01'},'2026-10-29'));
  assert.deepEqual(P.stages.slice(0,8).map(s=>s[0]), ['found','called','discuss','ready','offer','answered','approve','booking']);
});
test('списки «В работе · Резерв · Отказы»', () => {
  assert.ok(P.inList({stage:'called'},'work') && !P.inList({stage:'reserve'},'work') && !P.inList({stage:'declined'},'work'));
  assert.ok(P.inList({stage:'reserve'},'reserve') && P.inList({stage:'declined'},'declined') && !P.inList({stage:'called'},'declined'));
});
test('подсказки не меняют этап: позвонил → «Позвонили», готовы → «обсуждаем с руководителем»', () => {
  const r = {stage:'found',called:true,ready:'yes'};
  assert.deepEqual(P.hints(r), ['called','discuss']); assert.equal(r.stage,'found');
  assert.deepEqual(P.hints({stage:'ready'}, {versions:1}), ['offer']);
  assert.deepEqual(P.hints({stage:'approve',called:true,ready:'yes'}, {versions:1}), []);
});
test('фильтр: пора перезвонить, этап, подбор, карточка проекта', () => {
  const r = {stage:'offer',next_at:'2026-10-01',list:'list1',pj:'pabc'};
  assert.ok(P.matches(r,{show:'due',stage:'offer',list:'yes',pj:'yes'},'2026-10-27'));
  assert.ok(!P.matches(r,{stage:'ready'},'2026-10-27') && !P.matches(r,{list:'no'},'2026-10-27') && !P.matches(r,{pj:'no'},'2026-10-27'));
  assert.ok(!P.matches({...r,next_at:'2026-11-01'},{show:'due'},'2026-10-27'));
  assert.ok(P.matches(r,{},'2026-10-27'));
});
test('сезон — сентябрь…апрель; летом «этот сезон» — ближайший', () => {
  assert.deepEqual(P.season('2026-10-29'), {from:'2026-09-01',to:'2027-04-30',next:{from:'2027-09-01',to:'2028-04-30'}});
  assert.equal(P.season('2027-02-10').from, '2026-09-01');
  assert.equal(P.season('2027-06-10').from, '2027-09-01');
});
