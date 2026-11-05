const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Design/prototype/index.html', 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function setup() {
  const row = {id:'r1',city:'Кострома',venue:'Кострома|Первый зал',date:'2027-02-12',
    days:2,fill:70,ads:50000,agent:0,avg:1800,target:450,note:'Позвонить после обеда',
    decision:'Подходит',last_show:'2025-01-01',cannibal:false,region_ban:true,scores:{demand:4},
    zmode:true,zones:[{name:'Партер',seats:500,price:2000,fill:75}],
    ovr:{rent:90000,venue_services:0,services:4000,gross:1000000},
    ad_items:[{name:'Афиши',amount:5000}],
    cost_items:{variable:[{name:'Комиссия',amount:1.5}],org:[{name:'Встреча',amount:800}]}};
  const tour = {title:'Февраль',project:'p1',rows:[row,{id:'r2',city:'Ярославль'}]};
  const posted = [], messages = [], pending = [], state = {pl:{tour:'t1',row:null}};
  const ctx = {S:state,PLAN:{tours:{t1:tour}},toast:s=>messages.push(s),
    wkPopClose(){},closeDrawer(){},tbRe(){},setTimeout(){},plId:()=> 'rcopy',
    plPut:(kind,id,data)=>{ctx.PLAN[kind][id]=data;posted.push({kind,id,data});},
    askConfirm:(title,text,label,fn)=>pending.push(fn)};
  vm.createContext(ctx);
  for (const name of ['plCloneTourRow','plRowSelection','plAction']) {
    const match = source.match(new RegExp('function ' + name + '\\([^]*?\\n}'));
    assert.ok(match,name); vm.runInContext(match[0],ctx);
  }
  const action = (name,id) => ctx.plAction({getAttribute:key=>key==='data-pl'?name:key==='data-id'?id:null});
  return {ctx,tour,row,state,posted,messages,pending,action};
}

test('копия вставляется под исходной строкой и сохраняет все вложенные данные независимо от оригинала', () => {
  const {ctx,tour,row,action,posted,state} = setup(), before = plain(tour);
  action('row-copy','r1');
  const result = posted[0].data;
  assert.deepEqual(Array.from(result.rows,r=>r.id),['r1','rcopy','r2']);
  assert.deepEqual(plain(result.rows[1]),{...plain(row),id:'rcopy'});
  assert.deepEqual(tour,before);
  assert.equal(state.pl.row,'rcopy');
  result.rows[1].zones[0].price=5000; result.rows[1].ovr.rent=0;
  result.rows[1].ad_items[0].name='Новое'; result.rows[1].cost_items.org[0].amount=9000;
  assert.deepEqual(plain(result.rows[0]),before.rows[0]);
  assert.deepEqual(tour,before);
});

test('отсутствующая строка, повторный id и лимит 300 не создают повреждённую копию', () => {
  const {ctx,tour,posted,action,messages} = setup();
  assert.throws(()=>ctx.plCloneTourRow(tour,'missing','r3'),/не найдена/);
  for (const id of ['r1','r2','bad-id','']) assert.throws(()=>ctx.plCloneTourRow(tour,'r1',id),/номер копии/);
  tour.rows=Array.from({length:300},(_,i)=>({id:'r'+i,city:'Город'}));
  action('row-copy','r1'); assert.equal(posted.length,0); assert.match(messages[0],/300/);
});

test('выделение не сохраняется в тур, отмена не удаляет строки, подтверждение учитывает свежие правки', () => {
  const {ctx,action,pending,posted,state} = setup();
  action('row-select','r1'); action('row-select','r2');
  assert.equal(posted.length,0);
  action('rows-delete'); assert.equal(posted.length,0); // Пока диалог не подтверждён, данные прежние.
  assert.equal(ctx.PLAN.tours.t1.rows.length,2);
  action('rows-unselect'); assert.equal(state.pl.rowSelection.active,false);
  action('row-select','r1'); action('rows-delete');
  ctx.PLAN.tours.t1.rows[1].note='Правка после открытия подтверждения';
  ctx.PLAN.tours.t1.rows.push({id:'r3',city:'Тверь'});
  pending[1]();
  assert.deepEqual(Array.from(ctx.PLAN.tours.t1.rows,r=>r.id),['r2','r3']);
  assert.equal(ctx.PLAN.tours.t1.rows[0].note,'Правка после открытия подтверждения');
  assert.equal(state.pl.rowSelection.active,false);
  assert.ok(!JSON.stringify(posted[0].data).includes('rowSelection'));
});

test('выделение сбрасывается в другом туре и очищается для удалённых строк', () => {
  const {ctx,tour} = setup();
  const selection = ctx.plRowSelection(tour,'t1'); selection.ids={r1:true,missing:true};
  assert.deepEqual(plain(ctx.plRowSelection(tour,'t1').ids),{r1:true});
  assert.deepEqual(plain(ctx.plRowSelection({rows:[{id:'r1'}]},'t2').ids),{});
});
