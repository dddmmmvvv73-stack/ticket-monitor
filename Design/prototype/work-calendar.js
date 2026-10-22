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
  function items(work, filters, today) {
    var out = [], f = filters || {}, projects = work.projects || {};
    var taskOnly = !!(f.status || f.priority || f.tag);
    function push(kind, id, r, title, day, color, detail) {
      if (!day || (f.kind && f.kind !== kind)) return;
      var p = projects[r.project], pname = p ? p.title : '';
      if (f.project && (f.project === 'none' ? !!p : r.project !== f.project)) return;
      if (taskOnly && kind !== 'task') return;
      if (kind === 'task') {
        var status = r.done ? 'done' : r.status === 'work' || r.status === 'wait' ? 'work' : 'new';
        if (f.status === 'over' ? r.done || !today || day >= today : f.status && f.status !== status) return;
        if (f.priority && (f.priority === 'none' ? !!r.prio : r.prio !== f.priority)) return;
        if (f.tag && (f.tag === 'none' ? (r.tags || []).length > 0 : (r.tags || []).indexOf(f.tag) < 0)) return;
      }
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
  function emptyFilters() { return { project: '', kind: '', status: '', priority: '', tag: '' }; }
  function state() { return S.wk.calendar || (S.wk.calendar = { anchor: wkDay(0), day: wkDay(0), event: '', filters: emptyFilters(), view: 'month' }); }
  function filtered() { return items(WK, state().filters, wkDay(0)); }
  function filterCount(f) { return Object.keys(f).filter(function (k) { return !!f[k]; }).length; }
  function fmt(s, opts) { return date(s).toLocaleDateString('ru-RU', opts); }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function style(e) { var c = COLORS[e.color] || COLORS.blue; return '--wc-tint:' + c[0] + ';--wc-mark:' + c[1]; }
  function icon(name) {
    var paths = { plus: '<path d="M8 3v10M3 8h10"/>', prev: '<path d="M10 4L6 8l4 4"/>', next: '<path d="M6 4l4 4-4 4"/>', down: '<path d="M4.5 6l3.5 3.5L11.5 6"/>', filter: '<path d="M2 4h12M4 8h8M6 12h4"/>', check: '<path d="M3 8l3 3 7-7"/>' };
    return '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (paths[name] || paths.plus) + '</svg>';
  }
  function eventButton(e) {
    return '<button type="button" class="wkc-event' + (e.done ? ' done' : '') + (state().event === e.key ? ' active' : '') + '" data-wkc-event="' + esc(e.key) + '" style="' + style(e) + '" title="' + esc(KIND[e.kind] + ': ' + e.title + (e.pname ? ' · ' + e.pname : '')) + '">' + esc(e.title) + '</button>';
  }
  function grid(s, list, days) {
    var weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
    return '<div class="wkc-content' + (s.view === 'week' ? ' wkc-week' : '') + '"><div class="wkc-weekdays">' + weekdays.map(function (w, i) { return '<span><abbr title="' + w + '" data-short="' + ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][i] + '">' + w + '</abbr></span>'; }).join('') + '</div>' +
      '<div class="wkc-grid" role="group" aria-label="' + esc(fmt(s.anchor, { month: 'long', year: 'numeric' })) + '">' + days.map(function (day) {
        var l = list.filter(function (e) { return e.date === day; }), outside = day.slice(0, 7) !== s.anchor.slice(0, 7), weekend = date(day).getDay() % 6 === 0, limit = s.view === 'week' ? 5 : 3;
        return '<div class="wkc-day' + (l.length ? ' has-events' : '') + (outside ? ' outside' : '') + (weekend ? ' weekend' : '') + (s.day === day ? ' selected' : '') + (day === wkDay(0) ? ' today' : '') + '"' + (l.length ? ' style="' + style(l[0]) + '"' : '') + '>' +
          '<button type="button" class="wkc-daypick" data-wkc-day="' + day + '" aria-pressed="' + (s.day === day) + '" aria-label="' + esc(fmt(day, { day: 'numeric', month: 'long', year: 'numeric' }) + ' · записей: ' + l.length) + '"' + (day === wkDay(0) ? ' aria-current="date"' : '') + '></button><span class="wkc-daynum">' + +day.slice(8) + '</span>' +
          '<div class="wkc-events">' + l.slice(0, limit).map(eventButton).join('') + (l.length > limit ? '<button type="button" class="wkc-event wkc-more" data-wkc-day="' + day + '">Ещё ' + (l.length - limit) + '</button>' : '') + '</div></div>';
      }).join('') + '</div></div>';
  }
  function projectLink(e) {
    return e.project && WK.projects[e.project] ? '<button type="button" class="wkc-projectlink" data-wk-open="' + esc(e.project) + '">' + wtsAv(e.project) + '<span>' + esc(e.pname) + '</span></button>' : '';
  }
  function taskDetail(e) {
    var t = Object.assign({ id: e.id }, e.rec);
    return '<div class="wkc-detail"><div class="wkc-detail-top">' + wkPrioChip(t) + wkStatusChip(t) + '</div>' +
      '<h2>' + esc(t.text) + '</h2>' + projectLink(e) +
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
      (l.length ? '<div class="wkc-agenda-list">' + l.map(function (e) { return '<button type="button" class="wkc-agenda-item' + (e === selected ? ' on' : '') + '" data-wkc-event="' + esc(e.key) + '" style="' + style(e) + '" aria-pressed="' + (e === selected) + '"><i class="wkc-agenda-dot" aria-hidden="true"></i><span><b>' + esc(e.title) + '</b><small>' + esc(KIND[e.kind] + (e.pname ? ' · ' + e.pname : '')) + '</small></span></button>'; }).join('') + '</div>' : '<p class="wkc-agenda-empty">На этот день ничего не запланировано.</p>') +
      '<button type="button" class="wkc-addday" data-wkc-new>' + icon('plus') + 'Задача на этот день</button></div>' +
      (selected ? detail(selected) : '<div class="wkc-detail"><div class="wkc-quiet">Выберите запись в календаре,<br>чтобы посмотреть подробности.</div></div>') + '</aside>';
  }
  function renderCalendar() {
    var gate = wkGate('Календарь'); if (gate) return gate;
    var s = state(), list = filtered(), days = monthDays(s.anchor, s.view === 'week');
    // После смены срока из общего окна выбранная запись следует за своей датой.
    var active = list.filter(function (e) { return e.key === s.event; })[0];
    if (active && active.date !== s.day) { s.day = active.date; s.anchor = active.date; days = monthDays(s.anchor, s.view === 'week'); }
    var month = cap(fmt(s.anchor, { month: 'long', year: 'numeric' }).replace(/\sг\.$/, ''));
    var count = filterCount(s.filters);
    return '<div class="wkc"><section class="wkc-main" aria-label="Календарь работы"><header class="wkc-hero"><h1>Календарь</h1></header>' +
      '<div class="wkc-toolbar"><h2 class="wkc-month">' + esc(month) + '</h2><div class="wkc-controls">' +
      '<div class="wkc-nav"><button type="button" data-wkc-nav="-1" aria-label="Предыдущий период">' + icon('prev') + '</button><button type="button" data-wkc-today>Сегодня</button><button type="button" data-wkc-nav="1" aria-label="Следующий период">' + icon('next') + '</button></div>' +
      '<button type="button" class="wkc-button" data-wkc-view aria-label="Вид календаря" aria-haspopup="dialog" aria-expanded="false">' + (s.view === 'week' ? 'Неделя' : 'Месяц') + icon('down') + '</button>' +
      '<button type="button" class="wk-sq wkc-sqf' + (count ? ' on' : '') + '" data-wkc-filter aria-haspopup="dialog" aria-expanded="false" aria-label="Фильтр' + (count ? ': условий — ' + count : '') + '" title="Фильтр">' + WKT_ICON.group + (count ? '<i class="wk-sq-dot" aria-hidden="true"></i>' : '') + '</button>' +   // как в «Заметках» (22.10)
      '<button type="button" class="wkc-button primary" data-wkc-new>' + icon('plus') + 'Добавить</button></div></div>' +
      grid(s, list, days) + '</section>' + sidebar(s, list) + '</div>';
  }
  function fitPopup(el) {
    var r = el.getBoundingClientRect();
    if (r.bottom > window.innerHeight - 8) el.style.top = (window.scrollY + Math.max(8, window.innerHeight - r.height - 8)) + 'px';
  }
  function viewOpen(anchor) {
    if (WKPOP && WKPOP.anchor === anchor) { wkPopClose(); return; }
    var s = state(), el = wkPopOpen(anchor, 'wk-menu wkc-viewmenu', '<div class="wkp-title">Вид календаря</div>' + [['month', 'Месяц'], ['week', 'Неделя']].map(function (v) {
      var on = s.view === v[0];
      return '<button type="button" class="wk-menu-item' + (on ? ' on' : '') + '" data-wkc-view-set="' + v[0] + '" aria-pressed="' + on + '">' + v[1] + (on ? icon('check') : '') + '</button>';
    }).join(''), {});
    el.setAttribute('aria-label', 'Вид календаря'); fitPopup(el); el.querySelector('[aria-pressed="true"]').focus({ preventScroll: true });
  }
  function syncTaskFields(form) {
    var kind = form.elements.kind.value, off = !!kind && kind !== 'task';
    ['status', 'priority', 'tag'].forEach(function (k) { form.elements[k].disabled = off; if (off) form.elements[k].value = ''; });
    enhanceSelects(form);   // списки — в стиле сайта (22.10): кнопки обновляются (недоступно, «все»)
  }
  function filterOpen(anchor) {
    if (WKPOP && WKPOP.anchor === anchor) { wkPopClose(); return; }
    var f = state().filters;
    function field(name, title, options, search) {
      return '<div class="wkc-filter-field"><span>' + title + '</span><select name="' + name + '" aria-label="' + esc(title) + '"' + (search ? ' data-dd-search' : '') + '>' + options.map(function (o) {
        return '<option value="' + esc(o[0]) + '"' + (f[name] === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
      }).join('') + '</select></div>';
    }
    var el = wkPopOpen(anchor, 'wkc-filterpop', '<form data-wkc-filter-form><div class="wkp-title">Фильтр календаря</div>' +
      field('project', 'Проект', [['', 'Все проекты'], ['none', 'Без проекта']].concat(wkProjects().map(function (p) { return [p.id, p.title]; })), true) +   // проект — с поиском (22.10)
      field('kind', 'Записи', [['', 'Все записи'], ['task', 'Задачи'], ['deadline', 'Дедлайны проектов'], ['show', 'Гастроли']]) +
      field('status', 'Статус задачи', [['', 'Все статусы'], ['new', 'Не начата'], ['work', 'В работе'], ['done', 'Готово'], ['over', 'Просрочено']]) +
      field('priority', 'Приоритет', [['', 'Любой приоритет'], ['high', 'Высокий'], ['mid', 'Средний'], ['low', 'Низкий'], ['none', 'Без приоритета']]) +
      field('tag', 'Тег', [['', 'Все теги'], ['none', 'Без тегов']].concat(wkTagList().map(function (t) { return [t.id, t.name]; }))) +
      '<p class="wkc-filter-hint">Статус, приоритет и тег отбирают только задачи.</p><div class="wkc-filter-actions"><button type="button" class="btn-ghost" data-wkc-reset>Сбросить</button><button type="submit" class="btn-dark">Применить</button></div></form>', {});
    el.setAttribute('aria-label', 'Фильтр календаря'); syncTaskFields(el.querySelector('form')); fitPopup(el); el.querySelector('.dd-btn').focus({ preventScroll: true });
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { monthDays: monthDays, shift: shift, items: items };
  root.renderWkCalendar = renderCalendar;
  if (typeof document === 'undefined') return;
  document.addEventListener('click', function (ev) {
    if (S.view !== 'wkcal' || !ev.target.closest) return;
    var b = ev.target.closest('[data-wkc-day],[data-wkc-event],[data-wkc-nav],[data-wkc-today],[data-wkc-new],[data-wkc-view],[data-wkc-view-set],[data-wkc-filter],[data-wkc-reset]'); if (!b) return;
    var s = state();
    if (b.hasAttribute('data-wkc-new')) {
      var pid = s.filters.project !== 'none' && WK.projects[s.filters.project] ? s.filters.project : '';
      wkPopClose(); wkNewTaskOpen(); S.wk.draft.due = s.day; S.wk.draft.project = pid; if ($('wkn-proj')) $('wkn-proj').value = pid; wkNewTaskRefresh('#wkn-text'); return;
    }
    if (b.hasAttribute('data-wkc-view')) { viewOpen(b); return; }
    if (b.hasAttribute('data-wkc-filter')) { filterOpen(b); return; }
    var focus = '';
    if (b.hasAttribute('data-wkc-view-set')) { s.view = b.getAttribute('data-wkc-view-set'); s.anchor = s.day; wkPopClose(); focus = '[data-wkc-view]'; }
    if (b.hasAttribute('data-wkc-reset')) { s.filters = emptyFilters(); s.event = ''; wkPopClose(); focus = '[data-wkc-filter]'; }
    if (b.hasAttribute('data-wkc-day')) { s.day = b.getAttribute('data-wkc-day'); s.event = ''; }
    else if (b.hasAttribute('data-wkc-event')) {
      var e = filtered().filter(function (e) { return e.key === b.getAttribute('data-wkc-event'); })[0];
      if (e) { s.day = e.date; s.event = e.key; }
    } else if (b.hasAttribute('data-wkc-nav')) { s.anchor = shift(s.anchor, +b.getAttribute('data-wkc-nav'), s.view === 'week'); s.day = s.anchor; s.event = ''; }
    else if (b.hasAttribute('data-wkc-today')) { s.anchor = s.day = wkDay(0); s.event = ''; }
    render();
    if (focus) document.querySelector(focus).focus();
    if (window.matchMedia('(max-width: 650px)').matches && (b.hasAttribute('data-wkc-event') || b.classList.contains('wkc-more'))) {
      var side = document.querySelector('.wkc-side'); if (side) side.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    }
  });
  document.addEventListener('change', function (ev) {
    if (S.view !== 'wkcal' || !ev.target.closest) return;
    var form = ev.target.closest('[data-wkc-filter-form]'); if (form && ev.target.name === 'kind') syncTaskFields(form);
  });
  document.addEventListener('submit', function (ev) {
    if (S.view !== 'wkcal' || !ev.target.matches('[data-wkc-filter-form]')) return;
    ev.preventDefault(); var form = ev.target, f = emptyFilters();
    Object.keys(f).forEach(function (k) { f[k] = form.elements[k].disabled ? '' : form.elements[k].value; });
    state().filters = f; state().event = ''; wkPopClose(); render(); document.querySelector('[data-wkc-filter]').focus();
  });
})(typeof window !== 'undefined' ? window : globalThis);
