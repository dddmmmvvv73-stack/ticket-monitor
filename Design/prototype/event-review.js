// Управление афишей в существующих «Мероприятиях». Источник решений — сервер.
var EventReview = (function () {
  "use strict";
  var data = null, loading = false, refreshAgain = false, error = "", selected = {}, busy = false;
  var mode = "list", filter = "new", limit = 100, scope = "project", byKey = {}, byId = {}, ruleKeys = {}, ruleNames = {}, ruleArtists = {}, etag = "", poll, snackTimer;
  var batchObserver, mutation = 0;
  var ICON = {
    keep: '<path d="m3 8 3 3 7-7"/>',
    local: '<path d="M2 6h12L8 2 2 6Zm1 7h10M4 7v4m4-4v4m4-4v4"/>',
    uninteresting: '<path d="M3 4h10M6 2h4M4 4l1 10h6l1-10M7 7v4m2-4v4"/>'
  };
  function h(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function count(n,one,few,many) { return n + " " + (n%10===1 && n%100!==11 ? one : n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? few : many); }
  function icon(k) { return '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICON[k] + '</svg>'; }
  function actions(id, kept) {
    var area = scope === "artist" ? "весь исполнитель" : "все даты проекта";
    return '<span class="er-actions">' + [["keep", "Оставить проект", kept ? " kept" : ""], ["local", "Удалить как местное · " + area, ""], ["uninteresting", "Удалить: неинтересно · " + area, ""]].map(function (x) {
      return '<button type="button" class="er-icon' + x[2] + '" data-er-action="' + x[0] + '" data-er-id="' + h(id) + '" aria-label="' + x[1] + '" title="' + x[1] + '"' + (busy ? ' disabled' : '') + '>' + icon(x[0]) + '</button>';
    }).join("") + '</span>';
  }
  function changed() {
    if (typeof curApply === "function") curApply();
    if (typeof render === "function") rerender();
    snacks();
  }
  function queue() {
    clearTimeout(poll);var delay=refreshAgain ? 0 : data && data.pending.length ? 700 : 15000;refreshAgain=false;poll=setTimeout(refresh,delay);
  }
  function refresh() {
    if (!window.ON_APP) return;
    if (loading) { refreshAgain=true;return; }
    if (busy) { queue(); return; }
    loading = true; var started = mutation;
    fetch("/api/event-review", {cache:"no-store",headers:etag ? {"If-None-Match":etag} : {}}).then(function (r) {
      if(r.status===304) return null;
      return r.json().then(function (d) { if (!r.ok) throw Error(d.error || "Разбор недоступен"); d.versionTag=r.headers.get("ETag")||String(d.rev);return d; });
    }).then(function (d) {
      if (started !== mutation) { loading=false;queue();return; }
      if(!d) { loading=false;error="";snacks();queue();return; }
      var old = data && (data.content_version || data.versionTag);
      etag=d.versionTag;
      if(data && old===d.content_version){
        data.pending=d.pending;data.clockOffset=Date.now()/1000-d.server_time;
        data.versionTag=d.versionTag;loading=false;error="";snacks();queue();return;
      }
      data = d; data.clockOffset = Date.now() / 1000 - d.server_time;
      loading = false; error = ""; byId = {}; byKey = {};
      ruleKeys={};ruleNames={};ruleArtists={};
      d.rules.forEach(function(r){
        r.keys.forEach(function(k){ruleKeys[k]=true;});
        if(r.kind==="artist") (ruleArtists[r.artist_key]=ruleArtists[r.artist_key]||[]).push(r);
        else r.names.forEach(function(k){(ruleNames[k]=ruleNames[k]||[]).push(r);});
      });
      d.groups.forEach(function (g) { byId[g.id] = g; g.events.forEach(function (e) { (e.keys || []).forEach(function (k) { byKey[k] = g; }); }); });
      Object.keys(selected).forEach(function (id) { if (!byId[id]) delete selected[id]; });
      if (old !== (d.content_version || d.versionTag) || old == null) changed(); else snacks();
      queue();
    }).catch(function (e) { loading=false;if(started!==mutation){queue();return;}error=e.message;if(mode!=="list")rerender();clearTimeout(poll);poll=setTimeout(refresh,5000); });
  }
  function ensure() { if (!data && !loading && !error) refresh(); }
  function bar() {
    ensure();
    return '<div class="toolbar er-nav" aria-label="Управление афишей">' + [["list","Мероприятия"],["review","Разбор"],["deleted","Удалённые"]].map(function (x) {
      return '<button type="button" class="chip-btn' + (mode === x[0] ? ' chip-active' : '') + '" data-er-mode="' + x[0] + '" aria-pressed="' + (mode === x[0]) + '">' + x[1] + '</button>';
    }).join("") + (data ? '<span class="sub2 er-progress">Оставлено ' + data.kept + ' · исключено проектов ' + data.rule_count + '</span>' : '') + '</div>';
  }
  function groupOf(e) {
    if (!data) return null;
    var keys = (e.keys || []).concat([e.duid, e.uid, e.key]).filter(Boolean);
    for (var i = 0; i < keys.length; i++) if (byKey[keys[i]]) return byKey[keys[i]];
    return null;
  }
  function inline(e) {
    ensure(); var g = groupOf(e);
    return g ? '<div class="er-inline">' + actions(g.id, g.kept) + '<span class="sub2">все даты проекта · ' + g.events.length + '</span></div>' : '';
  }
  function blocked(e) {
    if (!data) return false;
    var keys = (e.keys || []).concat([e.duid, e.uid, e.key]).filter(Boolean), pk = typeof projKey === "function" ? projKey(e.title) : "";
    var norm = function (s) { return String(s || "").toLowerCase().replace(/ё/g,"е").replace(/\s+/g," ").trim(); };
    if(keys.some(function(k){return ruleKeys[k];})) return true;
    var ak=typeof artistPart === "function" ? projKey(artistPart(e.title)||"") : "";
    var candidates=(ruleNames[pk]||[]).concat(ruleNames[e.pk]||[],ruleArtists[pk]||[],ruleArtists[ak]||[]);
    return candidates.some(function (r) {
      if(r.kind==="project" && keys.some(function(k){return (r.protected_keys||[]).indexOf(k)>=0;})) return false;
      if (Object.keys(r.context || {}).some(function (k) { return norm(e[k]) !== norm(r.context[k]); })) return false;
      if (r.kind === "artist") return pk === r.artist_key || (typeof artistPart === "function" && projKey(artistPart(e.title) || "") === r.artist_key);
      if (r.qualifier) {
        var qual = Array.from(new Set(String(e.title || "").toLowerCase().replace(/ё/g,"е").replace(/\([^)]*\)/g," ").split(/[^a-zа-я0-9]+/).filter(function(w){return w.length===1 && ["и","в","с","к","у","о","г"].indexOf(w)<0;}))).sort();
        if (JSON.stringify(qual)!==JSON.stringify(r.qualifier)) return false;
      }
      return r.names.indexOf(pk) >= 0 || (e.pk && r.names.indexOf(e.pk) >= 0);
    });
  }
  function localDate(s) { return s ? s.slice(8,10) + '.' + s.slice(5,7) + '.' + s.slice(0,4) : '—'; }
  function rows() {
    var q = typeof S !== "undefined" ? S.q.trim().toLowerCase() : "";
    return data.groups.filter(function (g) {
      if (filter === "new" && g.kept || filter === "kept" && !g.kept) return false;
      return g.events.some(function (e) {
        return (typeof mInScope !== "function" || mInScope(e)) && (!q || [g.title,e.city,e.venue,e.org,g.genre,g.format].join(" ").toLowerCase().indexOf(q) >= 0);
      });
    });
  }
  function ticketLink(g) {
    var t=g.ticket;
    return t && /^https?:\/\//i.test(t.url) ? '<a class="er-ticket" href="' + h(t.url) + '" target="_blank" rel="noopener noreferrer" title="Открыть ' + h(g.title) + ' у билетного оператора">' + h(t.label || 'Билеты') + ' ↗</a>' : '<div class="sub2">Нет ссылки</div>';
  }
  function batch() {
    var ids=Object.keys(selected), disabled=busy || !ids.length ? ' disabled' : '';
    return '<b>Выбрано ' + ids.length + '</b><span class="sub2">' + ids.reduce(function(n,id){return n+(byId[id] ? byId[id].events.length : 0);},0) + ' текущих мероприятий · все города и будущие даты</span>' +
      '<button class="btn-ghost" data-er-batch="keep"' + disabled + '>Оставить</button><button class="btn-ghost" data-er-batch="local"' + disabled + '>Удалить: местное</button><button class="btn-ghost" data-er-batch="uninteresting"' + disabled + '>Удалить: неинтересно</button><button class="btn-ghost" data-er-clear' + disabled + '>Снять выбор</button>';
  }
  // Выбор меняет только чекбоксы и панель: строки, фокус и прокрутка сохраняются.
  function selection() {
    var box=document.querySelector('.er-batch');
    if (!box) return;
    box.innerHTML=batch();
    var inputs=Array.from(document.querySelectorAll('[data-er-select]'));
    inputs.forEach(function(el){el.checked=!!selected[el.dataset.erSelect];el.closest('tr').classList.toggle('sel',el.checked);});
    var all=document.querySelector('[data-er-all]'), n=inputs.filter(function(el){return el.checked;}).length;
    if(all){all.checked=!!inputs.length && n===inputs.length;all.indeterminate=n>0 && n<inputs.length;}
  }
  function fit() {
    if(batchObserver) batchObserver.disconnect();
    var box=document.querySelector('.er-batch'), wrap=document.querySelector('.er-table-wrap');
    if(!box || !wrap) return;
    var size=function(){wrap.style.setProperty('--er-batch-h',box.getBoundingClientRect().height+'px');};
    size();
    if(window.ResizeObserver){batchObserver=new ResizeObserver(size);batchObserver.observe(box);}
    var all=wrap.querySelector('[data-er-all]'), inputs=Array.from(wrap.querySelectorAll('[data-er-select]'));
    if(all) all.indeterminate=inputs.some(function(el){return el.checked;}) && !all.checked;
  }
  function rerender() {
    var wrap=document.querySelector('.er-table-wrap'), y=window.scrollY, x=wrap ? wrap.scrollLeft : 0, top=wrap ? wrap.scrollTop : 0;
    render();
    wrap=document.querySelector('.er-table-wrap');
    if(wrap){wrap.scrollLeft=x;wrap.scrollTop=top;window.scrollTo(0,y);}
  }
  function pendingState() {
    document.querySelectorAll('[data-er-action],[data-er-select],[data-er-all],[data-er-scope]').forEach(function(el){el.disabled=busy;});
    selection();
  }
  function renderReview() {
    if (!data) return bar() + '<div class="card card-pad">' + h(error || 'Загружаем список проектов…') + '</div>';
    if (mode === "deleted") return deleted();
    var list = rows(), shown = list.slice(0, limit), all = shown.length && shown.every(function (g) { return selected[g.id]; });
    var tools = '<div class="toolbar er-tools">' + [["new","Не разобраны"],["kept","Оставлены"],["all","Все"]].map(function (x) {
      return '<button class="chip-btn' + (filter === x[0] ? ' chip-active' : '') + '" data-er-filter="' + x[0] + '">' + x[1] + '</button>';
    }).join("") + '<span class="sub2">' + count(list.length,'проект','проекта','проектов') + ' · сначала предполагаемые местные</span><label class="er-scope sub2">Область <select data-er-scope aria-label="Область исключения"><option value="project"' + (scope === "project" ? ' selected' : '') + '>Проект / постановка</option><option value="artist"' + (scope === "artist" ? ' selected' : '') + '>Весь исполнитель</option></select></label></div>';
    var table = '<section class="card ev-card-table er-table-wrap" aria-label="Проекты для разбора"><div class="er-batch">' + batch() + '</div><table class="ev-table er-table er-review-table"><colgroup><col style="width:60px"><col style="width:25%"><col style="width:17%"><col style="width:14%"><col style="width:23%"><col style="width:21%"><col style="width:164px"></colgroup><thead><tr><th><label class="er-select-hit"><input type="checkbox" data-er-all aria-label="Выбрать показанные проекты"' + (all ? ' checked' : '') + '></label></th><th>Проект / постановка</th><th>Тип</th><th>Города</th><th>Площадка</th><th>Даты мероприятий</th><th>Разобрать</th></tr></thead><tbody>';
    shown.forEach(function (g) {
      var cities = Array.from(new Set(g.events.map(function (e) { return e.city; }))), venues = new Map();
      g.events.forEach(function(e){venues.set(JSON.stringify([e.city,e.venue]),e);});
      var venueHtml=Array.from(venues.values()).map(function(e){return '<div class="er-venue-item"><div>' + h(e.venue || '—') + '</div><div class="sub2">' + h(e.city) + '</div></div>';}).join('');
      var datesHtml=g.events.map(function(e){return '<div class="er-event-date"><div class="nowrap">' + h(localDate(e.date)) + (e.time ? ' · ' + h(e.time) : '') + '</div>' + (venues.size>1 ? '<div class="sub2">' + h([e.city,e.venue].filter(Boolean).join(' · ')) + '</div>' : '') + '</div>';}).join('');
      table += '<tr' + (selected[g.id] ? ' class="sel"' : '') + '><td><label class="er-select-hit"><input type="checkbox" data-er-select="' + h(g.id) + '" aria-label="Выбрать ' + h(g.title) + '"' + (selected[g.id] ? ' checked' : '') + '></label></td><td><div class="ev-title">' + h(g.title) + '</div><div class="sub2">' + h(g.format) + (g.genre ? ' · ' + h(g.genre) : '') + '</div></td><td><span class="' + (g.tour === "local" ? 'muted' : 'tb-tour') + '">' + (g.tour === "local" ? 'Предположительно местное' : 'Гастрольное') + '</span><div class="sub2">' + h(g.why) + '</div></td><td><div>' + h(cities.join(', ')) + '</div><div class="sub2">' + count(g.events.length,'дата','даты','дат') + ' · ' + count(venues.size,'площадка','площадки','площадок') + '</div></td><td>' + venueHtml + '</td><td>' + datesHtml + '</td><td>' + actions(g.id,g.kept) + '<div class="sub2">' + (scope === "artist" ? 'все программы исполнителя' : 'все даты проекта') + '</div>' + ticketLink(g) + '</td></tr>';
    });
    table += '</tbody></table>' + (!list.length ? '<div class="empty">Нет проектов для разбора по выбранным условиям</div>' : '') + '</section>';
    return bar() + (error ? '<div class="note">' + h(error) + '</div>' : '') + tools + table + (list.length > shown.length ? '<button class="btn-ghost er-more" data-er-more>Показать ещё 100</button>' : '');
  }
  function deleted() {
    var q = S.q.trim().toLowerCase(), list = data.deleted.filter(function (e) { return !q || [e.title,e.city,e.venue].join(' ').toLowerCase().indexOf(q)>=0; }).slice().reverse();
    return bar() + '<section class="card ev-card-table er-table-wrap" aria-label="Удалённые мероприятия"><table class="ev-table er-table er-deleted-table"><colgroup><col style="width:36%"><col style="width:28%"><col style="width:110px"><col style="width:120px"><col style="width:142px"></colgroup><thead><tr><th>Мероприятие</th><th>Город / площадка</th><th>Дата</th><th>Причина</th><th>Удалено</th></tr></thead><tbody>' + list.slice(0,limit).map(function (e) {
      return '<tr><td>' + h(e.title) + '</td><td>' + h(e.city) + '<div class="sub2">' + h(e.venue) + '</div></td><td>' + localDate(e.date) + '</td><td>' + (e.reason === "local" ? 'Местное' : 'Неинтересно') + '</td><td>' + localDate(e.at) + ' ' + h(e.at.slice(11,16)) + '</td></tr>';
    }).join('') + '</tbody></table>' + (!list.length ? '<div class="empty">Удалённых мероприятий пока нет</div>' : '') + '</section>' + (list.length>limit ? '<button class="btn-ghost er-more" data-er-more>Показать ещё 100</button>' : '');
  }
  function send(op) {
    if (busy) return;
    busy = true; mutation++; error = ""; pendingState();
    fetch('/api/event-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(op)}).then(function (r) {
      return r.json().then(function (d) { if (!r.ok) throw Error(d.error || 'Не сохранено'); return d; });
    }).then(function (result) {
      busy=false;selected={};
      if(data && op.op==='exclude') {
        data.clockOffset=Date.now()/1000-result.server_time;
        data.pending.push({id:result.id,count:op.ids.length,until:result.until,status:'pending'});
        var artists=op.scope==='artist' ? op.ids.map(function(id){return byId[id] && byId[id].artist;}).filter(Boolean) : [];
        data.groups=data.groups.filter(function(g){
          if(op.ids.indexOf(g.id)<0 && artists.indexOf(g.artist)<0) return true;
          g.events.forEach(function(e){(e.keys||[]).forEach(function(k){ruleKeys[k]=true;});});return false;
        });
        data.rule_count+=op.ids.length;data.versionTag='pending:'+result.id;data.content_version='pending:'+result.id;changed();
      }
      pendingState();
      etag='';refreshAgain=true;
      refresh();
    }).catch(function (e) { busy=false; error=e.message; toast(e.message); pendingState(); refresh(); });
  }
  function act(action, ids) {
    if (scope === "artist" && action !== "keep") {
      var names = ids.map(function(id){return byId[id] && byId[id].artist;});
      if (names.some(function(n){return !n;})) { toast("Исполнитель не определён. Выберите область «Проект / постановка»"); return; }
    }
    if (!ids.length) return;
    send(action === 'keep' ? {op:'keep',ids:ids} : {op:'exclude',ids:ids,reason:action,scope:scope});
  }
  function snacks() {
    clearTimeout(snackTimer);
    var box = document.getElementById('erSnacks');
    if (!box) { box=document.createElement('div');box.id='erSnacks';box.className='er-snacks';box.setAttribute('aria-live','polite');document.body.appendChild(box); }
    var now=Date.now()/1000-(data ? data.clockOffset : 0);
    var pending=data ? data.pending : [], present={};
    pending.forEach(function(p){present[p.id]=true;});
    Array.from(box.children).forEach(function(card){if(!present[card.dataset.erSnackId])card.remove();});
    pending.forEach(function(p){
      var left=Math.max(0,p.until-now), phase=p.status+':' +(left>0 ? 'undo':'expired')+':'+p.count+':'+(p.error||'');
      var card=Array.from(box.children).find(function(el){return el.dataset.erSnackId===p.id;});
      if(!card) { card=document.createElement('div');card.className='er-snack';card.dataset.erSnackId=p.id;card.setAttribute('role','status');box.appendChild(card); }
      // Сохранять ту же кнопку между опросами: замена DOM во время нажатия
      // может сорвать короткое окно отмены.
      if(card.dataset.phase===phase)return;
      card.dataset.phase=phase;
      card.innerHTML='<span>' + (p.status==='error' ? h(p.error) + ' · повторим автоматически' : left>0 ? 'Удаление: ' + count(p.count,'проект','проекта','проектов') + ' · отмена 4 секунды' : p.status==='pending' ? 'В очереди на очистку · ' + count(p.count,'проект','проекта','проектов') : 'Удаляем историю · ' + count(p.count,'проект','проекта','проектов') + '…') + '</span>' + (p.status==='pending' && left>0 ? '<button type="button" data-er-undo="' + h(p.id) + '">Отменить</button><i class="er-snack-progress" style="animation-duration:' + Math.round(left*1000) + 'ms"></i>' : '');
    });
    var deadlines=(data ? data.pending : []).filter(function(p){return p.status==='pending' && p.until>now;}).map(function(p){return p.until-now;});
    if(deadlines.length) snackTimer=setTimeout(snacks,Math.ceil(Math.min.apply(null,deadlines)*1000)+5);
  }
  document.addEventListener('click',function (ev) {
    var b=ev.target.closest('[data-er-mode],[data-er-filter],[data-er-action],[data-er-batch],[data-er-clear],[data-er-more],[data-er-undo]');
    if (!b) return;ev.preventDefault();ev.stopImmediatePropagation();
    if (b.disabled) return;
    if (b.hasAttribute('data-er-mode')) { mode=b.dataset.erMode;if(mode!=="review")scope="project";selected={};limit=100;ensure();render(); }
    else if (b.hasAttribute('data-er-filter')) { filter=b.dataset.erFilter;selected={};limit=100;render(); }
    else if (b.hasAttribute('data-er-action')) act(b.dataset.erAction,[b.dataset.erId]);
    else if (b.hasAttribute('data-er-batch')) act(b.dataset.erBatch,Object.keys(selected));
    else if (b.hasAttribute('data-er-clear')) { selected={};selection(); }
    else if (b.hasAttribute('data-er-more')) { limit+=100;rerender(); }
    else if (b.hasAttribute('data-er-undo')) send({op:'cancel',id:b.dataset.erUndo});
  },true);
  document.addEventListener('change',function (ev) {
    var el=ev.target;
    if (el.hasAttribute('data-er-select')) { if (el.checked) selected[el.dataset.erSelect]=true;else delete selected[el.dataset.erSelect];selection(); }
    else if (el.hasAttribute('data-er-all')) { document.querySelectorAll('[data-er-select]').forEach(function (input) { if(el.checked)selected[input.dataset.erSelect]=true;else delete selected[input.dataset.erSelect]; });selection(); }
    else if(el.hasAttribute('data-er-scope')) { scope=el.value;rerender(); }
  });
  return {bar:bar,inline:inline,blocked:blocked,render:renderReview,fit:fit,active:function(){return mode!=='list';},refresh:refresh};
})();
