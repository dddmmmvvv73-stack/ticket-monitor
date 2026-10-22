// Документы и контрагенты (решения пользователя 22.10). Документы — только статусы (файлы — у пользователя): договоры и счета + УПД
// по каждому контрагенту проекта; статусы Ожидаем → Получен → У бухгалтера → Подписан; без полного ЭДО — оригиналы (отправили /
// получили); счёт — аванс или полная оплата, оплачено; остаток — по договору. Контрагенту, добавленному в проект, сразу создаётся
// комплект «договор + счёт + УПД». Вкладка «Документы» проекта и раздел «Документы» — одна таблица (как «Гастроли»: красный «+»
// с окном на несколько контрагентов, фильтр); раздел «Контрагенты» — справочник. Данные — общий WK (work.json → docs, parties).
(function (root) {
  'use strict';
  var ST = [['wait', 'Ожидаем', 'new'], ['got', 'Получен', 'work'], ['acc', 'У бухгалтера', 'wait'], ['signed', 'Подписан', 'done']];
  var SERVICE = [['venue', 'Площадка'], ['hotel', 'Гостиница'], ['transport', 'Транспорт'], ['tech', 'Свет и звук'], ['promo', 'Реклама'], ['artist', 'Артист / правообладатель'], ['other', 'Прочее']];
  var EDO = [['full', 'Полное ЭДО'], ['in', 'Только входящий ЭДО'], ['none', 'Без ЭДО — оригиналы']];
  var KIT = ['Договор', 'Счёт', 'УПД'];                                     // автокомплект
  var KINDS = ['Договор', 'Допсоглашение', 'Счёт', 'Акт', 'УПД'];           // «+ документ» у контрагента
  var ORDER = { 'Договор': 1, 'Допсоглашение': 2, 'Счёт': 3, 'Акт': 4, 'УПД': 5 };
  var FILTERS = [['', 'Все документы'], ['wait', 'Ожидаем'], ['got', 'Получен'], ['acc', 'У бухгалтера'], ['signed', 'Подписан'], ['orig', 'Ждём оригиналы'], ['topay', 'К оплате']];
  var IC = {
    check: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.3l2.2 2.2 4.8-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    plus: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2v8M2 6h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
  };
  function lab(list, v) { var x = list.filter(function (o) { return o[0] === v; })[0]; return x ? x[1] : ''; }
  function money(v) { return v == null || v === '' ? '' : wkMoney(v) + ' ₽'; }
  function party(d) { return d.cp && WK.parties && WK.parties[d.cp] ? WK.parties[d.cp] : null; }
  function originals(p) { return !p || p.edo !== 'full'; }                  // без полного ЭДО (или не знаем) — оригиналы отслеживаем
  function isInvoice(d) { return /^сч[её]т/i.test(d.kind || ''); }
  function isContract(d) { return /^договор/i.test(d.kind || ''); }
  function docsAll() { return Object.keys(WK.docs || {}).map(function (id) { return Object.assign({ id: id }, WK.docs[id]); }); }
  function stChip(st) { var o = ST.filter(function (x) { return x[0] === st; })[0] || ST[0]; return '<span class="wk-st ws-' + o[2] + '"><i aria-hidden="true"></i>' + o[1] + '</span>'; }
  // группа — контрагент в проекте (без контрагента — по названию из строки); ключ: проект|контрагент
  function gkey(d) { return (d.project || '') + '|' + (d.cp || 't:' + (d.party || '')); }
  function groups(list) {
    var by = {}, out = [];
    list.forEach(function (d) { var k = gkey(d); if (!by[k]) { by[k] = { key: k, project: d.project || '', cp: d.cp || '', name: d.party || 'Без контрагента', docs: [] }; out.push(by[k]); } by[k].docs.push(d); });
    out.forEach(function (g) { g.docs.sort(function (a, b) { return (ORDER[a.kind] || 9) - (ORDER[b.kind] || 9) || a.id.localeCompare(b.id); }); g.first = g.docs.reduce(function (m, d) { return d.id < m ? d.id : m; }, g.docs[0].id); });
    return out.sort(function (a, b) { return (a.project === b.project ? 0 : wkPname(a.project).localeCompare(wkPname(b.project), 'ru')) || a.first.localeCompare(b.first); });
  }
  function sums(g) {   // остаток — по договору (решение 22.10): сумма договоров − оплачено по счетам контрагента в проекте
    var contract = 0, invoiced = 0, paid = 0;
    g.docs.forEach(function (d) { if (isContract(d)) contract += d.amount || 0; if (isInvoice(d)) { invoiced += d.amount || 0; paid += d.paid || 0; } });
    return { contract: contract, invoiced: invoiced, paid: paid, rest: contract ? contract - paid : invoiced - paid };
  }
  function sumHtml(g) {
    var s = sums(g); if (!s.contract && !s.invoiced) return '';
    return (s.contract ? 'договор <b class="num">' + money(s.contract) + '</b> · ' : '') + 'оплачено <b class="num">' + money(s.paid || 0) + '</b>' +
      (s.rest > 0 ? ' · остаток <b class="num wdc-rest">' + money(s.rest) + '</b>' : s.contract || s.invoiced ? ' · <span class="wdc-paidall">оплачено полностью</span>' : '');
  }
  function match(d, f) {
    if (!f) return true;
    if (f === 'orig') return originals(party(d)) && d.status !== 'wait' && !d.orig_in;
    if (f === 'topay') return isInvoice(d) && (d.amount || 0) > (d.paid || 0);
    return (d.status || 'wait') === f;
  }
  // фильтр — только там, где выбран (проект или весь раздел)
  function scope() { return S.view === 'work' && S.wk.proj ? S.wk.proj : '*'; }
  function filterOf() { return S.wk.wdcFS === scope() ? S.wk.wdcF || '' : ''; }

  // ---------- таблица: вкладка проекта (pid) и раздел (pid = null — все проекты, в заголовке группы — проект)
  function table(pid) {
    var all = docsAll().filter(function (d) { return pid == null || d.project === pid; }), f = filterOf();
    if (!all.length) return '<div class="note">' + (pid == null ? 'Документов пока нет.' : 'Документов пока нет.') + ' Нажмите красный «+» — выберите контрагентов (площадки, гостиницы, транспорт…): каждому сразу появятся договор, счёт и УПД.</div>';
    var gs = groups(all), rows = '';
    gs.forEach(function (g) {
      var vis = g.docs.filter(function (d) { return match(d, f); }); if (!vis.length) return;
      var p = g.cp && WK.parties[g.cp], orig = originals(p);
      var meta = p ? [p.city, lab(SERVICE, p.service), p.inn ? 'ИНН ' + p.inn : '', p.edo ? lab(EDO, p.edo) : 'ЭДО не указано'].filter(Boolean).join(' · ') : '';
      rows += '<tr class="wdc-g"><td colspan="7"><div class="wdc-gh"><div class="wdc-gl">' +
        (pid == null && g.project ? '<button type="button" class="wdc-proj" data-wk-open="' + esc(g.project) + '" data-wk-tab="docs" title="Открыть документы проекта">' + esc(wkPname(g.project) || 'Без проекта') + '</button><span class="wdc-dot">·</span>' : '') +
        (p ? '<button type="button" class="wdc-name" data-wdc-party="' + esc(g.cp) + '" title="' + esc(p.name) + ' — карточка контрагента">' + esc(p.name) + '</button>'
          : '<span class="wdc-name nolink">' + esc(g.name) + '</span><button type="button" class="pj-plain wdc-link" data-wdc-link="' + esc(g.key) + '">в контрагенты</button>') +
        (meta ? '<span class="wdc-meta" title="' + esc(meta) + '">' + esc(meta) + '</span>' : '') + '</div><div class="wdc-gr">' +
        '<span class="wdc-sum" data-wdc-sum="' + esc(g.key) + '">' + sumHtml(g) + '</span>' +
        '<button type="button" class="wdc-gbtn" data-wdc-add="' + esc(g.key) + '" aria-haspopup="menu" title="Добавить документ">' + IC.plus + 'документ</button>' +
        '<button type="button" class="icon-btn wk-x" data-wdc-gdel="' + esc(g.key) + '" aria-label="Убрать контрагента и его документы из проекта" title="Убрать контрагента и его документы">' + PJ_ICON.close + '</button></div></div></td></tr>';
      vis.forEach(function (d) {
        var fl = function (fld) { return 'data-wk-f="docs|' + d.id + '|' + fld + '"'; };
        rows += '<tr class="wdc-r' + (d.status === 'signed' && (!orig || d.orig_in) ? ' wdc-done' : '') + '">' +
          '<td class="wdc-kind">' + esc(d.kind || 'Документ') + '</td>' +
          '<td class="wdc-st"><button type="button" class="wkt-tags" data-wdc-st="' + d.id + '" aria-haspopup="menu" aria-label="Статус: ' + lab(ST, d.status || 'wait') + ' — изменить">' + stChip(d.status || 'wait') + '</button></td>' +
          '<td class="wdc-orig">' + (orig ? '<button type="button" class="wdc-ob' + (d.orig_out ? ' on' : '') + '" data-wdc-orig="' + d.id + '|out" aria-pressed="' + !!d.orig_out + '" title="Наш экземпляр оригинала отправили">' + (d.orig_out ? IC.check : '') + 'отправили</button>' +
            '<button type="button" class="wdc-ob' + (d.orig_in ? ' on' : '') + '" data-wdc-orig="' + d.id + '|in" aria-pressed="' + !!d.orig_in + '" title="Подписанный оригинал получили">' + (d.orig_in ? IC.check : '') + 'получили</button>' : '<span class="wdc-edo">ЭДО</span>') + '</td>' +
          '<td class="wdc-amt"><input class="wk-in wk-amount" inputmode="decimal" ' + fl('amount') + ' value="' + esc(wkMoney(d.amount)) + '" placeholder="Сумма" aria-label="Сумма, ₽"></td>' +
          '<td class="wdc-pay">' + (isInvoice(d) ? '<button type="button" class="wdc-inv' + (d.inv ? ' on' : '') + '" data-wdc-inv="' + d.id + '" aria-haspopup="menu">' + (d.inv === 'advance' ? 'Аванс' : d.inv === 'full' ? 'Полная оплата' : 'Аванс / полная?') + '</button>' +
            '<label class="wdc-paid"><span>оплачено</span><input class="wk-in wk-amount" inputmode="decimal" ' + fl('paid') + ' value="' + esc(wkMoney(d.paid)) + '" placeholder="0" aria-label="Оплачено, ₽"></label>' : '') + '</td>' +
          '<td class="wdc-note"><input class="wk-in" ' + fl('note') + ' value="' + esc(d.note || '') + '" placeholder="Заметка" aria-label="Заметка"></td>' +
          '<td class="wdc-x"><button class="icon-btn wk-x" data-wk-del="docs|' + d.id + '" aria-label="Удалить документ" title="Удалить документ">' + PJ_ICON.close + '</button></td></tr>';
      });
    });
    if (!rows) return '<div class="note">Нет документов «' + lab(FILTERS, f) + '» — <button type="button" class="pj-plain" data-wdc-f="">показать все</button></div>';
    return '<div class="card wk-docs-card"><table class="wk-docs wdc"><thead><tr><th>Документ</th><th>Статус</th><th>Оригинал</th><th class="r">Сумма, ₽</th><th>Оплата</th><th>Заметка</th><th></th></tr></thead><tbody>' +
      rows + '</tbody></table></div>';
  }
  // суммы в заголовках групп — после правки суммы без перерисовки (курсор остаётся там, куда перешли по Tab)
  function refreshSums() {
    var pid = S.view === 'work' ? S.wk.proj : null, gs = groups(docsAll().filter(function (d) { return pid == null || d.project === pid; }));
    gs.forEach(function (g) { var el = document.querySelector('[data-wdc-sum="' + g.key.replace(/"/g, '\\"') + '"]'); if (el) el.innerHTML = sumHtml(g); });
  }
  function tools() {   // у вкладки проекта и в разделе: фильтр + красный «+»
    var f = filterOf();
    return '<button type="button" class="wk-sq' + (f ? ' on' : '') + '" data-wdc-filter aria-haspopup="menu" aria-label="Фильтр документов" title="Фильтр документов">' + WKT_ICON.group + (f ? '<i class="wk-sq-dot" aria-hidden="true"></i>' : '') + '</button>' +
      '<button type="button" class="wk-sq wk-sq-add" data-wdc-new aria-haspopup="dialog" aria-label="Добавить контрагентов" title="Добавить контрагентов — каждому договор, счёт и УПД">' + WKT_ICON.plus + '</button>';
  }
  function renderDocsSection() {
    var g = wkGate('Документы'); if (g) return g;
    S.wk.proj = null;
    var all = docsAll(), uns = all.filter(function (d) { return d.status !== 'signed'; }).length;
    return head('Документы', all.length ? 'документов ' + all.length + (uns ? ' · не подписано ' + uns : '') : '', '<div class="wdc-tools">' + tools() + '</div>') + '<div class="wk-body">' + table(null) + '</div>';
  }

  // ---------- создать документы: комплект контрагенту в проекте (по очереди — ответ сервера весь WK)
  function putSeq(list, done) {
    var ok = 0, chain = Promise.resolve();
    list.forEach(function (x) {
      chain = chain.then(function () { return apiJson('POST', '/api/work', { op: 'put', kind: x[0], id: x[1], data: x[2] }).then(function (r) { if (r.ok) { WK = r.d; ok++; } }, function () {}); });
    });
    chain.then(function () { render(); done(ok, list.length); });
  }
  function kitOps(project, cp, name) { return KIT.map(function (k) { return ['docs', wkId('d'), { project: project, cp: cp, party: name, kind: k, status: 'wait' }]; }); }
  function partyInProject(project, cp) { return docsAll().some(function (d) { return d.project === project && d.cp === cp; }); }
  function partyFromVenue(v) {
    return { name: v.name || 'Площадка', legal: v.legal || '', inn: String(v.inn || '').replace(/\s/g, ''), city: v.city || '', service: 'venue',
      edo: v.edo === 'full' || v.edo === 'in' || v.edo === 'none' ? v.edo : '', contact: v.contact || '', phone: v.phone || '', email: v.email || '', note: '', venue: v.id };
  }
  function partyByVenue(vid) { return Object.keys(WK.parties || {}).filter(function (k) { return WK.parties[k].venue === vid; })[0] || ''; }
  // подсказки: контрагенты и площадки справочника (площадка, уже ставшая контрагентом, — им)
  function suggest(q) {
    var n = wksNorm(q.trim()); if (n.length < 2) return [];
    var words = n.split(/[\s,.·«»"]+/).filter(Boolean);
    var ps = Object.keys(WK.parties || {}).filter(function (k) { var p = WK.parties[k], h = wksNorm([p.name, p.legal, p.inn, p.city].join(' ')); return words.every(function (w) { return h.indexOf(w) >= 0; }); })
      .slice(0, 6).map(function (k) { var p = WK.parties[k]; return { t: 'p', id: k, name: p.name, sub: [p.city, lab(SERVICE, p.service), p.inn ? 'ИНН ' + p.inn : ''].filter(Boolean).join(' · ') }; });
    var vs = (typeof VB_ROWS !== 'undefined' ? wksMatch(q) : []).filter(function (v) { return !partyByVenue(v.id); }).slice(0, 6)
      .map(function (v) { return { t: 'v', id: v.id, name: v.name || 'Без названия', sub: [v.city, 'площадка из справочника', v.inn ? 'ИНН ' + v.inn : ''].filter(Boolean).join(' · ') }; });
    return ps.concat(vs);
  }

  // ---------- окно «Добавить контрагентов» (красный «+»): строка на контрагента; площадки гастролей — подсказкой сверху
  function newRow() { return { pick: '', name: '', city: '', service: '' }; }
  function newOpen(pid) {
    S.wk.wdcNew = { pid: pid || '', rows: [newRow(), newRow(), newRow()] };
    pjDialog('pj-edit wdc-dlg', 'Добавить контрагентов', newHtml());
    var i = document.querySelector('#pjDlg .wdc-nrow input[name=name]'); if (i) i.focus();
  }
  function showVenues(pid) {   // площадки гастролей проекта, которых ещё нет в документах
    if (!pid) return [];
    var seen = {};
    return Object.keys(WK.shows || {}).map(function (k) { return WK.shows[k]; }).filter(function (s) { return s.project === pid && s.venue && wkVenue(s.venue); })
      .map(function (s) { return wkVenue(s.venue); }).filter(function (v) { if (seen[v.id]) return false; seen[v.id] = 1; var cp = partyByVenue(v.id); return !(cp && partyInProject(pid, cp)); });
  }
  function newHtml() {
    var st = S.wk.wdcNew, sv = showVenues(st.pid);
    var picked = {}; st.rows.forEach(function (r) { if (r.pick) picked[r.pick] = 1; });
    sv = sv.filter(function (v) { return !picked['v:' + v.id] && !picked['p:' + partyByVenue(v.id)]; });
    return '<div class="wdc-new">' +
      (st.pid ? '' : '<label class="wdc-nproj"><span>Проект</span><select class="wk-in" name="wdc-proj" data-native>' + wkProjOpts(st.pid, 'Выберите проект') + '</select></label>') +
      '<p class="sub2 wks-nhint">Каждому контрагенту сразу появятся договор, счёт и УПД («Ожидаем»). Контрагент — из раздела «Контрагенты» или площадка из справочника; нет — впишите название, город и услугу: он добавится в «Контрагенты».</p>' +
      (sv.length ? '<div class="wdc-chips"><span>Площадки гастролей:</span>' + sv.map(function (v) { return '<button type="button" class="wdc-chip" data-wdc-venue="' + esc(v.id) + '">' + IC.plus + esc(v.name) + (v.city ? ' · ' + esc(v.city) : '') + '</button>'; }).join('') +
        (sv.length > 1 ? '<button type="button" class="pj-plain" data-wdc-venue="*">все</button>' : '') + '</div>' : '') +
      '<div class="wdc-nhead" aria-hidden="true"><span></span><span>Контрагент</span><span>Город</span><span>Услуга</span><span></span></div>' +
      st.rows.map(function (r, i) {
        var known = !!r.pick;
        return '<form class="wdc-nrow" data-wdc-nrow="' + i + '" autocomplete="off"><span class="wks-nnum">' + (i + 1) + '</span>' +
          '<div class="wdc-pick"><input class="wk-in" name="name" value="' + esc(r.name) + '" placeholder="Название, ИНН или город" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="wdcSug' + i + '" aria-label="Контрагент, строка ' + (i + 1) + '" maxlength="300">' +
            '<div class="wks-sug" id="wdcSug' + i + '" role="listbox" aria-label="Контрагенты и площадки" hidden></div></div>' +
          '<input class="wk-in" name="city" value="' + esc(r.city) + '" placeholder="Город" aria-label="Город, строка ' + (i + 1) + '" maxlength="120"' + (known ? ' disabled' : '') + '>' +
          '<select class="wk-in" name="service" data-native aria-label="Услуга, строка ' + (i + 1) + '"' + (known ? ' disabled' : '') + '><option value="">Услуга</option>' + SERVICE.map(function (o) { return '<option value="' + o[0] + '"' + (r.service === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select>' +
          (st.rows.length > 1 ? '<button type="button" class="icon-btn wk-x" data-wdc-nrow-del="' + i + '" aria-label="Убрать строку ' + (i + 1) + '" title="Убрать строку">' + PJ_ICON.close + '</button>' : '<span></span>') +
          '<button type="submit" hidden tabindex="-1"></button></form>';
      }).join('') +
      '<button type="button" class="btn-ghost wks-nmore" data-wdc-nrow-add>+ Ещё контрагент</button>' +
      '<div class="form-actions wkd-foot"><button type="button" class="btn-dark" data-wdc-nsave>Добавить в документы</button><button type="button" class="btn-ghost" data-pj="close">Отмена</button></div></div>';
  }
  function newSync() {
    var st = S.wk.wdcNew; if (!st) return;
    var ps = document.querySelector('#pjDlg [name=wdc-proj]'); if (ps) st.pid = ps.value;
    document.querySelectorAll('#pjDlg .wdc-nrow').forEach(function (f) {
      var r = st.rows[+f.getAttribute('data-wdc-nrow')]; if (!r) return;
      if (r.name !== f.elements.name.value) r.pick = r.pick && r.name === f.elements.name.value ? r.pick : '';
      r.name = f.elements.name.value; if (!r.pick) { r.city = f.elements.city.value; r.service = f.elements.service.value; }
    });
  }
  function newRefresh(focusRow) {
    var box = document.querySelector('#pjDlg .wdc-new'); if (!box) return;
    box.outerHTML = newHtml();
    var i = focusRow != null && document.querySelector('#pjDlg [data-wdc-nrow="' + focusRow + '"] input[name=name]'); if (i) i.focus();
  }
  function pickRow(i, it) {   // выбор из подсказки: контрагент или площадка справочника
    var r = S.wk.wdcNew.rows[i]; if (!r) return;
    r.pick = it.t + ':' + it.id; r.name = it.name;
    if (it.t === 'p') { var p = WK.parties[it.id]; r.city = p.city; r.service = p.service; } else { var v = wkVenue(it.id); r.city = v ? v.city || '' : ''; r.service = 'venue'; }
  }
  function newSave() {
    newSync();
    var st = S.wk.wdcNew, pid = st.pid;
    if (!pid) { toast('Выберите проект'); var ps = document.querySelector('#pjDlg [name=wdc-proj]'); if (ps) ps.focus(); return; }
    var rows = st.rows.filter(function (r) { return r.name.trim(); });
    if (!rows.length) { toast('Впишите хотя бы одного контрагента'); return; }
    $('pjDlg').close();
    var ops = [], skipped = 0, seen = {};
    rows.forEach(function (r) {   // контрагент: выбранный · площадка → контрагент (если ещё нет) · новый по названию
      var cp = '', rec = null, name = r.name.trim();
      if (r.pick.indexOf('p:') === 0) cp = r.pick.slice(2);
      else if (r.pick.indexOf('v:') === 0) { cp = partyByVenue(r.pick.slice(2)); if (!cp) { var v = wkVenue(r.pick.slice(2)); rec = v ? partyFromVenue(v) : null; } }
      else {
        var same = Object.keys(WK.parties || {}).filter(function (k) { return wksNorm(WK.parties[k].name) === wksNorm(name) && (!r.city || wksNorm(WK.parties[k].city) === wksNorm(r.city)); })[0];
        if (same) cp = same; else rec = { name: name, city: r.city.trim(), service: r.service };
      }
      if (rec) { cp = wkId('k'); ops.push(['parties', cp, rec]); name = rec.name; }
      else if (cp && WK.parties[cp]) name = WK.parties[cp].name;
      if (seen[cp] || (cp && partyInProject(pid, cp))) { skipped++; return; }
      seen[cp] = 1; ops = ops.concat(kitOps(pid, cp, name));
    });
    if (!ops.length) { toast('Эти контрагенты уже есть в документах проекта'); return; }
    putSeq(ops, function (ok, n) {
      var added = ops.filter(function (o) { return o[0] === 'docs'; }).length / KIT.length;
      toast(ok === n ? 'Добавлено контрагентов: ' + added + ' — каждому договор, счёт и УПД' + (skipped ? ' · уже были: ' + skipped : '') : 'Сохранено не всё — проверьте связь с сервером');
    });
  }
  function sugShow(inp) {
    var f = inp.closest('.wdc-nrow'), box = f.querySelector('.wks-sug'), l = suggest(inp.value);
    if (inp.value.trim().length < 2) { box.hidden = true; inp.setAttribute('aria-expanded', 'false'); return; }
    box.innerHTML = l.length ? l.map(function (it, i) {
      return '<button type="button" role="option" class="wks-opt' + (i === 0 ? ' on' : '') + '" data-wdc-pick="' + it.t + ':' + esc(it.id) + '" aria-selected="' + (i === 0) + '"><b>' + esc(it.name) + '</b><span>' + esc(it.sub) + '</span></button>';
    }).join('') : '<div class="wks-none">Не нашли — добавится новый контрагент «' + esc(inp.value.trim()) + '».</div>';
    box.hidden = false; inp.setAttribute('aria-expanded', 'true');
  }
  function sugPick(f, val) {
    var i = +f.getAttribute('data-wdc-nrow'), p = val.split(':'), it = p[0] === 'p' ? { t: 'p', id: p[1], name: WK.parties[p[1]].name } : { t: 'v', id: p[1], name: (wkVenue(p[1]) || {}).name || '' };
    newSync(); pickRow(i, it); newRefresh();
    var n = document.querySelector('#pjDlg [data-wdc-nrow="' + (i + 1) + '"] input[name=name]'); if (n) n.focus();
  }

  // ---------- карточка контрагента: правка — сразу; новый — «Создать»; из справочника площадок — заполнить
  var PF = [['name', 'Название', 'ОЦКНТ, ИП Иванов, гостиница «Липецк»'], ['legal', 'Юрлицо', 'ОБУК «ОЦКНТ»'], ['inn', 'ИНН', '10 или 12 цифр'], ['city', 'Город', ''],
    ['contact', 'Контактное лицо', 'Имя, должность'], ['phone', 'Телефон', ''], ['email', 'Почта', ''], ['note', 'Заметка', 'Реквизиты, бухгалтерия, что важно']];
  function partyHtml(id) {
    var p = id ? WK.parties[id] : S.wk.wdcParty, isNew = !id, used = {};
    docsAll().forEach(function (d) { if (id && d.cp === id) used[d.project] = (used[d.project] || 0) + 1; });
    var v = p.venue && wkVenue(p.venue);
    return '<div class="wdc-pcard" data-wdc-pcard="' + (id || '') + '">' +
      (isNew ? '<div class="wdc-pf wdc-vfind"><span>Площадка из справочника</span><div class="wdc-pick"><input class="wk-in" data-wdc-vfind placeholder="Найти площадку — заполнить карточку" autocomplete="off" aria-label="Найти площадку в справочнике"><div class="wks-sug" hidden></div></div></div>' : '') +
      PF.map(function (f) {
        var tag = f[0] === 'note' ? '<textarea class="wk-in" rows="2"' : '<input class="wk-in"' + (f[0] === 'inn' ? ' inputmode="numeric"' : '');
        return '<label class="wdc-pf"><span>' + f[1] + (f[0] === 'name' ? ' *' : '') + '</span>' + tag + ' data-wdcp-f="' + f[0] + '" placeholder="' + esc(f[2]) + '" maxlength="300"' + (f[0] === 'note' ? '>' + esc(p[f[0]] || '') + '</textarea>' : ' value="' + esc(p[f[0]] || '') + '">') + '</label>';
      }).slice(0, 4).join('') +
      '<label class="wdc-pf"><span>Услуга</span><select class="wk-in" data-native data-wdcp-f="service"><option value="">Не указана</option>' + SERVICE.map(function (o) { return '<option value="' + o[0] + '"' + (p.service === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select></label>' +
      '<label class="wdc-pf"><span>ЭДО</span><select class="wk-in" data-native data-wdcp-f="edo"><option value="">Не знаем</option>' + EDO.map(function (o) { return '<option value="' + o[0] + '"' + (p.edo === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('') + '</select></label>' +
      PF.slice(4).map(function (f) {
        return '<label class="wdc-pf"><span>' + f[1] + '</span>' + (f[0] === 'note' ? '<textarea class="wk-in" rows="2" data-wdcp-f="note" placeholder="' + esc(f[2]) + '" maxlength="3000">' + esc(p.note || '') + '</textarea>' : '<input class="wk-in" data-wdcp-f="' + f[0] + '" placeholder="' + esc(f[2]) + '" maxlength="300" value="' + esc(p[f[0]] || '') + '">') + '</label>';
      }).join('') +
      (v ? '<p class="sub2 wdc-pv">Площадка в справочнике: <button type="button" class="pj-plain" data-wdcp-venue="' + esc(v.id) + '">' + esc(v.name) + (v.city ? ' · ' + esc(v.city) : '') + '</button></p>' : '') +
      (Object.keys(used).length ? '<p class="sub2 wdc-pv">Документы: ' + Object.keys(used).map(function (pid) { return '<button type="button" class="pj-plain" data-wdcp-go="' + esc(pid) + '">' + esc(wkPname(pid) || 'без проекта') + '</button> (' + used[pid] + ')'; }).join(', ') + '</p>' : '') +
      '<div class="form-actions wkd-foot">' + (isNew ? '<button type="button" class="btn-dark" data-wdcp-create>Создать контрагента</button><button type="button" class="btn-ghost" data-pj="close">Отмена</button>'
        : '<button type="button" class="btn-dark" data-pj="close">Готово</button><button type="button" class="pj-plain wkd-del" data-wdcp-del>Удалить контрагента</button><span class="sub2">Сохраняется сразу</span>') + '</div></div>';
  }
  function partyOpen(id) {
    if (id && !WK.parties[id]) return;
    if (!id) S.wk.wdcParty = { name: '', legal: '', inn: '', city: '', service: '', edo: '', contact: '', phone: '', email: '', note: '', venue: '' };
    var dlg = pjDialog('pj-edit wdc-pdlg', id ? 'Контрагент' : 'Новый контрагент', partyHtml(id));
    if (!dlg.wdcBound) { dlg.wdcBound = true; dlg.addEventListener('close', function () { if (S.wk.wdcDirty) { S.wk.wdcDirty = false; if (wkOn()) render(); } }); }   // карточку правили — таблица под ней по-новому (ЭДО, город)
    var f = document.querySelector('#pjDlg ' + (id ? '[data-wdcp-f=name]' : '[data-wdc-vfind]')); if (f && !id) f.focus();
  }
  function partyRead() {
    var r = {}; document.querySelectorAll('#pjDlg [data-wdcp-f]').forEach(function (el) { r[el.getAttribute('data-wdcp-f')] = el.value.trim(); }); return r;
  }
  function partyRefresh() { var box = document.querySelector('#pjDlg .wdc-pcard'); if (box) box.outerHTML = partyHtml(box.getAttribute('data-wdc-pcard')); }

  // ---------- раздел «Контрагенты»
  function renderParties() {
    var g = wkGate('Контрагенты'); if (g) return g;
    S.wk.proj = null;
    var q = wksNorm((S.wk.pq || '').trim()), sf = S.wk.psf || '', cnt = {};
    docsAll().forEach(function (d) { if (d.cp) { cnt[d.cp] = cnt[d.cp] || {}; cnt[d.cp][d.project] = 1; } });
    var all = Object.keys(WK.parties || {}).map(function (k) { return Object.assign({ id: k }, WK.parties[k]); });
    var l = all.filter(function (p) {
      return (!q || wksNorm([p.name, p.legal, p.inn, p.city, p.contact].join(' ')).indexOf(q) >= 0) && (!sf || (sf.indexOf('e:') === 0 ? (p.edo || '') === sf.slice(2) : (p.service || '') === sf));
    }).sort(function (a, b) { return a.name.localeCompare(b.name, 'ru'); });
    var tools = '<div class="wkn-tools"><label class="wkn-search">' + WTS_IC.search + '<input type="search" data-wdc-pq value="' + esc(S.wk.pq || '') + '" placeholder="Название, ИНН, город" aria-label="Поиск контрагентов"></label>' +
      '<button type="button" class="wk-sq' + (sf ? ' on' : '') + '" data-wdc-pfilter aria-haspopup="menu" aria-label="Фильтр: услуга, ЭДО" title="Фильтр">' + WKT_ICON.group + (sf ? '<i class="wk-sq-dot" aria-hidden="true"></i>' : '') + '</button>' +
      '<button type="button" class="wk-sq wk-sq-add" data-wdc-pnew aria-haspopup="dialog" aria-label="Новый контрагент" title="Новый контрагент">' + WKT_ICON.plus + '</button></div>';
    var sub = all.length ? all.length + ' ' + plural(all.length, 'контрагент', 'контрагента', 'контрагентов') + (l.length !== all.length ? ' · показано ' + l.length : '') : '';
    if (!all.length) return head('Контрагенты', '', tools) + '<div class="note">Контрагентов пока нет. Нажмите «+» — впишите вручную или найдите площадку в справочнике. Они появляются и сами, когда добавляете контрагентов в документы проекта.</div>';
    if (!l.length) return head('Контрагенты', sub, tools) + '<p class="wkn-none">Ничего не нашлось — измените поиск или фильтр.</p>';
    return head('Контрагенты', sub, tools) + '<div class="card wk-docs-card"><table class="wk-docs wdc-pt"><thead><tr><th>Контрагент</th><th>Город</th><th>Услуга</th><th>ИНН</th><th>ЭДО</th><th>Контакт</th><th class="r">Проекты</th></tr></thead><tbody>' +
      l.map(function (p) {
        var n = cnt[p.id] ? Object.keys(cnt[p.id]).length : 0;
        return '<tr class="wdc-prow" data-wdc-party="' + esc(p.id) + '" tabindex="0" role="button" aria-label="Карточка: ' + esc(p.name) + '"><td class="wdc-pn"><b>' + esc(p.name) + '</b>' + (p.legal ? '<span>' + esc(p.legal) + '</span>' : '') + '</td>' +
          '<td>' + esc(p.city || '—') + '</td><td>' + esc(lab(SERVICE, p.service) || '—') + '</td><td class="num">' + esc(p.inn || '—') + '</td>' +
          '<td>' + (p.edo ? '<span class="wdc-edotag e-' + p.edo + '">' + esc(p.edo === 'full' ? 'полное' : p.edo === 'in' ? 'входящий' : 'оригиналы') + '</span>' : '<span class="muted">—</span>') + '</td>' +
          '<td class="wdc-pc">' + esc([p.contact, p.phone].filter(Boolean).join(' · ') || '—') + '</td><td class="r num">' + (n || '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  // ---------- события
  document.addEventListener('click', function (ev) {
    if (!wkOn() || !ev.target.closest) return;
    var b;
    if (ev.target.closest('[data-wdc-new]')) { newOpen(S.view === 'work' ? S.wk.proj : (S.wk.fproj && S.wk.fproj !== 'none' && WK.projects[S.wk.fproj] ? S.wk.fproj : '')); return; }
    if ((b = ev.target.closest('[data-wdc-filter]'))) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      var pid = S.view === 'work' ? S.wk.proj : null, l = docsAll().filter(function (d) { return pid == null || d.project === pid; }), f = filterOf();
      wkPopOpen(b, 'wk-menu wdc-fmenu', '<div class="wkp-title">Документы</div>' + FILTERS.map(function (o) {
        var on = f === o[0], n = l.filter(function (d) { return match(d, o[0]); }).length;
        return '<button type="button" class="wk-menu-item' + (on ? ' on' : '') + '" data-wdc-f="' + o[0] + '" role="menuitemradio" aria-checked="' + on + '">' + (ST.some(function (s) { return s[0] === o[0]; }) ? stChip(o[0]) : '<span>' + o[1] + '</span>') + '<span class="wks-fn">' + n + (on ? WKT_ICON.check : '') + '</span></button>';
      }).join(''), {});
      var r1 = b.getBoundingClientRect(); WKPOP.el.style.left = Math.max(8, r1.right - WKPOP.el.offsetWidth + window.scrollX) + 'px';
      return;
    }
    if ((b = ev.target.closest('[data-wdc-f]'))) { S.wk.wdcF = b.getAttribute('data-wdc-f'); S.wk.wdcFS = scope(); wkPopClose(); render(); return; }
    if ((b = ev.target.closest('[data-wdc-st]'))) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      var cur = (WK.docs[b.getAttribute('data-wdc-st')] || {}).status || 'wait';
      wkPopOpen(b, 'wk-menu wk-stmenu wdc-stmenu', '<div class="wkp-title">Статус документа</div>' + ST.map(function (o) {
        return '<button type="button" class="wk-menu-item' + (cur === o[0] ? ' on' : '') + '" data-wdc-st-set="' + o[0] + '" role="menuitemradio" aria-checked="' + (cur === o[0]) + '">' + stChip(o[0]) + (cur === o[0] ? WKT_ICON.check : '') + '</button>';
      }).join(''), { wdcId: b.getAttribute('data-wdc-st') });
      return;
    }
    if ((b = ev.target.closest('.wdc-stmenu [data-wdc-st-set]')) && WKPOP) { var sid = WKPOP.wdcId, st = b.getAttribute('data-wdc-st-set'); wkPopClose(); setDoc(sid, { status: st }, 'Статус: ' + lab(ST, st).toLowerCase()); return; }
    if ((b = ev.target.closest('[data-wdc-inv]'))) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      var ci = (WK.docs[b.getAttribute('data-wdc-inv')] || {}).inv || '';
      wkPopOpen(b, 'wk-menu wdc-invmenu', '<div class="wkp-title">Счёт</div>' + [['advance', 'Аванс'], ['full', 'Полная оплата'], ['', 'Не указано']].map(function (o) {
        return '<button type="button" class="wk-menu-item' + (ci === o[0] ? ' on' : '') + '" data-wdc-inv-set="' + o[0] + '" role="menuitemradio" aria-checked="' + (ci === o[0]) + '">' + o[1] + (ci === o[0] ? WKT_ICON.check : '') + '</button>';
      }).join(''), { wdcId: b.getAttribute('data-wdc-inv') });
      return;
    }
    if ((b = ev.target.closest('.wdc-invmenu [data-wdc-inv-set]')) && WKPOP) { var iid = WKPOP.wdcId; wkPopClose(); setDoc(iid, { inv: b.getAttribute('data-wdc-inv-set') }); return; }
    if ((b = ev.target.closest('[data-wdc-orig]'))) { var po = b.getAttribute('data-wdc-orig').split('|'), od = WK.docs[po[0]], fld = po[1] === 'out' ? 'orig_out' : 'orig_in'; if (od) { var pp = {}; pp[fld] = !od[fld]; setDoc(po[0], pp, pp[fld] ? (fld === 'orig_out' ? 'Оригинал отправили' : 'Оригинал получили') : ''); } return; }
    if ((b = ev.target.closest('[data-wdc-add]'))) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      wkPopOpen(b, 'wk-menu wdc-addmenu', '<div class="wkp-title">Добавить документ</div>' + KINDS.map(function (k) { return '<button type="button" class="wk-menu-item" data-wdc-add-kind="' + k + '" role="menuitem">' + k + '</button>'; }).join(''), { wdcKey: b.getAttribute('data-wdc-add') });
      return;
    }
    if ((b = ev.target.closest('.wdc-addmenu [data-wdc-add-kind]')) && WKPOP) {
      var gk = WKPOP.wdcKey, g0 = groups(docsAll()).filter(function (x) { return x.key === gk; })[0]; wkPopClose(); if (!g0) return;
      wkPut('docs', wkId('d'), { project: g0.project, cp: g0.cp, party: g0.name, kind: b.getAttribute('data-wdc-add-kind'), status: 'wait' }, b.getAttribute('data-wdc-add-kind') + ' добавлен');
      return;
    }
    if ((b = ev.target.closest('[data-wdc-gdel]'))) {   // убрать контрагента из проекта — все его документы здесь; «Вернуть» — обратно
      var g1 = groups(docsAll()).filter(function (x) { return x.key === b.getAttribute('data-wdc-gdel'); })[0]; if (!g1) return;
      askConfirm('Убрать «' + g1.name + '» из документов' + (g1.project ? ' проекта «' + wkPname(g1.project) + '»' : '') + '?', 'Удалятся его документы здесь: ' + g1.docs.length + '. Сам контрагент останется в разделе «Контрагенты». Вернуть можно сразу на плашке внизу.', 'Убрать', function () {
        var keep = g1.docs.map(function (d) { var r = Object.assign({}, d); delete r.id; delete r.upd; return ['docs', d.id, r]; });
        g1.docs.forEach(function (d) { delete WK.docs[d.id]; }); render();
        var chain = Promise.resolve();
        g1.docs.forEach(function (d) { chain = chain.then(function () { return apiJson('POST', '/api/work', { op: 'del', kind: 'docs', id: d.id }).then(function (x) { if (x.ok) WK = x.d; }); }); });
        chain.then(function () { render(); wkSnack('«' + g1.name + '» убран из документов', function () { putSeq(keep, function () { toast('Возвращено'); }); }); });
      });
      return;
    }
    if ((b = ev.target.closest('[data-wdc-link]'))) {   // документы без контрагента (до 22.10) — завести контрагента по названию и привязать
      var g2 = groups(docsAll()).filter(function (x) { return x.key === b.getAttribute('data-wdc-link'); })[0]; if (!g2) return;
      var same = Object.keys(WK.parties || {}).filter(function (k) { return wksNorm(WK.parties[k].name) === wksNorm(g2.name); })[0], kid = same || wkId('k');
      var ops = (same ? [] : [['parties', kid, { name: g2.name }]]).concat(g2.docs.map(function (d) { var r = Object.assign({}, d, { cp: kid }); delete r.id; delete r.upd; return ['docs', d.id, r]; }));
      putSeq(ops, function () { toast('«' + g2.name + '» — в контрагентах; заполните ИНН, город и ЭДО в карточке'); partyOpen(kid); });
      return;
    }
    if ((b = ev.target.closest('[data-wdc-party]')) && !ev.target.closest('#pjDlg')) { partyOpen(b.getAttribute('data-wdc-party')); return; }
    if (ev.target.closest('[data-wdc-pnew]')) { partyOpen(null); return; }
    if ((b = ev.target.closest('[data-wdc-pfilter]'))) {
      if (WKPOP && WKPOP.anchor === b) { wkPopClose(); return; }
      var cf = S.wk.psf || '', it = function (v, t) { var on = cf === v; return '<button type="button" class="wk-menu-item' + (on ? ' on' : '') + '" data-wdc-psf="' + v + '" role="menuitemradio" aria-checked="' + on + '">' + t + (on ? WKT_ICON.check : '') + '</button>'; };
      wkPopOpen(b, 'wk-menu wdc-pfmenu', '<div class="wkp-title">Услуга</div>' + it('', 'Все контрагенты') + SERVICE.map(function (o) { return it(o[0], o[1]); }).join('') +
        '<div class="wkp-title wk-menu-sep">ЭДО</div>' + EDO.map(function (o) { return it('e:' + o[0], o[1]); }).join('') + it('e:', 'ЭДО не указано'), {});
      return;
    }
    if ((b = ev.target.closest('[data-wdc-psf]'))) { S.wk.psf = b.getAttribute('data-wdc-psf'); wkPopClose(); render(); }
  });
  function setDoc(id, patch, msg) { var d = WK.docs[id]; if (!d) return; var r = Object.assign({}, d, patch); delete r.upd; wkPut('docs', id, r, msg || ''); }
  // окно «Добавить контрагентов»
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest && ev.target.closest('#pjDlg [data-wdc-nrow-add],#pjDlg [data-wdc-nrow-del],#pjDlg [data-wdc-nsave],#pjDlg [data-wdc-venue]'); if (!b || !S.wk.wdcNew) return;
    newSync(); var rows = S.wk.wdcNew.rows;
    if (b.hasAttribute('data-wdc-nrow-add')) { rows.push(newRow()); newRefresh(rows.length - 1); }
    else if (b.hasAttribute('data-wdc-nrow-del')) { rows.splice(+b.getAttribute('data-wdc-nrow-del'), 1); newRefresh(); }
    else if (b.hasAttribute('data-wdc-venue')) {   // площадки гастролей — в пустые строки (не хватает — новые)
      var vid = b.getAttribute('data-wdc-venue'), list = vid === '*' ? showVenues(S.wk.wdcNew.pid) : [wkVenue(vid)];
      list.forEach(function (v) {
        if (!v) return; var cp = partyByVenue(v.id), it = cp ? { t: 'p', id: cp, name: WK.parties[cp].name } : { t: 'v', id: v.id, name: v.name || '' };
        var i = rows.findIndex(function (r) { return !r.name.trim(); }); if (i < 0) { rows.push(newRow()); i = rows.length - 1; }
        pickRow(i, it);
      });
      newRefresh();
    } else newSave();
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.matches && ev.target.matches('#pjDlg [name=wdc-proj]') && S.wk.wdcNew) { newSync(); newRefresh(); }
  });
  document.addEventListener('submit', function (ev) {   // Enter в строке — к следующей (последняя — новая строка)
    var f = ev.target.closest && ev.target.closest('#pjDlg .wdc-nrow'); if (!f) return;
    ev.preventDefault(); newSync();
    var i = +f.getAttribute('data-wdc-nrow'), rows = S.wk.wdcNew.rows;
    if (i === rows.length - 1) { rows.push(newRow()); newRefresh(i + 1); }
    else { var n = document.querySelector('#pjDlg [data-wdc-nrow="' + (i + 1) + '"] input[name=name]'); if (n) n.focus(); }
  });
  document.addEventListener('input', function (ev) {
    var t = ev.target; if (!t.closest) return;
    if (t.closest('#pjDlg .wdc-nrow') && t.name === 'name') {
      var f = t.closest('.wdc-nrow'), r = S.wk.wdcNew && S.wk.wdcNew.rows[+f.getAttribute('data-wdc-nrow')];
      if (r && r.pick) { r.pick = ''; f.elements.city.disabled = false; f.elements.service.disabled = false; }   // меняют название — связь снимается
      sugShow(t); return;
    }
    if (t.hasAttribute && t.hasAttribute('data-wdc-vfind')) {   // карточка нового: площадка из справочника
      var box = t.parentNode.querySelector('.wks-sug'), l = t.value.trim().length >= 2 && typeof VB_ROWS !== 'undefined' ? wksMatch(t.value) : [];
      box.innerHTML = l.map(function (v) { return '<button type="button" class="wks-opt" data-wdc-vpick="' + esc(v.id) + '"><b>' + esc(v.name || 'Без названия') + '</b><span>' + esc([v.city, v.inn ? 'ИНН ' + v.inn : ''].filter(Boolean).join(' · ')) + '</span></button>'; }).join('') || (t.value.trim().length >= 2 ? '<div class="wks-none">В справочнике не нашли.</div>' : '');
      box.hidden = !box.innerHTML; return;
    }
    if (t.hasAttribute && t.hasAttribute('data-wdc-pq')) { S.wk.pq = t.value; var pos = t.selectionStart; render(); var qi = document.querySelector('[data-wdc-pq]'); if (qi) { qi.focus({ preventScroll: true }); qi.setSelectionRange(pos, pos); } }
  });
  document.addEventListener('keydown', function (ev) {   // подсказки: стрелки, Enter, Esc
    var t = ev.target; if (!t.closest || !t.closest('#pjDlg .wdc-pick') || t.hasAttribute('data-wdc-vfind')) return;
    var box = t.parentNode.querySelector('.wks-sug'), opts = [].slice.call(box.querySelectorAll('.wks-opt')), cur = opts.findIndex(function (o) { return o.classList.contains('on'); });
    if (ev.key === 'Escape' && !box.hidden) { ev.preventDefault(); ev.stopPropagation(); box.hidden = true; return; }
    if (box.hidden || !opts.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault(); var nx = (cur + (ev.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length;
      opts.forEach(function (o, i) { o.classList.toggle('on', i === nx); o.setAttribute('aria-selected', String(i === nx)); }); opts[nx].scrollIntoView({ block: 'nearest' });
    } else if (ev.key === 'Enter' && cur >= 0) { ev.preventDefault(); sugPick(t.closest('.wdc-nrow'), opts[cur].getAttribute('data-wdc-pick')); }
  });
  document.addEventListener('mousedown', function (ev) {   // выбор мышью — до того, как поле потеряет фокус
    var o = ev.target.closest && ev.target.closest('#pjDlg [data-wdc-pick],#pjDlg [data-wdc-vpick]'); if (!o) return;
    ev.preventDefault();
    if (o.hasAttribute('data-wdc-pick')) { sugPick(o.closest('.wdc-nrow'), o.getAttribute('data-wdc-pick')); return; }
    var v = wkVenue(o.getAttribute('data-wdc-vpick')); if (!v) return;
    S.wk.wdcParty = partyFromVenue(v); partyRefresh();
  });
  document.addEventListener('focusout', function (ev) {
    var t = ev.target; if (!t.closest || !t.closest('#pjDlg .wdc-pick')) return;
    setTimeout(function () { var box = t.parentNode && t.parentNode.querySelector('.wks-sug'); if (box && document.activeElement !== t) box.hidden = true; }, 150);
  });
  // карточка контрагента: правка — сразу (у существующего), «Создать» — у нового
  document.addEventListener('change', function (ev) {
    var el = ev.target; if (!el.hasAttribute || !el.hasAttribute('data-wdcp-f')) return;
    var box = el.closest('.wdc-pcard'), id = box && box.getAttribute('data-wdc-pcard'); if (!box) return;
    if (!id) { S.wk.wdcParty[el.getAttribute('data-wdcp-f')] = el.value.trim(); return; }
    var p = WK.parties[id]; if (!p) return;
    var r = Object.assign({}, p, partyRead()); delete r.upd;
    if (!r.name) { toast('У контрагента нужно название'); el.value = p.name; return; }
    if (r.inn && !/^\d{10}(\d{2})?$/.test(r.inn.replace(/\s/g, ''))) { toast('ИНН — 10 или 12 цифр'); el.value = p.inn || ''; return; }
    if (JSON.stringify(Object.assign({}, p, { upd: '' })) === JSON.stringify(Object.assign({}, r, { upd: '' }))) return;
    wkPut('parties', id, r, '', true); S.wk.wdcDirty = true;
  });
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest && ev.target.closest('#pjDlg [data-wdcp-create],#pjDlg [data-wdcp-del]'); if (!b) return;
    if (b.hasAttribute('data-wdcp-create')) {
      var r = Object.assign({}, S.wk.wdcParty, partyRead());
      if (!r.name) { toast('Впишите название'); var n = document.querySelector('#pjDlg [data-wdcp-f=name]'); if (n) n.focus(); return; }
      if (r.inn && !/^\d{10}(\d{2})?$/.test(r.inn.replace(/\s/g, ''))) { toast('ИНН — 10 или 12 цифр'); return; }
      $('pjDlg').close(); wkPut('parties', wkId('k'), r, 'Контрагент «' + r.name + '» добавлен');
      return;
    }
    var id = b.closest('.wdc-pcard').getAttribute('data-wdc-pcard'), p = WK.parties[id]; if (!p) return;
    $('pjDlg').close(); wkDel('parties', id, 'Контрагент «' + p.name + '» удалён — документы остались с его названием');
  });
  document.addEventListener('click', function (ev) {   // из карточки: проект (вкладка «Документы») или площадка в справочнике
    var b = ev.target.closest && ev.target.closest('#pjDlg [data-wdcp-go],#pjDlg [data-wdcp-venue]'); if (!b) return;
    $('pjDlg').close();
    if (b.hasAttribute('data-wdcp-go')) {
      S.wk.from = S.view !== 'work' ? S.view : null; S.view = 'work'; location.hash = 'work'; S.enter = true;
      S.wk.y = window.scrollY; S.wk.proj = b.getAttribute('data-wdcp-go'); S.wk.ptab = 'docs'; S.wk.mcal = null; S.wk.scrollT = {}; S.wk.qs = { open: '', done: '' }; S.wk.qAt = {};
    } else { S.view = 'venues'; S.sub.venues = 'book'; S.enter = true; location.hash = 'venues'; S.vb.y = 0; S.vb.sel = b.getAttribute('data-wdcp-venue'); S.vb.all = false; S.colsOpen = false; }
    render(); window.scrollTo(0, 0);
  });
  document.addEventListener('keydown', function (ev) {   // строка контрагента — с клавиатуры
    if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.classList && ev.target.classList.contains('wdc-prow')) { ev.preventDefault(); partyOpen(ev.target.getAttribute('data-wdc-party')); }
  });

  root.WorkDocs = { table: table, tools: tools, renderDocsSection: renderDocsSection, renderParties: renderParties, refreshSums: refreshSums, ST: ST, SERVICE: SERVICE, EDO: EDO };
})(typeof window !== 'undefined' ? window : globalThis);
