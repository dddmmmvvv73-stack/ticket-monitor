const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const workspace = fs.readFileSync('Design/prototype/project-workspace.js', 'utf8');
const source = fs.readFileSync('Design/prototype/index.html', 'utf8');

function setup() {
  const project = {title:'Артист',keys:['артист']};
  const ctx = {
    S:{view:'projects',sub:{projects:'all'},m:{tab:'projects',vproj:null,project:null}},
    MYP:{projects:{ptest:project}}, WorkProcesses:{stages:[]},
    document:{addEventListener(){}}, addEventListener(){}, render(){}, scrollTo(){},
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
