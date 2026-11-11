const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const workspace = fs.readFileSync('Design/prototype/project-workspace.js', 'utf8');
const source = fs.readFileSync('Design/prototype/index.html', 'utf8');

function setup() {
  const project = {title:'Артист',keys:['артист']};
  const events={};
  const ctx = {
    S:{view:'projects',sub:{projects:'all'},m:{tab:'projects',vproj:null,project:null}},
    MYP:{projects:{ptest:project}}, WorkProcesses:{stages:[]},
    document:{addEventListener(name,handler){(events[name] ||= []).push(handler);}}, events, addEventListener(){}, render(){}, scrollTo(){}, scrollY:0,
    myRec:k => k === 'артист' ? project : null, myFind:k => k === 'артист' ? 'ptest' : null,
    REP_SUB:{projects:'all',touring:'tour',favorites:'fav'}, REP_VIEW:{all:'projects',tour:'touring',fav:'favorites'},
    TAB_VIEW:{projects:['projects'],table:['events','market']},
    location:{hash:'#projectbase'}, history:{replaceState(){throw Error('Must not redirect the workspace');}},
    mTabOf:view => ['projects','touring','favorites'].includes(view) ? 'projects' : null,
  };
  ctx.window=ctx; vm.createContext(ctx); vm.runInContext(workspace,ctx);
  vm.runInContext(source.match(/function syncMarketView\([^]*?\n}/)[0],ctx);
  return ctx;
}

test('рабочая база — отдельный раздел; прежние три страницы не перехватываются', () => {
  const c=setup();
  for (const view of ['projects','touring','favorites','events']) {
    c.S.view=view; assert.equal(c.ProjectWorkspace.active(),false); assert.equal(c.ProjectWorkspace.hash(),null);
  }
  c.S.view='projectbase'; assert.equal(c.ProjectWorkspace.active(),true);
});

// Загружаем настоящий делегированный обработчик #view: тест должен ловить ранний выход по isM().
function clickHarness() {
  const c=setup(), clicks=[], fav=[], drawers=[];
  Object.assign(c,{$:()=>({addEventListener:(name,handler)=>{if(name==='click')clicks.push(handler);}}),
    isM:()=>['projects','touring','favorites','events'].includes(c.S.view),closeDrawer(){},
    myToggleFav:(...args)=>fav.push(args),openMDrawer:id=>drawers.push(id)});
  vm.runInContext(source.match(/function pjSharedAction\([^]*?\n}/)[0],c);
  const start=source.indexOf('$("view").addEventListener("click", function (ev) {\n  if (ev.target.closest(".resizer")');
  assert.ok(start>=0);
  const end=source.indexOf('$("view").addEventListener("change", function (ev)',start);
  vm.runInContext(source.slice(start,end),c);
  function click(attrs,anchor=false) {
    const button={getAttribute:k=>attrs[k]??null,hasAttribute:k=>Object.hasOwn(attrs,k)};
    const target={closest(selector){
      if(selector==='a')return anchor?button:null;
      if(selector==='.resizer')return null;
      return [...selector.matchAll(/\[([^=\]]+)/g)].some(m=>Object.hasOwn(attrs,m[1]))?button:null;
    }};
    clicks.forEach(handler=>handler({target}));
  }
  return {c,click,fav,drawers};
}

test('нажатия верхней кнопки и возврата работают в базе, сохраняя выбранную вкладку', () => {
  const {c,click}=clickHarness(); c.ProjectWorkspace.open('артист','work');
  click({'data-proute':'артист'});
  assert.equal(c.ProjectWorkspace.hash(),'projectbase:analysis:ptest:route');
  assert.equal(c.S.m.anFrom,'артист');
  click({'data-vopen':'артист'});
  assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:work');
  click({'data-proute':'артист'}); c.S.m.anFrom=null;
  click({'data-maction':'proj-back'});
  assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:work');
  click({'data-maction':'vproj-back'});
  assert.equal(c.ProjectWorkspace.hash(),null); assert.equal(c.S.view,'projectbase'); assert.equal(c.S.m.vproj,null);
});

test('раскрытие дат, избранное и переход к мероприятию обрабатываются один раз в обоих разделах', () => {
  for(const view of ['projectbase','projects']) {
    const {c,click,fav,drawers}=clickHarness(); c.S.view=view;
    click({'data-maction':'dates-all'}); assert.equal(c.S.m.datesAll,true);
    click({'data-maction':'cand-all'}); assert.equal(c.S.m.candAll,true);
    click({'data-fav':'артист','data-title':'Артист'}); assert.deepEqual(fav,[['артист','Артист']]);
    click({'data-mopen':'12'}); assert.deepEqual(drawers,[12]);
    click({'data-fav':'артист'},true); assert.equal(fav.length,1);
  }
});

