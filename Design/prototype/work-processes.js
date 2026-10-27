// Постоянные процессы и CRM поиска проектов (PROCESSES_PLAN.md, решения 27.10).
// Задачи/календарь/фокус/заметки используют существующие компоненты проекта через область proc:<id>.
(function (root) {
  'use strict';
  var stages = [['found','На входе'],['called','Позвонили'],['ready','Готовы, ждут предложения'],['offer','Получили предложение'],['answered','Ответили на предложение'],['decided','Решение'],['declined','Не готовы / отказ']];
  var ready = [['','—'],['yes','Да'],['no','Нет']], season = [['','—'],['this','Этот сезон'],['next','Следующий сезон']];
  function counts(rows) { var n = {total:0,called:0,ready:0,offer:0,decided:0}; rows.forEach(function (r) { if(r.stage !== 'declined') n.total++; if(r.called) n.called++; if(r.stage in n && r.stage !== 'called') n[r.stage]++; }); return n; }
  function hints(r, sh) { var a=[]; if(r.stage === 'found' && r.called) a.push('called'); if(r.ready === 'yes' && ['found','called'].indexOf(r.stage)>=0) a.push('ready'); if(sh && sh.versions && ['ready'].indexOf(r.stage)>=0) a.push('offer'); return a; }
  function matches(r, f, today) { return (!f.stage || r.stage===f.stage) && (!f.called || r.called===(f.called==='yes')) && (!f.ready || (r.ready||'empty')===f.ready) && (!f.season || (r.season||'empty')===f.season) && (!f.list || !!r.list===(f.list==='yes')) && (!f.over || !!r.next_at && r.next_at<today && r.stage!=='decided' && r.stage!=='declined'); }
  var api={stages:stages, counts:counts, hints:hints, matches:matches};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  root.WorkProcesses=api;
  if(typeof document==='undefined') return;
  var state={id:null,tab:'funnel',mode:'table',q:'',filters:{},lead:null,init:false}, queue=Promise.resolve();
  function records(k) { return Object.keys(WK[k]||{}).map(function(id){return Object.assign({id:id},WK[k][id]);}); }
  function leads(id) { return records('leads').filter(function(r){return (r.proc||'')===id;}); }
  function label(v) { return wkLabel(stages,v); }
  function action(a,text,id,cls) {
    var attrs='';
    if(a==='tasks'||a==='funnel'){cls='proc-tab';attrs=' role="tab" aria-selected="'+(state.tab===a)+'"';}
    if(a==='table'||a==='board'){cls='proc-view';attrs=' aria-pressed="'+(state.mode===a)+'"';}
    return '<button type="button" class="'+(cls||'btn-ghost')+'" data-proc-action="'+a+'"'+(id?' data-id="'+esc(id)+'"':'')+(a==='filter'?' aria-label="Фильтры воронки"':'')+attrs+'>'+text+'</button>';
  }
  function link(id,text) { return action('lead',esc(text||label((WK.leads[id]||{}).stage)),id,'pj-plain'); }
  function enqueue(fn) { var run=queue.then(fn); queue=run.catch(function(e){toast('Не сохранено: '+e.message);}); return run; }
  async function request(path,op) { var x=await apiJson('POST',path,op); if(!x.ok) throw new Error((x.d||{}).error||'ошибка записи'); return x.d; }
  async function save(kind,id,data) { WK=await request('/api/work',{op:'put',kind:kind,id:id,data:data}); return WK[kind][id]; }
  function redraw() { var y=window.scrollY; render(); window.scrollTo(0,y); }
  function patch(id,p,refresh) { return enqueue(async function(){var r=WK.leads[id]; if(!r) return; await save('leads',id,Object.assign({},r,p)); if(refresh!==false) redraw(); else refreshCounts(); if(state.lead===id && $('drawer').classList.contains('open')) panel(id,true);}); }
  function refreshCounts() { if(S.view!=='wkproc'||!state.id)return;var n=counts(leads(state.id));['total','called','ready','offer','decided'].forEach(function(k){var el=document.querySelector('[data-proc-count="'+k+'"]');if(el)el.textContent=n[k];}); }
  function scope() { return S.view==='wkproc' && state.id ? 'proc:'+state.id : S.wk.proj; }
  function owner(r) { return r.proc ? 'proc:'+r.proc : r.project||''; }
  function normalize(r) { r=Object.assign({},r); if((r.project||'').indexOf('proc:')===0) {r.proc=r.project.slice(5);r.project='';} return r; }
  function ownerName(r) { return r.proc ? ((WK.procs||{})[r.proc]||{}).title||'' : wkPname(r.project); }
  function ownerOptions(v,empty) { return wkProjOpts(v,empty)+records('procs').map(function(p){return '<option value="proc:'+p.id+'"'+(v==='proc:'+p.id?' selected':'')+'>Процесс: '+esc(p.title)+'</option>';}).join(''); }
  function open(id) { closeDrawer(); state.lead=null; state.id=id;state.tab=((WK.procs||{})[id]||{}).kind==='artists'?'funnel':'tasks';state.q='';state.filters={};S.wk.mcal=null;S.wk.qs={open:'',done:''};S.wk.qAt={};goView('wkproc');redraw(); }
  function installCols() {
    if(PL_COLSETS.leads) return;
    var defs=[['title','Проект',210],['stage','Этап',210],['called','Позвонил',85],['ready','Готовы',95],['fee','Гонорар',115],['cashless','% сверху',90],['next','Следующий шаг',220],['next_at','Дата шага',145],['season','Сезон',150],['list','Подбор городов',150],['task','Задача',180],['contact','Контакт',200],['afisha','Проект в афише',180],['called_at','Дата звонка',145],['source','Источник',180],['note','Заметка',220],['cities','Возможные города',210]];
    PL_COLSETS.leads={id:'leads',key:'leadcols',cols:defs.map(function(c,i){return {id:c[0],labels:[c[1]],w:c[2],left:true,lock:i===0,off:i>10};})};
  }
  function field(r,k,title,type,opts) {
    var v=r[k],attr=' data-lead-field="'+k+'" data-id="'+r.id+'" aria-label="'+esc(title)+'"';
    if(opts) return '<select class="pl-sel" data-native'+attr+'>'+wkOpts(opts.map(function(o){return [o[0],esc(o[1])];}),v||'')+'</select>';
    if(type==='checkbox') return '<input type="checkbox" class="wk-check"'+attr+(v?' checked':'')+'>';
    if(type==='textarea') return '<textarea class="pl-in"'+attr+'>'+esc(v||'')+'</textarea>';
    return '<input class="pl-in"'+attr+' type="'+(type||'text')+'" value="'+esc(v==null?'':String(v))+'"'+(type==='number'?' min="0" step="any"':'')+'>';
  }
  function cell(c,r) {
    var k=c.id,h;
    if(k==='title') h=link(r.id,r.title);
    else if(k==='list') h=PLAN.lists[r.list]?action('pick','Открыть →',r.id,'pj-plain'):'—';
    else if(k==='task') h=WK.tasks[r.task]?action('task-open',esc(WK.tasks[r.task].text),r.id,'pj-plain'):'—';
    else if(k==='cities') h=esc((r.cities||[]).map(function(c){return c.city;}).join(', ')||'—');
    else h=field(r,k,c.labels[0],k==='called'?'checkbox':k==='fee'||k==='cashless'?'number':/_at$/.test(k)?'date':null,k==='stage'?stages:k==='ready'?ready:k==='season'?season:null);
    return '<td class="pl-left'+(k==='next_at' && r.next_at && r.next_at<wkDay(0)?' proc-over':'')+'">'+h+'</td>';
  }
  function sortVal(k,r) { if(k==='stage')return stages.findIndex(function(s){return s[0]===r.stage;}); if(k==='called')return +!!r.called;if(k==='cities')return (r.cities||[]).length;return r[k]==null||r[k]===''?null:r[k]; }
  function filterHtml() { return '<div class="proc-fields">'+[['stage','Этап',[['','Все']].concat(stages)],['called','Позвонил',[['','Все'],['yes','Да'],['no','Нет']]],['ready','Готовы',[['','Все'],['yes','Да'],['no','Нет'],['empty','Не указано']]],['season','Сезон',[['','Все'],['this','Этот'],['next','Следующий'],['empty','Не указан']]],['list','Подбор',[['','Все'],['yes','Есть'],['no','Нет']]]].map(function(f){return '<label>'+f[1]+'<select data-native data-proc-filter="'+f[0]+'">'+wkOpts(f[2],state.filters[f[0]]||'')+'</select></label>';}).join('')+'<label><input type="checkbox" data-proc-filter="over"'+(state.filters.over?' checked':'')+'> Просрочен следующий шаг</label>'+action('reset','Сбросить фильтры')+'</div>'; }
  function funnel(id) {
    installCols(); var rows=leads(id).filter(function(r){return matches(r,state.filters,wkDay(0)) && (!state.q || [r.title,r.afisha,r.contact].join(' ').toLowerCase().indexOf(state.q.toLowerCase())>=0);});
    var filtered=Object.keys(state.filters).some(function(k){return !!state.filters[k];});
    var bar='<div class="tb-head proc-tools"><input class="pl-in" type="search" id="procQ" value="'+esc(state.q)+'" placeholder="Найти проект" aria-label="Найти проект"><div class="wkp-seg">'+action('table','Таблица',null,state.mode==='table'?'btn-dark':'btn-ghost')+action('board','Доска',null,state.mode==='board'?'btn-dark':'btn-ghost')+'</div>'+action('filter',WKT_ICON.group+(filtered?'<i class="wk-sq-dot"></i>':''),null,'wk-sq'+(filtered?' on':''))+plColsControl('leads')+'</div>';
    var body=state.mode==='table'?tbGrid(rows,'leads',{sortable:true,cell:cell,sortVal:sortVal,name:function(r){return r.title;},defSort:{id:'order',dir:1}}):board(rows);
    return bar+body+'<form class="proc-add" data-proc-add="'+id+'"><input class="pl-in" name="title" maxlength="300" placeholder="+ Проект" aria-label="Новый проект в воронке" required><button class="btn-ghost">Добавить</button></form>';
  }
  function board(rows) {
    return '<div class="proc-board">'+stages.map(function(s){var list=rows.filter(function(r){return r.stage===s[0];}).sort(function(a,b){return (a.order||0)-(b.order||0);});
      var cards=list.map(function(r){return '<article class="wkp-kc proc-lead" draggable="true" data-lead-drag="'+r.id+'">'+link(r.id,r.title)+'<div>'+esc(wkMoney(r.fee)||'—')+' ₽</div><div class="'+(r.next_at && r.next_at<wkDay(0)?'proc-over':'sub2')+'">'+esc(r.next||'')+' '+esc(r.next_at||'')+'</div><div class="sub2">'+(r.list?'подбор · ':'')+(r.task?'задача':'')+'</div></article>';}).join('');
      return s[0]==='declined'?'<details class="proc-column" data-lead-drop="declined"><summary>'+s[1]+' · '+list.length+'</summary>'+cards+'</details>':'<section class="proc-column" data-lead-drop="'+s[0]+'"><h3>'+s[1]+' · '+list.length+'</h3>'+cards+'</section>';
    }).join('')+'</div>';
  }
  function page() {
    var gate=wkGate('Процессы');if(gate)return gate;
    WK.procs=WK.procs||{};WK.leads=WK.leads||{};
    if(!Object.keys(WK.procs).length && !state.init) {state.init=true;enqueue(async function(){WK=await request('/api/work',{op:'init',kind:'procs',id:'defaults'});redraw();}).catch(function(){state.init=false;});}
    if(state.id && !WK.procs[state.id])state.id=null;
    if(!state.id) return head('Процессы','')+'<div class="tb-head">'+action('new','+ Новый процесс')+'</div><div class="wkp-cards">'+records('procs').sort(function(a,b){return (a.order||0)-(b.order||0);}).map(function(p){var n=counts(leads(p.id)),ts=wkTasksOf('proc:'+p.id).filter(function(t){return !t.done;});return '<article class="wkp-card proc-card" tabindex="0" role="link" data-proc-open="'+p.id+'">'+(wkMedia(p,'cover')?'<img class="proc-cover" src="'+esc(wkMedia(p,'cover'))+'" alt="">':'')+'<h3>'+esc(p.title)+'</h3><p class="sub2">'+(p.kind==='artists'?'в воронке '+n.total+' · ждут предложения '+n.ready+' · решено '+n.decided:ts.length+' открытых задач')+'</p></article>';}).join('')+'</div>'+(leads('').length?'<details><summary>Без процесса · '+leads('').length+'</summary>'+leads('').map(function(r){return '<p>'+link(r.id,r.title)+'</p>';}).join('')+'</details>':'');
    ixSharesLoad();
    var p=WK.procs[state.id],id=state.id,sc='proc:'+id,cover=wkMedia(p,'cover'),n=counts(leads(id)),tasks=wkTasksOf(sc),done=tasks.filter(function(t){return t.done;}).length;
    if(p.kind!=='artists')state.tab='tasks';
    var stats=p.kind==='artists'?[[n.total,'в воронке'],[n.called,'позвонили'],[n.ready,'готовы'],[n.offer,'с предложением'],[n.decided,'решено']]:[[tasks.filter(function(t){return !t.done&&t.due&&t.due<wkDay(0);}).length,'просрочено'],[done+'/'+tasks.length,'выполнено']];
    return '<section class="pj-hero wk-hero proc-hero'+(cover?' has-cover':'')+'"'+(cover?' style="background-image:url(\''+esc(cover)+'\')"':'')+'>'+action('back','← Все процессы',null,'pj-back-btn')+'<div class="pj-top-right">'+action('delete','Удалить',id,'pj-cover-btn')+'</div><div class="pj-hero-in"><div class="pj-hero-text"><h1 class="pj-name">'+esc(p.title)+'</h1><p>'+esc(p.note||'')+'</p><div class="pj-actions">'+action('edit','Редактировать',id,'pj-btn primary')+'</div></div><div class="wk-hstats">'+stats.map(function(x,i){return '<div class="wk-hstat"><b'+(p.kind==='artists'?' data-proc-count="'+['total','called','ready','offer','decided'][i]+'"':'')+'>'+x[0]+'</b><span>'+x[1]+'</span></div>';}).join('')+'</div></div></section><div class="wk-ptabs-row"><div class="mtabs subtabs wk-ptabs" role="tablist" aria-label="Разделы процесса">'+(p.kind==='artists'?action('funnel','Воронка',null,state.tab==='funnel'?'btn-dark':'btn-ghost'):'')+action('tasks','Задачи · '+tasks.filter(function(t){return !t.done;}).length,null,state.tab==='tasks'?'btn-dark':'btn-ghost')+'</div>'+(state.tab==='tasks'?'<div class="wk-tabtools"><button class="wk-sq" data-wkt-groupmenu aria-label="Фильтры и группировка задач">'+WKT_ICON.group+'</button><button class="wk-sq wk-sq-add" data-wkt-quickadd aria-label="Новая задача">'+WKT_ICON.plus+'</button></div>':'')+'</div>'+(state.tab==='funnel'?funnel(id):'<div class="wk-split"><div class="wk-split-main">'+wktTable(tasks,sc)+'</div><aside class="wk-split-side">'+wkCalBlock(sc)+wkFocusBlock(sc)+'</aside></div>')+wkNotesGrid(sc);
  }
  function edit(id) { var p=WK.procs[id]||{};pjDialog('proc-editor',id?'Редактировать процесс':'Новый процесс','<form data-proc-edit="'+(id||'')+'" class="proc-fields"><label>Название<input class="pl-in" name="title" required maxlength="300" value="'+esc(p.title||'')+'"></label><label>Описание<input class="pl-in" name="note" maxlength="3000" value="'+esc(p.note||'')+'"></label>'+(!id?'<label>Вид<select name="kind" data-native>'+wkOpts([['other','Задачи и заметки'],['artists','Поиск проектов'],['venue_dates','Запрос дат у площадок']],'other')+'</select></label>':'')+'<label>Обложка<input type="file" name="cover" accept="image/png,image/jpeg,image/webp"></label>'+(p.media&&p.media.cover?'<label><input type="checkbox" name="removeCover"> Убрать обложку</label>':'')+'<button class="btn-dark">Сохранить</button></form>'); }
  function shareLink(sh) {
    if(!sh || !(sh.tokens||[]).length)return '';
    var token=sh.tokens.slice().sort(function(a,b){return (b.created||'').localeCompare(a.created||'');})[0];
    var url=((S.pl.ixShares||{}).base||'http://127.0.0.1:5070')+'/s/'+token.token;
    return '<a class="pj-plain" href="'+esc(url)+'" target="_blank" rel="noopener">Ссылка руководителю →</a>';
  }
  function panel(id,keep) {
    var r=WK.leads[id];if(!r)return;state.lead=id;var row=Object.assign({id:id},r),L=PLAN.lists[r.list],sh=(((S.pl.ixShares||{}).lists)||{})[r.list];
    var fields=[['title','Название'],['afisha','Проект в афише'],['contact','Контакт'],['stage','Этап',null,stages],['called','Позвонил','checkbox'],['called_at','Дата звонка','date'],['ready','Готовы',null,ready],['fee','Гонорар','number'],['cashless','% сверху','number'],['season','Сезон',null,season],['next','Следующий шаг'],['next_at','Дата шага','date'],['source','Источник'],['note','Заметка','textarea'],['proc','Процесс',null,[['','Без процесса']].concat(records('procs').map(function(p){return [p.id,p.title];}))],['list','Подбор городов',null,[['','—']].concat(Object.keys(PLAN.lists).map(function(k){return [k,PLAN.lists[k].title];}))],['task','Задача',null,[['','—']].concat(wkTasksOf('proc:'+r.proc).map(function(t){return [t.id,t.text];}))]];
    var html='<div class="drawer-head"><h2>'+esc(r.title)+'</h2>'+action('close','✕',null,'icon-btn')+'</div><div class="proc-panel"><div class="proc-hints">'+hints(r,sh).map(function(s){return action('stage:'+s,'Перевести в «'+label(s)+'»?',id);}).join('')+'</div><div class="proc-fields">'+fields.map(function(f){return '<label>'+f[1]+field(row,f[0],f[1],f[2],f[3])+'</label>';}).join('')+'</div><div class="tb-actions">'+(L?action('pick','Открыть подбор →',id):action('pick-create','Создать подбор городов',id))+(WK.tasks[r.task]?action('task-open','Открыть задачу →',id):action('task-create','Создать задачу',id))+'</div>'+(L?'<section><h3>Подбор городов</h3><p>Гонорар: '+esc(wkMoney((L.econ||{}).fee)||'—')+' · '+esc(wkPickOffer(L))+'</p><p>'+(sh?'Руководитель: ✔ '+sh.ok+' · ? '+sh.ask+' · ✖ '+sh.no:'Ссылка не отправлялась')+'</p>'+shareLink(sh)+'<div class="tb-actions">'+action('pdf','PDF руководителю',id)+action('cities','Зафиксировать возможные города',id)+'</div></section>':'')+'<section><h3>Возможные города'+(r.cities_at?' · '+esc(r.cities_at):'')+'</h3>'+(r.cities||[]).map(function(c){return '<p>'+esc([c.city,c.venue,wkMoney(c.price)].filter(Boolean).join(' · '))+'</p>';}).join('')+'</section><div class="tb-actions">'+action('decision:this','Решение: этот сезон',id)+action('decision:next','Решение: следующий сезон',id)+'</div>'+(r.stage==='decided'?(WK.projects[r.project]?action('project-open','Открыть проект «Работы» →',id):action('project-create','Создать проект «Работы»',id)):'')+'<section><h3>Журнал</h3><form data-lead-log="'+id+'"><input class="pl-in" name="text" maxlength="2000" placeholder="Добавить запись" required><button class="btn-ghost">Добавить</button></form>'+(r.log||[]).slice().reverse().map(function(l){return '<p><span class="sub2">'+esc(l.at.replace('T',' '))+'</span><br>'+esc(l.text)+'</p>';}).join('')+'</section></div>';
    $('drawer').setAttribute('aria-label','Проект в воронке: '+r.title);
    if(keep){var y=$('drawer').scrollTop;$('drawer').innerHTML=html;$('drawer').scrollTop=y;}else showDrawer(html);
  }
  async function linkList(id,lid) {
    var r=WK.leads[id],L=PLAN.lists[lid],old=PLAN.lists[r.list];
    if(L && (L.work||{}).lead && L.work.lead!==id)throw new Error('Этот подбор уже связан с другой записью');
    if(old && (old.work||{}).lead===id && r.list!==lid){var o=JSON.parse(JSON.stringify(old));delete o.work.lead;await request('/api/planning',{op:'put',kind:'lists',id:r.list,data:o});PLAN.lists[r.list]=o;}
    if(L){var n=Object.assign({},L,{work:Object.assign({},L.work||{},{lead:id})});await request('/api/planning',{op:'put',kind:'lists',id:lid,data:n});PLAN.lists[lid]=n;}
    await save('leads',id,Object.assign({},r,{list:lid}));
  }
  async function leadAction(a,id) {
    var r=WK.leads[id];if(!r)return;
    if(a==='pick-create') {if(PLAN.lists[r.list])return;var lid=plId('l'),rec={title:r.title,project:r.afisha||'',econ:{fee:r.fee,cashless:r.cashless},work:{lead:id},rows:[],cities:{}};await request('/api/planning',{op:'put',kind:'lists',id:lid,data:rec});PLAN.lists[lid]=rec;await save('leads',id,Object.assign({},r,{list:lid}));}
    else if(a==='task-create') {if(WK.tasks[r.task])return;if(!WK.procs[r.proc])throw new Error('Сначала выберите процесс');var tid=wkId('t');await save('tasks',tid,{text:'Подбор городов: '+r.title,proc:r.proc,due:r.next_at||'',created:wkDay(0)});await save('leads',id,Object.assign({},r,{task:tid}));}
    else if(a==='cities') {var L=PLAN.lists[r.list];if(!L)throw new Error('Подбор удалён');var A=tbAnalyze(L,tbPrefs());tbPick(L,A);var cities=Object.keys(L.cities||{}).filter(function(c){return L.cities[c].dec==='yes';}).map(function(c){var o=L.cities[c],calc=A.rows.find(function(x){return x.city===c;}),p=calc&&calc.pick;return {city:c,venue:o.venue||(p&&p.v?p.v.name:'')||'',price:o.price!=null?o.price:(p&&p.k?p.k.price:null),at:wkDay(0)};});await save('leads',id,Object.assign({},r,{cities:cities,cities_at:wkDay(0)}));}
    else if(a==='project-create') {if(r.stage!=='decided')return;if(WK.projects[r.project])return;var pid=wkId('p');await save('projects',pid,{title:r.title,lead:id,stage:WK_STAGE[0][0],created:wkDay(0)});await save('leads',id,Object.assign({},r,{project:pid}));}
    else if(a.indexOf('stage:')===0) await save('leads',id,Object.assign({},r,{stage:a.slice(6)}));
    else if(a.indexOf('decision:')===0) await save('leads',id,Object.assign({},r,{stage:'decided',season:a.slice(9)}));
    redraw();if(state.lead===id)panel(id,true);
  }
  function openPick(id,pdf) {var r=WK.leads[id];if(!r||!PLAN.lists[r.list])return;closeDrawer();state.lead=null;S.pl.tab='build';S.pl.tb.list=r.list;S.pl.tb.draft=null;goView('planning');if(pdf)tbOfferDoc('boss');}
  document.addEventListener('click',function(ev){
    var op=ev.target.closest&&ev.target.closest('[data-proc-open]');if(op){open(op.getAttribute('data-proc-open'));return;}
    var b=ev.target.closest&&ev.target.closest('[data-proc-action]');if(!b)return;ev.preventDefault();var a=b.getAttribute('data-proc-action'),id=b.getAttribute('data-id');
    if(a==='lead'){var d=$('pjDlg');if(d&&d.open)d.close();var r=WK.leads[id];if(!r)return;if(r.proc)open(r.proc);else{state.id=null;goView('wkproc');}ixSharesLoad();panel(id);return;}
    if(a==='close'){state.lead=null;closeDrawer();return;}if(a==='back'){state.id=null;redraw();return;}if(a==='new'||a==='edit'){edit(id);return;}
    if(a==='tasks'||a==='funnel'){state.tab=a;redraw();return;}if(a==='table'||a==='board'){state.mode=a;redraw();return;}
    if(a==='filter'){wkPopOpen(b,'wk-menu proc-filter',filterHtml(),{});return;}if(a==='reset'){state.filters={};wkPopClose();redraw();return;}
    if(a==='pick'||a==='pdf'){openPick(id,a==='pdf');return;}if(a==='task-open'){closeDrawer();state.lead=null;wkOpenTask(WK.leads[id].task);return;}
    if(a==='project-open'){closeDrawer();state.lead=null;goView('work');wkpOpenPage(WK.leads[id].project);return;}
    if(a==='delete'){var n=leads(id).length;askConfirm('Удалить процесс «'+WK.procs[id].title+'»?','Записи воронки ('+n+'), задачи и заметки останутся без процесса.','Удалить',function(){enqueue(async function(){WK=await request('/api/work',{op:'del',kind:'procs',id:id});state.id=null;redraw();});});return;}
    enqueue(function(){return leadAction(a,id);});
  });
  document.addEventListener('change',function(ev){var el=ev.target;
    if(el.hasAttribute('data-proc-filter')){state.filters[el.getAttribute('data-proc-filter')]=el.type==='checkbox'?el.checked:el.value;redraw();return;}
    if(!el.hasAttribute('data-lead-field'))return;var id=el.getAttribute('data-id'),k=el.getAttribute('data-lead-field'),v=el.type==='checkbox'?el.checked:el.type==='number'?(el.value===''?null:+el.value):el.value,p={};p[k]=v;
    if(k==='called')p.called_at=v?wkDay(0):'';
    if(k==='list'){enqueue(async function(){await linkList(id,v);redraw();panel(id,true);});return;}
    if(k==='proc' && WK.tasks[(WK.leads[id]||{}).task] && WK.tasks[WK.leads[id].task].proc!==v)p.task='';
    patch(id,p,false).then(function(){var r=WK.leads[id];if(!state.lead&&hints(r).length){var s=hints(r)[0];toast('Сохранено');askConfirm('Перевести в «'+label(s)+'»?','Этап изменится только после подтверждения.','Перевести',function(){patch(id,{stage:s});});}},function(){});
  });
  document.addEventListener('submit',function(ev){var f=ev.target;
    if(f.hasAttribute('data-proc-add')){ev.preventDefault();var title=f.elements.title.value.trim(),proc=f.getAttribute('data-proc-add');if(!title)return;f.elements.title.value='';enqueue(async function(){await save('leads',wkId('l'),{title:title,proc:proc,stage:'found',order:leads(proc).length,created:wkDay(0)});redraw();var i=document.querySelector('[data-proc-add] input');if(i)i.focus();});}
    if(f.hasAttribute('data-lead-log')){ev.preventDefault();var id=f.getAttribute('data-lead-log'),text=f.elements.text.value.trim();if(text)enqueue(async function(){var r=WK.leads[id];await save('leads',id,Object.assign({},r,{log:(r.log||[]).concat([{id:wkId('log'),at:wkStamp(),text:text}])}));panel(id,true);});}
    if(f.hasAttribute('data-proc-edit')){ev.preventDefault();var pid=f.getAttribute('data-proc-edit')||wkId('proc'),file=f.elements.cover.files[0],remove=f.elements.removeCover&&f.elements.removeCover.checked,rec=Object.assign({},WK.procs[pid]||{kind:f.elements.kind.value},{title:f.elements.title.value.trim(),note:f.elements.note.value});if(!rec.title)return;var submit=f.querySelector('button');submit.disabled=true;enqueue(async function(){await save('procs',pid,rec);if(file||remove){var data=file?await new Promise(function(resolve,reject){var reader=new FileReader();reader.onload=function(){resolve(reader.result);};reader.onerror=reject;reader.readAsDataURL(file);}):'';WK=await request('/api/work',{op:'media',kind:'procs',id:pid,what:'cover',data:data});}$('pjDlg').close();redraw();}).then(function(){submit.disabled=false;},function(){submit.disabled=false;});}
  });
  var timer;document.addEventListener('input',function(ev){if(ev.target.id!=='procQ')return;state.q=ev.target.value;clearTimeout(timer);timer=setTimeout(function(){redraw();var i=$('procQ');if(i)i.focus();},180);});
  document.addEventListener('keydown',function(ev){var c=ev.target.closest&&ev.target.closest('[data-proc-open]');if(c&&ev.key==='Enter'){ev.preventDefault();c.click();}});
  var drag=null;document.addEventListener('dragstart',function(ev){var c=ev.target.closest&&ev.target.closest('[data-lead-drag]');if(!c)return;drag=c.getAttribute('data-lead-drag');ev.dataTransfer.setData('text/plain',drag);ev.dataTransfer.effectAllowed='move';});
  document.addEventListener('dragover',function(ev){if(drag&&ev.target.closest('[data-lead-drop]'))ev.preventDefault();});
  document.addEventListener('drop',function(ev){var col=ev.target.closest&&ev.target.closest('[data-lead-drop]');if(!drag||!col)return;ev.preventDefault();var id=drag;drag=null;var stage=col.getAttribute('data-lead-drop'),before=ev.target.closest('[data-lead-drag]');var list=leads(state.id).filter(function(r){return r.stage===stage&&r.id!==id;}).sort(function(a,b){return (a.order||0)-(b.order||0);});var at=before?list.findIndex(function(r){return r.id===before.getAttribute('data-lead-drag');}):list.length;list.splice(at<0?list.length:at,0,WK.leads[id]);enqueue(async function(){for(var i=0;i<list.length;i++){var row=list[i],rid=row.id||id;await save('leads',rid,Object.assign({},WK.leads[rid],{stage:stage,order:i}));}redraw();});});
  document.addEventListener('dragend',function(){drag=null;});
  api.closed=function(){state.lead=null;};
  api.refreshShares=function(){if(state.lead && $('drawer').classList.contains('open'))panel(state.lead,true);};
  api.page=page;api.scope=scope;api.owner=owner;api.normalize=normalize;api.ownerName=ownerName;api.ownerOptions=ownerOptions;api.open=open;api.link=link;
  api.taskLine=function(id){return records('leads').filter(function(r){return r.task===id;}).map(function(r){return '<div class="wk-pick">Воронка: '+link(r.id,r.title)+' · '+link(r.id,'Открыть →')+'</div>';}).join('');};
  api.chip=function(L){var id=(L.work||{}).lead;return id&&WK.leads&&WK.leads[id]?'<span class="tb-wchip">Воронка: '+link(id)+'</span>':'';};
  api.projectLine=function(p){return p.lead&&WK.leads&&WK.leads[p.lead]?'<div class="wk-pick">Воронка: '+link(p.lead,WK.leads[p.lead].title)+'</div>':'';};
})(typeof window!=='undefined'?window:globalThis);
