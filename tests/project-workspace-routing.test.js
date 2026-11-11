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
