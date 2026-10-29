// Постоянные процессы и CRM поиска проектов (PROCESSES_PLAN.md: решения 27.10; версия 2 воронки — раздел 10, 29.10).
// Задачи/календарь/фокус/заметки используют существующие компоненты проекта через область proc:<id>.
(function (root) {
  'use strict';
  // этапы v2: 8 в воронке, «Резерв» и «Отказ» — вне её (не видны в таблице и на доске, свои списки)
  var stages = [['found','На входе'],['called','Позвонили'],['discuss','Готовы, обсуждаем с руководителем'],['ready','Готовы, ждут предложения'],['offer','Получили предложение'],['answered','Ответили на предложение'],['approve','Согласование с руководителем'],['booking','Готово к бронированию площадок'],['reserve','Резерв'],['declined','Отказ']];
  var FUNNEL = stages.slice(0,8), OFF = ['reserve','declined'];
  var ready = [['','—'],['yes','Да'],['no','Нет']];
  var SEASON = [[9,'Сен'],[10,'Окт'],[11,'Ноя'],[12,'Дек'],[1,'Янв'],[2,'Фев'],[3,'Мар'],[4,'Апр']];
  var WHY = ['Работают с другим организатором','На эксклюзиве','Нет свободных дат','Не гастролируют','Не устроил гонорар','Не интересно'];
  function off(r) { return OFF.indexOf(r.stage)>=0; }
  // «перезвонить»: дата шага наступила (в резерве — «вернуться к вопросу»); финал и отказ не напоминают
  function due(r, today) { return !!r.next_at && r.next_at<=today && r.stage!=='booking' && r.stage!=='declined'; }
  function counts(rows, today) { var n={total:0,due:0,ready:0,approve:0,booking:0,reserve:0,declined:0}; rows.forEach(function (r) { if(off(r)){n[r.stage]++;return;} n.total++; if(due(r,today))n.due++; if(r.stage in n)n[r.stage]++; }); return n; }
  function hints(r, sh) { var a=[]; if(r.stage==='found' && r.called) a.push('called'); if(r.ready==='yes' && ['found','called'].indexOf(r.stage)>=0) a.push('discuss'); if(sh && sh.versions && r.stage==='ready') a.push('offer'); return a; }
  function matches(r, f, today) { return (f.show!=='due' || due(r,today)) && (!f.stage || r.stage===f.stage) && (!f.list || !!r.list===(f.list==='yes')) && (!f.pj || !!r.pj===(f.pj==='yes')); }
  function inList(r, list) { return list==='work' ? !off(r) : r.stage===list; }
  // сезон — сентябрь…апрель; летом «этот сезон» — ближайший
  function season(today) { var y=+today.slice(0,4), m=+today.slice(5,7), s=m<=4?y-1:y; return {from:s+'-09-01',to:(s+1)+'-04-30',next:{from:(s+1)+'-09-01',to:(s+2)+'-04-30'}}; }
  var api={stages:stages, counts:counts, hints:hints, matches:matches, due:due, inList:inList, season:season};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  root.WorkProcesses=api;
  if(typeof document==='undefined') return;
  var ASK_KEY='ticketmonitor.proc.discussAsk';
  var state={id:null,tab:'funnel',mode:'table',list:'work',q:'',filters:{},lead:null,init:false,wkReq:false}, queue=Promise.resolve();
  function records(k) { return Object.keys(WK[k]||{}).map(function(id){return Object.assign({id:id},WK[k][id]);}); }
  function leads(id) { return records('leads').filter(function(r){return (r.proc||'')===id;}); }
  function label(v) { return wkLabel(stages,v); }
  // цвета этапов — из палитры стадий «Проектов» (ps-*)
  var colors={found:'gray',called:'blue',discuss:'mint',ready:'amber',offer:'violet',answered:'teal',approve:'peach',booking:'green',reserve:'gray',declined:'pink'};
  // на доске колонки узкие (8 этапов во всю ширину, 28.10) — короткие названия, полное — в подсказке
  var SHORT={found:'На входе',called:'Позвонили',discuss:'Обсуждаем',ready:'Ждут предложения',offer:'Получили предложение',answered:'Ответили',approve:'Согласование',booking:'Бронирование'};
  function tag(s,n,short) { return '<span class="wkp-tag ps-'+(colors[s]||'gray')+'"'+(short?' title="'+esc(label(s))+'"':'')+'><i aria-hidden="true"></i>'+esc((short&&SHORT[s])||label(s)||'—')+(n!=null?' <span>'+n+'</span>':'')+'</span>'; }
  function stageAt(s) { return stages.findIndex(function(x){return x[0]===s;}); }
  function action(a,text,id,cls,attrs) {
    return '<button type="button" class="'+(cls||'btn-ghost')+'" data-proc-action="'+a+'"'+(id?' data-id="'+esc(id)+'"':'')+(attrs||'')+'>'+text+'</button>';
  }
  function link(id,text) { return action('lead',esc(text||label((WK.leads[id]||{}).stage)),id,'pj-plain'); }
  function enqueue(fn) { var run=queue.then(fn); queue=run.catch(function(e){toast('Не сохранено: '+e.message);}); return run; }
  async function request(path,op) { var x=await apiJson('POST',path,op); if(!x.ok) throw new Error((x.d||{}).error||'ошибка записи'); return x.d; }
  async function save(kind,id,data) { WK=await request('/api/work',{op:'put',kind:kind,id:id,data:data}); return WK[kind][id]; }
  async function myPost(op) { MYP=await request('/api/market/myprojects',op); return MYP; }
  function redraw() { var y=window.scrollY; render(); window.scrollTo(0,y); }
  function refreshPanel(id) { if(state.lead===id && $('drawer').classList.contains('open')) panel(id,true); }
  function patch(id,p,refresh) { return enqueue(async function(){var r=WK.leads[id]; if(!r) return; var old=Object.assign({},r); await save('leads',id,Object.assign({},r,p)); if('fee' in p||'cashless' in p||'pj' in p) await feeSync(id,old); if(refresh!==false) redraw(); refreshPanel(id);}); }
  function scope() { return S.view==='wkproc' && state.id ? 'proc:'+state.id : S.wk.proj; }
  function owner(r) { return r.proc ? 'proc:'+r.proc : r.project||''; }
  function normalize(r) { r=Object.assign({},r); if((r.project||'').indexOf('proc:')===0) {r.proc=r.project.slice(5);r.project='';} return r; }
  function ownerName(r) { return r.proc ? ((WK.procs||{})[r.proc]||{}).title||'' : wkPname(r.project); }
  function ownerOptions(v,empty) { return wkProjOpts(v,empty)+records('procs').map(function(p){return '<option value="proc:'+p.id+'"'+(v==='proc:'+p.id?' selected':'')+'>Процесс: '+esc(p.title)+'</option>';}).join(''); }
  function open(id) { closeDrawer(); state.lead=null; state.id=id;state.tab=((WK.procs||{})[id]||{}).kind==='artists'?'funnel':'tasks';state.q='';state.filters={};state.list='work';S.wk.mcal=null;S.wk.qs={open:'',done:''};S.wk.qAt={};goView('wkproc');redraw(); }
  function leadTasks(id) { return records('tasks').filter(function(t){return t.lead===id;}).sort(function(a,b){return (+!!a.done)-(+!!b.done)||(a.due||'9').localeCompare(b.due||'9');}); }
  function cbText(r) { return !r.next||/^в ожидании$/i.test(r.next)?'Перезвонить':r.next; }
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k,v) { try { localStorage.setItem(k,v); } catch (e) {} }

  // ---------------------------------------------------------------- «Репертуар»: карточка проекта записи (leads.pj)
  function pjRec(r) { return r && r.pj && MYP && MYP.projects ? MYP.projects[r.pj] : null; }
  function pjAva(p) { var a=typeof pjMedia==='function'?pjMedia(p,'avatar'):''; return '<span class="proc-ava">'+(a?'<img src="'+esc(a)+'" alt="">':esc(pjInitials(p.title)))+'</span>'; }
  function feeText(r) { return r.fee?wkMoney(r.fee)+' ₽'+(r.cashless?' + '+String(r.cashless).replace('.',',')+' %':''):''; }
  async function feeSync(id,old) {   // гонорар — в карточку проекта (решение 4): только из воронки, обратно не меняется
    var r=WK.leads[id]; if(!r||!pjRec(r)) return;
    if(old && old.pj===r.pj && feeText(old)===feeText(r)) return;
    if(!r.fee) return;
    await myPost({op:'fee',id:r.pj,fee:feeText(r)});
  }
  // карточка «Репертуара» с похожим названием, ещё не связанная ни с одной записью: подсказка «Связать»
  function pjAlike(r) {
    var t=norm(r.title),best=null,bd=1e9,used={}; if(t.length<3||!MYP||!MYP.projects) return null;
    records('leads').forEach(function(x){if(x.pj)used[x.pj]=1;});
    Object.keys(MYP.projects).forEach(function(k){if(used[k])return;var x=norm(MYP.projects[k].title),d=x.indexOf(t)>=0||t.indexOf(x)>=0?0:dist(t,x);if(d<bd&&d<=Math.max(1,Math.floor(Math.max(t.length,x.length)*0.25))){bd=d;best=k;}});
    return best;
  }
  function pjCell(r) {
    var p=pjRec(r);
    if(p) return '<span class="proc-pjl">'+pjAva(p)+action('pj-open',esc(p.title),r.id,'pj-plain proc-ell')+'</span>';
    var s=pjAlike(r); return s?action('pj-link:'+s,'связать: '+esc(MYP.projects[s].title),r.id,'pj-plain proc-sug'):'<span class="sub2">—</span>';
  }
  function openPj(pid) {
    var p=MYP.projects[pid]; if(!p) return;
    closeDrawer(); state.lead=null; goView('projects'); S.m.vproj=S.m.vsel=p.keys[0]; render(); window.scrollTo(0,0);
  }
  function riderUrl(x) { return '/api/market/myprojects/media/'+encodeURIComponent(x.file)+'?n='+encodeURIComponent(x.label||x.file); }

  // ---------------------------------------------------------------- таблицы
  function installCols() {
    if(PL_COLSETS.leads) return;
    var mk=function(id,key,defs){PL_COLSETS[id]={id:id,key:key,cols:defs.map(function(c,i){return {id:c[0],labels:[c[1]],w:c[2],left:true,lock:i===0,off:!!c[3]};})};};
    // по умолчанию — что нужно для прозвона и «перезвонить»; остальное — «Столбцы таблицы» (ключ leadcols2: набор v2, 29.10)
    mk('leads','leadcols2',[['title','Проект',220],['stage','Этап',210],['fee','Гонорар',112],['next','Следующий шаг',210],['next_at','Перезвонить',176],['list','Подбор городов',124],['tasks','Задачи',82],['pj','Карточка проекта',190],['called','Позвонил',90,1],['ready','Готовы',96,1],['cashless','% сверху',90,1],['contact','Контакт',200,1],['called_at','Дата звонка',132,1],['source','Источник',180,1],['note','Заметка',220,1],['cities','Возможные города',210,1]]);
    mk('leadsres','leadrescols2',[['title','Проект',220],['why','Почему не сейчас',280],['next_at','Вернуться к вопросу',176],['fee','Гонорар',112],['contact','Контакт',190],['pj','Карточка проекта',190],['back','',184]]);
    mk('leadsdec','leaddeccols2',[['title','Проект',220],['why','Причина отказа',320],['called_at','Дата звонка',132],['contact','Контакт',190],['pj','Карточка проекта',190],['back','',184]]);
  }
  function field(r,k,title,type,opts) {
    var v=r[k],attr=' data-lead-field="'+k+'" data-id="'+r.id+'" aria-label="'+esc(title)+'"';
    // списки — фирменные выпадающие сайта (enhanceSelects), поля — как в таблицах «Планирования»
    if(opts) return '<select class="pl-sel"'+attr+'>'+wkOpts(opts.map(function(o){return [o[0],esc(o[1])];}),v||'')+'</select>';
    if(type==='checkbox') return '<input type="checkbox" class="wk-check"'+attr+(v?' checked':'')+'>';
    if(type==='textarea') return '<textarea class="pl-in pl-text"'+attr+'>'+esc(v||'')+'</textarea>';
    return '<input class="pl-in'+(type==='number'?' proc-num':' pl-text')+'"'+attr+' type="'+(type||'text')+'" value="'+esc(v==null?'':String(v))+'"'+(type==='number'?' min="0" step="any"':'')+'>';
  }
  function cbBtns(id) { return '<span class="proc-cbq">'+action('cb:2','+2 дня',id,'proc-q',' title="Перезвонить через 2 дня"')+action('cb:7','+7',id,'proc-q',' title="Перезвонить через 7 дней"')+'</span>'; }
  function cell(c,r) {
    var k=c.id,h,t0=wkDay(0);
    if(k==='title') h=link(r.id,r.title);
    else if(k==='list') h=PLAN.lists[r.list]?action('pick','Открыть →',r.id,'pj-plain'):action('lead-link','связать',r.id,'pj-plain proc-muted');
    else if(k==='tasks') { var ts=leadTasks(r.id),o=ts.filter(function(t){return !t.done;}).length; h=ts.length?action('lead','<span class="proc-tn">'+o+'/'+ts.length+'</span>',r.id,'pj-plain',' title="Открытых задач: '+o+' из '+ts.length+'"'):'<span class="sub2">—</span>'; }
    else if(k==='pj') h=pjCell(r);
    else if(k==='back') h=action('back-work','Вернуть в работу',r.id,'btn-ghost proc-back');
    else if(k==='cities') h=esc((r.cities||[]).map(function(c){return c.city;}).join(', ')||'—');
    else if(k==='why') h=field(r,'why',c.labels[0]).replace('>',' maxlength="1000" placeholder="'+(r.stage==='declined'?'Укажите причину':'—')+'">');
    else if(k==='next_at') h='<span class="proc-cbw">'+field(r,'next_at',c.labels[0],'date')+(off(r)&&r.stage==='declined'?'':cbBtns(r.id))+'</span>';
    else h=field(r,k,c.labels[0],k==='called'?'checkbox':k==='fee'||k==='cashless'?'number':/_at$/.test(k)?'date':null,k==='stage'?stages:k==='ready'?ready:null);
    return '<td class="pl-left'+(k==='stage'?' proc-stage ps-'+(colors[r.stage]||'gray'):'')+(k==='title'?' proc-tt':'')+(k==='why'&&r.stage==='declined'&&!r.why?' proc-nowhy':'')+(k==='next_at'&&due(r,t0)?' proc-over':'')+'">'+h+'</td>';
  }
  function sortVal(k,r) { if(k==='stage')return stageAt(r.stage); if(k==='called')return +!!r.called;if(k==='cities')return (r.cities||[]).length;if(k==='tasks')return leadTasks(r.id).length;if(k==='pj'){var p=pjRec(r);return p?p.title:null;}if(k==='back')return null;return r[k]==null||r[k]===''?null:r[k]; }
  // «Фильтр» — как у «Проектов» (wkpFilterOpen): разделы, пункты, галочка; бывшие плитки шапки — здесь (решение 8, 29.10)
  function filterHtml() {
    var f=state.filters,rows=leads(state.id).filter(function(r){return !off(r);}),t0=wkDay(0);
    var item=function(key,val,lbl,n,dot,hot){var on=(f[key]||'')===val;return '<button type="button" class="wk-menu-item'+(on?' on':'')+'" data-proc-action="f:'+key+':'+val+'" role="menuitemradio" aria-checked="'+on+'"><span class="proc-fl">'+(dot?'<i class="proc-fdot ps-'+colors[dot]+'"></i>':'')+lbl+'</span>'+(n!=null?'<span class="proc-fc'+(hot&&n?' hot':'')+'">'+n+'</span>':'')+(on?WKT_ICON.check:'<span class="proc-fph"></span>')+'</button>';};
    var n=function(fn){return rows.filter(fn).length;};
    return '<div class="wkp-title">Показать</div>'+item('show','','Все в работе',rows.length)+item('show','due','Пора перезвонить',n(function(r){return due(r,t0);}),null,true)+
      '<div class="wkp-title">Этап</div>'+item('stage','','Все этапы')+FUNNEL.map(function(s){return item('stage',s[0],esc(s[1]),n(function(r){return r.stage===s[0];}),s[0]);}).join('')+
      '<div class="wkp-title">Подбор городов</div>'+item('list','','Все')+item('list','yes','Есть подбор',n(function(r){return !!r.list;}))+item('list','no','Нет подбора',n(function(r){return !r.list;}))+
      '<div class="wkp-title">Карточка проекта</div>'+item('pj','','Все')+item('pj','yes','Связана',n(function(r){return !!r.pj;}))+item('pj','no','Не связана',n(function(r){return !r.pj;}))+
      (Object.keys(f).some(function(k){return f[k];})?action('reset','Сбросить фильтры',null,'proc-freset'):'');
  }
  function filterOpen() { var b=document.querySelector('.proc-tools [data-proc-action="filter"]'); if(b) wkPopOpen(b,'wk-menu proc-fmenu',filterHtml(),{}); }
  function funnel(id) {
    installCols();
    var all=leads(id),t0=wkDay(0),list=state.list,fl=list==='work'?state.filters:{};
    var rows=all.filter(function(r){return inList(r,list) && matches(r,fl,t0) && (!state.q || [r.title,r.contact,r.why].join(' ').toLowerCase().indexOf(state.q.toLowerCase())>=0);});
    var nf=Object.keys(state.filters).filter(function(k){return state.filters[k];}).length,n=counts(all,t0);
    // панель — как у «Проектов» (wkpBar): вид и список слева; поиск, фильтр, столбцы и «+» справа
    var seg=list!=='work'?'':'<div class="wkp-seg" role="group" aria-label="Вид воронки">'+[['table','Таблица',WKP_VIEWS[1][2]],['board','Доска',WKP_VIEWS[0][2]]].map(function(v){return action(v[0],v[2]+'<span class="wkp-segl">'+v[1]+'</span>',null,'proc-seg',' aria-pressed="'+(state.mode===v[0])+'" title="'+v[1]+'"');}).join('')+'</div>';
    var lists='<div class="wkp-seg proc-lists" role="group" aria-label="Список">'+[['work','В работе',n.total],['reserve','Резерв',n.reserve],['declined','Отказы',n.declined]].map(function(v){return action('list:'+v[0],'<span class="wkp-segl">'+v[1]+'</span><span class="proc-segn">'+v[2]+'</span>',null,'proc-seg',' aria-pressed="'+(list===v[0])+'"');}).join('')+'</div>';
    var bar='<div class="wkp-bar proc-tools">'+seg+lists+'<span class="wkp-sp"></span>'+
      '<label class="wkp-search">'+WKP_IC.search+'<input type="search" id="procQ" value="'+esc(state.q)+'" placeholder="Поиск проектов" aria-label="Найти проект в воронке"></label>'+
      (list==='work'?action('filter',WKP_IC.filter+'Фильтр'+(nf?'<span class="proc-fn">'+nf+'</span>':''),null,'wkp-filter'+(nf?' on':''),' aria-haspopup="menu" aria-label="Фильтры воронки"'):'')+((state.mode==='table'||list!=='work')?plColsControl(list==='work'?'leads':list==='reserve'?'leadsres':'leadsdec'):'')+
      action('add',WKT_ICON.plus,null,'wk-sq wk-sq-add',' aria-label="Новый проект в воронке" title="Новый проект в воронке"')+'</div>';
    // разовый перенос (вопрос пользователю 29.10): «Позвонили» + «Готовы: да» — по логике v2 это «обсуждаем с руководителем»
    var ask=all.filter(function(r){return r.stage==='called'&&r.ready==='yes';}).length,noWhy=all.filter(function(r){return r.stage==='declined'&&!r.why;}).length;
    var banners=(ask&&list==='work'&&lsGet(ASK_KEY)!=='no'?'<div class="proc-banner"><span><b>'+ask+'</b> '+plural(ask,'запись','записи','записей')+' на этапе «Позвонили» отмечены «Готовы: да». По новой логике это этап «Готовы, обсуждаем с руководителем». Перенести?</span>'+action('ask-yes','Перенести',null,'btn-dark')+action('ask-no','Оставить в «Позвонили»')+'</div>':'')+
      (noWhy&&list!=='declined'?'<div class="proc-banner warn"><span>У '+noWhy+' '+plural(noWhy,'отказа','отказов','отказов')+' не указана причина.</span>'+action('list:declined','Показать отказы')+'</div>':'');
    var add='<form class="proc-add" data-proc-add="'+id+'"><span aria-hidden="true">+</span><input name="title" maxlength="300" placeholder="Добавить проект — название и Enter" aria-label="Новый проект в воронке" required autocomplete="off"></form>';
    var set=list==='work'?'leads':list==='reserve'?'leadsres':'leadsdec';
    var body=list==='work'&&state.mode==='board'?board(rows)+add:fit(tbGrid(rows,set,{sortable:true,cell:cell,sortVal:sortVal,name:function(r){return r.title;},defSort:list==='work'?{id:'stage',dir:-1}:{id:'title',dir:1}}));
    if(list==='work'&&state.mode==='table') body=body.replace('</table></section>','</table></section>'+add);
    var empty=!rows.length?'<p class="wkp-none">'+(state.q||nf&&list==='work'?'Ничего не нашлось — измените поиск или фильтр.':list==='reserve'?'В «Резерве» пусто. Сюда попадают проекты, готовые сотрудничать, которые сейчас не берём: этап «Обсуждаем с руководителем» → «Не сейчас — в резерв».':list==='declined'?'Отказов нет.':'')+'</p>':'';
    return banners+'<div class="proc-funnel'+(state.mode==='table'||list!=='work'?' is-table':'')+(list!=='work'?' is-off':'')+'">'+bar+body+empty+(list==='work'?'<p class="proc-offnote">«Резерв» и «Отказ» здесь не показываются — переключатель «В работе · Резерв · Отказы».</p>':'')+'</div>';
  }
  // таблица — во всю ширину без прокрутки вбок (просьба пользователя 28.10): ширины столбцов — доли от заданных;
  // на узком экране — не уже 70 % заданного, дальше прокрутка (иначе на телефоне не прочитать)
  function fit(h) {
    var sum=0; h.replace(/<col data-plcol="[^"]+" style="width:(\d+)px">/g,function(m,w){sum+=+w;return m;}); if(!sum) return h;
    return h.replace(/(<table class="[^"]*tb-grid" style=")width:\d+px/,'$1width:100%;min-width:'+Math.round(sum*0.7)+'px').replace(/<col data-plcol="([^"]+)" style="width:(\d+)px">/g,function(m,id,w){return '<col data-plcol="'+id+'" style="width:'+(w/sum*100).toFixed(2)+'%">';});
  }
  function board(rows) {   // колонки и карточки — как канбан «Проектов» (wkpKanban); «Резерв» и «Отказ» — не колонки
    var t0=wkDay(0);
    return '<div class="wkp-kb proc-board">'+FUNNEL.map(function(s){var list=rows.filter(function(r){return r.stage===s[0];}).sort(function(a,b){return (a.order||0)-(b.order||0);});
      var cards=list.map(function(r){var over=due(r,t0);
        return '<div class="wkp-kc proc-lead" draggable="true" data-lead-drag="'+r.id+'"><div class="wkp-nm">'+link(r.id,r.title)+'</div>'+
          (r.next||r.next_at?'<div class="proc-next'+(over?' over':'')+'">'+(r.next_at?'<b>'+WKP_IC.flag+esc(wkpShort(r.next_at))+'</b> ':'')+esc(r.next||'')+'</div>':'')+
          '<div class="wkp-kc-row"><span class="proc-fee">'+(r.fee?esc(wkMoney(r.fee))+' ₽':'<span class="sub2">гонорар?</span>')+'</span><span class="wkp-chips">'+(r.list?'<span class="wkp-chip">подбор</span>':'')+(leadTasks(r.id).length?'<span class="wkp-chip">задача</span>':'')+(r.pj?'<span class="wkp-chip">карточка</span>':'')+'</span></div></div>';}).join('');
      return '<div class="wkp-col" data-lead-drop="'+s[0]+'"><div class="wkp-gh">'+tag(s[0],list.length,true)+'</div><div class="wkp-kcs">'+(cards||'<div class="wkp-kc-empty">Перетащите сюда проект</div>')+'</div></div>';
    }).join('')+'</div>';
  }
  function page() {
    var gate=wkGate('Процессы');if(gate)return gate;
    WK.procs=WK.procs||{};WK.leads=WK.leads||{};
    if(!Object.keys(WK.procs).length && !state.init) {state.init=true;enqueue(async function(){WK=await request('/api/work',{op:'init',kind:'procs',id:'defaults'});redraw();}).catch(function(){state.init=false;});}
    if(state.id && !WK.procs[state.id])state.id=null;
    var t0=wkDay(0);
    if(!state.id) return head('Процессы','')+'<div class="wkp-cards proc-cards">'+records('procs').sort(function(a,b){return (a.order||0)-(b.order||0);}).map(function(p){   // карточки — как «Карточки» проектов (wkpCards)
      var n=counts(leads(p.id),t0),ts=wkTasksOf('proc:'+p.id),open=ts.filter(function(t){return !t.done;}).length,over=ts.filter(function(t){return !t.done&&t.due&&t.due<t0;}).length;
      var li=p.kind==='artists'?['в воронке: '+n.total,'перезвонить: '+n.due,'ждут предложения: '+n.ready,'к бронированию: '+n.booking]:['открытых задач: '+open+(over?', просрочено '+over:'')];
      return '<article class="wkp-card proc-card" tabindex="0" role="link" data-proc-open="'+p.id+'">'+(wkMedia(p,'cover')?'<img class="proc-cover" src="'+esc(wkMedia(p,'cover'))+'" alt="">':'')+'<h3>'+esc(p.title)+'</h3>'+(p.note?'<p class="proc-note1">'+esc(p.note)+'</p>':'')+'<ul>'+li.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul>'+
        '<div class="wkp-card-f"><span>'+esc(p.upd?wkpAgo(p.upd):'')+'</span><span class="wkp-sp"></span>'+(p.kind==='artists'?'':'<span class="wkp-pill ps-gray">'+(p.kind==='venue_dates'?'заготовка':'задачи')+'</span>')+'</div></article>';
    }).join('')+'<button type="button" class="wkp-card wkp-addcard" data-proc-action="new" aria-haspopup="dialog"><span aria-hidden="true">+</span>Новый процесс</button></div>'+(leads('').length?'<details class="proc-orphans"><summary>Без процесса · '+leads('').length+'</summary>'+leads('').map(function(r){return '<p>'+link(r.id,r.title)+'</p>';}).join('')+'</details>':'');
    ixSharesLoad();
    var p=WK.procs[state.id],id=state.id,sc='proc:'+id,cover=wkMedia(p,'cover'),n=counts(leads(id),t0),tasks=wkTasksOf(sc),done=tasks.filter(function(t){return t.done;}).length;
    if(p.kind!=='artists')state.tab='tasks';
    // шапка — как у проекта (wkProjectPage); у воронки плиток нет — числа в «Фильтре» (решение 8, 29.10)
    var stats=p.kind==='artists'?[]:[[tasks.filter(function(t){return !t.done&&t.due&&t.due<t0;}).length,'просрочено'],[done+'/'+tasks.length,'выполнено']];
    var openN=tasks.length-done,filtOn=S.wk.groupBy==='due'||!!S.wk.prioF,tab=function(a,t,num){return action(a,t+(num?' <span class="wk-tabn">'+num+'</span>':''),null,' ',' role="tab" aria-selected="'+(state.tab===a)+'"');};
    return '<section class="pj-hero wk-hero proc-hero'+(cover?' has-cover':'')+'"'+(cover?' style="background-image:url(\''+esc(cover)+'\')"':'')+'>'+action('back',PJ_ICON.back,null,'pj-back-btn',' aria-label="Назад: все процессы" title="Все процессы"')+'<div class="pj-top-right">'+action('delete',WKP_TRASH,id,'pj-cover-btn pj-icon wk-trash',' aria-label="Удалить процесс" title="Удалить процесс"')+'</div><div class="pj-hero-in"><div class="pj-hero-text"><h1 class="pj-name">'+esc(p.title)+'</h1>'+(p.note?'<p class="proc-hnote">'+esc(p.note)+'</p>':'')+'<div class="pj-actions">'+action('edit',PJ_ICON.edit+'Редактировать',id,'pj-btn primary')+'</div></div>'+(stats.length?'<div class="wk-hstats" role="group" aria-label="Задачи процесса">'+stats.map(function(x,i){return '<div class="wk-hstat'+(i===0&&x[0]?' over':'')+'"><b class="num">'+x[0]+'</b><span>'+x[1]+'</span></div>';}).join('')+'</div>':'')+'</div></section>'+
      '<div class="wk-ptabs-row"><div class="mtabs subtabs wk-ptabs" role="tablist" aria-label="Разделы процесса">'+(p.kind==='artists'?tab('funnel','Воронка',n.total):'')+tab('tasks','Задачи',openN)+'</div>'+(state.tab==='tasks'?'<div class="wk-tabtools"><button type="button" class="wk-sq'+(filtOn?' on':'')+'" data-wkt-groupmenu aria-haspopup="menu" aria-label="Фильтры и группировка задач" title="Фильтры и группировка">'+WKT_ICON.group+(filtOn?'<i class="wk-sq-dot" aria-hidden="true"></i>':'')+'</button><button type="button" class="wk-sq wk-sq-add" data-wkt-quickadd aria-haspopup="dialog" aria-label="Новая задача" title="Новая задача">'+WKT_ICON.plus+'</button></div>':'')+'</div>'+(state.tab==='funnel'?funnel(id):'<div class="wk-split"><div class="wk-split-main">'+wktTable(tasks,sc)+'</div><aside class="wk-split-side" aria-label="Календарь сроков и фокус">'+wkCalBlock(sc)+wkFocusBlock(sc)+'</aside></div>')+wkNotesGrid(sc);
  }
  function edit(id) { var p=WK.procs[id]||{};pjDialog('proc-editor',id?'Редактировать процесс':'Новый процесс','<form data-proc-edit="'+(id||'')+'" class="form-grid proc-form"><div class="field full"><label for="procT">Название</label><input id="procT" name="title" required maxlength="300" value="'+esc(p.title||'')+'"></div><div class="field full"><label for="procN">Описание — одна строка под названием</label><input id="procN" name="note" maxlength="3000" value="'+esc(p.note||'')+'"></div>'+(!id?'<div class="field full"><label for="procK">Вид</label><select id="procK" name="kind" data-native>'+wkOpts([['other','Задачи и заметки'],['artists','Поиск проектов (воронка)'],['venue_dates','Запрос дат у площадок']],'other')+'</select></div>':'')+'<div class="field full"><label for="procC">Обложка шапки</label><input id="procC" type="file" name="cover" accept="image/png,image/jpeg,image/webp"></div>'+(p.media&&p.media.cover?'<label class="proc-chk full"><input type="checkbox" class="wk-check" name="removeCover"> Убрать обложку</label>':'')+'<div class="form-actions full"><button class="btn-dark">Сохранить</button></div></form>'); }
  function shareLink(sh) {
    if(!sh || !(sh.tokens||[]).length)return '';
    var token=sh.tokens.slice().sort(function(a,b){return (b.created||'').localeCompare(a.created||'');})[0];
    var url=((S.pl.ixShares||{}).base||'http://127.0.0.1:5070')+'/s/'+token.token;
    return '<a class="pj-plain" href="'+esc(url)+'" target="_blank" rel="noopener">Ссылка руководителю →</a>';
  }

  // ---------------------------------------------------------------- смена этапа: окна и подсказки (решения 29.10)
  function setStage(id,s) {
    var r=WK.leads[id]; if(!r||r.stage===s) return;
    if(s==='declined') return askWhy(id);
    if(s==='reserve') return askHold(id);
    var p={stage:s}; if(s==='discuss'&&!r.ready) p.ready='yes';
    patch(id,p).then(function(){after(id,s);},function(){});
  }
  function after(id,s) {
    var r=WK.leads[id]; if(!r) return;
    if(s==='offer') askConfirm('Перезвонить через 2 дня?','«'+r.title+'»: предложение отправлено. Дата шага — '+wkpShort(wkDay(2))+', шаг — «Перезвонить».','Да',function(){callback(id,2);});
    else if(s==='ready'&&!leadTasks(id).some(function(t){return /^Подбор городов/.test(t.text);})) askTask(id,'Подбор городов: '+r.title);
    else if(s==='approve'&&!leadTasks(id).some(function(t){return /^Согласовать с руководителем/.test(t.text);})) askTask(id,'Согласовать с руководителем: '+r.title);
  }
  function callback(id,n) { var r=WK.leads[id]; if(r) patch(id,{next_at:wkDay(n),next:cbText(r)}); }
  function askWhy(id) {
    var r=WK.leads[id];
    pjDialog('proc-dlg','Отказ — '+r.title,'<form data-lead-why="'+id+'" class="proc-dform"><p class="sub2">Запись уйдёт из воронки в список «Отказы»; причина видна и в карточке проекта.</p><div class="proc-whyq">'+WHY.map(function(w){return action('why-q',esc(w),null,'proc-q',' data-v="'+esc(w)+'"');}).join('')+'</div>'+
      '<textarea name="why" maxlength="1000" required placeholder="Причина отказа" aria-label="Причина отказа">'+esc(r.why||'')+'</textarea><div class="form-actions">'+action('dlg-close','Отмена')+'<button class="btn-dark proc-red">'+(r.stage==='declined'?'Сохранить':'Отказ')+'</button></div></form>');
    var t=$('pjDlg').querySelector('textarea'); if(t) t.focus();
  }
  function askHold(id) {
    var r=WK.leads[id];
    pjDialog('proc-dlg','В резерв — '+r.title,'<form data-lead-hold="'+id+'" class="proc-dform"><p class="sub2">Готовы сотрудничать, но сейчас не берём. Запись уйдёт в список «Резерв»; в карточке проекта — статус «Резерв».</p>'+
      '<textarea name="why" maxlength="1000" placeholder="Почему не сейчас — необязательно" aria-label="Почему не сейчас"></textarea><label class="proc-dl">Вернуться к вопросу<input type="date" name="at" class="pl-in"></label><div class="form-actions">'+action('dlg-close','Отмена')+'<button class="btn-dark">В резерв</button></div></form>');
  }
  function askTask(id,text) {
    var r=WK.leads[id];
    pjDialog('proc-dlg',text?'Создать задачу?':'Новая задача','<form data-lead-task="'+id+'" class="proc-dform"><p class="sub2">Появится во вкладке «Задачи» процесса и в общих «Задачах».</p>'+
      '<input name="text" class="pl-in" maxlength="1000" required value="'+esc(text||'')+'" placeholder="Что сделать" aria-label="Задача"><label class="proc-dl">Срок<input type="date" name="due" class="pl-in" value="'+(r.next_at&&r.next_at>wkDay(0)?r.next_at:wkDay(2))+'"></label><div class="form-actions">'+action('dlg-close',text?'Не нужно':'Отмена')+'<button class="btn-dark">Создать</button></div></form>');
    var t=$('pjDlg').querySelector('input[name=text]'); if(t&&!text) t.focus();
  }

  // ---------------------------------------------------------------- карточка записи
  function panel(id,keep) {
    var r=WK.leads[id];if(!r)return;state.lead=id;var row=Object.assign({id:id},r),L=PLAN.lists[r.list],sh=(((S.pl.ixShares||{}).lists)||{})[r.list];
    var at=stageAt(r.stage),out=off(r),sent=sh&&(sh.tokens||[]).length,t0=wkDay(0),isAt=function(s){return !out&&at>=stageAt(s);},past=function(s){return !out&&at>stageAt(s);};
    var listSel='<span class="proc-link">'+field(row,'list','Подбор городов',null,[['',L?'—':'Связать с подбором…']].concat(Object.keys(PLAN.lists).sort(function(a,b){return (PLAN.lists[a].title||'').localeCompare(PLAN.lists[b].title||'','ru');}).map(function(k){return [k,PLAN.lists[k].title];})))+'</span>';
    var go=function(s,t,cls){return action('stage:'+s,t,id,cls||'btn-dark');};
    // ответ коллектива (этап «Ответили»): города подбора — «можем» / «другой организатор», даты сезона, следующий сезон
    var cities=L?Object.keys(L.cities||{}).filter(function(c){return L.cities[c].dec==='yes';}):[],se=season(t0),ns=r.ns||{};
    var art=function(c){return (L.cities[c]||{}).art||'';};
    var answer=isAt('answered')?'<div class="proc-mini"><div class="proc-mh">Города из подбора<span class="wkp-sp"></span>'+(cities.length?cities.filter(function(c){return art(c)==='ok';}).length+' можем · '+cities.filter(function(c){return art(c)==='busy';}).length+' другой организатор':'')+'</div>'+
        (cities.length?'<div class="proc-cities">'+cities.map(function(c){var a=art(c);return '<span class="proc-cname">'+esc(c)+'</span><span class="proc-tg">'+action('art:ok','можем',id,a==='ok'?'on ok':'',' data-c="'+esc(c)+'"')+action('art:busy','другой орг.',id,a==='busy'?'on busy':'',' data-c="'+esc(c)+'"')+'</span>'+(a==='busy'?'<input class="pl-in proc-org" data-art-org="'+esc(c)+'" data-id="'+id+'" maxlength="200" value="'+esc((L.cities[c]||{}).art_org||'')+'" placeholder="Кто работает в городе" aria-label="Организатор в городе '+esc(c)+'">':'');}).join('')+'</div>':'<span class="sub2">'+(L?'В подборе нет городов «подходит».':'Свяжите подбор городов — здесь появятся его города «подходит».')+'</span>')+'</div>'+
      '<div class="proc-mini"><div class="proc-mh">Даты этого сезона · '+wkpShort(se.from)+' — '+wkpShort(se.to)+'<span class="wkp-sp"></span>'+action('date-add','+ Диапазон',id,'proc-q')+'</div>'+
        ((r.dates||[]).length?r.dates.map(function(d,i){return '<div class="proc-dr"><input type="date" class="pl-in" data-lead-date="'+i+'" data-k="from" data-id="'+id+'" value="'+esc(d.from)+'" aria-label="С"><span>—</span><input type="date" class="pl-in" data-lead-date="'+i+'" data-k="to" data-id="'+id+'" value="'+esc(d.to)+'" aria-label="По"><input class="pl-in proc-drn" data-lead-date="'+i+'" data-k="note" data-id="'+id+'" maxlength="300" value="'+esc(d.note)+'" placeholder="пометка" aria-label="Пометка">'+action('date-del:'+i,PJ_ICON.close,id,'icon-btn proc-x',' aria-label="Убрать диапазон"')+'</div>';}).join(''):'<span class="sub2">Дат на остаток сезона нет.</span>')+'</div>'+
      '<div class="proc-mini"><div class="proc-mh">Следующий сезон · '+se.next.from.slice(0,4)+'–'+se.next.to.slice(0,4)+'</div><label class="proc-chk"><input type="checkbox" class="wk-check" data-lead-ns="ok" data-id="'+id+'"'+(ns.ok?' checked':'')+'> Подтвердили возможность гастролей</label>'+
        '<div class="proc-months">'+SEASON.map(function(m){return action('ns-m:'+m[0],m[1],id,(ns.months||[]).indexOf(m[0])>=0?'on':'');}).join('')+'</div><input class="pl-in" data-lead-ns="note" data-id="'+id+'" maxlength="1000" value="'+esc(ns.note||'')+'" placeholder="Комментарий — например, «весна, Поволжье»" aria-label="Следующий сезон: комментарий"></div>':'';
    // шаги по порядку v2 (PROCESSES_PLAN.md, 10.1): отметка — что сделано, справа — действие; ниже — содержимое шага
    var steps=[
      [r.called,'Позвонить',r.called?'позвонили'+(r.called_at?' '+wkpShort(r.called_at):''):'отметьте после звонка','<label class="proc-chk">'+field(row,'called','Позвонил','checkbox')+' Позвонил</label>'],
      [past('called')||r.stage==='reserve','Готовы сотрудничать?',r.stage==='declined'?'отказ':r.stage==='called'?'да — к обсуждению с руководителем; нет — отказ с причиной':past('called')||r.stage==='reserve'?'да':'после звонка',r.stage==='called'||r.stage==='found'?go('discuss','Да')+go('declined','Нет — отказ','btn-ghost'):'',r.stage==='declined'],
      [past('discuss'),'Обсудить с руководителем',r.stage==='reserve'?'не сейчас — в резерве':'интересен ли нам проект',r.stage==='discuss'?go('ready','Интересен')+go('reserve','Не сейчас — в резерв','btn-ghost'):''],
      [!!L&&!!r.fee,'Гонорар, подбор городов, задача',(r.fee?wkMoney(r.fee)+' ₽'+(r.cashless?' + '+r.cashless+' %':''):'гонорар не указан')+' · '+(L?'подбор: '+wkPickOffer(L):'подбора нет'),
        listSel+(L?action('pick','Открыть подбор →',id):(alike(r)?action('link:'+alike(r),'Связать с «'+esc(PLAN.lists[alike(r)].title)+'»',id,'btn-dark'):'')+action('pick-create','Создать подбор',id,alike(r)?'btn-ghost':'btn-dark'))+(r.stage==='ready'?go('offer','Отправили предложение'):''),
        false,'<span class="proc-pair">'+field(row,'fee','Гонорар','number').replace('>',' placeholder="гонорар, ₽">')+field(row,'cashless','% сверху','number').replace('>',' placeholder="% сверху">')+'</span><span class="sub2">'+(pjRec(r)?'→ попадает в карточку проекта':'свяжите карточку проекта — гонорар попадёт и туда')+'</span>'],
      [past('offer'),'Получили предложение — перезвонить',r.next_at?'перезвонить '+wkpShort(r.next_at)+(due(r,t0)?' — пора':''):'дата не задана',r.stage==='offer'?go('answered','Ответили'):'',false,
        isAt('offer')?'<span class="proc-row"><span class="sub2">Перезвонить через:</span>'+action('cb:2','2 дня',id,'proc-q')+action('cb:7','7 дней',id,'proc-q')+field(row,'next_at','Дата шага','date')+'</span>':''],
      [past('answered'),'Ответ коллектива','города · даты этого сезона · следующий сезон',r.stage==='answered'?go('approve','На согласование'):'',false,answer],
      [past('approve'),'Согласование с руководителем',!L?'нужен подбор городов':sent?'ссылка отправлена · ✔ '+sh.ok+' · ? '+sh.ask+' · ✖ '+sh.no:'подробная финмодель по городам → руководитель убирает или оставляет',
        (L&&isAt('answered')?action('pdf','PDF руководителю',id)+shareLink(sh)+action('cities',(r.cities||[]).length?'Обновить возможные города':'Зафиксировать возможные города',id):'')+(r.stage==='approve'?go('booking','Согласовано'):''),false,
        (r.cities||[]).length?'<span class="sub2">Возможные города'+(r.cities_at?' · '+wkpShort(r.cities_at):'')+': '+esc(r.cities.map(function(c){return c.city;}).join(', '))+'</span>':''],
      [r.stage==='booking','Готово к бронированию площадок','финальный статус; дальше — бронирование площадок','']
    ];
    var banner=r.stage==='declined'?'<div class="proc-banner warn"><span><b>Отказ.</b> '+(r.why?'Причина: '+esc(r.why):'<span class="proc-red-t">Причина не указана.</span>')+'</span>'+action('why',r.why?'Изменить':'Указать причину',id)+action('back-work','Вернуть в работу',id)+'</div>'
      :r.stage==='reserve'?'<div class="proc-banner"><span><b>Резерв.</b> '+(r.why?esc(r.why):'Готовы сотрудничать, сейчас не берём.')+(r.next_at?' Вернуться к вопросу '+wkpShort(r.next_at)+'.':'')+'</span>'+action('back-work','Вернуть в работу',id)+'</div>':'';
    // карточка «Репертуара»: связь, райдеры файлами (решения 29.10)
    var P=pjRec(r),sug=!P&&pjAlike(r),riders=P?((P.profile||{}).riders||[]):[];
    var pjOpts=[['','Выбрать карточку…']].concat(Object.keys((MYP||{}).projects||{}).sort(function(a,b){return MYP.projects[a].title.localeCompare(MYP.projects[b].title,'ru');}).map(function(k){return [k,MYP.projects[k].title];}));
    var pjSec=P?'<div class="proc-pjbox">'+pjAva(P)+'<div class="proc-pjt"><b>'+esc(P.title)+'</b><span class="sub2">'+((P.profile||{}).fee?'гонорар в карточке: '+esc(P.profile.fee):'гонорара в карточке нет')+'</span></div>'+action('pj-open','Открыть →',id)+action('pj-unlink',PJ_ICON.close,id,'icon-btn',' aria-label="Отвязать карточку" title="Отвязать карточку"')+'</div>'+
        '<div class="proc-mini"><div class="proc-mh">Райдеры<span class="wkp-sp"></span><label class="proc-q proc-upl">+ Загрузить файл<input type="file" data-lead-rider="'+id+'" hidden></label></div>'+
        (riders.length?riders.map(function(x){return x.file?'<div class="proc-file"><a class="pj-plain" href="'+esc(riderUrl(x))+'" target="_blank" rel="noopener">'+esc(x.label||x.file)+'</a>'+action('rider-del',PJ_ICON.close,id,'icon-btn proc-x',' data-f="'+esc(x.file)+'" aria-label="Удалить файл райдера"')+'</div>':'<div class="proc-file"><a class="pj-plain" href="'+esc(x.url)+'" target="_blank" rel="noopener">'+esc(x.label||x.url)+' ↗</a></div>';}).join(''):'<span class="sub2">Файл ляжет в райдеры карточки проекта.</span>')+'</div>'
      :'<div class="proc-pjbox">'+(sug?'<span>Похоже на карточку <b>'+esc(MYP.projects[sug].title)+'</b></span><span class="wkp-sp"></span>'+action('pj-link:'+sug,'Связать',id,'btn-dark'):'<span class="proc-link">'+wkSel(pjOpts,id)+'</span>'+action('pj-create','Создать карточку',id))+'</div>';
    var ts=leadTasks(id),tasks='<div class="proc-tasks">'+ts.map(function(t){return '<div class="proc-tk'+(t.done?' done':'')+'"><input type="checkbox" class="wk-check" data-lead-taskdone="'+t.id+'"'+(t.done?' checked':'')+' aria-label="Готово: '+esc(t.text)+'">'+action('task-open',esc(t.text),id,'pj-plain proc-ell',' data-t="'+t.id+'"')+'<span class="sub2">'+(t.due?esc(wkpShort(t.due)):'')+'</span></div>';}).join('')+
      action('task-new','+ Задача',id,'pj-plain proc-muted')+'</div>';
    var fields=[['next','Следующий шаг',null,null,1],['next_at',r.stage==='reserve'?'Вернуться к вопросу':'Перезвонить / дата шага','date'],['stage','Этап',null,stages],['contact','Контакт',null,null,1],['called_at','Дата звонка','date'],['source','Источник'],['note','Заметка','textarea',null,1],['proc','Процесс',null,[['','Без процесса']].concat(records('procs').map(function(p){return [p.id,p.title];})),1]];
    var html='<div class="proc-dhead"><div><h2>'+esc(r.title)+'</h2><div class="proc-dtags">'+tag(r.stage)+'</div></div>'+'<div class="proc-dbtns">'+action('lead-delete',WKP_TRASH,id,'icon-btn',' aria-label="Удалить из воронки" title="Удалить из воронки"')+action('close',PJ_ICON.close,null,'icon-btn',' aria-label="Закрыть карточку"')+'</div></div>'+banner+
      (hints(r,sh).length?'<div class="proc-hints">'+hints(r,sh).map(function(s){return '<span>Перевести в «'+esc(label(s))+'»?</span>'+action('stage:'+s,'Перевести',id,'btn-dark');}).join('')+'</div>':'')+
      '<section class="proc-sec"><h3>Шаги процесса</h3><ol class="proc-steps">'+steps.map(function(s,i){var cur=!out&&stageAt(r.stage)===i;return '<li class="'+(s[0]?'done':s[4]?'no':'')+(cur?' cur':'')+'"><span class="proc-dot" aria-hidden="true">'+(s[0]?'✓':s[4]?'✕':i+1)+'</span><div class="proc-stx"><b>'+s[1]+'</b><span>'+esc(s[2])+'</span></div><div class="proc-sact">'+s[3]+'</div>'+(s[5]?'<div class="proc-sfull">'+s[5]+'</div>':'')+'</li>';}).join('')+'</ol></section>'+
      '<section class="proc-sec"><h3>Карточка проекта <span class="sub2">· «Репертуар → Проекты»</span></h3>'+pjSec+'</section>'+
      '<section class="proc-sec"><h3>Задачи записи</h3>'+tasks+'</section>'+
      '<section class="proc-sec"><h3>Данные</h3><div class="form-grid proc-form">'+fields.map(function(f){return '<div class="field'+(f[4]?' full':'')+'"><label>'+f[1]+'</label>'+field(row,f[0],f[1],f[2],f[3])+'</div>';}).join('')+'</div></section>'+
      '<section class="proc-sec"><h3>Журнал</h3><form class="proc-log" data-lead-log="'+id+'"><input class="pl-in pl-text" name="text" maxlength="2000" placeholder="Добавить запись — Enter" aria-label="Запись в журнал" required></form>'+(r.log||[]).slice().reverse().map(function(l){return '<p class="proc-logl"><span class="sub2">'+esc(l.at.replace('T',' ').slice(0,16))+'</span>'+esc(l.text)+'</p>';}).join('')+'</section>';
    $('drawer').setAttribute('aria-label','Проект в воронке: '+r.title);
    if(keep){var dr=$('drawer'),y=dr.scrollTop,fo=document.activeElement&&dr.contains(document.activeElement)&&document.activeElement.getAttribute('data-lead-field');dr.innerHTML=html;dr.scrollTop=y;enhanceSelects(dr);var back=fo&&dr.querySelector('[data-lead-field="'+fo+'"]');if(back)back.focus({preventScroll:true});}else showDrawer(html);   // ввод по Tab не теряет поле после сохранения
  }
  function wkSel(opts,id) { return '<select class="pl-sel" data-lead-pj="'+id+'" aria-label="Карточка проекта">'+wkOpts(opts.map(function(o){return [o[0],esc(o[1])];}),'')+'</select>'; }
  // подбор с похожим названием, ещё ни с кем не связанный («Групп На-На» ↔ «Группа На-На»): подсказка в шаге 4
  function norm(t) { return String(t||'').toLowerCase().replace(/ё/g,'е').replace(/[^a-zа-я0-9]+/g,''); }
  function dist(a,b) { var d=[],i,j; for(i=0;i<=a.length;i++)d[i]=[i]; for(j=0;j<=b.length;j++)d[0][j]=j; for(i=1;i<=a.length;i++)for(j=1;j<=b.length;j++)d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+(a[i-1]===b[j-1]?0:1)); return d[a.length][b.length]; }
  function alike(r) { var t=norm(r.title),best=null,bd=1e9; if(t.length<3)return null; Object.keys(PLAN.lists).forEach(function(k){var L=PLAN.lists[k];if((L.work||{}).lead)return;var x=norm(L.title),d=dist(t,x);if(d<bd&&d<=Math.max(1,Math.floor(Math.max(t.length,x.length)*0.25))){bd=d;best=k;}}); return best; }
  async function dropLead(id) {   // подбор отвязываем, иначе он остаётся «занятым» удалённой записью (linkList, alike)
    var L=PLAN.lists[(WK.leads[id]||{}).list];
    if(L && (L.work||{}).lead===id){var o=JSON.parse(JSON.stringify(L));delete o.work.lead;await request('/api/planning',{op:'put',kind:'lists',id:WK.leads[id].list,data:o});PLAN.lists[WK.leads[id].list]=o;}
    WK=await request('/api/work',{op:'del',kind:'leads',id:id});
  }
  async function linkList(id,lid) {
    var r=WK.leads[id],L=PLAN.lists[lid],old=PLAN.lists[r.list];
    if(L && (L.work||{}).lead && L.work.lead!==id)throw new Error('Этот подбор уже связан с другой записью');
    if(old && (old.work||{}).lead===id && r.list!==lid){var o=JSON.parse(JSON.stringify(old));delete o.work.lead;await request('/api/planning',{op:'put',kind:'lists',id:r.list,data:o});PLAN.lists[r.list]=o;}
    if(L){var n=Object.assign({},L,{work:Object.assign({},L.work||{},{lead:id})});await request('/api/planning',{op:'put',kind:'lists',id:lid,data:n});PLAN.lists[lid]=n;}
    await save('leads',id,Object.assign({},r,{list:lid}));
  }
  async function putList(lid,fn) { var o=JSON.parse(JSON.stringify(PLAN.lists[lid]));fn(o);await request('/api/planning',{op:'put',kind:'lists',id:lid,data:o});PLAN.lists[lid]=o; }
  async function leadAction(a,id,b) {
    var r=WK.leads[id];if(!r)return;
    if(a==='pick-create') {if(PLAN.lists[r.list])return;var lid=plId('l'),rec={title:r.title,project:(pjRec(r)||{}).title||'',econ:{fee:r.fee,cashless:r.cashless},work:{lead:id},rows:[],cities:{}};await request('/api/planning',{op:'put',kind:'lists',id:lid,data:rec});PLAN.lists[lid]=rec;await save('leads',id,Object.assign({},r,{list:lid}));}
    else if(a==='cities') {var L=PLAN.lists[r.list];if(!L)throw new Error('Подбор удалён');var A=tbAnalyze(L,tbPrefs());tbPick(L,A);var cities=Object.keys(L.cities||{}).filter(function(c){return L.cities[c].dec==='yes';}).map(function(c){var o=L.cities[c],calc=A.rows.find(function(x){return x.city===c;}),p=calc&&calc.pick;return {city:c,venue:o.venue||(p&&p.v?p.v.name:'')||'',price:o.price!=null?o.price:(p&&p.k?p.k.price:null),at:wkDay(0)};});await save('leads',id,Object.assign({},r,{cities:cities,cities_at:wkDay(0)}));}
    else if(a.indexOf('link:')===0) await linkList(id,a.slice(5));
    else if(a.indexOf('art:')===0) {var c=b.getAttribute('data-c'),v=a.slice(4);await putList(r.list,function(o){var x=o.cities[c]=o.cities[c]||{};if(x.art===v){delete x.art;delete x.art_org;}else{x.art=v;if(v!=='busy')delete x.art_org;}});}
    else if(a==='date-add') await save('leads',id,Object.assign({},r,{dates:(r.dates||[]).concat([{from:'',to:'',note:''}])}));
    else if(a.indexOf('date-del:')===0) {var ds=(r.dates||[]).slice();ds.splice(+a.slice(9),1);await save('leads',id,Object.assign({},r,{dates:ds}));}
    else if(a.indexOf('ns-m:')===0) {var m=+a.slice(5),ns=Object.assign({ok:false,months:[],note:''},r.ns||{}),i=ns.months.indexOf(m);ns.months=ns.months.slice();if(i>=0)ns.months.splice(i,1);else ns.months.push(m);await save('leads',id,Object.assign({},r,{ns:ns}));}
    else if(a.indexOf('pj-link:')===0) {var old=Object.assign({},r);await save('leads',id,Object.assign({},r,{pj:a.slice(8)}));await feeSync(id,old);}
    else if(a==='pj-unlink') await save('leads',id,Object.assign({},r,{pj:''}));
    else if(a==='pj-create') {var key=projKey(r.title),pid=myFind(key);if(!pid){await myPost({op:'create',key:key,title:r.title,id:'p'+Date.now().toString(36)});pid=myFind(key);}var o2=Object.assign({},r);await save('leads',id,Object.assign({},r,{pj:pid}));await feeSync(id,o2);}
    else if(a==='rider-del') {await myPost({op:'rider-del',id:r.pj,file:b.getAttribute('data-f')});}
    else return;
    redraw();if(state.lead===id)panel(id,true);
  }
  function openPick(id,pdf) {var r=WK.leads[id];if(!r||!PLAN.lists[r.list])return;closeDrawer();state.lead=null;S.pl.tab='build';S.pl.tb.list=r.list;S.pl.tb.draft=null;goView('planning');if(pdf)tbOfferDoc('boss');}
  function closeDlg() { var d=$('pjDlg'); if(d&&d.open) d.close(); }
  document.addEventListener('click',function(ev){
    var op=ev.target.closest&&ev.target.closest('[data-proc-open]');if(op){open(op.getAttribute('data-proc-open'));return;}
    var b=ev.target.closest&&ev.target.closest('[data-proc-action]');if(!b)return;ev.preventDefault();var a=b.getAttribute('data-proc-action'),id=b.getAttribute('data-id');
    if(a==='lead'||a==='lead-link'){closeDlg();wkPopClose();var r=WK.leads[id];if(!r)return;if(r.proc){if(S.view!=='wkproc'||state.id!==r.proc)open(r.proc);if(off(r)&&state.list!==r.stage){state.list=r.stage;redraw();}}else{state.id=null;goView('wkproc');}ixSharesLoad();panel(id);return;}
    if(a==='close'){state.lead=null;closeDrawer();return;}if(a==='back'){state.id=null;redraw();return;}if(a==='new'||a==='edit'){edit(id);return;}
    if(a==='tasks'||a==='funnel'){state.tab=a;redraw();return;}if(a==='add'){if(state.list!=='work'){state.list='work';redraw();}var inp=document.querySelector('[data-proc-add] input');if(inp){inp.scrollIntoView({block:'center'});inp.focus();}return;}if(a==='table'||a==='board'){state.mode=a;redraw();return;}
    if(a.indexOf('list:')===0){state.list=a.slice(5);wkPopClose();redraw();return;}
    if(a==='filter'){if(WKPOP&&WKPOP.anchor===b){wkPopClose();return;}filterOpen();return;}
    if(a.indexOf('f:')===0){var fp=a.split(':');state.filters[fp[1]]=fp[2];redraw();filterOpen();return;}
    if(a==='reset'){state.filters={};wkPopClose();redraw();return;}
    if(a==='ask-yes'){var list=leads(state.id).filter(function(r){return r.stage==='called'&&r.ready==='yes';});enqueue(async function(){for(var i=0;i<list.length;i++)await save('leads',list[i].id,Object.assign({},WK.leads[list[i].id],{stage:'discuss'}));redraw();toast('Перенесено: '+list.length);});return;}
    if(a==='ask-no'){lsSet(ASK_KEY,'no');redraw();return;}
    if(a==='dlg-close'){closeDlg();return;}
    if(a==='why-q'){var t=$('pjDlg').querySelector('textarea[name=why]');if(t){t.value=b.getAttribute('data-v');t.focus();}return;}
    if(a==='why'){askWhy(id);return;}if(a==='task-new'){askTask(id,'');return;}
    if(a.indexOf('stage:')===0){setStage(id,a.slice(6));return;}
    if(a.indexOf('cb:')===0){callback(id,+a.slice(3));return;}
    if(a==='back-work'){var br=WK.leads[id];patch(id,{stage:br.stage==='declined'?'called':'discuss'});return;}
    if(a==='pick'||a==='pdf'){openPick(id,a==='pdf');return;}
    if(a==='task-open'){var tid=b.getAttribute('data-t')||WK.leads[id].task;closeDrawer();state.lead=null;wkOpenTask(tid);return;}
    if(a==='pj-open'){openPj(WK.leads[id].pj);return;}
    if(a==='lead-delete'){var lr=WK.leads[id];if(!lr)return;askConfirm('Удалить «'+lr.title+'» из воронки?',(PLAN.lists[lr.list]||leadTasks(id).length?'Подбор городов и задачи останутся, только без связи с записью. ':'')+'Вернуть запись нельзя.','Удалить',function(){enqueue(async function(){await dropLead(id);closeDrawer();state.lead=null;redraw();toast('Удалено из воронки');});});return;}
    if(a==='delete'){var n=leads(id).length;askConfirm('Удалить процесс «'+WK.procs[id].title+'»?','Записи воронки ('+n+'), задачи и заметки останутся без процесса.','Удалить',function(){enqueue(async function(){WK=await request('/api/work',{op:'del',kind:'procs',id:id});state.id=null;redraw();});});return;}
    enqueue(function(){return leadAction(a,id,b);});
  });
  document.addEventListener('change',function(ev){var el=ev.target,id=el.getAttribute&&el.getAttribute('data-id');
    if(el.hasAttribute('data-lead-pj')){var lid=el.getAttribute('data-lead-pj'),pid=el.value;if(pid)enqueue(function(){return leadAction('pj-link:'+pid,lid,el);});return;}
    if(el.hasAttribute('data-lead-rider')){var rid=el.getAttribute('data-lead-rider'),file=el.files[0];if(!file)return;if(file.size>15*1024*1024){toast('Райдер: файл до 15 МБ');return;}enqueue(async function(){var data=await new Promise(function(res,rej){var fr=new FileReader();fr.onload=function(){res(fr.result);};fr.onerror=rej;fr.readAsDataURL(file);});var r=WK.leads[rid];await myPost({op:'rider',id:r.pj,name:file.name,data:data});await save('leads',rid,Object.assign({},r,{log:(r.log||[]).concat([{id:wkId('log'),at:wkStamp(),text:'Райдер «'+file.name+'» → карточка проекта'}])}));refreshPanel(rid);toast('Райдер загружен в карточку проекта');});return;}
    if(el.hasAttribute('data-lead-taskdone')){var tid=el.getAttribute('data-lead-taskdone'),t=WK.tasks[tid];if(t)enqueue(async function(){await save('tasks',tid,Object.assign({},t,{done:el.checked}));redraw();refreshPanel(state.lead);});return;}
    if(el.hasAttribute('data-art-org')){var c=el.getAttribute('data-art-org'),v0=el.value.trim();enqueue(async function(){await putList(WK.leads[id].list,function(o){(o.cities[c]=o.cities[c]||{}).art_org=v0;});});return;}
    if(el.hasAttribute('data-lead-date')){var i=+el.getAttribute('data-lead-date'),k0=el.getAttribute('data-k'),ds=(WK.leads[id].dates||[]).map(function(d){return Object.assign({},d);});ds[i][k0]=el.value;patch(id,{dates:ds},false);return;}
    if(el.hasAttribute('data-lead-ns')){var nk=el.getAttribute('data-lead-ns'),ns=Object.assign({ok:false,months:[],note:''},WK.leads[id].ns||{});ns[nk]=el.type==='checkbox'?el.checked:el.value;patch(id,{ns:ns},false);return;}
    if(!el.hasAttribute('data-lead-field'))return;var k=el.getAttribute('data-lead-field'),v=el.type==='checkbox'?el.checked:el.type==='number'?(el.value===''?null:+el.value):el.value,p={};p[k]=v;
    if(k==='stage'){redraw();refreshPanel(id);setStage(id,v);return;}   // отказ и резерв — через окно; выбор вернётся, если окно закрыли
    if(k==='called')p.called_at=v?wkDay(0):'';
    if(k==='list'){enqueue(async function(){await linkList(id,v);redraw();panel(id,true);});return;}
    if(k==='why'&&!v&&WK.leads[id].stage==='declined'){toast('Без причины отказ не сохраняется');redraw();return;}
    patch(id,p,!!el.closest('#drawer')||el.tagName==='SELECT'||el.type==='checkbox'||k==='next_at').then(function(){var r=WK.leads[id];if(!state.lead&&r&&hints(r).length){var s=hints(r)[0];toast('Сохранено');askConfirm('Перевести в «'+label(s)+'»?','Этап изменится только после подтверждения.','Перевести',function(){setStage(id,s);});}},function(){});
  });
  document.addEventListener('submit',function(ev){var f=ev.target;
    if(f.hasAttribute('data-proc-add')){ev.preventDefault();var title=f.elements.title.value.trim(),proc=f.getAttribute('data-proc-add');if(!title)return;f.elements.title.value='';enqueue(async function(){await save('leads',wkId('l'),{title:title,proc:proc,stage:'found',order:leads(proc).length,created:wkDay(0)});redraw();var i=document.querySelector('[data-proc-add] input');if(i)i.focus();});}
    if(f.hasAttribute('data-lead-log')){ev.preventDefault();var id=f.getAttribute('data-lead-log'),text=f.elements.text.value.trim();if(text)enqueue(async function(){var r=WK.leads[id];await save('leads',id,Object.assign({},r,{log:(r.log||[]).concat([{id:wkId('log'),at:wkStamp(),text:text}])}));panel(id,true);});}
    if(f.hasAttribute('data-lead-why')){ev.preventDefault();var wid=f.getAttribute('data-lead-why'),why=f.elements.why.value.trim();if(!why)return;closeDlg();patch(wid,{stage:'declined',why:why});}
    if(f.hasAttribute('data-lead-hold')){ev.preventDefault();var hid=f.getAttribute('data-lead-hold'),hr=WK.leads[hid],hat=f.elements.at.value;closeDlg();patch(hid,{stage:'reserve',why:f.elements.why.value.trim(),next_at:hat||hr.next_at||'',next:hat?'Вернуться к вопросу':hr.next});}
    if(f.hasAttribute('data-lead-task')){ev.preventDefault();var kid=f.getAttribute('data-lead-task'),kr=WK.leads[kid],text2=f.elements.text.value.trim(),due2=f.elements.due.value;if(!text2)return;closeDlg();enqueue(async function(){if(!WK.procs[kr.proc])throw new Error('Сначала выберите процесс');await save('tasks',wkId('t'),{text:text2,proc:kr.proc,lead:kid,due:due2,created:wkDay(0)});redraw();refreshPanel(kid);toast('Задача создана');});}
    if(f.hasAttribute('data-proc-edit')){ev.preventDefault();var pid=f.getAttribute('data-proc-edit')||wkId('proc'),file=f.elements.cover.files[0],remove=f.elements.removeCover&&f.elements.removeCover.checked,rec=Object.assign({},WK.procs[pid]||{kind:f.elements.kind.value},{title:f.elements.title.value.trim(),note:f.elements.note.value});if(!rec.title)return;var submit=f.querySelector('button.btn-dark');submit.disabled=true;enqueue(async function(){await save('procs',pid,rec);if(file||remove){var data=file?await new Promise(function(resolve,reject){var reader=new FileReader();reader.onload=function(){resolve(reader.result);};reader.onerror=reject;reader.readAsDataURL(file);}):'';WK=await request('/api/work',{op:'media',kind:'procs',id:pid,what:'cover',data:data});}$('pjDlg').close();redraw();}).then(function(){submit.disabled=false;},function(){submit.disabled=false;});}
  });
  // перед перетаскиванием границы столбца — ширины снова в пикселях: общий обработчик «Планирования» считает в px
  document.addEventListener('mousedown',function(ev){var h=ev.target.closest&&ev.target.closest('.proc-funnel [data-plresize]');if(!h)return;var t=h.closest('table'),sum=0;t.querySelectorAll('col').forEach(function(c){var w=Math.round(c.getBoundingClientRect().width);c.style.width=w+'px';sum+=w;});t.style.width=sum+'px';t.style.minWidth='';},true);
  var timer;document.addEventListener('input',function(ev){if(ev.target.id!=='procQ')return;state.q=ev.target.value;clearTimeout(timer);timer=setTimeout(function(){redraw();var i=$('procQ');if(i)i.focus();},180);});
  document.addEventListener('keydown',function(ev){var c=ev.target.closest&&ev.target.closest('[data-proc-open]');if(c&&ev.key==='Enter'){ev.preventDefault();c.click();}});
  var drag=null;document.addEventListener('dragstart',function(ev){var c=ev.target.closest&&ev.target.closest('[data-lead-drag]');if(!c)return;drag=c.getAttribute('data-lead-drag');ev.dataTransfer.setData('text/plain',drag);ev.dataTransfer.effectAllowed='move';});
  document.addEventListener('dragover',function(ev){var col=drag&&ev.target.closest&&ev.target.closest('[data-lead-drop]');document.querySelectorAll('[data-lead-drop].drop').forEach(function(c){if(c!==col)c.classList.remove('drop');});if(col){ev.preventDefault();col.classList.add('drop');}});
  document.addEventListener('drop',function(ev){var col=ev.target.closest&&ev.target.closest('[data-lead-drop]');if(!drag||!col)return;ev.preventDefault();var id=drag;drag=null;var stage=col.getAttribute('data-lead-drop'),moved=WK.leads[id].stage!==stage,before=ev.target.closest('[data-lead-drag]');var list=leads(state.id).filter(function(r){return r.stage===stage&&r.id!==id;}).sort(function(a,b){return (a.order||0)-(b.order||0);});var at=before?list.findIndex(function(r){return r.id===before.getAttribute('data-lead-drag');}):list.length;list.splice(at<0?list.length:at,0,WK.leads[id]);enqueue(async function(){for(var i=0;i<list.length;i++){var row=list[i],rid=row.id||id;await save('leads',rid,Object.assign({},WK.leads[rid],{stage:stage,order:i}));}redraw();if(moved)after(id,stage);});});
  document.addEventListener('dragend',function(){drag=null;document.querySelectorAll('[data-lead-drop].drop').forEach(function(c){c.classList.remove('drop');});});

  // ---------------------------------------------------------------- «Репертуар»: блок «Сотрудничество» и «Пул проектов»
  function ensureWK() {   // «Репертуар» открыт раньше «Работы»: данные воронки — догрузить и перерисовать
    if(WK_OK||state.wkReq||!CAN_SAVE) return WK_OK;
    state.wkReq=true; apiJson('GET','/api/work').then(function(x){if(x.ok){WK=x.d;WK_OK=true;render();}},function(){}).then(function(){state.wkReq=false;});
    return false;
  }
  function leadOf(pid) { var l=records('leads').filter(function(r){return r.pj===pid;}); return l.filter(function(r){return !off(r);})[0]||l[0]||null; }
  api.coop=function(pid) {
    if(!pid||!ensureWK()) return '';
    var r=leadOf(pid); if(!r) return '';
    var row=function(k,v){return v?'<dt>'+k+'</dt><dd>'+v+'</dd>':'';},n=(r.dates||[]).length;
    return '<section class="proc-coop"><h3 class="pj-h4">Сотрудничество</h3><dl class="pj-dl">'+row('Статус',tag(r.stage))+
      row(r.stage==='declined'?'Причина отказа':'Почему не сейчас',(r.stage==='declined'||r.stage==='reserve')?(r.why?esc(r.why):r.stage==='declined'?'<span class="proc-red-t">не указана</span>':''):'')+
      row('Гонорар',r.fee?esc(feeText(r))+'<span class="sub2"> · из переговоров</span>':'')+row('Контакт',esc(r.contact||''))+
      row('Звонок',r.called_at?esc(wkpShort(r.called_at)):'')+row(r.stage==='reserve'?'Вернуться к вопросу':'Перезвонить',r.next_at&&r.stage!=='declined'&&r.stage!=='booking'?esc(wkpShort(r.next_at))+(r.next?' · '+esc(r.next):''):'')+
      row('Даты',[n?n+' '+plural(n,'диапазон','диапазона','диапазонов')+' в этом сезоне':'',(r.ns||{}).ok?'следующий сезон подтверждён':''].filter(Boolean).join(' · '))+
      '</dl>'+action('lead','Открыть в воронке →',r.id,'btn-ghost')+'</section>';
  };
  api.poolPage=function() {
    if(!CAN_SAVE) return head('Пул проектов','')+'<div class="note">Раздел хранится на сервере — откройте сайт через приложение.</div>';
    if(!ensureWK()) return head('Пул проектов','')+'<div class="sub">Загружаем…</div>';
    var all=records('leads').filter(function(r){return WK.procs[r.proc]&&WK.procs[r.proc].kind==='artists'||!r.proc;}),q=(state.pq||'').toLowerCase();
    if(q) all=all.filter(function(r){return [r.title,r.contact,r.why,(pjRec(r)||{}).title].join(' ').toLowerCase().indexOf(q)>=0;});
    var can=all.filter(function(r){return r.stage==='reserve'||stageAt(r.stage)>=stageAt('discuss')&&r.stage!=='declined';}),talk=all.filter(function(r){return r.stage==='found'||r.stage==='called';}),dec=all.filter(function(r){return r.stage==='declined';});
    var tbl=function(rows){rows=rows.slice().sort(function(a,b){return a.title.localeCompare(b.title,'ru');});return rows.length?'<div class="proc-poolw"><table class="proc-pool"><thead><tr><th>Проект</th><th>Статус</th><th class="num">Гонорар</th><th>Контакт</th><th>Карточка проекта</th></tr></thead><tbody>'+rows.map(function(r){
      return '<tr><td>'+link(r.id,r.title)+'</td><td>'+(r.stage==='declined'?(r.why?esc(r.why):'<span class="proc-red-t">причина не указана</span>'):tag(r.stage))+'</td><td class="num">'+(r.fee?esc(wkMoney(r.fee))+' ₽':'—')+'</td><td>'+(esc(r.contact)||'—')+'</td><td>'+pjCell(r)+'</td></tr>';}).join('')+'</tbody></table></div>':'<p class="wkp-none">Пусто.</p>';};
    return head('Пул проектов','Все проекты из воронки «Поиск проектов» по статусу сотрудничества — чтобы добирать репертуар')+
      '<div class="wkp-bar proc-tools"><span class="wkp-sp"></span><label class="wkp-search">'+WKP_IC.search+'<input type="search" id="procPoolQ" value="'+esc(state.pq||'')+'" placeholder="Поиск проектов" aria-label="Найти проект в пуле"></label></div>'+
      '<h2 class="proc-ph">Можем работать <span class="sub2">· '+can.length+' — резерв и все, кто готов сотрудничать</span></h2>'+tbl(can)+
      '<h2 class="proc-ph">Идут переговоры <span class="sub2">· '+talk.length+'</span></h2>'+tbl(talk)+
      '<h2 class="proc-ph">Отказ <span class="sub2">· '+dec.length+'</span></h2>'+tbl(dec);
  };
  document.addEventListener('input',function(ev){if(ev.target.id!=='procPoolQ')return;state.pq=ev.target.value;clearTimeout(timer);timer=setTimeout(function(){render();var i=$('procPoolQ');if(i){i.focus();i.setSelectionRange(i.value.length,i.value.length);}},180);});

  api.closed=function(){state.lead=null;};
  api.refreshShares=function(){if(state.lead && $('drawer').classList.contains('open'))panel(state.lead,true);};
  api.page=page;api.scope=scope;api.owner=owner;api.normalize=normalize;api.ownerName=ownerName;api.ownerOptions=ownerOptions;api.open=open;api.link=link;
  api.taskLine=function(id){var t=WK.tasks[id]||{},r=WK.leads&&WK.leads[t.lead];return r?'<div class="wk-pick">Воронка: '+link(t.lead,r.title)+' · '+link(t.lead,'Открыть →')+'</div>':'';};
  api.chip=function(L){var id=(L.work||{}).lead;return id&&WK.leads&&WK.leads[id]?'<span class="tb-wchip">Воронка: '+link(id)+'</span>':'';};
  api.projectLine=function(p){return p.lead&&WK.leads&&WK.leads[p.lead]?'<div class="wk-pick">Воронка: '+link(p.lead,WK.leads[p.lead].title)+'</div>':'';};
  api.dueLeads=function(){var t0=wkDay(0);return records('leads').filter(function(r){return due(r,t0);});};
})(typeof window!=='undefined'?window:globalThis);
