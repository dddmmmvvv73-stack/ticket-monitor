// «Обзор» работы (#wkhome) — утверждённый пользователем макет 26.10.2026 (Design/mockups/obzor.html, референсы: «Tasks progress»,
// «Task progress», дашборд «Hi, Dilan!»): сводка и «что горит» одной плиткой, документы и деньги, цели месяца, «в фокусе»,
// готовность (проекты · задачи), ближайшие гастроли, проекты. Данные — общий WK (/api/work), запись — wkPut / wkDel / wkStatusSet
// из index.html (журнал изменений, «Вернуть»); цели месяца — WK.goals (competitors/work.py).
(function (root) {
  'use strict';
  var SALE_DAYS = 90;   // «Что горит»: дата ближе стольких дней, а не «в продаже»
  var IC = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    dots: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    pencil: '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    chev: '<path d="m9 18 6-6-6-6"/>', chev2: '<path d="m6 17 5-5-5-5M13 17l5-5-5-5"/>', down: '<path d="m6 9 6 6 6-6"/>',
    cal: '<rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    check: '<path d="M20 6 9 17l-5-5"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>', up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    pin: '<path d="M12 17v5M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    trend: '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    task: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m9 12 2 2 4-4"/>',
    note: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M8 13h8M8 17h5"/>',
    doc: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M9 15l2 2 4-4"/>',
    ticket: '<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 17v2M13 11v2"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
    plane: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
    pen: '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    build: '<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6"/>',
    wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    coin: '<circle cx="12" cy="12" r="9"/><path d="M15 9.5a3 2.5 0 0 0-6 0c0 3 6 2 6 5a3 2.5 0 0 1-6 0M12 5.5v2M12 16.5v2"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    megaphone: '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>'
  };
  function ico(n, s, w) { return '<svg width="' + (s || 20) + '" height="' + (s || 20) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (w || 1.8) + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (IC[n] || '') + '</svg>'; }
  var TAG_ICON = { 'Билеты': 'ticket', 'Артист': 'mic', 'Логистика': 'plane', 'Договоры': 'pen', 'Площадка': 'build', 'Техника': 'wrench', 'Финансы': 'coin', 'Реклама': 'megaphone', 'Организация': 'spark' };
  var STAGE_HEX = { gray: '#bdbdbb', amber: '#f2b84b', violet: '#a78bfa', blue: '#6c9bff', green: '#4cc38a', peach: '#f6a37a', mint: '#7fd6b5', pink: '#f19bb8', teal: '#4fc1c0' };
  var MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var MONTH = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
  var MONTH_G = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var WD = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  var WDL = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
  var SALE = { '': 'Ждём площадку', allowed: 'Разрешено', onsale: 'В продаже' };
  var TST = [['new', 'Не начата', '#b4b4b2'], ['work', 'В работе', 'var(--wh-lilac)'], ['over', 'Просрочено', 'var(--wh-orange)'], ['done', 'Готово', '#ffffff']];

  function D(s) { return new Date(s + 'T12:00:00'); }   // местный полдень: без сдвига дня
  function days(a, b) { return Math.round((D(b) - D(a)) / 864e5); }
  function short(s) { var d = D(s); return d.getDate() + ' ' + MON[d.getMonth()]; }
  function plural(n, a, b, c) { var m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 12 || h > 14) ? b : c; }
  function rub(n) { return n >= 1e6 ? (n / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн' : n >= 1e3 ? Math.round(n / 1e3).toLocaleString('ru-RU') + ' тыс.' : Math.round(n).toLocaleString('ru-RU'); }
  function money(n) { return Math.round(n).toLocaleString('ru-RU') + ' ₽'; }
  function ls(k, v) { try { if (v === undefined) return localStorage.getItem('ticketmonitor.wkhome.' + k); localStorage.setItem('ticketmonitor.wkhome.' + k, v); } catch (e) { return null; } }
  function st() {
    if (!S.wk.home) S.wk.home = { fire: 'all', money: 0, month: wkDay(0).slice(0, 7), gedit: false, focus: 'today', rv: ls('rv') || 'projects', rf: 'all', sort: ls('sort') || 'date', list: ls('list') === '1' };
    return S.wk.home;
  }

  // ---------------------------------------------------------------- данные
  function late(t) { return !t.done && t.due && t.due < wkDay(0); }
  function active() { return wkProjects().filter(function (p) { return !wkStageDone(p.stage); }); }
  function tasks() { return wkTasksOf(null); }
  function shows() { return Object.keys(WK.shows || {}).map(function (id) { return Object.assign({ id: id }, WK.shows[id]); }).filter(function (s) { return s.date && WK.projects[s.project]; }).sort(function (a, b) { return a.date.localeCompare(b.date); }); }
  function ahead() { var t0 = wkDay(0); return shows().filter(function (s) { return s.date >= t0; }); }
  function docs() { return wkDocsOf(null); }
  function party(d) { return d.cp && WK.parties && WK.parties[d.cp]; }
  function waitOrig(d) { var p = party(d); return !!(p && p.edo !== 'full' && !d.orig_in); }   // без полного ЭДО — ждём оригинал
  function tagName(t) { var g = (t.tags || [])[0], x = g && WK.tags && WK.tags[g]; return x ? x.name : ''; }
  function goals(m) { return Object.keys(WK.goals || {}).map(function (id) { return Object.assign({ id: id }, WK.goals[id]); }).filter(function (g) { return g.month === m; }).sort(function (a, b) { return (a.order || 0) - (b.order || 0) || (a.upd || '').localeCompare(b.upd || ''); }); }
  function ready() {
    var t0 = wkDay(0), wk = wkDay(-7);
    return active().map(function (p) {
      var ts = wkTasksOf(p.id), done = ts.filter(function (t) { return t.done; }).length, pct = ts.length ? Math.round(done / ts.length * 100) : 0;
      var week = ts.length ? Math.round(ts.filter(function (t) { return t.done && (t.done_at || '') >= wk; }).length / ts.length * 100) : 0;
      var span = p.deadline && p.created ? days(p.created, p.deadline) : 0;
      var plan = span > 0 ? Math.max(0, Math.min(100, Math.round(days(p.created, t0) / span * 100))) : null;
      return { p: p, n: ts.length, done: done, pct: pct, week: week, plan: plan, behind: plan !== null && ts.length > 0 && pct < plan };
    });
  }
  function fire() {
    var out = [], t0 = wkDay(0), all = tasks();
    all.filter(late).sort(function (a, b) { return a.due.localeCompare(b.due); }).forEach(function (t) { out.push({ g: 'tasks', sev: 'red', k: 'Просрочено · ' + short(t.due), t: t.text, p: wkPname(t.project) || 'Без проекта', task: t.id }); });
    all.filter(function (t) { return !t.done && t.due === t0; }).forEach(function (t) { out.push({ g: 'tasks', sev: 'orange', k: 'Сегодня', t: t.text, p: wkPname(t.project) || 'Без проекта', task: t.id }); });
    active().filter(function (p) { return p.deadline && p.deadline >= t0 && days(t0, p.deadline) <= 7; }).forEach(function (p) { out.push({ g: 'tasks', sev: 'orange', k: 'Дедлайн готовности · ' + short(p.deadline), t: p.title, p: '', proj: p.id }); });
    var by = {};
    ahead().filter(function (s) { return s.sale !== 'onsale' && days(t0, s.date) <= SALE_DAYS; }).forEach(function (s) { (by[s.project] = by[s.project] || []).push(s); });
    Object.keys(by).forEach(function (pid) {
      var ss = by[pid], a = days(t0, ss[0].date), b = days(t0, ss[ss.length - 1].date);
      out.push({ g: 'sales', sev: a <= 60 ? 'red' : 'orange', k: 'Не в продаже · через ' + (a === b ? a : a + '–' + b) + ' дн.', t: ss.map(function (s) { return s.city || s.name; }).join(', '), p: wkPname(pid), proj: pid, tab: 'shows' });
    });
    docs().filter(function (d) { return d.kind === 'Счёт' && d.amount && !((d.paid || 0) >= d.amount); }).forEach(function (d) { out.push({ g: 'docs', sev: 'amber', k: 'Счёт не оплачен', t: (d.party || 'Без контрагента') + ' · ' + money(d.amount - (d.paid || 0)), p: wkPname(d.project), proj: d.project, tab: 'docs' }); });
    var un = {};
    docs().filter(function (d) { return d.kind === 'Договор' && d.status !== 'signed'; }).forEach(function (d) { (un[d.project] = un[d.project] || []).push(d.party || 'без контрагента'); });
    Object.keys(un).forEach(function (pid) { out.push({ g: 'docs', sev: 'gray', k: 'Договоры не подписаны', t: un[pid].join(', '), p: wkPname(pid), proj: pid, tab: 'docs' }); });
    return out;
  }
  function focusList(f) {
    var t0 = wkDay(0), t7 = wkDay(7), o = tasks().filter(function (t) { return !t.done; });
    var l = f === 'pin' ? o.filter(function (t) { return t.pin; }) : f === 'week' ? o.filter(function (t) { return t.due && t.due > t0 && t.due <= t7; }) : o.filter(function (t) { return t.due && t.due <= t0; });
    var pr = function (t) { return t.prio in WK_PRIO_RANK ? WK_PRIO_RANK[t.prio] : 3; };
    return l.sort(function (a, b) { return (a.due || '9').localeCompare(b.due || '9') || pr(a) - pr(b); });
  }

  // ---------------------------------------------------------------- подсказки у столбиков
  var TIPS = [];
  function tipAttr(html) { TIPS.push(html); return ' data-wh-tip="' + (TIPS.length - 1) + '"'; }
  function tipEl() { var el = document.getElementById('whTip'); if (!el) { el = document.createElement('div'); el.id = 'whTip'; el.className = 'wh-tip'; el.setAttribute('role', 'tooltip'); document.body.appendChild(el); } return el; }
  function tipMove(ev) { var el = tipEl(); el.style.left = Math.min(ev.clientX + 14, window.innerWidth - el.offsetWidth - 8) + 'px'; el.style.top = (ev.clientY + 16) + 'px'; }

  function ring(done, total, size, dark) {
    var r = size / 2 - 3, c = 2 * Math.PI * r, f = total ? done / total : 0;
    return '<span class="wh-ring" style="width:' + size + 'px;height:' + size + 'px" role="img" aria-label="' + done + ' из ' + total + '"><svg width="' + size + '" height="' + size + '"><circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + (dark ? 'rgba(255,255,255,.18)' : '#e4e4e2') + '" stroke-width="3"/>' +
      '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + (dark ? '#fff' : '#141414') + '" stroke-width="3" stroke-linecap="round" stroke-dasharray="' + (c * f) + ' ' + c + '"/></svg><span>' + done + '/' + total + '</span></span>';
  }
  function chips(list, cur, attr) { return list.map(function (x) { return '<button type="button" class="wh-chip' + (x[0] === cur ? ' on' : '') + '" data-' + attr + '="' + x[0] + '" aria-pressed="' + (x[0] === cur) + '">' + x[1] + '</button>'; }).join(''); }

  // ---------------------------------------------------------------- блоки
  function header() {
    var h = new Date().getHours(), d = D(wkDay(0)), wd = WDL[d.getDay()];
    return '<header class="wh-top"><div class="wh-hello"><h1>' + (h < 5 ? 'Доброй ночи!' : h < 12 ? 'Доброе утро!' : h < 18 ? 'Добрый день!' : 'Добрый вечер!') + '</h1>' +
      '<p>' + wd[0].toUpperCase() + wd.slice(1) + ', ' + d.getDate() + ' ' + MONTH_G[d.getMonth()] + '</p></div>' +
      '<div class="wh-act"><label class="wh-search' + (st().q ? ' open' : '') + '"><button type="button" data-wh-search aria-label="Поиск">' + ico('search') + '</button>' +
        '<input type="search" data-wh-q placeholder="Задачи, проекты, контрагенты…" aria-label="Поиск по работе" value="' + esc(st().q || '') + '" autocomplete="off"></label>' +
      '<button type="button" class="wh-circle" data-wh-bell aria-label="Что горит" aria-haspopup="dialog">' + ico('bell') + (fire().length ? '<span class="wh-dot"></span>' : '') + '</button>' +
      '<button type="button" class="wh-create" data-wh-create aria-haspopup="menu">' + ico('plus') + ' Создать</button></div></header>';
  }
  function topCard() {
    var nx = ahead()[0], all = tasks(), done = all.filter(function (t) { return t.done; }).length, lateN = all.filter(late).length;
    var dl = active().filter(function (p) { return p.deadline && p.deadline >= wkDay(0); }).sort(function (a, b) { return a.deadline.localeCompare(b.deadline); })[0];
    var wk = all.filter(function (t) { return t.done && (t.done_at || '') >= wkDay(-7); }).length, n = nx ? days(wkDay(0), nx.date) : 0, dn = dl ? days(wkDay(0), dl.deadline) : 0;
    var f = fire(), fl = f.filter(function (x) { return st().fire === 'all' || x.g === st().fire; });
    var cnt = function (g) { return f.filter(function (x) { return x.g === g; }).length; };
    var open = all.length - done;
    return '<section class="wh-card wh-dark wh-a-top" aria-label="Сводка и что горит"><div class="wh-top2">' +
      '<div class="wh-col wh-sum"><div class="wh-h"><h2>Сводка</h2></div>' +
        '<div class="wh-sum-top"><div class="wh-big"><b class="num">' + (nx ? n : '—') + '</b><span>' + (nx ? plural(n, 'день', 'дня', 'дней') + ' до гастролей<br>' + esc(nx.city || nx.name) + ', ' + short(nx.date) : 'дат гастролей<br>пока нет') + '</span></div>' +
          '<div class="wh-vsep"></div><div class="wh-big"><b class="num">' + lateN + '</b><span>' + plural(lateN, 'задача', 'задачи', 'задач') + '<br>' + plural(lateN, 'просрочена', 'просрочены', 'просрочено') + '</span></div></div>' +
        '<div class="wh-bar"><i style="width:' + (all.length ? Math.round(done / all.length * 100) : 0) + '%"></i></div>' +
        '<div class="wh-cap">Сделано ' + done + ' из ' + all.length + ' ' + plural(all.length, 'задачи', 'задач', 'задач') + ' по всем проектам</div>' +
        '<div class="wh-rows">' + (dl ? '<button type="button" class="wh-row" data-wh-open="' + dl.id + '"><small>Ближайший дедлайн готовности</small><span>через ' + dn + ' ' + plural(dn, 'день', 'дня', 'дней') + '</span><b>' + short(dl.deadline) + ' · ' + esc(dl.title) + '</b></button>' : '') +
          '<div class="wh-row"><small>Сделано за 7 дней</small><span>по всем проектам</span><b>' + wk + ' ' + plural(wk, 'задача', 'задачи', 'задач') + '</b></div></div>' +
        '<div class="wh-tiles">' +
          '<a class="wh-tile on" href="#work">' + ico('folder', 18) + '<b class="num">' + active().length + '</b><small>' + plural(active().length, 'проект', 'проекта', 'проектов') + ' в работе</small></a>' +
          '<a class="wh-tile" href="#wkcal">' + ico('cal', 18) + '<b class="num">' + ahead().length + '</b><small>' + plural(ahead().length, 'дата', 'даты', 'дат') + ' впереди</small></a>' +
          '<a class="wh-tile" href="#wktasks">' + ico('task', 18) + '<b class="num">' + open + '</b><small>' + plural(open, 'задача', 'задачи', 'задач') + ' открыто</small></a></div></div>' +
      '<div class="wh-vline"></div>' +
      '<div class="wh-col wh-firecol"><div class="wh-h"><h2>Что горит</h2>' + (f.length ? '<span class="wh-badge">' + f.length + '</span>' : '') + '<span class="wh-sp"></span><button type="button" class="wh-icon" data-wh-fireinfo aria-label="Что сюда попадает" aria-haspopup="dialog">' + ico('info') + '</button></div>' +
        '<div class="wh-chips">' + chips([['all', 'Все ' + f.length], ['tasks', 'Задачи ' + cnt('tasks')], ['sales', 'Продажи ' + cnt('sales')], ['docs', 'Документы ' + cnt('docs')]], st().fire, 'wh-fire') + '</div>' +
        '<div class="wh-fire">' + (fl.length ? fl.map(fireItem).join('') : '<p class="wh-empty">Здесь ничего не горит</p>') + '</div></div>' +
      '</div></section>';
  }
  function fireItem(x) {
    var go = x.task ? ' data-wh-task="' + x.task + '"' : x.proj ? ' data-wh-open="' + x.proj + '"' + (x.tab ? ' data-wh-tab="' + x.tab + '"' : '') : ' data-wh-go="' + (x.g === 'docs' ? 'wkdocs' : 'wktasks') + '"';
    return '<button type="button" class="wh-fi"' + go + '><i class="wh-sev-' + x.sev + '"></i><span class="wh-fi-b"><span class="wh-fi-k">' + esc(x.k) + '</span><span class="wh-fi-t">' + esc(x.t) + '</span>' + (x.p ? '<span class="wh-fi-p">' + esc(x.p) + '</span>' : '') + '</span>' + ico('chev', 18) + '</button>';
  }
  function moneyCard() {
    var v = st().money, ds = docs(), titles = ['Документы', 'Деньги', 'Оригиналы'], panel, stats;
    var contracts = ds.filter(function (d) { return (d.kind === 'Договор' || d.kind === 'Допсоглашение') && d.amount; });
    var sumC = contracts.reduce(function (s, d) { return s + d.amount; }, 0), paid = ds.filter(function (d) { return d.kind === 'Счёт'; }).reduce(function (s, d) { return s + (d.paid || 0); }, 0);
    var byP = {};   // остаток — по договору: договоры контрагента в проекте − оплачено по его счетам в проекте
    ds.forEach(function (d) {
      var k = d.project + '|' + (d.cp || d.party || ''), x = byP[k] = byP[k] || { party: d.party || 'Без контрагента', project: d.project, c: 0, p: 0 };
      if ((d.kind === 'Договор' || d.kind === 'Допсоглашение') && d.amount) x.c += d.amount;
      if (d.kind === 'Счёт' && d.paid) x.p += d.paid;
    });
    var rows = Object.keys(byP).map(function (k) { return byP[k]; }).filter(function (x) { return x.c; }), left = rows.reduce(function (s, x) { return s + Math.max(0, x.c - x.p); }, 0);
    if (v === 0) {
      var sts = [['wait', 'Ожидаем'], ['got', 'Получен'], ['acc', 'У бухгалтера'], ['signed', 'Подписан']];
      var cnt = sts.map(function (s) { return ds.filter(function (d) { return d.status === s[0]; }).length; }), top = Math.max(2, Math.ceil(Math.max.apply(null, cnt) / 2) * 2), H = 166;
      panel = '<div class="wh-mchart"><div class="wh-maxis"><span>' + top + '</span><span>' + top / 2 + '</span><span>0</span></div><div class="wh-mline" style="top:' + H / 2 + 'px"></div>' +
        sts.map(function (s, i) {
          return '<div class="wh-mcol" style="grid-column:' + (i + 2) + '">' + (s[0] === 'signed' && ds.length ? '<span class="wh-mtag" style="top:' + (1 - cnt[i] / top) * H + 'px">' + ico('up', 12, 2.4) + ' ' + cnt[i] + ' из ' + ds.length + '</span>' : '') +
            '<button type="button" class="wh-mbar' + (s[0] === 'signed' ? ' on' : '') + '" style="height:' + Math.max(6, cnt[i] / top * H) + 'px" data-wh-go="wkdocs"' + tipAttr('<b>' + s[1] + '</b> — ' + cnt[i] + ' ' + plural(cnt[i], 'документ', 'документа', 'документов')) + ' aria-label="' + s[1] + ': ' + cnt[i] + '"></button><span>' + s[1] + '</span></div>';
        }).join('') + '</div>';
      var wo = ds.filter(waitOrig).length;
      stats = [[ds.length, plural(ds.length, 'документ', 'документа', 'документов')], [ds.filter(function (d) { return d.status !== 'signed'; }).length, 'не подписано'], [wo, 'ждём оригиналы']];
    } else if (v === 1) {
      panel = rows.length ? '<div class="wh-mrows">' + rows.sort(function (a, b) { return (b.c - b.p) - (a.c - a.p); }).map(function (x) {
        return '<button type="button" class="wh-mrow" data-wh-open="' + x.project + '" data-wh-tab="docs"><b>' + esc(x.party) + '</b><span class="num">' + money(Math.max(0, x.c - x.p)) + '</span><span class="wh-mtrack"><i style="width:' + Math.min(100, x.p / x.c * 100) + '%"></i></span><small>' + esc(wkPname(x.project) || 'Без проекта') + ' · оплачено ' + money(x.p) + ' из ' + money(x.c) + '</small></button>';
      }).join('') + '</div>' : '<p class="wh-mempty">Сумм по договорам пока нет — впишите их в «Документах»</p>';
      stats = [[rub(sumC), 'по договорам'], [rub(paid), 'оплачено'], [rub(left), 'к оплате']];
    } else {
      var o = {};
      ds.filter(function (d) { return party(d) && party(d).edo !== 'full'; }).forEach(function (d) { var k = d.cp; (o[k] = o[k] || { name: party(d).name, wait: [], pid: d.project }).wait.push(d); });
      var ks = Object.keys(o);
      panel = ks.length ? '<div class="wh-mrows">' + ks.map(function (k) {
        var w = o[k].wait.filter(function (d) { return !d.orig_in; });
        return '<button type="button" class="wh-mrow" data-wh-open="' + o[k].pid + '" data-wh-tab="docs"><b>' + esc(o[k].name) + '</b><span>' + w.length + '</span><small>' + (w.length ? 'без ЭДО — ждём оригиналы: ' + w.map(function (d) { return d.kind; }).join(', ') : 'все оригиналы получены') + '</small></button>';
      }).join('') + '</div>' : '<p class="wh-mempty">Все контрагенты — с полным ЭДО: оригиналы не нужны</p>';
      var od = ds.filter(function (d) { return party(d) && party(d).edo !== 'full'; });
      stats = [[od.filter(function (d) { return !d.orig_in; }).length, 'ждём оригиналы'], [od.filter(function (d) { return d.orig_out; }).length, 'отправили'], [od.filter(function (d) { return d.orig_in; }).length, 'получили']];
    }
    return '<section class="wh-card wh-yellow wh-a-money" aria-label="' + titles[v] + '"><div class="wh-h"><h2>' + titles[v] + '</h2><span class="wh-sp"></span><div class="wh-dots" role="tablist">' +
      titles.map(function (t, i) { return '<button type="button" class="' + (i === v ? 'on' : '') + '" data-wh-money="' + i + '" role="tab" aria-selected="' + (i === v) + '" aria-label="' + t + '"></button>'; }).join('') + '</div></div>' +
      '<div class="wh-mpanel">' + panel + '</div><div class="wh-mstats">' + stats.map(function (s) { return '<div><b class="num">' + s[0] + '</b><small>' + s[1] + '</small></div>'; }).join('') + '</div></section>';
  }
  function goalsCard() {
    var s = st(), g = goals(s.month), y = +s.month.slice(0, 4), m = +s.month.slice(5);
    var list = s.gedit
      ? g.map(function (x) { return '<li class="wh-goal"><input type="checkbox" data-wh-gdone="' + x.id + '"' + (x.done ? ' checked' : '') + ' aria-label="Выполнена"><input class="wh-gtx" data-wh-gtx="' + x.id + '" value="' + esc(x.text) + '" maxlength="300" aria-label="Цель"><button type="button" class="wh-icon" data-wh-gdel="' + x.id + '" aria-label="Удалить цель">' + ico('x', 16) + '</button></li>'; }).join('') +
        '<li class="wh-goal"><span class="wh-gplus">' + ico('plus', 16) + '</span><input class="wh-gtx" data-wh-gnew placeholder="Новая цель — впишите и Enter" maxlength="300" aria-label="Новая цель"></li>'
      : g.length ? g.map(function (x) { return '<li class="wh-goal' + (x.done ? ' done' : '') + '"><label><input type="checkbox" data-wh-gdone="' + x.id + '"' + (x.done ? ' checked' : '') + '><span>' + esc(x.text) + '</span></label></li>'; }).join('')
      : '<li class="wh-goal wh-gempty">Целей на этот месяц нет — нажмите карандаш</li>';
    return '<section class="wh-card wh-white wh-a-goals" aria-label="Цели месяца"><div class="wh-h"><h2>Цели месяца</h2><span class="wh-sp"></span>' + ring(g.filter(function (x) { return x.done; }).length, g.length, 34) +
      '<button type="button" class="wh-icon' + (s.gedit ? ' on' : '') + '" data-wh-gedit aria-pressed="' + s.gedit + '" aria-label="' + (s.gedit ? 'Закончить правку' : 'Править цели') + '">' + ico(s.gedit ? 'check' : 'pencil') + '</button></div>' +
      '<div class="wh-month"><button type="button" data-wh-month="-1" aria-label="Прошлый месяц">‹</button><span>' + MONTH[m - 1] + ' ' + y + '</span><button type="button" data-wh-month="1" aria-label="Следующий месяц">›</button></div>' +
      '<ul class="wh-goals">' + list + '</ul></section>';
  }
  function focusCard() {
    var s = st(), fs = [['today', 'Сегодня'], ['pin', 'Закреплённые'], ['week', 'На неделе']], l = focusList(s.focus), t0 = wkDay(0), rot = ['-2.5deg', '1.5deg', '-1deg', '2deg', '-1.5deg', '1deg'];
    return '<section class="wh-a-focus" aria-label="В фокусе"><div class="wh-h wh-fh"><h2>В фокусе (' + l.length + ')</h2><span class="wh-sp"></span><div class="wh-chips">' +
      chips(fs.map(function (f) { return [f[0], f[1] + ' ' + focusList(f[0]).length]; }), s.focus, 'wh-focus') + '</div></div>' +
      '<div class="wh-frow" data-wh-frow>' + l.map(function (t, i) {
        var due = !t.due ? 'Без срока' : t.due === t0 ? 'Сегодня' : t.due < t0 ? 'Просрочено · ' + short(t.due) : short(t.due), pn = wkPname(t.project);
        return '<article class="wh-tc" style="--rot:' + rot[i % rot.length] + '"><div class="wh-tc-h"><span class="wh-tc-ic">' + ico(TAG_ICON[tagName(t)] || 'task', 26, 1.6) + '</span>' +
          (t.pin ? '<span class="wh-tc-pin" title="Закреплена">' + ico('pin', 15) + '</span>' : '') +
          '<button type="button" class="wh-icon" data-wh-tmore="' + t.id + '" aria-label="Ещё" aria-haspopup="menu">' + ico('dots') + '</button></div>' +
          '<h3 data-wh-task="' + t.id + '" title="' + esc(t.text) + '" tabindex="0" role="button">' + esc(t.text) + '</h3>' +
          (pn ? '<button type="button" class="wh-tc-p" data-wh-open="' + t.project + '" title="' + esc(pn) + '">' + esc(pn) + '</button>' : '<span class="wh-tc-p">Без проекта</span>') +
          '<span class="wh-tc-due' + (late(t) ? ' late' : '') + '">' + due + '</span>' +
          '<div class="wh-tc-f"><span class="wh-prio p-' + (t.prio || 'none') + '" title="Приоритет: ' + (wkLabel(WK_PRIO, t.prio) || 'не задан').toLowerCase() + '">' + wkPrioIcon(t.prio) + '</span>' +
          '<span class="wh-tc-btns"><button type="button" class="wh-bell' + (t.remind ? ' on' : '') + '" data-wh-remind="' + t.id + '" aria-pressed="' + !!t.remind + '" aria-label="Напомнить в Telegram" title="' + (t.remind ? 'Напомню в Telegram утром' : 'Напомнить в Telegram') + '">' + ico('bell', 17) + '</button>' +
          '<button type="button" class="wh-done" data-wh-done="' + t.id + '" aria-label="Готово: ' + esc(t.text) + '" title="Готово">' + ico('check', 18, 2.4) + '</button></span></div></article>';
      }).join('') + '<button type="button" class="wh-tadd" data-wh-newtask><span>' + ico('plus') + ' Задача</span></button></div></section>';
  }
  function readyCard() {
    var s = st(), body, legend, chipsH = '';
    if (s.rv === 'projects') {
      var all = ready(), rows = all.filter(function (x) { return s.rf === 'all' || x.behind; }), fills = ['var(--wh-lilac)', '#ffffff', '#b4b4b2', '#d9d3e8'];
      chipsH = '<div class="wh-chips">' + chips([['all', 'Все'], ['behind', 'Отстают ' + all.filter(function (x) { return x.behind; }).length]], s.rf, 'wh-rf') + '</div>';
      legend = '<div class="wh-rd-legend"><span><i class="wh-dash"></i>где проект должен быть сейчас — от создания до дедлайна готовности</span><span><i class="wh-sq"></i>отстаёт</span></div>';
      body = !rows.length ? '<p class="wh-rd-empty">' + (all.length ? 'Отстающих проектов нет' : 'Проектов в работе пока нет') + '</p>' : cols(rows,
        function (x) { return [x.week ? '+' + x.week + '%' : '–', x.behind]; },
        function (x) { return esc(x.p.title); },
        function (x, i) { return '<button type="button" class="wh-rd-col" data-wh-open="' + x.p.id + '"' + tipAttr('<b>' + esc(x.p.title) + '</b><br>Сделано ' + x.done + ' из ' + x.n + ' ' + plural(x.n, 'задачи', 'задач', 'задач') + ' — ' + x.pct + '%<br>' + (x.plan === null ? 'Дедлайн готовности не задан — плана нет' : 'По плану сейчас ' + x.plan + '% (создан ' + short(x.p.created) + ', дедлайн ' + short(x.p.deadline) + ')<br>' + (x.behind ? '<span class="wh-tip-or">Отстаёт на ' + (x.plan - x.pct) + ' п.п.</span>' : 'Впереди плана на ' + (x.pct - x.plan) + ' п.п.'))) + ' aria-label="' + esc(x.p.title) + ': ' + x.pct + '%"><span class="wh-fill" style="height:' + Math.max(3, x.pct) + '%;background:' + (x.behind ? 'var(--wh-orange)' : fills[i % fills.length]) + '"></span>' + (x.plan !== null ? '<span class="wh-plan" style="bottom:' + x.plan + '%"></span>' : '') + '</button>'; },
        function (x) { return x.pct + '%<small>' + x.done + ' из ' + x.n + ' ' + plural(x.n, 'задачи', 'задач', 'задач') + '</small>'; });
    } else {
      var all2 = tasks(), total = all2.length, o = all2.filter(function (t) { return !t.done; }), wk = all2.filter(function (t) { return t.done && (t.done_at || '') >= wkDay(-7); }).length;
      var rows2 = TST.map(function (x) { var ts = all2.filter(function (t) { return wtsKey(t) === x[0]; }); return { key: x[0], name: x[1], fill: x[2], ts: ts, n: ts.length, pct: total ? Math.round(ts.length / total * 100) : 0, hl: x[0] === 'over' && ts.length > 0 }; });
      body = cols(rows2,
        function (x) { return [x.pct + '% от всех', x.hl]; },
        function (x) { return x.name; },
        function (x) { return '<button type="button" class="wh-rd-col" data-wh-tst="' + x.key + '"' + tipAttr('<b>' + x.name + ' — ' + x.n + '</b><br>' + (x.ts.slice(0, 4).map(function (t) { return '· ' + esc(t.text.length > 40 ? t.text.slice(0, 40) + '…' : t.text); }).join('<br>') || 'Задач нет') + (x.n > 4 ? '<br>и ещё ' + (x.n - 4) : '')) + ' aria-label="' + x.name + ': ' + x.n + '"><span class="wh-fill" style="height:' + Math.max(3, x.pct) + '%;background:' + x.fill + '"></span></button>'; },
        function (x) { return x.n + '<small>' + plural(x.n, 'задача', 'задачи', 'задач') + '</small>'; });
      legend = '<div class="wh-rd-stats">' + [[total, plural(total, 'задача', 'задачи', 'задач') + ' всего'], [wk, 'сделано за 7 дней · ' + (wk / 7).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' в день'],
        [o.filter(function (t) { return t.prio === 'high'; }).length, 'открыто с высоким приоритетом'], [o.filter(function (t) { return !t.due; }).length, 'открыто без срока']].map(function (x) { return '<div><b class="num">' + x[0] + '</b><small>' + x[1] + '</small></div>'; }).join('') + '</div>';
    }
    return '<section class="wh-card wh-dark wh-a-ready" aria-label="Готовность"><div class="wh-h wh-rh"><h2>Готовность ' + ico('trend') + '</h2>' +
      '<div class="wh-seg" role="tablist">' + [['projects', 'Проекты'], ['tasks', 'Задачи']].map(function (x) { return '<button type="button" role="tab" class="' + (x[0] === s.rv ? 'on' : '') + '" aria-selected="' + (x[0] === s.rv) + '" data-wh-rv="' + x[0] + '">' + x[1] + '</button>'; }).join('') + '</div>' +
      '<span class="wh-sp"></span>' + chipsH + '<a class="wh-icon" href="#' + (s.rv === 'projects' ? 'work' : 'wktasks') + '" aria-label="' + (s.rv === 'projects' ? 'Все проекты' : 'Все задачи') + '">' + ico('chev2') + '</a></div>' +
      '<div class="wh-rd-wrap">' + body + '</div>' + legend + '</section>';
  }
  function cols(rows, top, name, col, pct) {   // четыре ряда сетки: прирост · название · столбик · итог
    var c = function (fn) { return rows.map(function (x, i) { return fn(x, i); }).join(''); };
    return '<div class="wh-rd" style="--n:' + rows.length + '">' +
      c(function (x) { var t = top(x); return '<div class="wh-rd-d' + (t[1] ? ' hl' : '') + '">' + t[0] + (t[1] ? '<span class="wh-up" title="Требует внимания">!</span>' : '') + '</div>'; }) +
      c(function (x) { var t = top(x); return '<div class="wh-rd-n' + (t[1] ? ' hl' : '') + '">' + name(x) + '</div>'; }) +
      c(col) + c(function (x) { return '<div class="wh-rd-p num">' + pct(x) + '</div>'; }) + '</div>';
  }
  function toursCard() {
    var l = ahead(), t0 = wkDay(0);
    return '<section class="wh-card wh-glass wh-a-tours" aria-label="Ближайшие гастроли"><div class="wh-h"><h2>Ближайшие гастроли</h2><span class="wh-sp"></span><a class="wh-icon" href="#wkcal" aria-label="Календарь">' + ico('cal') + '</a></div>' +
      (l.length ? '<div class="wh-tours">' + l.slice(0, 6).map(function (s) {
        var d = D(s.date), we = d.getDay() === 0 || d.getDay() === 6, n = days(t0, s.date), sale = s.sale || '';
        return '<button type="button" class="wh-tour" data-wh-show="' + s.id + '" aria-haspopup="menu"><span class="wh-tdate' + (we ? ' we' : '') + '"><b class="num">' + ('0' + d.getDate()).slice(-2) + '</b><small>' + MON[d.getMonth()] + ' · ' + WD[d.getDay()] + '</small></span>' +
          '<span class="wh-tour-b"><span class="wh-tour-c">' + esc(s.city || s.name) + '</span><span class="wh-tour-v">' + esc([s.city ? s.name : '', wkPname(s.project)].filter(Boolean).join(' · ')) + '</span></span>' +
          '<span class="wh-tour-r"><span class="wh-sale s-' + (sale || 'wait') + '">' + SALE[sale] + '</span><span class="wh-tour-in">' + (n ? 'через ' + n + ' ' + plural(n, 'день', 'дня', 'дней') : 'сегодня') + '</span></span></button>';
      }).join('') + (l.length > 6 ? '<a class="wh-chip wh-more" href="#wkcal">Ещё ' + (l.length - 6) + ' ' + plural(l.length - 6, 'дата', 'даты', 'дат') + '</a>' : '') + '</div>'
        : '<p class="wh-empty">Дат гастролей пока нет — их добавляют во вкладке «Гастроли» проекта</p>') + '</section>';
  }
  function projectsBlock() {
    var s = st(), data = ready(), first = function (p) { return wkShowsOf(p.id).filter(function (x) { return x.date; }).sort(function (a, b) { return a.date.localeCompare(b.date); }); };
    var SORT = { date: 'дате гастролей', title: 'названию', ready: 'готовности' };
    var key = { date: function (x) { var f = first(x.p).filter(function (v) { return v.date >= wkDay(0); })[0]; return f ? f.date : '9999'; }, title: function (x) { return x.p.title.toLowerCase(); }, ready: function (x) { return -x.pct; } }[s.sort] || function () { return 0; };
    data.sort(function (a, b) { var ka = key(a), kb = key(b); return ka < kb ? -1 : ka > kb ? 1 : 0; });
    return '<section class="wh-a-proj" aria-label="Проекты"><div class="wh-ph"><h2>Проекты</h2><span class="wh-sp"></span>' +
      '<button type="button" class="wh-sort" data-wh-sort aria-haspopup="menu"><span class="wh-lbl">Сортировка: </span>' + SORT[s.sort] + ' ' + ico('down', 16) + '</button>' +
      '<div class="wh-vt"><button type="button" class="' + (s.list ? '' : 'on') + '" data-wh-view="grid" aria-pressed="' + !s.list + '" aria-label="Карточки">' + ico('grid') + '</button><button type="button" class="' + (s.list ? 'on' : '') + '" data-wh-view="list" aria-pressed="' + s.list + '" aria-label="Список">' + ico('list') + '</button></div></div>' +
      (data.length ? '<div class="wh-projs' + (s.list ? ' list' : '') + '">' + data.map(function (x) {
        var ss = first(x.p), up = ss.filter(function (v) { return v.date >= wkDay(0); }), on = ss.filter(function (v) { return v.sale === 'onsale'; }).length, nx = up[0];
        var nt = wkTasksOf(x.p.id).filter(function (t) { return !t.done; }).sort(function (a, b) { return (a.due || '9').localeCompare(b.due || '9'); })[0];
        return '<button type="button" class="wh-pc" data-wh-open="' + x.p.id + '"><span class="wh-pc-h"><span class="wh-pc-t">' + esc(x.p.title) + '</span>' + ring(x.done, x.n, 38, true) + '</span>' +
          '<span class="wh-pc-st"><i style="background:' + (STAGE_HEX[wkStageColor(x.p.stage)] || '#bdbdbb') + '"></i>' + esc(wkLabel(WK_STAGE, x.p.stage)) + '</span>' +
          '<span class="wh-pc-m">' + (nx ? 'Гастроли: <b>' + short(nx.date) + ' · ' + esc(nx.city || nx.name) + '</b>' + (up.length > 1 ? ' + ещё ' + (up.length - 1) : '') + '<br>В продаже: <b>' + on + '/' + ss.length + '</b>' : ss.length ? 'Гастроли прошли' : 'Дат гастролей пока нет') + '</span>' +
          '<span class="wh-pc-m">' + (nt ? 'Дальше: ' + esc(nt.text) + (nt.due ? ' · ' + short(nt.due) : '') : x.n ? 'Все задачи сделаны' : 'Задач пока нет') + '</span></button>';
      }).join('') + '</div>' : '<p class="wh-empty wh-empty-l">Проектов в работе нет — «Создать» → «Проект»</p>') + '</section>';
  }

  function page() {
    var g = wkGate('Обзор'); if (g) return g;
    TIPS = [];
    return '<div class="wh">' + header() + '<div class="wh-grid">' + topCard() + moneyCard() + goalsCard() + focusCard() + readyCard() + toursCard() + projectsBlock() + '</div></div>';
  }

  var api = { fire: fire, ready: ready, focusList: focusList, goals: goals, SALE_DAYS: SALE_DAYS };   // правила — для tests/work-home.test.js
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  // ---------------------------------------------------------------- действия
  function openProj(pid, tab) {   // как data-wk-open в «Задачах»: «Назад» со страницы проекта вернёт в «Обзор»
    if (!WK.projects[pid]) return;
    wkPopClose(); S.wk.from = 'wkhome'; S.view = 'work'; location.hash = 'work'; S.enter = true;
    S.wk.y = window.scrollY; S.wk.proj = pid; S.wk.ptab = tab || 'tasks'; S.wk.mcal = null; S.wk.scrollT = {}; S.wk.qs = { open: '', done: '' }; S.wk.qAt = {};
    window.render(); window.scrollTo(0, 0);
  }
  function go(view) { wkPopClose(); location.hash = view; }
  function putTask(id, patch, msg) { var r = Object.assign({}, WK.tasks[id], patch); delete r.upd; wkPut('tasks', id, r, msg || ''); }
  function putGoal(id, patch, msg) { var r = Object.assign({}, WK.goals[id], patch); delete r.upd; wkPut('goals', id, r, msg || '', true); }
  function menu(anchor, cls, items) {   // items: [подпись, атрибут, значок] | '-' | {cap}
    wkPopOpen(anchor, 'wk-menu wh-menu ' + cls, items.map(function (it) {
      if (it === '-') return '<hr>';
      if (it.cap) return '<div class="wkp-title">' + it.cap + '</div>';
      return '<button type="button" class="wk-menu-item" role="menuitem" ' + it[1] + '><span>' + it[0] + '</span>' + (it[2] ? ico(it[2], 16) : '') + '</button>';
    }).join(''));
  }
  function searchPop(input) {
    var q = (input.value || '').trim().toLowerCase().replace(/ё/g, 'е'); st().q = input.value;
    if (q.length < 2) { if (WKPOP && WKPOP.anchor === input) wkPopClose(); return; }
    var has = function (s) { return String(s || '').toLowerCase().replace(/ё/g, 'е').indexOf(q) >= 0; }, res = [];
    wkProjects().filter(function (p) { return has(p.title); }).slice(0, 4).forEach(function (p) { res.push(['Проект', p.title, 'data-wh-open="' + p.id + '"']); });
    tasks().filter(function (t) { return has(t.text); }).sort(function (a, b) { return a.done - b.done; }).slice(0, 6).forEach(function (t) { res.push([t.done ? 'Задача · готово' : 'Задача', t.text, 'data-wh-task="' + t.id + '"']); });
    Object.keys(WK.parties || {}).filter(function (k) { return has(WK.parties[k].name) || has(WK.parties[k].inn); }).slice(0, 3).forEach(function (k) { res.push(['Контрагент', WK.parties[k].name, 'data-wh-go="wkparties"']); });
    shows().filter(function (s) { return has(s.city) || has(s.name); }).slice(0, 3).forEach(function (s) { res.push(['Гастроли · ' + short(s.date), (s.city || '') + (s.name ? ' · ' + s.name : ''), 'data-wh-open="' + s.project + '" data-wh-tab="shows"']); });
    var html = res.length ? res.map(function (r) { return '<button type="button" class="wk-menu-item wh-sr" ' + r[2] + '><small>' + esc(r[0]) + '</small><span>' + esc(r[1]) + '</span></button>'; }).join('') : '<div class="wh-sr-none">Ничего не нашлось</div>';
    if (WKPOP && WKPOP.anchor === input) { WKPOP.el.innerHTML = html; wkPopPlace(); } else wkPopOpen(input, 'wk-menu wh-menu wh-search-pop', html);
  }
  function doneTask(id, btn) {
    var t = WK.tasks[id]; if (!t) return;
    var prev = wkStatusOf(t), card = btn && btn.closest('.wh-tc');
    var fin = function () { wkStatusSet(id, 'done'); wkSnack('Готово: ' + t.text, function () { wkStatusSet(id, prev === 'done' ? '' : prev); }); };
    if (card && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) { card.classList.add('gone'); setTimeout(fin, 200); } else fin();
  }
  function goalAdd(input) {
    var text = input.value.trim(); if (!text) return;
    var g = goals(st().month), order = g.reduce(function (m, x) { return Math.max(m, x.order || 0); }, 0) + 1;
    wkPut('goals', wkId('g'), { month: st().month, text: text, done: false, order: order }, '');
    var n = document.querySelector('[data-wh-gnew]'); if (n) n.focus();
  }

  document.addEventListener('click', function (ev) {
    if (S.view !== 'wkhome' || !ev.target.closest) return;
    var b = ev.target.closest('[data-wh-open],[data-wh-task],[data-wh-go],[data-wh-tst],[data-wh-fire],[data-wh-focus],[data-wh-money],[data-wh-rv],[data-wh-rf],[data-wh-view],[data-wh-sort],[data-wh-sortset],[data-wh-month],[data-wh-gedit],[data-wh-gdel],[data-wh-remind],[data-wh-done],[data-wh-tmore],[data-wh-pin],[data-wh-tdel],[data-wh-newtask],[data-wh-create],[data-wh-new],[data-wh-bell],[data-wh-fireinfo],[data-wh-search],[data-wh-show],[data-wh-sale],[data-wh-shownew]');
    if (!b) return;
    var s = st(), a = function (n) { return b.getAttribute(n); };
    if (b.hasAttribute('data-wh-open')) { ev.preventDefault(); openProj(a('data-wh-open'), a('data-wh-tab')); return; }
    if (b.hasAttribute('data-wh-task')) { ev.preventDefault(); wkPopClose(); wkOpenTask(a('data-wh-task')); return; }
    if (b.hasAttribute('data-wh-go')) { ev.preventDefault(); go(a('data-wh-go')); return; }
    if (b.hasAttribute('data-wh-tst')) { S.wk.tst = a('data-wh-tst'); go('wktasks'); return; }
    if (b.hasAttribute('data-wh-fire')) { s.fire = a('data-wh-fire'); window.render(); return; }
    if (b.hasAttribute('data-wh-focus')) { s.focus = a('data-wh-focus'); window.render(); return; }
    if (b.hasAttribute('data-wh-money')) { s.money = +a('data-wh-money'); window.render(); return; }
    if (b.hasAttribute('data-wh-rv')) { s.rv = a('data-wh-rv'); ls('rv', s.rv); window.render(); return; }
    if (b.hasAttribute('data-wh-rf')) { s.rf = a('data-wh-rf'); window.render(); return; }
    if (b.hasAttribute('data-wh-view')) { s.list = a('data-wh-view') === 'list'; ls('list', s.list ? '1' : '0'); window.render(); return; }
    if (b.hasAttribute('data-wh-sort')) { menu(b, 'wh-sortpop', [['по дате гастролей', 'data-wh-sortset="date"'], ['по названию', 'data-wh-sortset="title"'], ['по готовности', 'data-wh-sortset="ready"']]); return; }
    if (b.hasAttribute('data-wh-sortset')) { s.sort = a('data-wh-sortset'); ls('sort', s.sort); wkPopClose(); window.render(); return; }
    if (b.hasAttribute('data-wh-month')) { var d = D(s.month + '-01'); d.setMonth(d.getMonth() + +a('data-wh-month')); s.month = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2); window.render(); return; }
    if (b.hasAttribute('data-wh-gedit')) { s.gedit = !s.gedit; window.render(); if (s.gedit) { var n = document.querySelector('[data-wh-gnew]'); if (n) n.focus(); } return; }
    if (b.hasAttribute('data-wh-gdel')) { wkDel('goals', a('data-wh-gdel'), 'Цель удалена'); return; }
    if (b.hasAttribute('data-wh-remind')) { var rt = WK.tasks[a('data-wh-remind')]; putTask(a('data-wh-remind'), { remind: !rt.remind }, rt.remind ? 'Напоминание снято' : 'Напомню в Telegram утром в день срока'); return; }
    if (b.hasAttribute('data-wh-done')) { doneTask(a('data-wh-done'), b); return; }
    if (b.hasAttribute('data-wh-tmore')) {
      var tid = a('data-wh-tmore'), tt = WK.tasks[tid];
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      menu(b, 'wh-tmenu', [[tt.pin ? 'Открепить' : 'Закрепить в фокусе', 'data-wh-pin="' + tid + '"', 'pin'], ['Открыть задачу', 'data-wh-task="' + tid + '"', 'pencil'], ['Удалить', 'data-wh-tdel="' + tid + '"', 'trash']]);
      return;
    }
    if (b.hasAttribute('data-wh-pin')) { var pt = WK.tasks[a('data-wh-pin')]; wkPopClose(); putTask(a('data-wh-pin'), { pin: !pt.pin }, pt.pin ? 'Откреплена' : 'Закреплена в фокусе'); return; }
    if (b.hasAttribute('data-wh-tdel')) { wkPopClose(); wkDel('tasks', a('data-wh-tdel'), 'Задача удалена'); return; }
    if (b.hasAttribute('data-wh-newtask')) { wkNewTaskOpen(); if (s.focus !== 'pin') { S.wk.draft.due = wkDay(0); wkNewTaskRefresh('#wkn-text'); } return; }
    if (b.hasAttribute('data-wh-create')) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      menu(b, 'wh-createpop', [['Задача', 'data-wh-new="task"', 'task'], ['Проект', 'data-wh-new="project"', 'folder'], ['Гастроли', 'data-wh-new="shows"', 'cal'], ['Быстрая заметка', 'data-wh-new="quick"', 'note'], ['Рабочая заметка', 'data-wh-new="work"', 'doc'], '-', ['Цель месяца', 'data-wh-new="goal"', 'check']]);
      return;
    }
    if (b.hasAttribute('data-wh-new')) {
      var what = a('data-wh-new'), anchor = document.querySelector('[data-wh-create]'); wkPopClose();
      if (what === 'task') wkNewTaskOpen();
      else if (what === 'project') wkpCreateOpen();
      else if (what === 'quick') wknEdOpen(anchor, null, '');
      else if (what === 'work') wnOpen(null, {});
      else if (what === 'goal') { s.gedit = true; s.month = wkDay(0).slice(0, 7); window.render(); var gn = document.querySelector('[data-wh-gnew]'); if (gn) { gn.scrollIntoView({ block: 'center' }); gn.focus(); } }
      else if (what === 'shows') {
        var ps = active();
        if (!ps.length) { toast('Сначала создайте проект'); return; }
        menu(anchor, 'wh-createpop', [{ cap: 'Гастроли какого проекта?' }].concat(ps.map(function (p) { return [esc(p.title), 'data-wh-shownew="' + p.id + '"']; })));
      }
      return;
    }
    if (b.hasAttribute('data-wh-shownew')) { wkPopClose(); wksNewOpen(a('data-wh-shownew')); return; }
    if (b.hasAttribute('data-wh-bell')) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      var f = fire().slice(0, 6);
      wkPopOpen(b, 'wk-menu wh-menu wh-bellpop', '<div class="wkp-title">Что горит</div>' + (f.length ? f.map(fireItem).join('') : '<p class="wh-empty">Здесь ничего не горит</p>') +
        '<p class="wh-pop-note">Колокольчик у задачи — напоминание в Telegram утром в день срока и каждое утро, пока она не сделана.</p>');
      return;
    }
    if (b.hasAttribute('data-wh-fireinfo')) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      wkPopOpen(b, 'wk-menu wh-menu wh-infopop', '<div class="wkp-title">Что сюда попадает</div><ul class="wh-rules"><li>Просроченные задачи и задачи на сегодня</li><li>Дедлайн готовности проекта — за 7 дней</li><li>Дата гастролей ближе ' + SALE_DAYS + ' дней, а ещё не «в продаже»</li><li>Неоплаченные счета</li><li>Неподписанные договоры</li></ul>');
      return;
    }
    if (b.hasAttribute('data-wh-search')) { var box = b.closest('.wh-search'), inp = box.querySelector('input'); box.classList.add('open'); inp.focus(); return; }
    if (b.hasAttribute('data-wh-show')) {
      var sid = a('data-wh-show'), sh = WK.shows[sid]; if (!sh) return;
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      menu(b, 'wh-showpop', [{ cap: short(sh.date) + ' · ' + esc(sh.city || sh.name) + ' · ' + esc(wkPname(sh.project)) }].concat(Object.keys(SALE).map(function (k) { return [((sh.sale || '') === k ? '✓ ' : '') + SALE[k], 'data-wh-sale="' + sid + '|' + k + '"']; }), ['-', ['Гастроли проекта', 'data-wh-open="' + sh.project + '" data-wh-tab="shows"', 'chev']]));
      return;
    }
    if (b.hasAttribute('data-wh-sale')) { var sp = a('data-wh-sale').split('|'); wkPopClose(); wksSaleSet(sp[0], sp[1]); return; }
  });
  // всплывающие окошки — вне #view: их кнопки обрабатываются тем же обработчиком (выше он смотрит на S.view, не на место кнопки)
  document.addEventListener('change', function (ev) {
    if (S.view !== 'wkhome' || !ev.target.hasAttribute) return;
    var t = ev.target;
    if (t.hasAttribute('data-wh-gdone')) { putGoal(t.getAttribute('data-wh-gdone'), { done: t.checked }, t.checked ? 'Цель выполнена' : ''); window.render(); return; }
    if (t.hasAttribute('data-wh-gtx')) {
      var id = t.getAttribute('data-wh-gtx'), v = t.value.trim();
      if (!v) { t.value = WK.goals[id].text; toast('У цели нужен текст — чтобы убрать, нажмите ×'); return; }
      if (v !== WK.goals[id].text) putGoal(id, { text: v });
    }
  });
  document.addEventListener('keydown', function (ev) {
    if (S.view !== 'wkhome' || !ev.target.hasAttribute) return;
    var t = ev.target;
    if (ev.key === 'Enter' && t.hasAttribute('data-wh-gnew')) { ev.preventDefault(); goalAdd(t); return; }
    if (ev.key === 'Enter' && t.hasAttribute('data-wh-gtx')) { ev.preventDefault(); t.blur(); return; }
    if (ev.key === 'Escape' && t.hasAttribute('data-wh-gtx')) { t.value = WK.goals[t.getAttribute('data-wh-gtx')].text; t.blur(); return; }
    if ((ev.key === 'Enter' || ev.key === ' ') && t.hasAttribute('data-wh-task') && t.tagName === 'H3') { ev.preventDefault(); wkOpenTask(t.getAttribute('data-wh-task')); return; }
    if (ev.key === 'Escape' && t.hasAttribute('data-wh-q')) { t.value = ''; st().q = ''; wkPopClose(); t.blur(); return; }
    if (ev.key === 'Enter' && t.hasAttribute('data-wh-q') && WKPOP) { var first = WKPOP.el.querySelector('button'); if (first) { ev.preventDefault(); first.click(); } }
  });
  document.addEventListener('input', function (ev) { if (S.view === 'wkhome' && ev.target.hasAttribute && ev.target.hasAttribute('data-wh-q')) searchPop(ev.target); });
  document.addEventListener('focusout', function (ev) {   // поиск пустой — свернуть
    var t = ev.target; if (S.view !== 'wkhome' || !t.hasAttribute || !t.hasAttribute('data-wh-q') || t.value) return;
    var box = t.closest('.wh-search'); if (box) box.classList.remove('open');
  });
  document.addEventListener('mouseover', function (ev) {
    if (S.view !== 'wkhome' || !ev.target.closest) return;
    var b = ev.target.closest('[data-wh-tip]'), el = tipEl();
    if (!b) { el.classList.remove('show'); return; }
    el.innerHTML = TIPS[+b.getAttribute('data-wh-tip')] || ''; el.classList.add('show'); tipMove(ev);
  });
  document.addEventListener('mousemove', function (ev) { if (S.view === 'wkhome' && ev.target.closest && ev.target.closest('[data-wh-tip]')) tipMove(ev); });
  // лента «В фокусе» шире блока — правый край затухает; докрутили до конца — без затухания
  function edge() { var r = document.querySelector('[data-wh-frow]'); if (!r) return; r.classList.toggle('more', r.scrollWidth > r.clientWidth + 2); r.classList.toggle('end', r.scrollLeft + r.clientWidth >= r.scrollWidth - 2); }
  document.addEventListener('scroll', function (ev) { if (ev.target && ev.target.hasAttribute && ev.target.hasAttribute('data-wh-frow')) edge(); }, true);
  window.addEventListener('resize', function () { if (S.view === 'wkhome') edge(); });

  root.renderWkHome = function () { var html = page(); setTimeout(function () { edge(); var el = document.getElementById('whTip'); if (el) el.classList.remove('show'); }, 0); return html; };
  root.WorkHome = api;
})(typeof window !== 'undefined' ? window : globalThis);
