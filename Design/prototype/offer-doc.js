// Документы предложения артисту и руководителю (CITY_PICK_PLAN.md, п. 2.6 и 2.8; решения пользователя 26.10.2026).
// Один снимок (offerSnapshot в index.html) рисуется и в окне для печати (PDF), и на странице ссылки для руководителя
// (share_app.py вставляет этот файл в страницу) — цифры в PDF и по ссылке одинаковые.
//
// Снимок: {v, list, title, who, period, created, econ: [[подпись, значение]…], rows: [город…]}; город:
//   {city, reg, dec: yes | maybe, venue, seats, price, priceNote, need, sales, total, profit, be, beShare, status, margin}
// Тест — tests/offer-doc.test.js (node --test).
var OFFER_DEC = { yes: "Подходит", maybe: "На рассмотрении" };
var OFFER_ST = { ok: "окупается", edge: "на грани", no: "не окупается", nohall: "нет зала", noprice: "нет цен" };
var OFFER_CSS = 'body{font:14px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1c1917;background:#fff;margin:0;padding:28px 32px;max-width:1120px}' +
  'h1{font-size:22px;margin:0 0 4px}h3{font-size:15px;margin:18px 0 6px}.sub{color:#57534e;margin:0 0 16px}' +
  '.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:10px 0 16px}th,td{border-bottom:1px solid #e7e5e4;padding:6px 8px;text-align:left;vertical-align:top}' +
  'th{font-size:12px;color:#57534e;font-weight:600}.r{text-align:right;white-space:nowrap}.neg{color:#b42318}.ok{color:#15803d}.edge{color:#b45309}.no{color:#b42318}.muted{color:#78716c;font-size:12px}' +
  'tr.grp td{background:#f5f5f4;font-weight:600}.ed{border:1px dashed #d6d3d1;border-radius:8px;padding:10px 12px;margin:10px 0;min-height:1.5em}.ed:focus{outline:2px solid #1d6fae}' +
  '.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:4px 24px;margin:6px 0 12px}.kv div{display:flex;justify-content:space-between;gap:8px;border-bottom:1px dotted #e7e5e4;padding:3px 0}' +
  '.bar{position:sticky;top:0;z-index:3;background:#fff;padding:8px 0 12px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}' +
  'button{font:inherit;padding:8px 16px;border-radius:9999px;border:1px solid #1c1917;background:#1c1917;color:#fff;cursor:pointer}.hint{color:#78716c;font-size:12px}' +
  '@media (max-width:640px){body{padding:16px}}@media print{.bar,.noprint{display:none!important}.ed{border:0;padding:0}body{padding:0}}';

function ofEsc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
function ofNum(n) { return n == null || !isFinite(n) ? "—" : Math.round(n).toLocaleString("ru-RU"); }
function ofMoney(n) { return n == null || !isFinite(n) ? "—" : ofNum(n) + " ₽"; }
function ofHas(r) { return r.status === "ok" || r.status === "edge" || r.status === "no"; }
function ofMargin(r) { return r.margin == null ? "" : " · " + (r.margin >= 0 ? "+" : "−") + Math.abs(Math.round(r.margin * 100)) + "%"; }

// Итоги по городам, где есть расчёт: число, окупается / на грани / нет, сборы, расходы, прибыль
function offerTotals(rows) {
  var t = { n: rows.length, ok: 0, edge: 0, no: 0, sales: 0, total: 0, profit: 0 };
  rows.forEach(function (r) { if (!ofHas(r)) return; t[r.status]++; t.sales += r.sales || 0; t.total += r.total || 0; t.profit += r.profit || 0; });
  return t;
}

