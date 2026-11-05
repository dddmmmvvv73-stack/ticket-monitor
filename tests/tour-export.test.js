const test = require('node:test');
const assert = require('node:assert/strict');
const {PLAN_DEFAULTS,planCalc} = require('../Design/prototype/plan-model.js');
const {tourExportSnapshot,tourExportGroups,tourExportHtml} = require('../Design/prototype/tour-export.js');
const copy = x => JSON.parse(JSON.stringify(x));
const x = {gross:1000000,seats:500,fill:70,fee:100000,cashless:5,per_diem:2000,crew:4,days:2,
  moscow:60000,cities:3,author:5000,rao_on:true,rao:1.5,kassa:5,agent:2,ads:20000,rent:50000,
  venue_services:1000,logistics:10000,org:{services:4000,transfer:5000},
  ad_items:[{name:'Таргет',amount:1200}],cost_items:{variable:[{name:'Доп. комиссия',amount:2.5}],
    project:[{name:'Доплата',amount:500}],org:[{name:'Своя встреча',amount:100}],
    rent:[{name:'Уборка',amount:300}],logistics:[{name:'Багаж',amount:600}]}};
const tour = {title:'Тур <Дедищев>',month:'2027-02',rows:[{id:'r1',city:'Кострома',venue:'Кострома|Первый зал',note:'<script>alert(1)</script>'},
  {id:'r2',city:'Кострома',venue:'Кострома|Второй зал',avg:2000},{id:'r3',city:'Тверь',zmode:true}]};
const meta = {cfg:PLAN_DEFAULTS,project:'Артист',scenario:'По строкам',created:'2026-11-05T12:00:00Z',details:true,zones:true};

test('снимок содержит только выбранные строки, сохраняет площадки, порядок и делитель полного тура', () => {
  const snap = tourExportSnapshot(tour,{...meta,rowIds:['r2','r1']},()=>x);
  assert.deepEqual(snap.rows.map(r=>r.id),['r1','r2']);
  assert.notEqual(snap.rows[0].venue,snap.rows[1].venue);
  assert.equal(snap.rows[0].input.cities,3);
  assert.equal(snap.rows[0].calc.project.moscow,20000);
  assert.equal(snap.rows[0].calc.profit,planCalc(x).profit);
  snap.rows[0].input.org.services=999; assert.equal(x.org.services,4000);
  snap.cfg.tax=99; assert.equal(PLAN_DEFAULTS.tax,2);
  assert.throws(()=>tourExportSnapshot(tour,{...meta,rowIds:[]},()=>x),/нет строк/);
  assert.throws(()=>tourExportSnapshot(tour,{...meta,rowIds:['missing']},()=>x),/нет строк/);
});

test('в расшифровке все группы и свои статьи сходятся с итоговыми расходами, включая процентные', () => {
  const snap=tourExportSnapshot(tour,meta,()=>x),groups=tourExportGroups(snap.rows[0],snap.cfg);
  assert.equal(groups.length,6);
  for(const g of groups) assert.ok(Math.abs(g.sum-g.items.reduce((n,a)=>n+a.sum,0))<1e-6,g.title);
  assert.equal(groups.reduce((n,g)=>n+g.sum,0),snap.rows[0].calc.total);
  assert.ok(groups.find(g=>g.key==='rent').items.some(a=>a.label==='Службы площадки'));
  assert.ok(groups.find(g=>g.key==='org').items.some(a=>a.label==='Службы'));
});

test('PDF содержит сметы каждой площадки, ставки с дробями, экранирует текст и поддерживает сводку без деталей', () => {
  const snap=tourExportSnapshot(tour,{...meta,rowIds:['r1','r2']},()=>x),html=tourExportHtml(snap);
  assert.match(html,/Первый зал/);assert.match(html,/Второй зал/);assert.match(html,/1,5%/);
  assert.match(html,/Своя встреча/);assert.match(html,/ТБУ продаж/);
  assert.ok(!html.includes('<script>alert'));
  assert.match(html,/&lt;script&gt;/);
  snap.options={details:false,zones:false};
  assert.ok(!tourExportHtml(snap).includes('Своя встреча'));
  assert.match(tourExportHtml(snap),/Первый зал/);
});

test('распоясовка учитывает собственные проценты; сценарий использует разрешённые входы без изменения оригинала', () => {
  const input={...copy(x),zones:[{name:'Партер',price:2000,seats:100,fill:50},{name:'Балкон',price:1000,seats:50}]};
  const snap=tourExportSnapshot(tour,{...meta,rowIds:['r3']},()=>input);
  assert.equal(snap.rows[0].mode,'Распоясовка');assert.equal(snap.rows[0].calc.sales,135000);
  assert.match(tourExportHtml(snap),/Партер/);
  const scenario=tourExportSnapshot(tour,{...meta,rowIds:['r3'],scenario:'90%'},()=>({...input,fill:90,zones:input.zones.map(({fill,...z})=>z)}));
  assert.equal(scenario.rows[0].calc.sales,225000);
  assert.equal(input.zones[0].fill,50);
});

test('PDF: средняя цена и вал в сводке, показатели в таблице, итоги групп после расходов', () => {
  const snap=tourExportSnapshot(tour,{...meta,rowIds:['r1']},()=>x),html=tourExportHtml(snap);
  const summary=html.match(/<section class="summary">([\s\S]*?)<\/section>/)[1];
  const heads=Array.from(summary.matchAll(/<th>(.*?)<\/th>/g),m=>m[1]);
  assert.equal(heads[3],'Средняя цена билета, ₽');assert.equal(heads[5],'Вал, ₽');
  const cells=Array.from(summary.match(/<tbody><tr>([\s\S]*?)<\/tr>/)[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g),m=>m[1]);
  assert.equal(cells.length,13);assert.equal(cells[3],(2000).toLocaleString('ru-RU'));
  assert.equal(cells[5],(1000000).toLocaleString('ru-RU'));
  assert.match(html,/<table class="metrics-table"><thead><tr><th>Показатель<\/th><th class="num">Значение<\/th>/);
  assert.ok(!html.includes('<div class="metrics">'));
  const groups=Array.from(html.matchAll(/<tr class="group"><td colspan="3">(.*?)<\/td><\/tr>([\s\S]*?)<tr class="group-total"><td colspan="2">Итого (.*?)<\/td>/g));
  assert.equal(groups.length,6);
  for(const g of groups){assert.equal(g[3],g[1].toLowerCase());assert.ok(g[2].includes('class="num"'));}
  const org=groups.find(g=>g[1]==='Организационные');assert.ok(org[2].includes('Своя встреча'));
  const mixed=tourExportSnapshot(tour,{...meta,rowIds:['r1','r2']},r=>r.id==='r1'?x:{...x,gross:300000,seats:100});
  const footer=tourExportHtml(mixed).match(/<tfoot>([\s\S]*?)<\/tfoot>/)[1];
  assert.ok(footer.includes((1300000).toLocaleString('ru-RU')));
  assert.ok(footer.includes((2167).toLocaleString('ru-RU')),'средняя цена итога взвешена по местам');
});
