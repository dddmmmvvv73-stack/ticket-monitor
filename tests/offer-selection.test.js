// Проверяем реальные обработчики PDF и ссылки: отбор делается до расчёта итогов документа.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {offerDocBody, offerTotals} = require('../Design/prototype/offer-doc.js');
const source = fs.readFileSync('Design/prototype/index.html', 'utf8');

function setup() {
  const row = (city, reg, dec, profit) => ({city, reg, pick:{dec, o:{}, inp:{src:{price:'ovr'}},
    v:{name:'Зал ' + city}, k:{price:2000, need:1000, status:'ok', margin:0.2,
      r:{seats:500, sales:1000000 + profit, total:1000000, profit, beTickets:250, beShare:0.5}}}});
  const A = {rows:[row('Тверь','Тверская область','yes',100), row('Курск','Курская область','yes',900),
    row('Раменское','Московская область','maybe',200), row('Тюмень','Тюменская область','yes',400),
    row('Не подходит','Московская область','no',800)]};
  const L = {title:'Павел Дедищев', econ:{fee:100000}}, prefs = {}, pdf = [], posted = [], messages = [];
  const ctx = {S:{pl:{tb:{list:'list1'},tbCtx:{A,P:{}}}}, PICK_DEFAULTS:{crew:3,fill:70,kassa:10},
    RU_FD_OF:{'Тверская область':'c','Курская область':'c','Московская область':'c','Тюменская область':'u'},
    plCfg:()=>({tax:6}), plMoney:String, pickRider:()=>0, planNum:Number, periodLabel:()=> 'Ноябрь 2026',
    tbPrefs:()=>prefs, tbCur:()=>L, esc:String, OFFER_CSS:'', TB_PDF_JS:'', location:{origin:'http://test'},
    offerDocBody:(snap,kind,options)=>{pdf.push({snap,kind});return offerDocBody(snap,kind,options);},
    window:{open:()=>({document:{open(){},write(){},close(){}}})},
    apiJson:(method,url,body)=>{posted.push({method,url,body});return Promise.resolve({ok:true,d:{}});},
    toast:s=>messages.push(s), tbSharesLoad(){}, CAN_SAVE:true};
  vm.createContext(ctx);
  for (const name of ['tbOfSel','tbOfPdfCities','tbOfferRows','tbSnapshot','tbOfferDoc','tbShareAction']) {
    const code = source.match(new RegExp('function ' + name + '\\([^]*?\\n}'));
    assert.ok(code, name); vm.runInContext(code[0],ctx);
  }
  return {ctx,A,L,prefs,pdf,posted,messages,selection:ctx.tbOfSel()};
}
const cities = rows => Array.from(rows,r=>r.city);

test('PDF и ссылка руководителю содержат только галочки, включая «на рассмотрении»; итоги по ним же', () => {
  const {ctx,selection,pdf,posted} = setup();
  selection.ck = {'Тверь':1,'Раменское':1};
  ctx.tbOfferDoc('boss'); ctx.tbShareAction('tb-share');
  assert.deepEqual(cities(pdf[0].snap.rows),['Тверь','Раменское']);
  assert.deepEqual(cities(posted[0].body.snapshot.rows),['Тверь','Раменское']);
  assert.equal(offerTotals(pdf[0].snap.rows).profit,300);
  const html = offerDocBody(pdf[0].snap,'boss');
  assert.ok(!html.includes('Курск') && !html.includes('Тюмень'));
  assert.match(html,/Подходит · 1/); assert.match(html,/На рассмотрении · 1/);
  ctx.tbOfferDoc('artist');
  assert.deepEqual(cities(pdf[1].snap.rows),['Тверь']);
});

test('без галочек документы используют выбранные округа; без округов — всё предложение', () => {
  const {ctx,selection,pdf,prefs} = setup();
  selection.fd = {c:1};
  ctx.tbOfferDoc('boss');
  assert.deepEqual(cities(pdf[0].snap.rows),['Курск','Тверь','Раменское']);
  prefs.ofArtMaybe=true; ctx.tbOfferDoc('artist');
  assert.deepEqual(cities(pdf[1].snap.rows),cities(pdf[0].snap.rows));
  selection.fd={}; ctx.tbOfferDoc('boss');
  assert.deepEqual(cities(pdf[2].snap.rows),['Курск','Тверь','Тюмень','Раменское']);
});

test('галочки пересекаются с округами: пустой отбор не превращается в отправку всех городов', () => {
  const {ctx,selection,pdf,posted,messages} = setup();
  selection.ck={'Тверь':1,'Тюмень':1}; selection.fd={c:1};
  ctx.tbOfferDoc('boss');
  assert.deepEqual(cities(pdf[0].snap.rows),['Тверь']);
  selection.ck={'Тюмень':1};
  ctx.tbOfferDoc('boss'); ctx.tbShareAction('tb-share');
  assert.equal(pdf.length,1); assert.equal(posted.length,0); assert.equal(messages.length,2);
  selection.fd={}; selection.ck={'Раменское':1};
  ctx.tbOfferDoc('artist');
  assert.equal(pdf.length,1, 'отмеченный «на рассмотрении» без включения этой группы не выгружает все подходящие');
});