// Тело документа (без <html>). kind: "artist" — города и залы без экономики (o.maybe — с «на рассмотрении»);
// "boss" — с экономикой. o.share — страница руководителя: у каждого города и внизу пустые места [data-mgr] под
// решение и комментарии (их заполняет скрипт страницы), поля «правьте здесь» не нужны.
function offerDocBody(snap, kind, o) {
  o = o || {};
  var rows = (snap.rows || []).filter(function (r) { return r.dec === "yes" || (r.dec === "maybe" && (kind === "boss" || o.maybe)); });
  var when = snap.created ? new Date(snap.created).toLocaleString("ru-RU", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  if (kind === "artist") {
    return '<h1>Предложение по городам</h1><p class="sub">' + ofEsc(snap.who) + ' · период: ' + ofEsc(snap.period) + (when ? ' · ' + ofEsc(when) : '') + '</p>' +
      '<div class="ed" contenteditable="true">Добрый день! Предлагаем города для концертов в период «' + ofEsc(snap.period) + '». Залы ниже — предварительные; даты и площадки подтверждаем после вашего согласия.</div>' +
      '<div class="tw"><table><thead><tr><th>№</th><th>Город</th><th>Область</th><th>Площадка</th><th class="r">Мест</th></tr></thead><tbody>' +
      rows.map(function (r, i) { return '<tr><td>' + (i + 1) + '</td><td>' + ofEsc(r.city) + '</td><td>' + ofEsc(r.reg) + '</td><td>' + ofEsc(r.venue || "уточняется") + '</td><td class="r">' + (r.seats ? ofNum(r.seats) : "—") + '</td></tr>'; }).join("") +
      '</tbody></table></div><div class="ed" contenteditable="true">Контакт: </div>';
  }
  var yes = rows.filter(function (r) { return r.dec === "yes"; }), maybe = rows.filter(function (r) { return r.dec === "maybe"; });
  var ty = offerTotals(yes), ta = offerTotals(rows);
  var kv = function (a, b) { return '<div><span>' + a + '</span><b>' + b + '</b></div>'; };
  var tot = function (label, t) { return kv(label, t.n + ' · прибыль <span class="' + (t.profit < 0 ? 'neg' : 'ok') + '">' + ofMoney(t.profit) + '</span>'); };
  var low = rows.filter(function (r) { return r.priceNote === "мало данных"; }).map(function (r) { return r.city; });
  var nod = rows.filter(function (r) { return !ofHas(r); }).map(function (r) { return r.city; });
  var cols = '<tr><th>№</th><th>Город</th><th>Зал</th><th class="r">Мест</th><th class="r">Цена города</th><th class="r">Нужна цена</th><th class="r">Сборы</th><th class="r">Расходы</th><th class="r">Прибыль</th><th class="r">В ноль</th><th>Окупаемость</th>' + (o.share ? '' : '<th>Решение</th>') + '</tr>';
  var n = 0, line = function (r) {
    var h = ofHas(r);
    return '<tr><td>' + (++n) + '</td><td>' + ofEsc(r.city) + '<div class="muted">' + ofEsc(r.reg) + '</div></td><td>' + ofEsc(r.venue || "—") + '</td><td class="r">' + (r.seats ? ofNum(r.seats) : "—") + '</td>' +
      '<td class="r">' + ofMoney(r.price) + (r.priceNote ? '<div class="muted">' + ofEsc(r.priceNote) + '</div>' : '') + '</td><td class="r">' + (h ? ofMoney(r.need) : "—") + '</td>' +
      '<td class="r">' + (h ? ofMoney(r.sales) : "—") + '</td><td class="r">' + (h ? ofMoney(r.total) : "—") + '</td><td class="r' + (h && r.profit < 0 ? ' neg' : '') + '">' + (h ? ofMoney(r.profit) : "—") + '</td>' +
      '<td class="r">' + (h && r.be != null ? ofNum(Math.ceil(r.be)) + ' бил. · ' + Math.round(r.beShare * 100) + '%' : "—") + '</td>' +
      '<td class="' + ofEsc(r.status) + '">' + (OFFER_ST[r.status] || "—") + ofMargin(r) + '</td>' + (o.share ? '' : '<td contenteditable="true"></td>') + '</tr>' +
      (o.share ? '<tr class="noprint"><td></td><td colspan="10" data-mgr="' + ofEsc(r.city) + '"></td></tr>' : '');
  };
  var grp = function (label, list) { return list.length ? '<tr class="grp"><td colspan="' + (o.share ? 11 : 12) + '">' + label + ' · ' + list.length + '</td></tr>' + list.map(line).join("") : ''; };
  return '<h1>На согласование: ' + ofEsc(snap.who) + '</h1><p class="sub">Подбор городов · период: ' + ofEsc(snap.period) + (when ? ' · версия от ' + ofEsc(when) : '') + '</p>' +
    '<div class="kv">' + tot("Подходит", ty) + (maybe.length ? tot("Вместе с «на рассмотрении»", ta) : '') + kv("Сборы / расходы (подходит)", ofMoney(ty.sales) + " / " + ofMoney(ty.total)) +
      kv("Окупается / на грани / нет", ty.ok + " / " + ty.edge + " / " + ty.no) + '</div>' +
    '<h3>Допущения</h3><div class="kv">' + (snap.econ || []).map(function (e) { return kv(ofEsc(e[0]), ofEsc(e[1])); }).join("") + '</div>' +
    '<p class="hint">Цена города — по гастролям этого формата в нашей афише и архиве; аренда, реклама, дорога, райдер — нормы, если не вписаны. Наша афиша видит около 40 % мероприятий площадок, которые продают билеты сами.</p>' +
    '<div class="tw"><table><thead>' + cols + '</thead><tbody>' + grp(OFFER_DEC.yes, yes) + grp(OFFER_DEC.maybe, maybe) + '</tbody></table></div>' +
    (low.length || nod.length ? '<h3>Риски</h3><ul>' + (low.length ? '<li>Мало данных о ценах (область или 1–2 гастроли): ' + ofEsc(low.join(", ")) + '</li>' : '') + (nod.length ? '<li>Нет данных о зале или ценах — не посчитано: ' + ofEsc(nod.join(", ")) + '</li>' : '') + '</ul>' : '') +
    (o.share ? '<h3>Общий комментарий</h3><div data-mgr=""></div>' : '<h3>Комментарий руководителя</h3><div class="ed" contenteditable="true"></div>');
}

if (typeof module !== "undefined") module.exports = { OFFER_DEC: OFFER_DEC, OFFER_ST: OFFER_ST, OFFER_CSS: OFFER_CSS, offerTotals: offerTotals, offerDocBody: offerDocBody, ofEsc: ofEsc };
