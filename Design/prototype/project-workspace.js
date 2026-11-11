/* Постоянная база репертуара. Афиша, архив и сбор сайтов используют прежние данные и обработчики. */
(function (g) {
  'use strict';
  var state = { scope: 'mine', q: '', format: '', status: '', only: '', order: 'title', tabs: {}, periods: {}, pending: '', busy: false };
  var editor = null, draftTimer = null, searchTimer = null, draftSession;
  try { draftSession = sessionStorage.getItem('ticketmonitor.projectDraftSession'); if (!draftSession) { draftSession = crypto.randomUUID(); sessionStorage.setItem('ticketmonitor.projectDraftSession', draftSession); } } catch (_) { draftSession = String(Date.now()) + Math.random(); }
  var STAGES = Object.fromEntries(WorkProcesses.stages);
  function active() { return ['projects', 'touring', 'favorites'].indexOf(S.view) >= 0; }
  function key() { return S.sub.projects === 'tour' ? S.m.project : S.m.vproj; }
  function rec() { return myRec(key()); }
  function button(action, label, cls, attrs) { return '<button type="button" class="' + (cls || 'btn-ghost') + '" data-pw="' + action + '"' + (attrs || '') + '>' + label + '</button>'; }
  function val(v) { return esc(v || '—'); }
  function select(name, value, items, label) { return '<select class="pl-sel" data-pw-filter="' + name + '" aria-label="' + label + '">' + items.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (value === x[0] ? ' selected' : '') + '>' + esc(x[1]) + '</option>'; }).join('') + '</select>'; }
  function leads(id) { return Object.keys(WK.leads || {}).map(function (k) { return Object.assign({ id: k }, WK.leads[k]); }).filter(function (r) { return id && r.pj === id; }); }
  function norm(s) { return String(s || '').toLowerCase().replace(/ё/g, 'е'); }
  function redraw() { var y = scrollY; render(); scrollTo(0, y); }
  function open(k, tab) { state.pending = ''; state.tabs[k] = tab || 'profile'; S.view = 'projects'; S.sub.projects = 'all'; S.m.project = null; S.m.vproj = k; render(); scrollTo(0, 0); }
  function tabOf(k) { return state.tabs[k] || 'profile'; }
  function tabs(k) { var t = tabOf(k); return '<div class="pw-tabs" role="tablist" aria-label="Карточка проекта">' + [['profile', 'Профиль'], ['dates', 'Афиша'], ['analysis', 'Аналитика'], ['work', 'Связанные работы']].map(function (x) { return button('tab', esc(x[1]), 'pw-tab', ' role="tab" data-tab="' + x[0] + '" aria-selected="' + (t === x[0]) + '"'); }).join('') + '</div>'; }
  function header(k, r, title) {
    var p = r && r.profile || {}, ava = pjMedia(r, 'avatar'), cover = pjMedia(r, 'cover'), ls = leads(myFind(k)), st = ls.length ? STAGES[ls[0].stage] || ls[0].stage : '';
    return '<div class="pw-back">' + button('back', '← Все проекты', 'pj-plain') + '</div><section id="pjHero" class="pw-hero"' + (cover ? ' style="--pw-cover:url(\'' + esc(cover) + '\');background-position:center ' + (r.cover_y == null ? 30 : r.cover_y) + '%"' : '') + '>' +
      '<button class="pw-avatar" data-pj="photo" data-kind="avatar" aria-label="' + (ava ? 'Сменить' : 'Загрузить') + ' фото">' + (ava ? '<img src="' + esc(ava) + '" alt="">' : esc(pjInitials(title))) + '</button>' +
      '<div class="pw-title"><h1>' + esc(title) + '</h1>' + ((p.format || mostOf(S.pj && S.pj.l || [], 'format')) ? '<span class="pw-format-tag">' + esc(p.format || mostOf(S.pj.l, 'format')) + '</span>' : '') + (p.sub && p.sub !== title ? '<p>' + esc(p.sub) + '</p>' : '') + (st ? '<span class="pw-status">' + esc(st) + '</span>' : '') + '</div>' +
      '<div class="pw-actions"><button class="btn-ghost" data-fav="' + esc(k) + '" data-title="' + esc(title) + '" aria-pressed="' + !!(r && r.fav) + '" aria-label="' + (r && r.fav ? 'Убрать из избранного' : 'В избранное') + '">' + (r && r.fav ? '★' : '☆') + '</button>' +
      (!r ? button('register', 'В мою базу', 'btn-ghost') : '') + '<button class="btn-dark" data-pj="edit">Редактировать</button></div></section>' + tabs(k);
  }
  function currentPeriod() { var k = key() || ''; return state.periods[k] || { from: '', to: '' }; }
  function inPeriod(e) { var p = currentPeriod(); return (!p.from || e.date >= p.from) && (!p.to || e.date <= p.to); }
  function periodActive() { var p = currentPeriod(); return !!(p.from || p.to); }
  function periodLabel() { var p = currentPeriod(); return [p.from ? 'с ' + human(p.from) : '', p.to ? 'по ' + human(p.to) : ''].filter(Boolean).join(' ') || 'Все даты'; }
  function periodBar() { var p = currentPeriod(); return '<div class="pw-period"><span>Даты</span><label>С <input type="date" data-pw-date="from" value="' + p.from + '"></label><label>По <input type="date" data-pw-date="to" value="' + p.to + '"></label>' + (periodActive() ? button('period-clear', 'Все даты', 'pj-plain') : '<span class="sub2">Весь период</span>') + '<span id="pwPeriodError" class="err" hidden></span></div>'; }
  function clearPeriod() { state.periods[key()] = { from: '', to: '' }; }
  function linkRows(rows) { return (rows || []).map(function (r) { return '<a class="pj-plain" href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.label || r.url) + ' ↗</a>'; }).join('<br>'); }
  function riders(r) {
    var pr = r && r.profile || {}, list = pr.riders || [], id = r && myFind(key());
    return '<section class="card pw-box"><div class="pw-section-head"><h2>Райдеры</h2>' + button('rider-upload', '+ Файл', 'btn-ghost') + '</div>' +
      (list.length ? '<div class="pw-files">' + list.map(function (x) {
        var url = x.file ? '/api/market/myprojects/media/' + encodeURIComponent(x.file) + '?n=' + encodeURIComponent(x.label || x.file) : x.url;
        var type = { technical: 'Технический', hospitality: 'Бытовой', other: 'Райдер' }[x.kind] || 'Райдер';
        return '<div class="pw-file"><div><span class="sub2">' + type + '</span><a class="pj-plain" href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(x.label || x.file || x.url) + ' ↗</a></div>' +
          (x.file ? '<div class="pw-file-actions"><a class="pj-plain" href="' + esc(url + '&dl=1') + '">Скачать</a>' + button('rider-replace', 'Заменить', 'pj-plain', ' data-file="' + esc(x.file) + '" data-kind="' + esc(x.kind || 'other') + '"') + button('rider-remove', 'Убрать', 'pj-plain', ' data-file="' + esc(x.file) + '"') + '</div>' : '') + '</div>';
      }).join('') + '</div>' : '<p class="sub2">Добавьте файл или ссылку в редакторе профиля.</p>') + '</section>';
  }
  function aliases(r) {
    if (!r) return '';
    return '<section class="card pw-box"><div class="pw-section-head"><h2>Названия в афише</h2>' + button('alias-dialog', '+ Связать название', 'pj-plain') + '</div><p class="sub2">Даты всех связанных названий объединяются в карточке и аналитике.</p>' + (r.keys || []).map(function (k) { return '<span class="pw-alias">' + esc(k) + '</span>'; }).join('') + '</section>';
  }
  function aliasOptions(q) {
    var r = rec(), map = {};
    MR.forEach(function (e) { if (e.pk && r.keys.indexOf(e.pk) < 0 && (!q || norm(e.title).indexOf(norm(q)) >= 0)) map[e.pk] = e.title; });
    return Object.keys(map).slice(0, 30).map(function (k) { return button('alias-pick', esc(map[k]), 'wk-menu-item', ' data-key="' + esc(k) + '"'); }).join('') || '<p class="sub2">Других названий не найдено.</p>';
  }
  function profile(o) {
    var p = o.rec && o.rec.profile || {}, row = function (label, text) { return '<dt>' + label + '</dt><dd>' + text + '</dd>'; };
    return '<div class="pw-profile"><div><section class="card pw-box"><div class="pw-section-head"><h2>О проекте</h2><button class="pj-plain" data-pj="edit">Изменить</button></div>' +
      (p.about ? '<p class="pw-text">' + esc(p.about) + '</p>' : '<p class="sub2">Описание пока не заполнено.</p>') + '<dl class="pj-dl">' + row('Формат', val(p.format || mostOf(o.l, 'format'))) + row('Состав', val(p.crew)) + row('Гонорар', val(p.fee)) + row('Оценка', '<button class="pj-plain" data-pj="rating">' + (pjRating(o.rec) ? esc(ptLabel(ptTypeOf(o.rec.rating.s))) : 'Оценить проект') + '</button>') + '</dl></section>' +
      riders(o.rec) + aliases(o.rec) + '<section class="card pw-box"><h2>Заметки и ссылки</h2><p class="pw-text">' + val(o.rec && o.rec.note) + '</p>' + linkRows(o.rec && o.rec.links) + '</section></div><div>' +
      '<section class="card pw-box"><h2>Контакты</h2><dl class="pj-dl">' + row('Контакт', val(p.contact)) + row('Телефон', p.phone ? '<a class="pj-plain" href="tel:' + esc(p.phone.replace(/[^\d+]/g, '')) + '">' + esc(p.phone) + '</a>' : '—') +
      [['site', 'Сайт'], ['vk', 'ВКонтакте'], ['tg', 'Telegram'], ['instagram', 'Instagram']].map(function (x) { return row(x[1], p[x[0]] ? '<a class="pj-plain" href="' + esc(p[x[0]]) + '" target="_blank" rel="noopener">' + esc(p[x[0]]) + ' ↗</a>' : '—'); }).join('') + '</dl>' + (o.rec && o.rec.contacts ? '<p class="pw-text">' + esc(o.rec.contacts) + '</p>' : '') + '</section>' +
      WorkProcesses.coop(o.id) + '<section class="card pw-box"><h2>Афиша</h2><p>' + o.l.length + ' текущих · ' + o.past.length + ' архивных дат</p>' + button('tab', 'Открыть афишу →', 'pj-plain', ' data-tab="dates"') + '</section></div></div>';
  }
  function linkedIds(r, kind) { return ((r && r.connections || {})[kind] || []).slice(); }
  function connected(o) {
    var r = o.rec, ls = leads(o.id), s = '<section class="card pw-box"><div class="pw-section-head"><h2>Переговоры</h2>' + (!ls.length ? button('create-lead', '+ Переговоры', 'btn-ghost') : '') + '</div>';
    s += ls.length ? ls.map(function (l) { return '<div class="pw-work-row"><span>' + esc(l.title) + '<small>' + esc(STAGES[l.stage] || l.stage) + '</small></span><button class="pj-plain" data-proc-action="lead" data-id="' + l.id + '">Открыть →</button></div>'; }).join('') : '<p class="sub2">Запись воронки не связана.</p>';
    s += '</section>';
    [['lists', 'Подбор городов'], ['tours', 'Финмодели туров'], ['work', 'Рабочие проекты']].forEach(function (group) {
      var kind = group[0], source = kind === 'work' ? WK.projects : PLAN[kind], ids = linkedIds(r, kind);
      ls.forEach(function (l) { var id = kind === 'lists' ? l.list : kind === 'work' ? l.project : ''; if (id && ids.indexOf(id) < 0) ids.push(id); });
      s += '<section class="card pw-box"><div class="pw-section-head"><h2>' + group[1] + '</h2>' + button('create-' + kind, '+ Создать', 'btn-ghost') + '</div>';
      if (!ids.length) s += '<p class="sub2">Пока нет связанных записей.</p>';
      ids.forEach(function (id) { var item = (source || {})[id], manual = linkedIds(r, kind).indexOf(id) >= 0;
        s += '<div class="pw-work-row"><span>' + esc(item ? item.title : 'Запись удалена') + (item && kind === 'tours' ? '<small>' + (item.rows || []).length + ' городов · ' + esc(item.status || '') + '</small>' : '') + '</span><div>' + (item ? button('work-open', 'Открыть →', 'pj-plain', ' data-kind="' + kind + '" data-id="' + id + '"') : '') + (manual ? button('unlink', 'Отвязать', 'pj-plain', ' data-kind="' + kind + '" data-id="' + id + '"') : '') + '</div></div>';
      });
      var candidates = Object.keys(source || {}).filter(function (id) { return ids.indexOf(id) < 0; }).sort(function (a, b) { var aa = norm(source[a].title).indexOf(norm(o.title)) >= 0, bb = norm(source[b].title).indexOf(norm(o.title)) >= 0; return (+bb) - (+aa) || source[a].title.localeCompare(source[b].title, 'ru'); });
      s += '<div class="pw-link-form">' + select('link-' + kind, '', [['', 'Выбрать существующую запись…']].concat(candidates.map(function (id) { return [id, source[id].title]; })), 'Связать: ' + group[1]) + button('link', 'Связать', 'btn-ghost', ' data-kind="' + kind + '"') + '</div></section>';
    });
    return '<div class="pw-connected">' + s + '</div>';
  }
  function card(o) {
    var t = tabOf(o.k), main;
    if (t === 'analysis') return mProjectDetail(o.k);
    if (t === 'work') main = connected(o);
    else if (t === 'dates') main = '<div class="pw-date-tools"><button class="btn-ghost" data-pj="orgs">Организаторы</button></div>' + periodBar() + '<div class="pw-dates">' + o.list.replace(/<button class="pj-seg-btn" data-proute=[\s\S]*?<\/button>/g, '') + '</div>';
    else main = profile(o);
    return header(o.k, o.rec, o.rec ? o.rec.title : o.title) + main;
  }
  function analysis(k, r, title, l, body, nav, tiles) { state.tabs[k] = 'analysis'; var site = S.m.anTab === 'site'; return header(k, r, title) + (site ? '' : periodBar()) + '<div class="pw-analysis-tabs" role="tablist" aria-label="Разделы аналитики">' + nav + '</div>' + (site ? '' : '<div class="pw-analysis-summary">' + tiles + '</div>') + body; }
  function emptyAnalysis(k, allDates) {
    var r = myRec(k), title = r ? r.title : k; S.pj = { k: k, id: myFind(k), title: title, l: allDates, orgs: pjOrgs(allDates) }; state.tabs[k] = 'analysis';
    if (S.m.anTab === 'site' || !allDates.length && !periodActive()) return header(k, r, title) + '<div class="pw-analysis-tabs">' + button('site', 'Официальный сайт', 'btn-ghost') + '</div>' + siteSection(k, title);
    return header(k, r, title) + periodBar() + '<div class="empty"><h2>Нет дат за выбранный период</h2><p>Можно изменить период или подключить афишу официального сайта.</p>' + button('period-clear', 'Все даты', 'btn-ghost') + button('site', 'Официальный сайт', 'btn-ghost') + '</div>';
  }
  function database() {
    var market = S.view === 'touring' || state.scope === 'market', fav = S.view === 'favorites';
    var scopeTabs = '<div class="pw-tabs" role="tablist" aria-label="База проектов">' + [['mine', 'Моя база'], ['market', 'Найти в афише']].map(function (x) { return button('scope', x[1], 'pw-tab', ' data-scope="' + x[0] + '" role="tab" aria-selected="' + ((market ? 'market' : 'mine') === x[0]) + '"'); }).join('') + '</div>';
    var items = [], grouped = {};
    if (market) {
      MR.forEach(function (e) { if (e.pk) (grouped[e.pk] = grouped[e.pk] || []).push(e); });
      items = Object.keys(grouped).map(function (k) { var dates = grouped[k].slice().sort(function (a, b) { return a.date.localeCompare(b.date); }), r = myRec(k); return { k: k, title: mostOf(dates, 'title'), dates: dates, r: r, fmt: mostOf(dates, 'format') }; });
      if (S.view === 'touring') items = items.filter(function (x) { return mUniq(x.dates, 'city').length >= 2 && x.dates.some(function (e) { return e.tour === 'tour'; }); });
    } else items = Object.keys(MYP.projects).map(function (id) { var r = MYP.projects[id], dates = myEvents(r.keys); return { k: r.keys[0], title: r.title, dates: dates, r: r, fmt: (r.profile || {}).format || mostOf(dates, 'format'), id: id }; });
    if (fav) items = items.filter(function (x) { return x.r && x.r.fav; });
    var total = items.length, formats = items.map(function (x) { return x.fmt; }).filter(function (x, i, a) { return x && a.indexOf(x) === i; }).sort();
    items = items.filter(function (x) { var p = x.r && x.r.profile || {}, ls = leads(x.id || myFind(x.k));
      return (!state.q || norm([x.title, p.contact, p.phone, p.about].join(' ')).indexOf(norm(state.q)) >= 0) && (!state.format || x.fmt === state.format) && (!state.status || ls.some(function (l) { return l.stage === state.status; })) &&
        (!state.only || state.only === 'fav' && x.r && x.r.fav || state.only === 'incomplete' && (!p.contact || !p.fee || !(p.riders || []).length));
    });
    items.sort(function (a, b) { return state.order === 'updated' ? ((b.r || {}).upd || '').localeCompare((a.r || {}).upd || '') : a.title.localeCompare(b.title, 'ru'); });
    var limited = items.slice(0, state.limit || 150);
    var body = limited.length ? '<div class="card pw-table-wrap"><table class="vtable pw-table"><thead><tr><th>Проект</th><th>' + (market ? 'Городов' : 'Сотрудничество') + '</th><th>Гонорар</th><th>Контакт</th><th>Ближайшая дата</th></tr></thead><tbody>' + limited.map(function (x) {
      var p = x.r && x.r.profile || {}, ls = leads(x.id || myFind(x.k)), ava = pjMedia(x.r, 'avatar'), next = x.dates[0];
      return '<tr><th scope="row"><div class="pw-project-cell"><span class="pw-mini" aria-hidden="true">' + (ava ? '<img src="' + esc(ava) + '" alt="">' : esc(pjInitials(x.title))) + '</span>' + button('open', esc(x.title), 'pj-plain', ' data-key="' + esc(x.k) + '"') + (x.r && x.r.fav ? '<span class="pw-star" title="Избранное">★</span>' + (myDiff(x.r).n ? button('changes', String(myDiff(x.r).n), 'pw-change-count', ' data-key="' + esc(x.k) + '" aria-label="Изменения: ' + myDiff(x.r).n + '"') : '') : '') + '</div>' + (x.fmt ? '<small class="pw-format">' + esc(x.fmt) + '</small>' : '') + '</th><td>' + (market ? mUniq(x.dates, 'city').length : ls.length ? esc(STAGES[ls[0].stage] || ls[0].stage) : '—') + '</td><td>' + val(p.fee) + '</td><td>' + val(p.contact) + '</td><td>' + (next ? human(next.date) + '<small>' + esc(next.city) + '</small>' : '<span class="sub2">Нет текущих дат</span>') + '</td></tr>';
    }).join('') + '</tbody></table></div>' : '<div class="empty"><h2>' + (state.q ? 'Проект не найден' : 'Пока нет проектов') + '</h2><p>Добавьте проект вручную или найдите его в афише.</p>' + button('new', '+ Добавить проект', 'btn-dark') + '</div>';
    return head(fav ? 'Избранные проекты' : S.view === 'touring' ? 'Гастролирует' : 'Проекты', '', button('new', '+ Добавить проект', 'btn-dark')) + scopeTabs +
      '<div class="pw-toolbar"><input class="pl-in pw-search" type="search" data-pw-search aria-label="Найти проект" placeholder="Проект, контакт, телефон" value="' + esc(state.q) + '">' + select('format', state.format, [['', 'Все форматы']].concat(formats.map(function (x) { return [x, x]; })), 'Формат') +
      select('status', state.status, [['', 'Любое сотрудничество']].concat(Object.keys(STAGES).map(function (x) { return [x, STAGES[x]]; })), 'Сотрудничество') + select('only', state.only, [['', 'Все проекты'], ['fav', 'Избранные'], ['incomplete', 'Есть незаполненные поля']], 'Показать') +
      select('order', state.order, [['title', 'По названию'], ['updated', 'Недавно изменённые']], 'Порядок') + button('reset', 'Сбросить', 'pj-plain') + '<span class="sub2">' + items.length + ' из ' + total + '</span></div>' + body + (limited.length < items.length ? button('more', 'Показать ещё', 'btn-ghost pw-more') : '');
  }
  function renderWorkspace() {
    if (!MY_READY) return head('Проекты', '') + '<p class="sub">Загружаем вашу базу…</p>' + button('reload', 'Повторить загрузку', 'btn-ghost');
    if (state.pending) { var r = MYP.projects[state.pending]; if (r) { S.m.vproj = r.keys[0]; S.m.project = null; S.sub.projects = 'all'; if (state.pendingTab) { state.tabs[r.keys[0]] = state.pendingTab; state.pendingTab = ''; } } else { var id = state.pending; state.pending = ''; return head('Проект не найден', '') + '<p>Карточка ' + esc(id) + ' недоступна.</p>' + button('back', 'Все проекты', 'btn-ghost'); } state.pending = ''; }
    if (S.sub.projects === 'tour' && S.m.project) { state.tabs[S.m.project] = 'analysis'; return mProjectDetail(S.m.project); }
    if (S.m.vproj) return mShowcaseDetail(S.m.vproj);
    return database();
  }
  function draftKey(k) { return 'ticketmonitor.projectDraft.' + k + '.' + draftSession; }
  function formData() { var f = document.getElementById('pjForm'), d = { fields: {}, riders: [], links: [] }; if (!f) return d;
    f.querySelectorAll('input[name],textarea[name]').forEach(function (x) { if (!x.closest('.mylink')) d.fields[x.name] = x.value; });
    f.querySelectorAll('.mylink').forEach(function (row) { d[row.dataset.list].push({ label: row.querySelector('[name="label"]').value, url: row.querySelector('[name="url"]').value }); }); return d;
  }
  function readDraft(k) { try { var keys = Object.keys(localStorage).filter(function(n){return n === 'ticketmonitor.projectDraft.' + k || n.indexOf('ticketmonitor.projectDraft.' + k + '.') === 0;}); var drafts = keys.map(function(n){var d=JSON.parse(localStorage.getItem(n));if(d)d.storageKey=n;return d;}).filter(Boolean).sort(function(a,b){return b.at.localeCompare(a.at);}); return drafts.find(function(d){return d.storageKey===draftKey(k);}) || drafts[0] || null; } catch (_) { return null; } }
  function dirty() { return !!(editor && JSON.stringify(formData()) !== JSON.stringify(editor.base)); }
  function storeDraft() { if (!editor || !document.getElementById('pjForm') || !dirty()) return; try { localStorage.setItem(draftKey(editor.key), JSON.stringify({ data: formData(), base: editor.base, rev: editor.rev, at: new Date().toISOString() })); } catch (_) { showError('Не удалось сохранить черновик в браузере. Сохраните профиль перед закрытием.'); } }
  function fillForm(d) { var f = document.getElementById('pjForm'); if (!f) return; Object.keys(d.fields).forEach(function (n) { if (f.elements[n]) f.elements[n].value = d.fields[n]; }); [['riders', 'pjRiders'], ['links', 'pjLinks']].forEach(function (x) { document.getElementById(x[1]).innerHTML = pjLinkRows(d[x[0]], x[0]); }); }
  function editorOpened() {
    var r = myRec(S.pj.k); editor = { key: S.pj.k, rev: r ? r.rev || 0 : 0, base: formData(), busy: false };
    var draft = readDraft(editor.key); if (draft) document.getElementById('pjForm').insertAdjacentHTML('afterbegin', '<div class="note pw-draft">Есть несохранённый черновик. ' + button('draft-restore', 'Восстановить', 'pj-plain') + ' · ' + button('draft-discard', 'Удалить черновик', 'pj-plain') + '</div>');
  }
  function showError(message, conflict) { var e = document.getElementById('pj-err'); if (!e) return; e.hidden = false; e.textContent = message; if (conflict) e.insertAdjacentHTML('beforeend', ' ' + button('draft-refresh', 'Перечитать и сравнить', 'pj-plain')); }
  function editorSaving() { if (!editor) return; storeDraft(); editor.busy = true; document.querySelectorAll('#pjForm input,#pjForm textarea,#pjForm select,#pjForm button').forEach(function(x){if(!x.disabled){x.dataset.pwSaving='1';x.disabled=true;}}); var b = document.querySelector('#pjDlg [data-pj="save"]'); if (b) { b.disabled = true; b.textContent = 'Сохраняем…'; } }
  function saveError(e) { if (editor && document.getElementById('pjForm')) { editor.busy = false; document.querySelectorAll('#pjForm [data-pw-saving]').forEach(function(x){x.disabled=false;delete x.dataset.pwSaving;}); var b = document.querySelector('#pjDlg [data-pj="save"]'); if (b) { b.disabled = false; b.textContent = 'Сохранить'; } storeDraft(); showError(e.message || 'Нет связи с сервером. Черновик сохранён.', e.conflict); } }
  function editorDone() { if (editor) { localStorage.removeItem(draftKey(editor.key)); editor = null; } var d = document.getElementById('pjDlg'); if (d && d.open) d.close(); }
  function closeDialog(d) { if (editor && d.querySelector('#pjForm')) { if (editor.busy) return; storeDraft(); if (dirty() && !confirm('Закрыть без сохранения на сервере? Черновик останется в этом браузере.')) return; editor = null; } d.close(); }
  function saved(op, rev) { if (editor && ['media', 'coverpos'].indexOf(op.op) >= 0 && editor.rev === rev) editor.rev = (myRec(editor.key) || {}).rev || rev; if (document.getElementById('pjForm') && op.op === 'media') { pjPhRefresh('avatar'); pjPhRefresh('cover'); } }
  async function ensureCard() { if (!CAN_SAVE) { toast('Откройте сайт через приложение для сохранения в базу'); return null; } if (rec()) return rec(); var d = await mySave({ op: 'register', key: key(), title: S.pj.title }, 'Проект в вашей базе'); return d ? rec() : null; }
  async function connect(kind, id, on) { if (!await ensureCard()) return; return mySave({ op: 'connections', key: key(), title: S.pj.title, kind: kind, target: id, on: on }, on ? 'Связь сохранена' : 'Связь убрана'); }
  async function request(path, data) { var x = await apiJson('POST', path, data); if (!x.ok) throw new Error(x.d.error || 'Ошибка сохранения'); return x.d; }
  async function createWork(kind) {
    if (!await ensureCard()) return;
    var r = rec(), title = r.title, p = r.profile || {}, fee = parseFloat(String(p.fee || '').replace(/[\s\u00a0]/g, '').replace(',', '.')), crew = parseFloat(p.crew), id, d;
    if (kind === 'work') { id = wkId('p'); var stage = WK_STAGE[0]; d = await request('/api/work', { op: 'put', kind: 'projects', id: id, data: { title: title, stage: stage ? stage[0] : 'idea', created: TODAY } }); WK = d; }
    else {
      id = plId(kind === 'lists' ? 'l' : 't'); var data;
      if (kind === 'lists') { data = { title: title, project: title, rows: [], econ: {} }; if (p.format) data.format = p.format; if (fee > 0) data.econ.fee = fee; if (crew > 0) data.econ.crew = crew; var extra = String(p.fee || '').match(/\+\s*([\d.,]+)\s*%/); if (extra) data.econ.cashless = Number(extra[1].replace(',', '.')); }
      else { var project = plId('p'), pr = { title: title, key: key() }; if (fee > 0) pr.fee = fee; if (crew > 0) pr.crew = crew; var extra = String(p.fee || '').match(/\+\s*([\d.,]+)\s*%/); if (extra) pr.cashless = Number(extra[1].replace(',', '.')); PLAN = await request('/api/planning', { op: 'put', kind: 'projects', id: project, data: pr }); data = { title: title + ' — новый тур', project: project, status: 'Черновик', rows: [] }; }
      PLAN = await request('/api/planning', { op: 'put', kind: kind, id: id, data: data });
    }
    await connect(kind, id, true);
  }
  function fileUpload(replace, kind) {
    var input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.webp,.rtf,.odt,.ods,.txt,.zip';
    input.onchange = async function () { var f = input.files[0]; if (!f) return; if (f.size > 15 * 1024 * 1024) { toast('Файл до 15 МБ'); return; } try { if (!await ensureCard()) return; var data = await new Promise(function (resolve, reject) { var reader = new FileReader(); reader.onload = function () { resolve(reader.result); }; reader.onerror = reject; reader.readAsDataURL(f); }); await mySave({ op: 'rider', id: myFind(key()), name: f.name, data: data, replace: replace || '', rider_kind: kind || 'other' }, 'Райдер сохранён'); } catch (e) { toast('Не сохранено: ' + e.message); } };
    input.click();
  }
  async function action(b) {
    var a = b.dataset.pw, k = key();
    if (a === 'reload') await myLoad();
    else if (a === 'back') { S.m.vproj = S.m.project = null; S.view = 'projects'; S.sub.projects = 'all'; state.pending = ''; render(); scrollTo(0, 0); }
    else if (a === 'scope') { state.scope = b.dataset.scope; S.view = 'projects'; S.sub.projects = 'all'; S.m.project = S.m.vproj = null; state.limit = 150; redraw(); }
    else if (a === 'open') open(b.dataset.key);
    else if (a === 'changes') { open(b.dataset.key, 'dates'); S.m.pjMode = 'chg'; redraw(); }
    else if (a === 'tab') { state.tabs[k] = b.dataset.tab; if (state.tabs[k] === 'analysis' && !S.m.anTab) S.m.anTab = 'route'; redraw(); }
    else if (a === 'site') { state.tabs[k] = 'analysis'; S.m.anTab = 'site'; redraw(); }
    else if (a === 'register') await ensureCard();
    else if (a === 'alias-dialog') pjDialog('pj-alias', 'Связать название из афиши', '<input class="pl-in" type="search" data-pw-alias-search aria-label="Название в афише" placeholder="Найти название"><div id="pwAliasOptions">' + aliasOptions(S.pj.title) + '</div>');
    else if (a === 'alias-pick') { var d = await mySave({op:'link',id:myFind(k),key:b.dataset.key}, 'Название связано'); if (d) document.getElementById('pjDlg').close(); }
    else if (a === 'new' && !CAN_SAVE) toast('Добавление проекта работает на сайте через приложение');
    else if (a === 'new') pjDialog('pj-edit-new', 'Добавить проект', '<form id="pwNewForm"><div class="field"><label for="pwNewTitle">Название проекта</label><input id="pwNewTitle" class="pl-in" name="title" maxlength="300" required placeholder="Артист, спектакль или программа"></div><p class="sub2">Карточку можно заполнить без дат в афише.</p><div id="pwNewError" class="err" hidden></div><div class="form-actions">' + button('create', 'Создать проект', 'btn-dark') + '</div></form>');
    else if (a === 'create') { var title = document.getElementById('pwNewTitle').value.trim(), err = document.getElementById('pwNewError'); if (!title) { err.hidden = false; err.textContent = 'Введите название проекта'; return; } b.disabled = true; var op = { op: 'create', manual: true, title: title, key: projKey(title) }; var d = await mySave(op, 'Карточка проекта готова'); b.disabled = false; if (d) { var made = d.projects[op.id] || myRec(projKey(title)); document.getElementById('pjDlg').close(); open(made.keys[0]); } else { err.hidden = false; err.textContent = 'Не удалось создать проект. Попробуйте ещё раз.'; } }
    else if (a === 'period-clear') { clearPeriod(); redraw(); }
    else if (a === 'reset') { state.q = state.format = state.status = state.only = ''; state.order = 'title'; redraw(); }
    else if (a === 'more') { state.limit = (state.limit || 150) + 150; redraw(); }
    else if (a === 'rider-upload') pjDialog('pj-rider', 'Добавить райдер', '<div class="pw-upload-types">' + [['technical', 'Технический райдер'], ['hospitality', 'Бытовой райдер'], ['other', 'Другой файл']].map(function (x) { return button('rider-pick', x[1], 'btn-ghost', ' data-kind="' + x[0] + '"'); }).join('') + '</div>');
    else if (a === 'rider-pick') { document.getElementById('pjDlg').close(); fileUpload('', b.dataset.kind); }
    else if (a === 'rider-replace') fileUpload(b.dataset.file, b.dataset.kind);
    else if (a === 'rider-remove') { if (confirm('Убрать райдер из карточки? Его можно будет вернуть через журнал изменений.')) await mySave({ op: 'rider-del', id: myFind(k), file: b.dataset.file }, 'Райдер убран'); }
    else if (a === 'link') { var choice = b.parentNode.querySelector('select').value; if (choice) await connect(b.dataset.kind, choice, true); }
    else if (a === 'unlink') await connect(b.dataset.kind, b.dataset.id, false);
    else if (a === 'work-open') { var kind = b.dataset.kind, id = b.dataset.id; if (kind === 'work') { goView('work'); wkpOpenPage(id); } else { S.pl.tab = kind === 'lists' ? 'build' : 'tours'; if (kind === 'lists') S.pl.tb.list = id; else S.pl.tour = id; goView('planning'); } }
    else if (a === 'create-lists' || a === 'create-tours' || a === 'create-work') await createWork(a.slice(7));
    else if (a === 'create-lead') { if (!await ensureCard()) return; var proc = Object.keys(WK.procs || {}).find(function (id) { return WK.procs[id].kind === 'artists'; }); if (!proc) { toast('Сначала создайте процесс поиска артистов'); return; } var p = rec().profile || {}, fee = parseFloat(String(p.fee || '').replace(/\s/g, '')), id = wkId('l'); WK = await request('/api/work', { op: 'put', kind: 'leads', id: id, data: { title: rec().title, proc: proc, stage: 'found', pj: myFind(k), contact: [p.contact, p.phone].filter(Boolean).join(' · '), fee: fee > 0 ? fee : null, created: TODAY } }); redraw(); }
    else if (a === 'draft-restore') { var draft = readDraft(editor.key); if (draft) { fillForm(draft.data); editor.rev = draft.rev; editor.base = draft.base; showError('Черновик восстановлен. Сохраните его на сервере.'); } }
    else if (a === 'draft-discard') { var draft = readDraft(editor.key); if (draft) localStorage.removeItem(draft.storageKey); var banner = document.querySelector('.pw-draft'); if (banner) banner.remove(); }
    else if (a === 'draft-refresh') {
      var local = formData(), base = editor.base, oldKey = editor.key, loaded = await myLoad(); if (!loaded || editor.key !== oldKey) return;
      var fresh = myRec(oldKey), latest = { fields: {}, riders: [], links: [] }, pr = fresh.profile || {}, conflicts = [];
      Object.keys(local.fields).forEach(function (n) { var remote = n === 'note' || n === 'contacts' ? fresh[n] || '' : n === 'name' ? fresh.title : pr[n] || ''; latest.fields[n] = remote; if (local.fields[n] !== base.fields[n]) { if (remote !== base.fields[n] && remote !== local.fields[n]) conflicts.push(n === 'fee' ? 'Гонорар: на сервере «' + remote + '»' : 'Изменено поле «' + n + '»'); latest.fields[n] = local.fields[n]; } });
      ['riders', 'links'].forEach(function (n) { var remote = n === 'riders' ? (pr.riders || []).filter(function (x) { return !x.file; }) : fresh.links || []; if (!remote.length) remote = [{ label: '', url: '' }]; latest[n] = JSON.stringify(local[n]) !== JSON.stringify(base[n]) ? local[n] : remote; });
      editor.rev = fresh.rev || 0; editor.base = { fields: Object.assign({}, latest.fields), riders: (pr.riders || []).filter(function (x) { return !x.file; }), links: fresh.links || [] }; Object.keys(editor.base.fields).forEach(function (n) { editor.base.fields[n] = n === 'note' || n === 'contacts' ? fresh[n] || '' : n === 'name' ? fresh.title : pr[n] || ''; });
      fillForm(latest); storeDraft(); showError(conflicts.length ? conflicts.join('. ') + '. В форме оставлены ваши изменения. Проверьте их перед сохранением.' : 'Свежие данные загружены, ваши изменения сохранены в форме. Можно сохранить.');
    }
  }
  document.addEventListener('click', function (e) { var b = e.target.closest && e.target.closest('[data-pw]'); if (!b || b.disabled || state.busy) return; e.preventDefault(); state.busy = true; Promise.resolve(action(b)).catch(function (er) { toast('Не сохранено: ' + er.message); }).finally(function () { state.busy = false; }); });
  document.addEventListener('submit', function (e) { if (e.target.id === 'pwNewForm') { e.preventDefault(); action(e.target.querySelector('[data-pw="create"]')); } if (e.target.id === 'pjForm') { e.preventDefault(); pjSave(); } });
  document.addEventListener('input', function (e) {
    if (e.target.hasAttribute('data-pw-search')) { state.q = e.target.value; state.limit = 150; clearTimeout(searchTimer); if (!e.isComposing) searchTimer = setTimeout(function(){ var field=document.querySelector('[data-pw-search]'), focused=field===document.activeElement, at=field&&field.selectionStart; redraw(); var q=document.querySelector('[data-pw-search]'); if(focused&&q) {q.focus();try{q.setSelectionRange(at,at);}catch(_){}} },200); }
    if (e.target.hasAttribute('data-pw-alias-search')) document.getElementById('pwAliasOptions').innerHTML = aliasOptions(e.target.value);
    if (e.target.closest('#pjForm')) { clearTimeout(draftTimer); draftTimer = setTimeout(storeDraft, 150); }
  });
  document.addEventListener('change', function (e) {
    if (e.target.hasAttribute('data-pw-filter') && e.target.dataset.pwFilter.indexOf('link-') !== 0) { state[e.target.dataset.pwFilter] = e.target.value; state.limit = 150; redraw(); }
    if (e.target.hasAttribute('data-pw-date')) { var p = Object.assign({}, currentPeriod()); p[e.target.dataset.pwDate] = e.target.value; if (p.from && p.to && p.from > p.to) { var er = document.getElementById('pwPeriodError'); er.hidden = false; er.textContent = 'Конец периода раньше начала'; return; } state.periods[key()] = p; redraw(); }
  });
  window.addEventListener('beforeunload', function (e) { storeDraft(); if (editor && (dirty() || editor.busy)) { e.preventDefault(); e.returnValue = ''; } });
  function relatedLine(kind, id) { var names = Object.keys(MYP.projects).filter(function (pid) { return linkedIds(MYP.projects[pid], kind).indexOf(id) >= 0 || leads(pid).some(function (l) { return kind === 'lists' ? l.list === id : kind === 'work' && l.project === id; }); }).map(function (pid) { var r = MYP.projects[pid]; return button('open', esc(r.title), 'pj-plain', ' data-key="' + esc(r.keys[0]) + '"'); }); return names.length ? '<div class="wk-pick">Репертуар: ' + names.join(' · ') + '</div>' : ''; }
  g.ProjectWorkspace = { relatedLine: relatedLine, active: active, render: renderWorkspace, card: card, analysis: analysis, emptyAnalysis: emptyAnalysis, inPeriod: inPeriod, periodActive: periodActive, periodLabel: periodLabel, clearPeriod: clearPeriod,
    editorOpened: editorOpened, editorBusy: function () { return editor && editor.busy; }, editorRevision: function () { return editor ? editor.rev : 0; }, profileVersion: function(k, fallback) { return editor && editor.key === k ? editor.rev : fallback; }, editorSaving: editorSaving, editorDone: editorDone, closeDialog: closeDialog, saved: saved, saveError: saveError,
    hash: function () { if (!active()) return null; var r = rec(), id = r && myFind(key()); return active() && id ? 'projects:card:' + id + ':' + tabOf(key()) : state.pending ? 'projects:card:' + state.pending + ':' + (state.pendingTab || 'profile') : null; },
    fromHash: function (parts) { if (parts[0] === 'projects' && parts[1] === 'card' && /^p[a-z0-9]{1,20}$/.test(parts[2] || '')) { S.view = 'projects'; S.sub.projects = 'all'; S.m.vproj = S.m.project = null; state.pending = parts[2]; var r = MYP.projects[parts[2]]; if (r) state.tabs[r.keys[0]] = parts[3] || 'profile'; else state.pendingTab = parts[3] || 'profile'; return true; } state.pending = ''; state.pendingTab = ''; return false; }
  };
})(window);