test('команды карточки прежних «Проектов» сохраняют переход в аналитику и обратно', () => {
  const {c,click}=clickHarness(); c.S.m.vproj='артист';
  click({'data-proute':'артист'}); assert.equal(c.S.sub.projects,'tour'); assert.equal(c.S.m.project,'артист');
  click({'data-vopen':'артист'}); assert.equal(c.S.sub.projects,'all'); assert.equal(c.S.m.vproj,'артист');
});

test('открытие карточки не разрешает командам фильтров рынка менять базу', () => {
  const {c,click}=clickHarness(); c.ProjectWorkspace.open('артист'); c.S.q='свой поиск';
  click({'data-maction':'all-reset'}); click({'data-mtab':'table'}); click({'data-mset':'format','data-mval':'Другое'});
  assert.equal(c.S.view,'projectbase'); assert.equal(c.S.q,'свой поиск'); assert.equal(c.S.m.format,undefined);
});

test('«Разобрать» открывает выбранный город и окно дат из аналитики базы', () => {
  const {c,click}=clickHarness(); c.ProjectWorkspace.openAnalysis('артист','cands');
  c.mGo=patch=>Object.assign(c.S.m,patch);
  click({'data-mcity-go':'Тверь','data-from':'2027-01-02','data-to':'2027-01-09','data-fmt':'Концерт','data-genre':'Поп'});
  assert.equal(c.S.view,'city'); assert.equal(c.S.m.city,'Тверь'); assert.equal(c.S.from,'2027-01-02'); assert.equal(c.S.to,'2027-01-09');
});

test('конкуренты и цены базы не зависят от пустого или отфильтрованного кэша афиши', () => {
  const c=setup();
  const addDays=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*864e5).toISOString().slice(0,10);
  Object.assign(c,{TODAY:'2026-11-11',MRV_CITY:{},MK:{cities:['A','B','C']},addDays,
    daysList:(a,b)=>{const out=[];for(let d=a;d<=b;d=addDays(d,1))out.push(d);return out;},
    fmtSphere:()=>'Музыка',human:String,dDiff:(a,b)=>(Date.parse(b)-Date.parse(a))/864e5,
    geoKm:(a,b)=>a===b?0:([a,b].includes('C')?100:200),bestDates:()=>[],
    median:arr=>arr.length?arr.slice().sort((a,b)=>a-b)[Math.floor(arr.length/2)]:null});
  for(const name of ['mComp','mCandidates'])vm.runInContext(source.match(new RegExp('function '+name+'\\([^]*?\\n}'))[0],c);
  const p={l:[{city:'A',date:'2027-01-01'},{city:'B',date:'2027-01-10'}],cities:['A','B'],format:'Концерт',marketCities:{C:[
    {date:'2027-01-04',format:'Концерт',sphere:'Музыка',pmin:2000},
    {date:'2027-01-20',format:'Концерт',sphere:'Музыка',pmin:3000}]}};
  const row=c.mCandidates(p)[0]; assert.equal(row.events,2); assert.equal(row.price,3000); assert.equal(row.sameN,1);
  const old=c.mCandidates({...p,marketCities:undefined})[0]; assert.equal(old.events,0); assert.equal(old.price,null);
  assert.deepEqual(c.MRV_CITY,{});
});

test('связанное название использует тот же проект и локальный период при входе и возврате', () => {
  const {c,click}=clickHarness(); c.MYP.projects.ptest.keys.push('другое название');
  c.myRec=k=>c.MYP.projects.ptest.keys.includes(k)?c.MYP.projects.ptest:null;
  c.myFind=k=>c.myRec(k)?'ptest':null;
  c.ProjectWorkspace.open('артист','dates');
  c.events.change.forEach(handler=>handler({target:{hasAttribute:k=>k==='data-pw-date',dataset:{pwDate:'from'},value:'2027-01-01'}}));
  click({'data-proute':'другое название'});
  assert.equal(c.S.m.project,'артист'); assert.equal(c.ProjectWorkspace.inPeriod({date:'2026-12-01'}),false);
  assert.equal(c.ProjectWorkspace.inPeriod({date:'2027-02-01'}),true);
  click({'data-vopen':'другое название'});
  assert.equal(c.S.m.vproj,'артист'); assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:dates');
  assert.equal(c.ProjectWorkspace.inPeriod({date:'2026-12-01'}),false);
});

test('карточка и обратные ссылки открывают базу; синхронизация рынка не уводит в старый раздел', () => {
  const c=setup(); c.S.mTabSeen='table'; c.ProjectWorkspace.open('артист','work');
  c.syncMarketView();
  assert.equal(c.S.view,'projectbase'); assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:work');
  assert.equal(c.S.mTabSeen,'projects');
  c.S.view='projects'; c.S.m.vproj=null; c.syncMarketView();
  assert.equal(c.S.view,'projects'); assert.equal(c.ProjectWorkspace.active(),false);
});

