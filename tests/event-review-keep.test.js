const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('Design/prototype/event-review.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function setup(){
  const listeners={},timers=new Map(),requests=[],notices=[];let timerId=0,renders=0,applies=0;
  function element(dataset={}){
    const classes=new Set(),attrs={};
    return {dataset,disabled:false,checked:false,innerHTML:'',textContent:'',
      classList:{toggle(k,v){if(v)classes.add(k);else classes.delete(k);},contains:k=>classes.has(k)},
      setAttribute(k,v){attrs[k]=v;},removeAttribute(k){delete attrs[k];},
      hasAttribute(k){return k in attrs;},closest(){return this.row || this;}};
  }
  const inputs=['a','b'].map(id=>{const el=element({erSelect:id});el.row=element();return el;});
  const buttons=['a','b'].flatMap(id=>['keep','local','uninteresting'].map(action=>element({erId:id,erAction:action})));
  const all=element(),scope=element(),batch=element(),progress=element(),snacks={children:[]};
  const document={addEventListener(name,fn){listeners[name]=fn;},getElementById:()=>snacks,
    querySelector(s){return ({'.er-batch':batch,'[data-er-all]':all,'.er-progress':progress})[s] || null;},
    querySelectorAll(s){
      if(s==='[data-er-select]')return inputs;
      if(s==='[data-er-action],[data-er-select],[data-er-scope]')return [...buttons,...inputs,scope];
      return [];
    }};
  const c={document,ON_APP:true,S:{q:''},fetch(url,opts){return new Promise((resolve,reject)=>requests.push({url,opts,resolve,reject}));},
    setTimeout(fn,delay){timers.set(++timerId,{fn,delay});return timerId;},clearTimeout(id){timers.delete(id);},
    render(){renders++;},curApply(){applies++;},toast:s=>notices.push(s),scrollY:0,scrollTo(){}};
  c.window=c;vm.createContext(c);vm.runInContext(source,c);
  const response=(value,ok=true,etag='tag')=>({ok,status:ok?200:409,headers:{get:()=>etag},json:()=>Promise.resolve(value)});
  const data={rev:1,catalogue_version:'catalogue',content_version:'content',server_time:Date.now()/1000,
    groups:['a','b'].map(id=>({id,title:'Проект '+id,kept:false,events:[{keys:[id],city:'Тверь',venue:'ДК',date:'2099-01-01'}]})),
    pending:[],rules:[],deleted:[],kept:0,rule_count:0};
  function click(dataset){
    const el=element(dataset);el.hasAttribute=k=>Object.hasOwn(dataset,k.replace(/^data-/, '').replace(/-([a-z])/g,(_,x)=>x.toUpperCase()));
    listeners.click({target:el,preventDefault(){},stopImmediatePropagation(){}});
  }
  function action(action,id){click({erAction:action,erId:id});}
  function select(id,value){const el=inputs.find(x=>x.dataset.erSelect===id);el.checked=value;el.hasAttribute=k=>k==='data-er-select';listeners.change({target:el});}
  function flush(delay=40){const entry=[...timers].find(([,t])=>t.delay===delay);assert.ok(entry,'expected scheduled work');timers.delete(entry[0]);entry[1].fn();}
  async function ready(){c.EventReview.refresh();requests[0].resolve(response(data));await tick();renders=0;applies=0;}
  const keepButton=id=>buttons.find(b=>b.dataset.erId===id && b.dataset.erAction==='keep');
  return {c,data,requests,buttons,inputs,all,batch,notices,ready,response,action,select,flush,keepButton,
    counts:()=>({renders,applies})};
}

test('задержанное «Оставить» блокирует только свой проект, соседний выбор работает',async()=>{
  const h=setup();await h.ready();h.action('keep','a');h.flush();
  assert.equal(h.keepButton('a').disabled,true);assert.equal(h.keepButton('b').disabled,false);
  assert.equal(h.inputs[1].disabled,false);assert.equal(h.all.disabled,false);
  h.select('b',true);assert.match(h.batch.innerHTML,/Выбрано 1/);
  assert.equal(h.requests.length,2);assert.deepEqual(h.counts(),{renders:0,applies:0});
  h.requests[1].resolve(h.response({ok:true,ids:['a']}));await tick();
  assert.match(h.batch.innerHTML,/Выбрано 1/);assert.equal(h.inputs[1].checked,true);
  assert.equal(h.keepButton('a').classList.contains('kept'),true);
  assert.deepEqual(h.counts(),{renders:0,applies:0});
});

test('следующий проект принимается во время сохранения, повтор своего не отправляется',async()=>{
  const h=setup();await h.ready();h.action('keep','a');h.flush();
  h.action('keep','a');h.action('keep','b');h.flush();
  assert.equal(h.requests.length,2);
  h.requests[1].resolve(h.response({ok:true}));await tick();
  assert.equal(h.requests.length,3);assert.deepEqual(JSON.parse(h.requests[2].opts.body).ids,['b']);
  h.requests[2].resolve(h.response({ok:true}));await tick();
  assert.equal(h.keepButton('b').classList.contains('kept'),true);
  assert.deepEqual(h.counts(),{renders:0,applies:0});
});

test('ошибка не выдаёт проект за сохранённый и не теряет следующий запрос',async()=>{
  const h=setup();await h.ready();h.action('keep','a');h.flush();h.action('keep','b');
  h.requests[1].resolve(h.response({error:'Тестовая ошибка'},false));await tick();
  assert.equal(h.keepButton('a').disabled,false);assert.equal(h.keepButton('a').classList.contains('kept'),false);
  assert.deepEqual(h.notices,['Тестовая ошибка']);assert.equal(h.requests.length,3);
  assert.deepEqual(JSON.parse(h.requests[2].opts.body).ids,['b']);
});

test('сверка решений запрашивает короткий ответ и не перестраивает экран',async()=>{
  const h=setup();await h.ready();h.c.EventReview.refresh();
  assert.match(h.requests[1].url,/catalogue_version=catalogue&deleted_count=0/);
  h.requests[1].resolve(h.response({rev:2,catalogue_version:'catalogue',content_version:'changed',
    kept_ids:['b'],pending:[],server_time:Date.now()/1000,rule_count:0}));await tick();
  assert.equal(h.keepButton('b').classList.contains('kept'),true);
  assert.deepEqual(h.counts(),{renders:0,applies:0});
});

test('быстрые нажатия объединяются в один пакет без повторов',async()=>{
  const h=setup();await h.ready();h.action('keep','a');h.action('keep','b');h.action('keep','a');h.flush();
  assert.equal(h.requests.length,2);
  assert.deepEqual(JSON.parse(h.requests[1].opts.body).ids,['a','b']);
});

test('старый ответ каталога не откатывает уже подтверждённое сохранение',async()=>{
  const h=setup();await h.ready();const stale=JSON.parse(JSON.stringify(h.data));
  h.c.EventReview.refresh();h.action('keep','a');h.flush();
  h.requests[2].resolve(h.response({ok:true}));await tick();
  h.requests[1].resolve(h.response(stale));await tick();
  assert.equal(h.keepButton('a').classList.contains('kept'),true);
  assert.deepEqual(h.counts(),{renders:0,applies:0});
});
