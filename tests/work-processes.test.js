const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../Design/prototype/work-processes.js');
test('воронка: отказ не входит в активную, ждут предложения и решения считаются по этапам', () => {
  assert.deepEqual(P.counts([{stage:'found'}, {stage:'ready',called:true}, {stage:'decided',called:true}, {stage:'declined',called:true}]), {total:3,called:3,ready:1,offer:0,decided:1});
});
test('подсказки не меняют этап и не предлагают возврат назад', () => {
  const r = {stage:'found',called:true,ready:'yes'};
  assert.deepEqual(P.hints(r), ['called','ready']); assert.equal(r.stage,'found');
  assert.deepEqual(P.hints({stage:'ready'}, {versions:1}), ['offer']);
  assert.deepEqual(P.hints({stage:'decided',called:true,ready:'yes'}, {versions:1}), []);
});
test('фильтры объединяются; закрытые записи не просрочены', () => {
  const r = {stage:'ready',called:true,ready:'yes',next_at:'2026-10-01',list:'list1'};
  assert.ok(P.matches(r,{called:'yes',ready:'yes',list:'yes',over:true},'2026-10-27'));
  assert.ok(!P.matches(r,{season:'next'},'2026-10-27'));
  assert.ok(P.matches(r,{season:'empty'},'2026-10-27'));
  assert.ok(!P.matches({...r,stage:'decided'},{over:true},'2026-10-27'));
});
