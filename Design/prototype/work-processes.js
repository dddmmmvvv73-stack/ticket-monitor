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
  // цвета этапов — из палитры стадий «Проектов» (ps-*)
  var colors={found:'gray',called:'blue',ready:'amber',offer:'violet',answered:'teal',decided:'green',declined:'pink'};
  function tag(s,n) { return '<span class="wkp-tag ps-'+(colors[s]||'gray')+'"><i aria-hidden="true"></i>'+esc(label(s)||'—')+(n!=null?' <span>'+n+'</span>':'')+'</span>'; }
  function stageAt(s) { return stages.findIndex(function(x){return x[0]===s;}); }
  function action(a,text,id,cls,attrs) {
    return '<button type="button" class="'+(cls||'btn-ghost')+'" data-proc-action="'+a+'"'+(id?' data-id="'+esc(id)+'"':'')+(attrs||'')+'>'+text+'</button>';
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
    // по умолчанию видно то, что нужно для прозвона и следующего шага; остальное — «Столбцы таблицы»
    var defs=[['title','Проект',220],['stage','Этап',200],['called','Позвонил',90],['ready','Готовы',96],['fee','Гонорар',112],['cashless','% сверху',90,1],['next','Следующий шаг',210],['next_at','Дата шага',132],['season','Сезон',140,1],['list','Подбор городов',130],['task','Задача',170],['contact','Контакт',200,1],['afisha','Проект в афише',180,1],['called_at','Дата звонка',132,1],['source','Источник',180,1],['note','Заметка',220,1],['cities','Возможные города',210,1]];
    PL_COLSETS.leads={id:'leads',key:'leadcols',cols:defs.map(function(c,i){return {id:c[0],labels:[c[1]],w:c[2],left:true,lock:i===0,off:!!c[3]};})};
  }
  function field(r,k,title,type,opts) {
    var v=r[k],attr=' data-lead-field="'+k+'" data-id="'+r.id+'" aria-label="'+esc(title)+'"';
    // списки — фирменные выпадающие сайта (enhanceSelects), поля — как в таблицах «Планирования»
    if(opts) return '<select class="pl-sel"'+attr+'>'+wkOpts(opts.map(function(o){return [o[0],esc(o[1])];}),v||'')+'</select>';
    if(type==='checkbox') return '<input type="checkbox" class="wk-check"'+attr+(v?' checked':'')+'>';
    if(type==='textarea') return '<textarea class="pl-in pl-text"'+attr+'>'+esc(v||'')+'</textarea>';
    return '<input class="pl-in'+(type==='number'?' proc-num':' pl-text')+'"'+attr+' type="'+(type||'text')+'" value="'+esc(v==null?'':String(v))+'"'+(type==='number'?' min="0" step="any"':'')+'>';
  }
  function cell(c,r) {
    var k=c.id,h;
    if(k==='title') h=link(r.id,r.title);
    else if(k==='list') h=PLAN.lists[r.list]?action('pick','Открыть →',r.id,'pj-plain'):action('lead-link','связать',r.id,'pj-plain proc-muted');
    else if(k==='task') h=WK.tasks[r.task]?action('task-open',esc(WK.tasks[r.task].text),r.id,'pj-plain proc-ell'):'<span class="sub2">—</span>';
    else if(k==='cities') h=esc((r.cities||[]).map(function(c){return c.city;}).join(', ')||'—');
    else h=field(r,k,c.labels[0],k==='called'?'checkbox':k==='fee'||k==='cashless'?'number':/_at$/.test(k)?'date':null,k==='stage'?stages:k==='ready'?ready:k==='season'?season:null);
    return '<td class="pl-left'+(k==='stage'?' proc-stage ps-'+(colors[r.stage]||'gray'):'')+(k==='title'?' proc-tt':'')+(k==='next_at' && r.next_at && r.next_at<wkDay(0) && !/decided|declined/.test(r.stage)?' proc-over':'')+'">'+h+'</td>';
  }
  function sortVal(k,r) { if(k==='stage')return stages.findIndex(function(s){return s[0]===r.stage;}); if(k==='called')return +!!r.called;if(k==='cities')return (r.cities||[]).length;return r[k]==null||r[k]===''?null:r[k]; }
  function filterHtml() { return '<div class="proc-fields proc-filterf">'+[['stage','Этап',[['','Все']].concat(stages)],['called','Позвонил',[['','Все'],['yes','Да'],['no','Нет']]],['ready','Готовы',[['','Все'],['yes','Да'],['no','Нет'],['empty','Не указано']]],['season','Сезон',[['','Все'],['this','Этот'],['next','Следующий'],['empty','Не указан']]],['list','Подбор',[['','Все'],['yes','Есть'],['no','Нет']]]].map(function(f){return '<div class="field"><label>'+f[1]+'</label><select data-native data-proc-filter="'+f[0]+'" aria-label="'+f[1]+'">'+wkOpts(f[2],state.filters[f[0]]||'')+'</select></div>';}).join('')+'<label class="proc-chk"><input type="checkbox" class="wk-check" data-proc-filter="over"'+(state.filters.over?' checked':'')+'> Просрочен следующий шаг</label>'+action('reset','Сбросить фильтры')+'</div>'; }
  function funnel(id) {
    installCols(); var rows=leads(id).filter(function(r){return matches(r,state.filters,wkDay(0)) && (!state.q || [r.title,r.afisha,r.contact].join(' ').toLowerCase().indexOf(state.q.toLowerCase())>=0);});
    var filtered=Object.keys(state.filters).some(function(k){return !!state.filters[k];});
    // панель — как у «Проектов» (wkpBar): вид слева; поиск, фильтр, столбцы и «+» справа
    var seg=[['table','Таблица',WKP_VIEWS[1][2]],['board','Доска',WKP_VIEWS[0][2]]].map(function(v){return action(v[0],v[2]+'<span class="wkp-segl">'+v[1]+'</span>',null,'proc-seg',' aria-pressed="'+(state.mode===v[0])+'" title="'+v[1]+'"');}).join('');
    var bar='<div class="wkp-bar proc-tools"><div class="wkp-seg" role="group" aria-label="Вид воронки">'+seg+'</div><span class="wkp-sp"></span>'+
      '<label class="wkp-search">'+WKP_IC.search+'<input type="search" id="procQ" value="'+esc(state.q)+'" placeholder="Поиск проектов" aria-label="Найти проект в воронке"></label>'+
      action('filter',WKP_IC.filter+'Фильтр',null,'wkp-filter'+(filtered?' on':''),' aria-haspopup="dialog" aria-label="Фильтры воронки"')+(state.mode==='table'?plColsControl('leads'):'')+
      action('add',WKT_ICON.plus,null,'wk-sq wk-sq-add',' aria-label="Новый проект в воронке" title="Новый проект в воронке"')+'</div>';
    var add='<form class="proc-add" data-proc-add="'+id+'"><span aria-hidden="true">+</span><input name="title" maxlength="300" placeholder="Добавить проект — название и Enter" aria-label="Новый проект в воронке" required autocomplete="off"></form>';
    var body=state.mode==='table'?tbGrid(rows,'leads',{sortable:true,cell:cell,sortVal:sortVal,name:function(r){return r.title;},defSort:{id:'order',dir:1}}).replace('</table></section>','</table></section>'+add):board(rows)+add;
    return '<div class="proc-funnel'+(state.mode==='table'?' is-table':'')+'">'+bar+body+(!rows.length&&(state.q||filtered)?'<p class="wkp-none">Ничего не нашлось — измените поиск или фильтр.</p>':'')+'</div>';
  }
  function board(rows) {   // колонки и карточки — как канбан «Проектов» (wkpKanban)
    return '<div class="wkp-kb proc-board">'+stages.map(function(s){var list=rows.filter(function(r){return r.stage===s[0];}).sort(function(a,b){return (a.order||0)-(b.order||0);});
      var cards=list.map(function(r){var over=r.next_at && r.next_at<wkDay(0);
        return '<div class="wkp-kc proc-lead" draggable="true" data-lead-drag="'+r.id+'"><div class="wkp-nm">'+link(r.id,r.title)+'</div>'+
          (r.next||r.next_at?'<div class="proc-next'+(over?' over':'')+'">'+(r.next_at?'<b>'+WKP_IC.flag+esc(wkpShort(r.next_at))+'</b> ':'')+esc(r.next||'')+'</div>':'')+
          '<div class="wkp-kc-row"><span class="proc-fee">'+(r.fee?esc(wkMoney(r.fee))+' ₽':'<span class="sub2">гонорар?</span>')+'</span><span class="wkp-chips">'+(r.list?'<span class="wkp-chip">подбор</span>':'')+(r.task?'<span class="wkp-chip">задача</span>':'')+'</span></div></div>';}).join('');
      return '<div class="wkp-col" data-lead-drop="'+s[0]+'"><div class="wkp-gh">'+tag(s[0],list.length)+'</div><div class="wkp-kcs">'+(cards||'<div class="wkp-kc-empty">Перетащите сюда проект</div>')+'</div></div>';
    }).join('')+'</div>';
  }
  function page() {
    var gate=wkGate('Процессы');if(gate)return gate;
    WK.procs=WK.procs||{};WK.leads=WK.leads||{};
    if(!Object.keys(WK.procs).length && !state.init) {state.init=true;enqueue(async function(){WK=await request('/api/work',{op:'init',kind:'procs',id:'defaults'});redraw();}).catch(function(){state.init=false;});}
    if(state.id && !WK.procs[state.id])state.id=null;
    if(!state.id) return head('Процессы','')+'<div class="wkp-cards proc-cards">'+records('procs').sort(function(a,b){return (a.order||0)-(b.order||0);}).map(function(p){   // карточки — как «Карточки» проектов (wkpCards)
      var n=counts(leads(p.id)),ts=wkTasksOf('proc:'+p.id),open=ts.filter(function(t){return !t.done;}).length,over=ts.filter(function(t){return !t.done&&t.due&&t.due<wkDay(0);}).length;
      var li=p.kind==='artists'?['в воронке: '+n.total,'ждут предложения: '+n.ready,'с предложением: '+n.offer,'решено: '+n.decided]:['открытых задач: '+open+(over?', просрочено '+over:'')];
      return '<article class="wkp-card proc-card" tabindex="0" role="link" data-proc-open="'+p.id+'">'+(wkMedia(p,'cover')?'<img class="proc-cover" src="'+esc(wkMedia(p,'cover'))+'" alt="">':'')+'<h3>'+esc(p.title)+'</h3>'+(p.note?'<p class="proc-note1">'+esc(p.note)+'</p>':'')+'<ul>'+li.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul>'+
        '<div class="wkp-card-f"><span>'+esc(p.upd?wkpAgo(p.upd):'')+'</span><span class="wkp-sp"></span>'+(p.kind==='artists'?'':'<span class="wkp-pill ps-gray">'+(p.kind==='venue_dates'?'заготовка':'задачи')+'</span>')+'</div></article>';
    }).join('')+'<button type="button" class="wkp-card wkp-addcard" data-proc-action="new" aria-haspopup="dialog"><span aria-hidden="true">+</span>Новый процесс</button></div>'+(leads('').length?'<details class="proc-orphans"><summary>Без процесса · '+leads('').length+'</summary>'+leads('').map(function(r){return '<p>'+link(r.id,r.title)+'</p>';}).join('')+'</details>':'');
    ixSharesLoad();
    var p=WK.procs[state.id],id=state.id,sc='proc:'+id,cover=wkMedia(p,'cover'),n=counts(leads(id)),tasks=wkTasksOf(sc),done=tasks.filter(function(t){return t.done;}).length;
    if(p.kind!=='artists')state.tab='tasks';
    var stats=p.kind==='artists'?[[n.total,'в воронке'],[n.called,'позвонили'],[n.ready,'готовы'],[n.offer,'с предложением'],[n.decided,'решено']]:[[tasks.filter(function(t){return !t.done&&t.due&&t.due<wkDay(0);}).length,'просрочено'],[done+'/'+tasks.length,'выполнено']];
    // шапка — как у проекта (wkProjectPage): круглые «назад» и «удалить», «Редактировать» с карандашом, плитки справа
    var openN=tasks.length-done,filtOn=S.wk.groupBy==='due'||!!S.wk.prioF,tab=function(a,t,num){return action(a,t+(num?' <span class="wk-tabn">'+num+'</span>':''),null,' ',' role="tab" aria-selected="'+(state.tab===a)+'"');};
    return '<section class="pj-hero wk-hero proc-hero'+(cover?' has-cover':'')+(p.kind==='artists'?' proc-hero5':'')+'"'+(cover?' style="background-image:url(\''+esc(cover)+'\')"':'')+'>'+action('back',PJ_ICON.back,null,'pj-back-btn',' aria-label="Назад: все процессы" title="Все процессы"')+'<div class="pj-top-right">'+action('delete',WKP_TRASH,id,'pj-cover-btn pj-icon wk-trash',' aria-label="Удалить процесс" title="Удалить процесс"')+'</div><div class="pj-hero-in"><div class="pj-hero-text"><h1 class="pj-name">'+esc(p.title)+'</h1>'+(p.note?'<p class="proc-hnote">'+esc(p.note)+'</p>':'')+'<div class="pj-actions">'+action('edit',PJ_ICON.edit+'Редактировать',id,'pj-btn primary')+'</div></div><div class="wk-hstats" role="group" aria-label="'+(p.kind==='artists'?'Воронка':'Задачи процесса')+'">'+stats.map(function(x,i){return '<div class="wk-hstat'+(p.kind!=='artists'&&i===0&&x[0]?' over':'')+'"><b class="num"'+(p.kind==='artists'?' data-proc-count="'+['total','called','ready','offer','decided'][i]+'"':'')+'>'+x[0]+'</b><span>'+x[1]+'</span></div>';}).join('')+'</div></div></section>'+
      '<div class="wk-ptabs-row"><div class="mtabs subtabs wk-ptabs" role="tablist" aria-label="Разделы процесса">'+(p.kind==='artists'?tab('funnel','Воронка',n.total):'')+tab('tasks','Задачи',openN)+'</div>'+(state.tab==='tasks'?'<div class="wk-tabtools"><button type="button" class="wk-sq'+(filtOn?' on':'')+'" data-wkt-groupmenu aria-haspopup="menu" aria-label="Фильтры и группировка задач" title="Фильтры и группировка">'+WKT_ICON.group+(filtOn?'<i class="wk-sq-dot" aria-hidden="true"></i>':'')+'</button><button type="button" class="wk-sq wk-sq-add" data-wkt-quickadd aria-haspopup="dialog" aria-label="Новая задача" title="Новая задача">'+WKT_ICON.plus+'</button></div>':'')+'</div>'+(state.tab==='funnel'?funnel(id):'<div class="wk-split"><div class="wk-split-main">'+wktTable(tasks,sc)+'</div><aside class="wk-split-side" aria-label="Календарь сроков и фокус">'+wkCalBlock(sc)+wkFocusBlock(sc)+'</aside></div>')+wkNotesGrid(sc);
  }
  function edit(id) { var p=WK.procs[id]||{};pjDialog('proc-editor',id?'Редактировать процесс':'Новый процесс','<form data-proc-edit="'+(id||'')+'" class="form-grid proc-form"><div class="field full"><label for="procT">Название</label><input id="procT" name="title" required maxlength="300" value="'+esc(p.title||'')+'"></div><div class="field full"><label for="procN">Описание — одна строка под названием</label><input id="procN" name="note" maxlength="3000" value="'+esc(p.note||'')+'"></div>'+(!id?'<div class="field full"><label for="procK">Вид</label><select id="procK" name="kind" data-native>'+wkOpts([['other','Задачи и заметки'],['artists','Поиск проектов (воронка)'],['venue_dates','Запрос дат у площадок']],'other')+'</select></div>':'')+'<div class="field full"><label for="procC">Обложка шапки</label><input id="procC" type="file" name="cover" accept="image/png,image/jpeg,image/webp"></div>'+(p.media&&p.media.cover?'<label class="proc-chk full"><input type="checkbox" class="wk-check" name="removeCover"> Убрать обложку</label>':'')+'<div class="form-actions full"><button class="btn-dark">Сохранить</button></div></form>'); }
  function shareLink(sh) {
    if(!sh || !(sh.tokens||[]).length)return '';
    var token=sh.tokens.slice().sort(function(a,b){return (b.created||'').localeCompare(a.created||'');})[0];
    var url=((S.pl.ixShares||{}).base||'http://127.0.0.1:5070')+'/s/'+token.token;
    return '<a class="pj-plain" href="'+esc(url)+'" target="_blank" rel="noopener">Ссылка руководителю →</a>';
  }
  function panel(id,keep) {
    var r=WK.leads[id];if(!r)return;state.lead=id;var row=Object.assign({id:id},r),L=PLAN.lists[r.list],sh=(((S.pl.ixShares||{}).lists)||{})[r.list];
    // поля, которых нет в «Шагах»: шаги сами правят «позвонил», «готовы» и гонорар
    var fields=[['next','Следующий шаг',null,null,1],['next_at','Дата шага','date'],['stage','Этап',null,stages],['season','Сезон',null,season],['contact','Контакт',null,null,1],['afisha','Проект в афише'],['source','Источник'],['called_at','Дата звонка','date'],['note','Заметка','textarea',null,1],['task','Задача',null,[['','—']].concat(wkTasksOf('proc:'+r.proc).map(function(t){return [t.id,t.text];}))],['proc','Процесс',null,[['','Без процесса']].concat(records('procs').map(function(p){return [p.id,p.title];})),1]];
    var at=stageAt(r.stage),out=r.stage==='declined',sent=sh&&(sh.tokens||[]).length,task=WK.tasks[r.task];
    // шаги процесса по порядку (PROCESSES_PLAN.md, п. 1.4): отметка — что сделано, справа — действие для этого шага
    var steps=[
      [r.called,'Позвонить',r.called?'позвонили'+(r.called_at?' '+wkpShort(r.called_at):''):'отметьте после звонка','<label class="proc-chk">'+field(row,'called','Позвонил','checkbox')+' Позвонил</label>'],
      [r.ready==='yes','Готовы сотрудничать?',r.ready==='yes'?'да — ждут предложения':r.ready==='no'?'нет':'не спросили',field(row,'ready','Готовы',null,ready),r.ready==='no'],
      [!!r.fee,'Гонорар',r.fee?wkMoney(r.fee)+' ₽'+(r.cashless?' + '+r.cashless+' %':''):'узнать у коллектива','<span class="proc-pair">'+field(row,'fee','Гонорар','number').replace('>',' placeholder="гонорар, ₽">')+field(row,'cashless','% сверху','number').replace('>',' placeholder="% сверху">')+'</span>'],
      [!!L,'Подбор городов',L?'гонорар '+(wkMoney((L.econ||{}).fee)||'—')+' · '+wkPickOffer(L):'финмодели по городам','<span class="proc-link">'+field(row,'list','Подбор городов',null,[['',L?'—':'Связать с подбором…']].concat(Object.keys(PLAN.lists).sort(function(a,b){return (PLAN.lists[a].title||'').localeCompare(PLAN.lists[b].title||'','ru');}).map(function(k){return [k,PLAN.lists[k].title];})))+'</span>'+(L?action('pick','Открыть подбор →',id):(alike(r)?action('link:'+alike(r),'Связать с «'+esc(PLAN.lists[alike(r)].title)+'»',id,'btn-dark'):'')+action('pick-create','Создать новый',id,alike(r)?'btn-ghost':'btn-dark'))+(task?action('task-open','Задача: '+esc(task.text)+' →',id,'pj-plain proc-ell'):action('task-create','Создать задачу',id))],
      [!!sent,'Согласовать с руководителем',!L?'после подбора городов':sh&&sent?'ссылка отправлена · ✔ '+sh.ok+' · ? '+sh.ask+' · ✖ '+sh.no:'ссылка не отправлялась',L?action('pdf','PDF руководителю',id)+shareLink(sh):''],
      [at>=stageAt('offer')&&!out,'Отправить предложение артисту',at>=stageAt('answered')&&!out?'артист ответил':at===stageAt('offer')?'отправлено, ждём ответа':'после согласования',at<stageAt('offer')?action('stage:offer','Отправили',id):r.stage==='offer'?action('stage:answered','Ответили',id):''],
      [!!(r.cities||[]).length,'Возможные города',(r.cities||[]).length?(r.cities.map(function(c){return c.city;}).join(', ')+(r.cities_at?' · '+wkpShort(r.cities_at):'')):'города «подходит» из подбора',L?action('cities',(r.cities||[]).length?'Обновить':'Зафиксировать',id):''],
      [r.stage==='decided','Решение',r.stage==='decided'?(r.season==='this'?'этот сезон':r.season==='next'?'следующий сезон':'принято'):'этот или следующий сезон',action('decision:this','Этот сезон',id,r.stage==='decided'&&r.season==='this'?'btn-dark':'btn-ghost')+action('decision:next','Следующий сезон',id,r.stage==='decided'&&r.season==='next'?'btn-dark':'btn-ghost')],
      [!!WK.projects[r.project],'Проект «Работы»',WK.projects[r.project]?'создан':'после решения',r.stage==='decided'?(WK.projects[r.project]?action('project-open','Открыть проект →',id):action('project-create','Создать проект «Работы»',id,'btn-dark')):'']
    ];
    var html='<div class="proc-dhead"><div><h2>'+esc(r.title)+'</h2><div class="proc-dtags">'+tag(r.stage)+(r.season?'<span class="wkp-pill ps-green">'+esc(wkLabel(season,r.season))+'</span>':'')+'</div></div>'+action('close',PJ_ICON.close,null,'icon-btn',' aria-label="Закрыть карточку"')+'</div>'+
      (hints(r,sh).length?'<div class="proc-hints">'+hints(r,sh).map(function(s){return '<span>Перевести в «'+esc(label(s))+'»?</span>'+action('stage:'+s,'Перевести',id,'btn-dark');}).join('')+'</div>':'')+
      '<section class="proc-sec"><h3>Шаги процесса</h3><ol class="proc-steps">'+steps.map(function(s,i){return '<li class="'+(s[0]?'done':s[4]?'no':'')+'"><span class="proc-dot" aria-hidden="true">'+(s[0]?'✓':s[4]?'✕':i+1)+'</span><div class="proc-stx"><b>'+s[1]+'</b><span>'+esc(s[2])+'</span></div><div class="proc-sact">'+s[3]+'</div></li>';}).join('')+'</ol></section>'+
      '<section class="proc-sec"><h3>Данные</h3><div class="form-grid proc-form">'+fields.map(function(f){return '<div class="field'+(f[4]?' full':'')+'"><label>'+f[1]+'</label>'+field(row,f[0],f[1],f[2],f[3])+'</div>';}).join('')+'</div></section>'+
      '<section class="proc-sec"><h3>Журнал</h3><form class="proc-log" data-lead-log="'+id+'"><input class="pl-in pl-text" name="text" maxlength="2000" placeholder="Добавить запись — Enter" aria-label="Запись в журнал" required></form>'+(r.log||[]).slice().reverse().map(function(l){return '<p class="proc-logl"><span class="sub2">'+esc(l.at.replace('T',' ').slice(0,16))+'</span>'+esc(l.text)+'</p>';}).join('')+'</section>';
    $('drawer').setAttribute('aria-label','Проект в воронке: '+r.title);
    if(keep){var dr=$('drawer'),y=dr.scrollTop,fo=document.activeElement&&dr.contains(document.activeElement)&&document.activeElement.getAttribute('data-lead-field');dr.innerHTML=html;dr.scrollTop=y;enhanceSelects(dr);var back=fo&&dr.querySelector('[data-lead-field="'+fo+'"]');if(back)back.focus({preventScroll:true});}else showDrawer(html);   // ввод по Tab не теряет поле после сохранения
  }
  // подбор с похожим названием, ещё ни с кем не связанный («Групп На-На» ↔ «Группа На-На»): подсказка в шаге 4
  function norm(t) { return String(t||'').toLowerCase().replace(/ё/g,'е').replace(/[^a-zа-я0-9]+/g,''); }
  function dist(a,b) { var d=[],i,j; for(i=0;i<=a.length;i++)d[i]=[i]; for(j=0;j<=b.length;j++)d[0][j]=j; for(i=1;i<=a.length;i++)for(j=1;j<=b.length;j++)d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+(a[i-1]===b[j-1]?0:1)); return d[a.length][b.length]; }
  function alike(r) { var t=norm(r.title),best=null,bd=1e9; if(t.length<3)return null; Object.keys(PLAN.lists).forEach(function(k){var L=PLAN.lists[k];if((L.work||{}).lead)return;var x=norm(L.title),d=dist(t,x);if(d<bd&&d<=Math.max(1,Math.floor(Math.max(t.length,x.length)*0.25))){bd=d;best=k;}}); return best; }
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
    else if(a.indexOf('link:')===0) await linkList(id,a.slice(5));
    else if(a.indexOf('stage:')===0) await save('leads',id,Object.assign({},r,{stage:a.slice(6)}));
    else if(a.indexOf('decision:')===0) await save('leads',id,Object.assign({},r,{stage:'decided',season:a.slice(9)}));
    redraw();if(state.lead===id)panel(id,true);
  }
  function openPick(id,pdf) {var r=WK.leads[id];if(!r||!PLAN.lists[r.list])return;closeDrawer();state.lead=null;S.pl.tab='build';S.pl.tb.list=r.list;S.pl.tb.draft=null;goView('planning');if(pdf)tbOfferDoc('boss');}
  document.addEventListener('click',function(ev){
    var op=ev.target.closest&&ev.target.closest('[data-proc-open]');if(op){open(op.getAttribute('data-proc-open'));return;}
    var b=ev.target.closest&&ev.target.closest('[data-proc-action]');if(!b)return;ev.preventDefault();var a=b.getAttribute('data-proc-action'),id=b.getAttribute('data-id');
    if(a==='lead'||a==='lead-link'){var d=$('pjDlg');if(d&&d.open)d.close();var r=WK.leads[id];if(!r)return;if(r.proc)open(r.proc);else{state.id=null;goView('wkproc');}ixSharesLoad();panel(id);return;}
    if(a==='close'){state.lead=null;closeDrawer();return;}if(a==='back'){state.id=null;redraw();return;}if(a==='new'||a==='edit'){edit(id);return;}
    if(a==='tasks'||a==='funnel'){state.tab=a;redraw();return;}if(a==='add'){var inp=document.querySelector('[data-proc-add] input');if(inp){inp.scrollIntoView({block:'center'});inp.focus();}return;}if(a==='table'||a==='board'){state.mode=a;redraw();return;}
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
    patch(id,p,!!el.closest('#drawer')||el.tagName==='SELECT'||el.type==='checkbox').then(function(){var r=WK.leads[id];if(!state.lead&&hints(r).length){var s=hints(r)[0];toast('Сохранено');askConfirm('Перевести в «'+label(s)+'»?','Этап изменится только после подтверждения.','Перевести',function(){patch(id,{stage:s});});}},function(){});
  });
  document.addEventListener('submit',function(ev){var f=ev.target;
    if(f.hasAttribute('data-proc-add')){ev.preventDefault();var title=f.elements.title.value.trim(),proc=f.getAttribute('data-proc-add');if(!title)return;f.elements.title.value='';enqueue(async function(){await save('leads',wkId('l'),{title:title,proc:proc,stage:'found',order:leads(proc).length,created:wkDay(0)});redraw();var i=document.querySelector('[data-proc-add] input');if(i)i.focus();});}
    if(f.hasAttribute('data-lead-log')){ev.preventDefault();var id=f.getAttribute('data-lead-log'),text=f.elements.text.value.trim();if(text)enqueue(async function(){var r=WK.leads[id];await save('leads',id,Object.assign({},r,{log:(r.log||[]).concat([{id:wkId('log'),at:wkStamp(),text:text}])}));panel(id,true);});}
    if(f.hasAttribute('data-proc-edit')){ev.preventDefault();var pid=f.getAttribute('data-proc-edit')||wkId('proc'),file=f.elements.cover.files[0],remove=f.elements.removeCover&&f.elements.removeCover.checked,rec=Object.assign({},WK.procs[pid]||{kind:f.elements.kind.value},{title:f.elements.title.value.trim(),note:f.elements.note.value});if(!rec.title)return;var submit=f.querySelector('button');submit.disabled=true;enqueue(async function(){await save('procs',pid,rec);if(file||remove){var data=file?await new Promise(function(resolve,reject){var reader=new FileReader();reader.onload=function(){resolve(reader.result);};reader.onerror=reject;reader.readAsDataURL(file);}):'';WK=await request('/api/work',{op:'media',kind:'procs',id:pid,what:'cover',data:data});}$('pjDlg').close();redraw();}).then(function(){submit.disabled=false;},function(){submit.disabled=false;});}
  });
  var timer;document.addEventListener('input',function(ev){if(ev.target.id!=='procQ')return;state.q=ev.target.value;clearTimeout(timer);timer=setTimeout(function(){redraw();var i=$('procQ');if(i)i.focus();},180);});
  document.addEventListener('keydown',function(ev){var c=ev.target.closest&&ev.target.closest('[data-proc-open]');if(c&&ev.key==='Enter'){ev.preventDefault();c.click();}});
  var drag=null;document.addEventListener('dragstart',function(ev){var c=ev.target.closest&&ev.target.closest('[data-lead-drag]');if(!c)return;drag=c.getAttribute('data-lead-drag');ev.dataTransfer.setData('text/plain',drag);ev.dataTransfer.effectAllowed='move';});
  document.addEventListener('dragover',function(ev){var col=drag&&ev.target.closest&&ev.target.closest('[data-lead-drop]');document.querySelectorAll('[data-lead-drop].drop').forEach(function(c){if(c!==col)c.classList.remove('drop');});if(col){ev.preventDefault();col.classList.add('drop');}});
  document.addEventListener('drop',function(ev){var col=ev.target.closest&&ev.target.closest('[data-lead-drop]');if(!drag||!col)return;ev.preventDefault();var id=drag;drag=null;var stage=col.getAttribute('data-lead-drop'),before=ev.target.closest('[data-lead-drag]');var list=leads(state.id).filter(function(r){return r.stage===stage&&r.id!==id;}).sort(function(a,b){return (a.order||0)-(b.order||0);});var at=before?list.findIndex(function(r){return r.id===before.getAttribute('data-lead-drag');}):list.length;list.splice(at<0?list.length:at,0,WK.leads[id]);enqueue(async function(){for(var i=0;i<list.length;i++){var row=list[i],rid=row.id||id;await save('leads',rid,Object.assign({},WK.leads[rid],{stage:stage,order:i}));}redraw();});});
  document.addEventListener('dragend',function(){drag=null;document.querySelectorAll('[data-lead-drop].drop').forEach(function(c){c.classList.remove('drop');});});
  api.closed=function(){state.lead=null;};
  api.refreshShares=function(){if(state.lead && $('drawer').classList.contains('open'))panel(state.lead,true);};
  api.page=page;api.scope=scope;api.owner=owner;api.normalize=normalize;api.ownerName=ownerName;api.ownerOptions=ownerOptions;api.open=open;api.link=link;
  api.taskLine=function(id){return records('leads').filter(function(r){return r.task===id;}).map(function(r){return '<div class="wk-pick">Воронка: '+link(r.id,r.title)+' · '+link(r.id,'Открыть →')+'</div>';}).join('');};
  api.chip=function(L){var id=(L.work||{}).lead;return id&&WK.leads&&WK.leads[id]?'<span class="tb-wchip">Воронка: '+link(id)+'</span>':'';};
  api.projectLine=function(p){return p.lead&&WK.leads&&WK.leads[p.lead]?'<div class="wk-pick">Воронка: '+link(p.lead,WK.leads[p.lead].title)+'</div>':'';};
})(typeof window!=='undefined'?window:globalThis);