test('новые и ранее сохранённые адреса карточек ведут в отдельную базу', () => {
  for (const view of ['projectbase','projects']) {
    const c=setup();
    assert.equal(c.ProjectWorkspace.fromHash([view,'card','ptest','dates']),true);
    assert.equal(c.S.view,'projectbase'); assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:dates');
  }
  const c=setup(); assert.equal(c.ProjectWorkspace.fromHash(['projects']),false);
  assert.equal(c.S.view,'projects');
});

test('возврат по адресу списка закрывает карточку; адрес вкладки сохраняет нужную вкладку', () => {
  const c=setup(); c.VIEWS=['projects','projectbase']; c.SUBS={}; c.closeDrawer=()=>{};
  c.addEventListener=(name,handler)=>{if(name==='hashchange') c.hashchange=handler;};
  for (const name of ['repReset','viewHash','fromHash']) {
    const code=name==='repReset'||name==='viewHash' ? source.match(new RegExp('function '+name+'[^\\n]+'))[0]
      : source.match(new RegExp('function '+name+'\\([^]*?\\n}'))[0];
    vm.runInContext(code,c);
  }
  vm.runInContext(source.match(/window.addEventListener\("hashchange", function \(\) \{[^]*?\n\}\);/)[0],c);
  c.ProjectWorkspace.open('артист','work'); c.location.hash='#projectbase'; c.hashchange();
  assert.equal(c.S.m.vproj,null); assert.equal(c.S.view,'projectbase');
  c.location.hash='#projectbase:card:ptest:dates'; c.hashchange();
  assert.equal(c.ProjectWorkspace.hash(),'projectbase:card:ptest:dates');
});

test('все новые вкладки находятся после «О проекте», сохраняя прежние обложку и мероприятия', () => {
  const c=setup(); Object.assign(c,{esc:String,WK:{leads:{},projects:{}},PLAN:{lists:{},tours:{}},AN_TABS:[['route','Маршрут'],['site','Официальный сайт']]});
  const o={k:'артист',id:'ptest',rec:c.MYP.projects.ptest,title:'Артист',l:[{}],past:[],
    hero:'<section class="pj-hero">ORIGINAL COVER</section>',list:'ORIGINAL EVENTS',aside:'<section>ORIGINAL ABOUT</section>'};
  for (const tab of ['profile','dates','analysis','work']) {
    c.ProjectWorkspace.open('артист',tab);
    const html=c.ProjectWorkspace.card(o);
    assert.ok(html.startsWith(o.hero));
    assert.match(html,/<div class="pj-main">ORIGINAL EVENTS<\/div>/);
    assert.ok(html.indexOf('ORIGINAL ABOUT') < html.indexOf('pw-side-tools'));
    assert.ok(html.indexOf('pw-side-tools') < html.indexOf('role="tablist"'));
    assert.doesNotMatch(html,/class="pw-hero"/);
  }
});

test('подробная аналитика имеет свой адрес и открывается после перезагрузки', () => {
  const c=setup(); c.ProjectWorkspace.openAnalysis('артист','site');
  assert.equal(c.ProjectWorkspace.hash(),'projectbase:analysis:ptest:site');
  const fresh=setup(); fresh.MY_READY=true; fresh.mProjectDetail=k=>'ANALYSIS:'+k;
  assert.equal(fresh.ProjectWorkspace.fromHash(['projectbase','analysis','ptest','site']),true);
  assert.equal(fresh.ProjectWorkspace.hash(),'projectbase:analysis:ptest:site');
  assert.equal(fresh.ProjectWorkspace.render(),'ANALYSIS:артист');
  assert.equal(fresh.S.m.anTab,'site');
  assert.equal(fresh.ProjectWorkspace.hash(),'projectbase:analysis:ptest:site');
});

test('пустая аналитика возвращает понятное состояние карточки с согласованным адресом', () => {
  const c=setup(); c.ProjectWorkspace.openAnalysis('артист');
  c.history.replaceState=(_state,_title,url)=>{c.location.hash=url;};
  c.mShowcaseDetail=k=>'EMPTY CARD:'+k;
  assert.equal(c.ProjectWorkspace.emptyAnalysis('артист'),'EMPTY CARD:артист');
  assert.equal(c.location.hash,'#'+c.ProjectWorkspace.hash());
  Object.assign(c,{esc:String,AN_TABS:[['site','Официальный сайт']],siteSection:()=>'<div>SITE FORM</div>'});
  const html=c.ProjectWorkspace.card({k:'артист',id:'ptest',rec:c.MYP.projects.ptest,title:'Артист',l:[],past:[],hero:'HERO',list:'EVENTS',aside:'ABOUT'});
  assert.match(html,/role="status"/); assert.match(html,/В афише пока нет мероприятий/); assert.match(html,/SITE FORM/);
});
