// Exercise the imported mockup's actual actions/calculations with a minimal DOM/API adapter.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');

test('goals: creation, all tabs, check-in, habits, tasks, archive, restore and persistence', async () => {
  const els = new Map(), handlers = {}, storage = new Map();
  const el = () => ({innerHTML:'', textContent:'', value:'', open:false, style:{}, classList:{add(){},remove(){},toggle(){}}, showModal(){this.open=true;}, close(){this.open=false;}, focus(){}, select(){}, appendChild(){}, addEventListener(){}, remove(){}, getBoundingClientRect(){return {left:0,bottom:0};}});
  const root = {querySelector(s){if(!els.has(s)) els.set(s,el()); return els.get(s);}, querySelectorAll(){return [];}, getElementById(s){return this.querySelector('#'+s);}, addEventListener(n,f){handlers[n]=f;}, appendChild(){}};
  let Component;
  const db = {projects:{project1:{title:'Проект'}}, tasks:{}, stages:{done:{done:true}}, docs:{doc1:{project:'project1',kind:'Договор',status:'signed'}}, shows:{}, objectives:{}, goalvision:{}};
  const ctx = {console, crypto, Date, Math, JSON, Number, String, Object, Array, Set, Map, Blob, URL, setTimeout(){},clearTimeout(){},
    HTMLElement: class {constructor(){this.isConnected=true;} attachShadow(){this.shadowRoot=root;return root;}},
    customElements:{define(n,c){Component=c;}}, localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    document:{createElement:el}, S:{wk:{}}, wkOpenTask(){}, wkpOpenPage(){},
    fetch:async (url, options) => {if(options && options.method==='POST'){const o=JSON.parse(options.body); db[o.kind] ||= {}; if(o.op==='del') delete db[o.kind][o.id];else db[o.kind][o.id]={...o.data,upd:'2026-10-27T16:00:00'};} return {ok:true,json:async()=>JSON.parse(JSON.stringify(db))};}
  };
  ctx.window=ctx;ctx.addEventListener=()=>{};ctx.scrollTo=()=>{};ctx.render=()=>{};
  const code=fs.readFileSync('Design/prototype/work-goals.js','utf8').replace('model.paint = render;', 'globalThis.goalTest = {model, DB, UI, A, render, openWizard, wzSave, wzSet, get draft(){return WZ.d;}, get ci(){return CI;}, saveCI, syncAuto}; model.paint = render;');
  vm.createContext(ctx);vm.runInContext(code,ctx);new Component().connectedCallback();
  const drain=async()=>{for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));};
  await drain();const t=ctx.goalTest;assert.ok(t, root.querySelector("#main").textContent);
  assert.match(root.querySelector('#main').innerHTML,/Чего хочу добиться/);
  t.openWizard(null);Object.assign(t.draft,{title:'Подготовить большой тур',why:'Увеличить количество гастролей',deadline:'2027-12-31',projects:['project1'],first:'Позвонить площадке',krs:[{id:'k1',title:'Договоры',unit:'шт.',start:0,target:10}],habits:[{id:'h1',title:'Звонки',per:3}],stages:[]});
  t.wzSave();await drain();assert.equal(t.model.error,'');assert.equal(Object.keys(db.objectives).length,1);
  const g=t.DB.goals[0];assert.equal(g.title,'Подготовить большой тур');
  for(const tab of ['ov','plan','hab','an','log']) {t.A.tab({dataset:{t:tab}});assert.ok(root.querySelector('#main').innerHTML.length>100);}
  t.A.checkin({dataset:{id:g.id}});t.ci.vals.k1=4;root.querySelector('#ci-note').value='Есть прогресс';root.querySelector('#ci-next').value='';t.saveCI();await drain();
  assert.equal(db.objectives[g.id].krs[0].cur,4);assert.equal(db.objectives[g.id].checkins.length,1);
  t.A.hstep({dataset:{g:g.id,h:'h1',d:'1'}});await drain();assert.equal(Object.values(db.objectives[g.id].habits[0].log)[0],1);
  const st=g.stages[0],step=st.steps[0];await t.A.totask({dataset:{g:g.id,s:st.id,k:step.id}});await drain();assert.equal(Object.keys(db.tasks).length,1);assert.ok(step.task);
  await t.A.step({dataset:{g:g.id,s:st.id,k:step.id}});await drain();assert.equal(db.tasks[step.task].done,true);
  t.A.drop({dataset:{id:g.id}});await drain();assert.equal(db.objectives[g.id].status,'drop');
  t.A.restore({dataset:{id:g.id}});await drain();assert.equal(db.objectives[g.id].status,'active');
  g.krs[0].auto='docs';t.syncAuto();assert.equal(g.krs[0].cur,1);
  t.A.done({dataset:{id:g.id}});await drain();assert.equal(db.objectives[g.id].status,'done');
  t.A.del({dataset:{id:g.id}});await drain();assert.equal(Object.keys(db.objectives).length,0);assert.equal(t.model.error,'');
});

