// Календарь работы: только существующие задачи, дедлайны проектов и гастроли. Данные — общий WK, запись — /api/work.
(function (root) {
  'use strict';
  function iso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function date(s) { return new Date(s + 'T12:00:00'); } // местный полдень: без сдвига дня при UTC и переходе на летнее время
  function add(s, n) { var d = date(s); d.setDate(d.getDate() + n); return iso(d); }
  function monthDays(anchor, week) {
    var d = date(anchor), first = week ? anchor : anchor.slice(0, 7) + '-01';
    var start = add(first, -((date(first).getDay() + 6) % 7));
    var days = week ? 7 : Math.max(35, Math.ceil((((date(first).getDay() + 6) % 7) + new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()) / 7) * 7);
    return Array.from({ length: days }, function (_, i) { return add(start, i); });
  }
  function shift(anchor, step, week) {
    if (week) return add(anchor, step * 7);
    var d = date(anchor), day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + step);
    d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate())); return iso(d);
  }
  var COLORS = {
    blue: ['#eaf6fa', '#41a2ca'], green: ['#effbe8', '#81b55a'], violet: ['#f4effc', '#a08ac5'],
    teal: ['#e9f9f5', '#5dafa3'], pink: ['#fcefeb', '#ce9eaa'], amber: ['#fffbe5', '#c9b952'],
    indigo: ['#eef2fc', '#8294ce'], brown: ['#f8f1eb', '#b1977c'], gray: ['#f4f6f7', '#a0aaaf']
  };
  function items(work, project, query) {
    var out = [], q = (query || '').trim().toLocaleLowerCase('ru');
    function push(kind, id, r, title, day, color, detail) {
      if (!day || (project && r.project !== project)) return;
      var p = (work.projects || {})[r.project], pname = p ? p.title : '';
      if (q && (title + ' ' + pname + ' ' + (detail || '')).toLocaleLowerCase('ru').indexOf(q) < 0) return;
      out.push({ key: kind + ':' + id, kind: kind, id: id, title: title, date: day, project: r.project || '', pname: pname, color: color, done: !!r.done, detail: detail || '', rec: r });
    }
    Object.keys(work.tasks || {}).forEach(function (id) {
      var t = work.tasks[id], tag = (work.tags || {})[(t.tags || [])[0]];
      push('task', id, t, t.text, t.due, tag && COLORS[tag.color] ? tag.color : 'blue', t.desc);
    });
    Object.keys(work.projects || {}).forEach(function (id) {
      var p = work.projects[id]; push('deadline', id, Object.assign({}, p, { project: id }), p.title, p.deadline, 'amber', p.note);
    });
    Object.keys(work.shows || {}).forEach(function (id) {
      var s = work.shows[id]; push('show', id, s, s.city || s.name || 'Гастроли', s.date, 'green', [s.name, s.city].filter(Boolean).join(' · '));
    });
    var rank = { task: 0, deadline: 1, show: 2 };
    return out.sort(function (a, b) { return a.date.localeCompare(b.date) || Number(a.done) - Number(b.done) || rank[a.kind] - rank[b.kind] || a.title.localeCompare(b.title, 'ru'); });
  }
  var KIND = { task: 'Задача', deadline: 'Готовность проекта', show: 'Гастроли' };
  function state() { return S.wk.calendar || (S.wk.calendar = { anchor: wkDay(0), day: wkDay(0), event: '', project: '', query: '', search: false, view: 'month' }); }
  function fmt(s, opts) { return date(s).toLocaleDateString('ru-RU', opts); }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function style(e) { var c = COLORS[e.color] || COLORS.blue; return '--wc-tint:' + c[0] + ';--wc-mark:' + c[1]; }
  function icon(name) {
    var paths = { plus: '<path d="M8 3v10M3 8h10"/>', prev: '<path d="M10 4L6 8l4 4"/>', next: '<path d="M6 4l4 4-4 4"/>', search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>', clock: '<circle cx="8" cy="8" r="6"/><path d="M8 4v4l2 1.5"/>', calendar: '<rect x="2" y="3" width="12" height="11" rx="2"/><path d="M2 7h12M5 1.5v3M11 1.5v3"/>' };
    return '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (paths[name] || paths.plus) + '</svg>';
  }
  function eventButton(e) {
    return '<button type="button" class="wkc-event' + (e.done ? ' done' : '') + (state().event === e.key ? ' active' : '') + '" data-wkc-event="' + esc(e.key) + '" style="' + style(e) + '" title="' + esc(KIND[e.kind] + ': ' + e.title + (e.pname ? ' · ' + e.pname : '')) + '">' + esc(e.title) + '</button>';
  }
  function grid(s, list, days) {
    var weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
    return '<div class="wkc-content' + (s.view === 'week' ? ' wkc-week' : '') + '"><div class="wkc-weekdays">' + weekdays.map(function (w, i) { return '<span><abbr title="' + w + '" data-short="' + ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][i] + '">' + w + '</abbr></span>'; }).join('') + '</div>' +
      '<div class="wkc-grid" role="group" aria-label="' + esc(fmt(s.anchor, { month: 'long', year: 'numeric' })) + '">' + days.map(function (day) {
        var l = list.filter(function (e) { return e.date === day; }), outside = day.slice(0, 7) !== s.anchor.slice(0, 7), limit = s.view === 'week' ? l.length : 3;
        return '<div class="wkc-day' + (l.length ? ' has-events' : '') + (outside ? ' outside' : '') + (s.day === day ? ' selected' : '') + (day === wkDay(0) ? ' today' : '') + '"' + (l.length ? ' style="' + style(l[0]) + '"' : '') + '>' +
          '<button type="button" class="wkc-daypick" data-wkc-day="' + day + '" aria-pressed="' + (s.day === day) + '" aria-label="' + esc(fmt(day, { day: 'numeric', month: 'long', year: 'numeric' }) + ' · записей: ' + l.length) + '"' + (day === wkDay(0) ? ' aria-current="date"' : '') + '></button><span class="wkc-daynum">' + +day.slice(8) + '</span>' +
          '<div class="wkc-events">' + l.slice(0, limit).map(eventButton).join('') + (l.length > limit ? '<button type="button" class="wkc-event wkc-more" data-wkc-day="' + day + '">Ещё ' + (l.length - limit) + '</button>' : '') + '</div></div>';
      }).join('') + '</div></div>';
  }
  function projectLink(e) {
    return e.project && WK.projects[e.project] ? '<button type="button" class="wkc-projectlink" data-wk-open="' + esc(e.project) + '">' + wtsAv(e.project) + '<span>' + esc(e.pname) + '</span></button>' : '';
  }
  function taskDetail(e) {
    var t = Object.assign({ id: e.id }, e.rec), subs = wkSubsOrdered(t.subs), nd = subs.filter(function (x) { return x.done; }).length;
    return '<div class="wkc-detail"><div class="wkc-detail-top">' + wkPrioChip(t) + wkStatusChip(t) + '<button type="button" class="wkc-edit" data-wkt-open="' + t.id + '" aria-label="Редактировать задачу">•••</button></div>' +
      '<div class="wkc-meta">' + (t.created ? 'Создана ' + esc(fmt(t.created, { day: 'numeric', month: 'short' })) : 'Задача') + (t.upd ? ' · изменена ' + esc(fmt(t.upd.slice(0, 10), { day: 'numeric', month: 'short' })) : '') + '</div>' +
      '<h2>' + esc(t.text) + '</h2>' + projectLink(e) + '<div class="wkc-facts"><div><small>Срок</small>' + wkDateBtn('tasks|' + t.id + '|due', t.due, { due: true, done: t.done, label: 'Срок задачи' }) + '</div><div><small>План</small><b>' + (t.est ? esc(wkDur(t.est * 60)) : 'Не задан') + '</b></div></div>' +
      '<label class="wkc-toggle-row">Задача выполнена<input type="checkbox" class="wkc-switch" data-wkc-done="' + t.id + '" aria-label="Задача выполнена"' + (t.done ? ' checked' : '') + '></label>' +
      '<p class="wkc-description" style="margin-top:20px">' + esc(t.desc || t.note || 'Добавьте описание в окне задачи.') + '</p>' +
      '<div class="wkc-subhead">Подзадачи <span>' + (subs.length ? nd + ' из ' + subs.length : '') + '</span><button type="button" data-wkc-addsub="' + t.id + '" aria-label="Добавить подзадачу">' + icon('plus') + '</button></div>' +
      '<ul class="wkc-subs">' + subs.map(function (sub) { return '<li class="' + (sub.done ? 'done' : '') + '"><label><input type="checkbox" class="wkc-switch" data-wkc-sub="' + t.id + '|' + sub.id + '"' + (sub.done ? ' checked' : '') + ' aria-label="' + esc(sub.text) + '"><span>' + esc(sub.text) + '</span></label></li>'; }).join('') + '</ul>' +
      '<button type="button" class="wkc-opentask" data-wkt-open="' + t.id + '">Открыть задачу<b aria-hidden="true">↗</b></button></div>';
  }
  function detail(e) {
    if (e.kind === 'task') return taskDetail(e);
    return '<div class="wkc-detail"><div class="wkc-meta">' + KIND[e.kind] + '</div><h2>' + esc(e.kind === 'show' ? e.pname || 'Гастроли' : e.title) + '</h2>' + projectLink(e) +
      '<div class="wkc-facts"><div><small>Дата</small><b>' + esc(fmt(e.date, { day: 'numeric', month: 'long' })) + '</b></div></div>' +
      '<p class="wkc-description">' + esc(e.detail || (e.kind === 'deadline' ? 'Дедлайн готовности проекта.' : '')) + '</p>' +
      (e.project && WK.projects[e.project] ? '<button type="button" class="wkc-opentask" data-wk-open="' + esc(e.project) + '">Открыть проект<b aria-hidden="true">↗</b></button>' : '') + '</div>';
  }
  function sidebar(s, list) {
    var l = list.filter(function (e) { return e.date === s.day; }), selected = l.filter(function (e) { return e.key === s.event; })[0] || l[0];
    s.event = selected ? selected.key : '';
    return '<aside class="wkc-side" aria-label="Расписание и детали выбранного дня"><div class="wkc-agenda"><h2>' + cap(fmt(s.day, { weekday: 'long' })) + ',<br>' + esc(fmt(s.day, { day: 'numeric', month: 'long' })) + '</h2>' +
      '<div class="wkc-agenda-date">' + icon('calendar') + fmt(s.day, { year: 'numeric' }) + ' · ' + l.length + ' ' + plural(l.length, 'запись', 'записи', 'записей') + '</div>' +
      (l.length ? '<div class="wkc-agenda-list">' + l.map(function (e) { return '<button type="button" class="wkc-agenda-item' + (e === selected ? ' on' : '') + '" data-wkc-event="' + esc(e.key) + '" style="' + style(e) + '" aria-pressed="' + (e === selected) + '"><i class="wkc-agenda-dot" aria-hidden="true"></i><span><b>' + esc(e.title) + '</b><small>' + esc(KIND[e.kind] + (e.pname ? ' · ' + e.pname : '')) + '</small></span></button>'; }).join('') + '</div>' : '<p class="wkc-agenda-empty">На этот день ничего не запланировано.</p>') +
      '<button type="button" class="wkc-addday" data-wkc-new>' + icon('plus') + 'Задача на этот день</button></div>' +
      (selected ? detail(selected) : '<div class="wkc-detail"><div class="wkc-quiet">Выберите запись в календаре,<br>чтобы посмотреть подробности.</div></div>') + '</aside>';
  }
  function renderCalendar() {
    var gate = wkGate('Календарь'); if (gate) return gate;
    var s = state(), list = items(WK, s.project, s.query), days = monthDays(s.anchor, s.view === 'week');
    // После смены срока из общего окна выбранная запись следует за своей датой.
    var active = list.filter(function (e) { return e.key === s.event; })[0];
    if (active && active.date !== s.day) { s.day = active.date; s.anchor = active.date; days = monthDays(s.anchor, s.view === 'week'); }
    var month = cap(fmt(s.anchor, { month: 'long', year: 'numeric' }).replace(/\sг\.$/, ''));
    var from = s.view === 'week' ? days[0] : s.anchor.slice(0, 7) + '-01', to = s.view === 'week' ? days[6] : iso(new Date(date(s.anchor).getFullYear(), date(s.anchor).getMonth() + 1, 0, 12));
    return '<div class="wkc"><section class="wkc-main" aria-label="Календарь работы"><header class="wkc-hero"><div class="wkc-topline"><span class="wkc-eyebrow">' + icon('clock') + 'Работа <span aria-hidden="true">·</span> ' + esc(month) + '</span>' +
      '<button type="button" class="wkc-button" data-wkc-new>' + icon('plus') + 'Новая задача</button></div><h1>Календарь</h1><p class="wkc-intro">Задачи, дедлайны и гастроли<br>ваших проектов в одном календаре.</p>' +
      '<div class="wkc-tabs"><nav class="wkc-tabset" aria-label="Работа"><button type="button" aria-current="page">' + icon('calendar') + 'Календарь</button><button type="button" data-go="wktasks">Задачи</button><button type="button" data-go="work">Проекты</button></nav>' +
      '<select class="wkc-project" data-native data-wkc-project aria-label="Проект календаря"><option value="">Все проекты</option>' + wkProjects().map(function (p) { return '<option value="' + esc(p.id) + '"' + (s.project === p.id ? ' selected' : '') + '>' + esc(p.title) + '</option>'; }).join('') + '</select></div></header>' +
      '<div class="wkc-toolbar"><div class="wkc-month"><span class="wkc-stamp"><span>' + esc(fmt(s.anchor, { month: 'short' }).replace('.', '')) + '</span>' + +s.day.slice(8) + '</span><div><b>' + esc(month) + '</b><span class="wkc-range">' + esc(fmt(from, { day: 'numeric', month: 'short' }) + ' — ' + fmt(to, { day: 'numeric', month: 'short', year: 'numeric' })) + '</span></div></div>' +
      '<div class="wkc-controls"><button type="button" class="wkc-searchbtn" data-wkc-search aria-label="Поиск в календаре" aria-expanded="' + s.search + '">' + icon('search') + '</button>' +
      '<div class="wkc-nav"><button type="button" data-wkc-nav="-1" aria-label="Предыдущий период">' + icon('prev') + '</button><button type="button" data-wkc-today>Сегодня</button><button type="button" data-wkc-nav="1" aria-label="Следующий период">' + icon('next') + '</button></div>' +
      '<select class="wkc-view" data-native data-wkc-view aria-label="Вид календаря"><option value="month"' + (s.view === 'month' ? ' selected' : '') + '>Месяц</option><option value="week"' + (s.view === 'week' ? ' selected' : '') + '>Неделя</option></select>' +
      '<button type="button" class="wkc-button primary" data-wkc-new>' + icon('plus') + 'Добавить</button></div>' +
      (s.search ? '<label class="wkc-search">' + icon('search') + '<input type="search" data-wkc-query value="' + esc(s.query) + '" placeholder="Найти задачу, проект или город" aria-label="Поиск записей календаря"></label>' : '') + '</div>' +
      grid(s, list, days) + '<div class="wkc-legend"><span><i></i>Задачи</span><span><i></i>Дедлайны проектов</span><span><i></i>Гастроли</span></div></section>' + sidebar(s, list) + '</div>';
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { monthDays: monthDays, shift: shift, items: items };
  root.renderWkCalendar = renderCalendar;
  if (typeof document === 'undefined') return;
  document.addEventListener('click', function (ev) {
    if (S.view !== 'wkcal' || !ev.target.closest) return;
    var b = ev.target.closest('[data-wkc-day],[data-wkc-event],[data-wkc-nav],[data-wkc-today],[data-wkc-new],[data-wkc-search],[data-wkc-addsub]'); if (!b) return;
    var s = state();
    if (b.hasAttribute('data-wkc-new')) {
      wkNewTaskOpen(); S.wk.draft.due = s.day; S.wk.draft.project = s.project; if ($("wkn-proj")) $("wkn-proj").value = s.project; wkNewTaskRefresh('#wkn-text'); return;
    }
    if (b.hasAttribute('data-wkc-addsub')) { wkOpenTask(b.getAttribute('data-wkc-addsub')); var input = document.querySelector('#pjDlg [data-wkd-sub-add] input'); if (input) input.focus(); return; }
    if (b.hasAttribute('data-wkc-day')) { s.day = b.getAttribute('data-wkc-day'); s.event = ''; }
    else if (b.hasAttribute('data-wkc-event')) {
      var e = items(WK, s.project, s.query).filter(function (e) { return e.key === b.getAttribute('data-wkc-event'); })[0];
      if (e) { s.day = e.date; s.event = e.key; }
    } else if (b.hasAttribute('data-wkc-nav')) { s.anchor = shift(s.anchor, +b.getAttribute('data-wkc-nav'), s.view === 'week'); s.day = s.anchor; s.event = ''; }
    else if (b.hasAttribute('data-wkc-today')) { s.anchor = s.day = wkDay(0); s.event = ''; }
    else if (b.hasAttribute('data-wkc-search')) { s.search = !s.search; if (!s.search) s.query = ''; }
    render();
    if (window.matchMedia('(max-width: 650px)').matches && (b.hasAttribute('data-wkc-event') || b.classList.contains('wkc-more'))) {
      var side = document.querySelector('.wkc-side'); if (side) side.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    }
    if (b.hasAttribute('data-wkc-search') && s.search) { var input = document.querySelector('[data-wkc-query]'); if (input) input.focus(); }
  });
  document.addEventListener('change', function (ev) {
    if (S.view !== 'wkcal') return;
    var el = ev.target, s = state();
    if (el.hasAttribute('data-wkc-project')) { s.project = el.value; s.event = ''; render(); }
    else if (el.hasAttribute('data-wkc-view')) { s.view = el.value; s.anchor = s.day; render(); }
    else if (el.hasAttribute('data-wkc-done')) { var tid = el.getAttribute('data-wkc-done'); wkStatusSet(tid, el.checked ? 'done' : (WK.tasks[tid].status === 'wait' ? 'work' : WK.tasks[tid].status || '')); }
    else if (el.hasAttribute('data-wkc-sub')) {
      var p = el.getAttribute('data-wkc-sub').split('|'), t = WK.tasks[p[0]];
      if (t) wkPut('tasks', p[0], Object.assign({}, t, { subs: (t.subs || []).map(function (x) { return x.id === p[1] ? Object.assign({}, x, { done: el.checked }) : x; }) }), '');
    }
  });
  document.addEventListener('input', function (ev) {
    if (S.view !== 'wkcal' || !ev.target.hasAttribute('data-wkc-query')) return;
    var pos = ev.target.selectionStart; state().query = ev.target.value; render();
    var input = document.querySelector('[data-wkc-query]'); if (input) { input.focus({ preventScroll: true }); input.setSelectionRange(pos, pos); }
  });
})(typeof window !== 'undefined' ? window : globalThis);