// 28.10: after a reload nested edits (steps, habits, check-ins) were never sent — the loaded goal shared arrays with the saved copy.
test('goals: edits of a goal loaded from the server reach the server', async () => {
  const els = new Map(), handlers = {}, storage = new Map();
  const el = () => ({innerHTML:'', textContent:'', value:'', open:false, style:{}, classList:{add(){},remove(){},toggle(){}}, showModal(){this.open=true;}, close(){this.open=false;}, focus(){}, select(){}, appendChild(){}, addEventListener(){}, remove(){}, getBoundingClientRect(){return {left:0,bottom:0};}});
  const root = {querySelector(s){if(!els.has(s)) els.set(s,el()); return els.get(s);}, querySelectorAll(){return [];}, getElementById(s){return this.querySelector('#'+s);}, addEventListener(n,f){handlers[n]=f;}, appendChild(){}};
  let Component;
  const goal = {title:'Цель', why:'', sphere:'biz', status:'active', start:'2026-10-28', deadline:'2026-11-30', projects:[],
    krs:[{id:'k1',title:'Мероприятия',unit:'шт.',start:2,target:10,cur:2,auto:''}],
    stages:[{id:'st1',title:'Этап',due:'2026-11-30',steps:[{id:'s1',t:'Шаг',done:false,due:''}]}],
    habits:[{id:'h1',title:'Прозвонить',per:10,log:{}}], checkins:[], upd:'2026-10-28T15:07:50'};
  const db = {projects:{}, tasks:{}, stages:{}, docs:{}, shows:{}, objectives:{g1:goal}, goalvision:{}};
  const ctx = {console, crypto, Date, Math, JSON, Number, String, Object, Array, Set, Map, Blob, URL, setTimeout(){},clearTimeout(){},
    HTMLElement: class {constructor(){this.isConnected=true;} attachShadow(){this.shadowRoot=root;return root;}},
    customElements:{define(n,c){Component=c;}}, localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    document:{createElement:el}, S:{wk:{}}, wkOpenTask(){}, wkpOpenPage(){},
    fetch:async (url, options) => {if(options && options.method==='POST'){const o=JSON.parse(options.body); if(o.op==='del') delete db[o.kind][o.id];else db[o.kind][o.id]={...o.data,upd:'2026-10-29T12:00:00'};} return {ok:true,json:async()=>JSON.parse(JSON.stringify(db))};}
  };
  ctx.window=ctx;ctx.addEventListener=()=>{};ctx.scrollTo=()=>{};ctx.render=()=>{};
  const code=fs.readFileSync('Design/prototype/work-goals.js','utf8').replace('model.paint = render;', 'globalThis.goalTest = {model, DB, A, get ci(){return CI;}, saveCI}; model.paint = render;');
  vm.createContext(ctx);vm.runInContext(code,ctx);new Component().connectedCallback();
  const drain=async()=>{for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));};
  await drain();const t=ctx.goalTest;assert.ok(t, root.querySelector("#main").textContent);
  await t.A.step({dataset:{g:'g1',s:'st1',k:'s1'}});await drain();
  assert.equal(db.objectives.g1.stages[0].steps[0].done,true,'отметка шага');
  root.querySelector('#hb-t').value='Новое действие';root.querySelector('#hb-n').value='3';
  t.A['habit-add']({dataset:{g:'g1'}});await drain();
  assert.equal(db.objectives.g1.habits.length,2,'новое регулярное действие');
  t.A.hstep({dataset:{g:'g1',h:'h1',d:'1'}});await drain();
  assert.equal(Object.values(db.objectives.g1.habits[0].log)[0],1,'«+» регулярного действия');
  t.A.checkin({dataset:{id:'g1'}});t.ci.vals.k1=4;root.querySelector('#ci-note').value='';root.querySelector('#ci-next').value='';t.saveCI();await drain();
  assert.equal(db.objectives.g1.krs[0].cur,4,'отметка прогресса');assert.equal(db.objectives.g1.checkins.length,1);
  assert.equal(t.model.error,'');
});
