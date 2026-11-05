// Экспорт тура: один снимок разрешённых входов и расчётов для PDF и рабочего Excel.
var TE_MODEL = typeof module !== "undefined" ? require("./plan-model.js") : null;
function teEsc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
function teNum(n) { return n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("ru-RU", {maximumFractionDigits:0}); }
function teMoney(n) { return teNum(n) + (n == null ? "" : " ₽"); }
function tePct(n) { return n == null ? "—" : (n * 100).toLocaleString("ru-RU", {maximumFractionDigits:1}) + "%"; }
function teRate(n) { return n.toLocaleString("ru-RU", {maximumFractionDigits:4}) + "%"; }
function tourExportSnapshot(tour, meta, resolve) {
  var rows = (tour.rows || []).filter(function (r) { return meta.rowIds == null || meta.rowIds.indexOf(r.id) >= 0; });
  if (!rows.length) throw new Error("Для экспорта нет строк. Проверьте выделение.");
  var cfg = JSON.parse(JSON.stringify(meta.cfg)), calc = TE_MODEL ? TE_MODEL.planCalc : planCalc;
  return {version:1, title:tour.title, project:meta.project || "", month:tour.month || "", created:meta.created || new Date().toISOString(),
    scenario:meta.scenario || "По строкам", cfg:cfg, options:{details:meta.details !== false, zones:!!meta.zones},
    rows:rows.map(function (r) {
      var input = JSON.parse(JSON.stringify(resolve(r)));
      return {id:r.id, city:r.city || "Город не выбран", venue:r.venue ? r.venue.split("|").slice(1).join("|") : "Площадка не выбрана",
        date:r.date || "", note:r.note || "", decision:r.decision || "", mode:input.zones && input.zones.length ? "Распоясовка" : r.avg != null ? "Средняя цена" : "Вал",
        input:input, calc:calc(input,cfg)};
    })};
}
function tourExportGroups(row, cfg) {
  var x = row.input, c = row.calc, n = TE_MODEL ? TE_MODEL.planNum : planNum, org = TE_MODEL ? TE_MODEL.PLAN_ORG : PLAN_ORG;
  var extra = function (g) { return (g === "ads" ? x.ad_items || [] : (x.cost_items || {})[g] || []).map(function (a) {
    return {label:a.name || "Своя статья", rate:g === "variable" ? n(a.amount) : null, sum:g === "variable" ? c.sales * n(a.amount) / 100 : n(a.amount)};
  }); };
  var item = function (label, sum, rate, note) { return {label:label,sum:sum,rate:rate,note:note}; };
  return [
    {key:"variable",title:"Переменные",sum:c.variable,items:[item("РАО / ВОИС",x.rao_on ? c.sales*n(x.rao)/100 : 0,x.rao_on ? n(x.rao) : 0,x.rao_on ? "" : "Выключено"),
      item("Налог",c.sales*n(cfg.tax)/100,n(cfg.tax)),item("Комиссия касс",c.sales*n(x.kassa)/100,n(x.kassa)),item("Агентские",c.sales*n(x.agent)/100,n(x.agent))].concat(extra("variable"))},
    {key:"project",title:"Проектные",sum:c.project.total,items:[item("Гонорар",c.project.fee),item("Безналичная оплата",c.project.cashless,n(x.cashless),"От гонорара"),
      item("Суточные",c.project.per_diem,null,x.per_diem_sum != null ? "Сумма на город" : teNum(n(x.per_diem))+" ₽ × "+n(x.crew)+" чел. × "+n(x.days)+" дн."),
      item("Авторские",c.project.author),item("Московские расходы",c.project.moscow,null,teMoney(n(x.moscow))+" на тур ÷ "+Math.max(1,n(x.cities))+" строк")].concat(extra("project"))},
    {key:"org",title:"Организационные",sum:c.org,items:org.map(function (o) { return item(o[1],n((x.org || {})[o[0]])); }).concat(extra("org"))},
    {key:"rent",title:"Аренда",sum:c.rent+c.venue_services,items:[item("Аренда площадки",n(x.rent)),item("Службы площадки",c.venue_services)].concat(extra("rent"))},
    {key:"logistics",title:"Логистика",sum:c.logistics,items:[item("Логистика",n(x.logistics))].concat(extra("logistics"))},
    {key:"ads",title:"Реклама",sum:c.ads,items:[item("Рекламный бюджет",n(x.ads))].concat(extra("ads"))}
  ];
}
var TOUR_EXPORT_CSS = 'body{font:12px/1.4 Arial,sans-serif;color:#201d1b;margin:0}h1{font-size:24px;margin:0 0 8px}h2{font-size:19px;margin:0}p{margin:8px 0 14px}.muted{color:#716c68}.neg{color:#bc2315}.num{text-align:right;font-variant-numeric:tabular-nums}table{width:100%;border-collapse:collapse}th,td{padding:7px 8px;border-bottom:1px solid #e8e5e2;vertical-align:top}thead{display:table-header-group}thead th{font-size:11px;text-align:left;background:#f5f4f2}tr{break-inside:avoid}tfoot{display:table-row-group;font-weight:bold}.group td{background:#f0f4f7;font-weight:bold}.group{break-after:avoid}.total{font-weight:bold;background:#f5f4f2}.summary{page:summary}.city{page:city;break-before:page}.city-title{text-align:left;background:white;padding:0 0 14px}.metrics{font-weight:normal;margin:8px 0;font-size:11px}.metrics span{display:inline-block;margin:0 16px 5px 0}.note{white-space:pre-wrap;overflow-wrap:anywhere}.summary td{font-size:10px}.city td{font-size:11px}.summary th{font-size:10px}th,td{overflow-wrap:anywhere}.zones{margin-top:16px}@page summary{size:A4 landscape;margin:12mm 10mm}@page city{size:A4 portrait;margin:12mm 10mm}';
TOUR_EXPORT_CSS += '.city th,.city td{padding:5px 7px;font-size:10.5px;line-height:1.3}.city .city-title{background:white;font-weight:bold;padding:8px 7px}.city h2{margin:0 0 4px}.city .metrics{margin:8px 0 12px}';
TOUR_EXPORT_CSS += '.summary .num{white-space:nowrap}.summary th,.summary td{padding:6px 5px}.metrics-table{margin:12px 0 18px;break-inside:avoid}.metrics-table td:first-child{width:64%;color:#625d58}.metrics-table td:last-child{width:36%;font-size:11.5px}.metrics-table .key td{font-weight:bold;color:#201d1b;background:#f6f8fa}.group-total{break-before:avoid}.group-total td{font-weight:bold;background:#fafaf9;border-top:1px solid #d6d2ce}';
function tourExportHtml(snap) {
  var sums = {seats:0,gross:0,sales:0,total:0,profit:0}; snap.rows.forEach(function (r) { Object.keys(sums).forEach(function (k) { sums[k] += r.calc[k]; }); });
  var meta = teEsc(snap.project) + (snap.month ? " · " + teEsc(snap.month) : "") + " · " + teEsc(snap.scenario) + " · " + teEsc(new Date(snap.created).toLocaleString("ru-RU"));
  var html = '<section class="summary"><h1>Смета: '+teEsc(snap.title)+'</h1><p class="muted">'+meta+'</p><p>'+snap.rows.length+' строк · Вал <b>'+teMoney(sums.gross)+'</b> · Сборы <b>'+teMoney(sums.sales)+'</b> · Расходы <b>'+teMoney(sums.total)+'</b> · Прибыль <b>'+teMoney(sums.profit)+'</b></p>'+
    '<table><thead><tr>'+['Город / площадка','Дата','Мест','Средняя цена билета, ₽','Аншлаг, %','Вал, ₽','Сборы, ₽','Расходы, ₽','Прибыль, ₽','Рентаб., %','ТБУ продаж, ₽','ТБУ, бил.','ТБУ, %'].map(function (s) { return '<th>'+s+'</th>'; }).join('')+'</tr></thead><tbody>'+
    snap.rows.map(function (r) { var c=r.calc; return '<tr><td><b>'+teEsc(r.city)+'</b><br>'+teEsc(r.venue)+'</td><td>'+teEsc(r.date || '—')+'</td>'+[teNum(c.seats),teNum(c.avg),tePct(c.fillEff/100),teNum(c.gross),teNum(c.sales),teNum(c.total),teNum(c.profit),tePct(c.ros),teNum(c.beRub),teNum(c.beTickets == null ? null : Math.ceil(c.beTickets)),tePct(c.beShare)].map(function (s) { return '<td class="num">'+s+'</td>'; }).join('')+'</tr>'; }).join('')+
    '</tbody><tfoot><tr><td colspan="2">Итого / средняя</td><td class="num">'+teNum(sums.seats)+'</td><td class="num">'+teNum(sums.seats ? sums.gross/sums.seats : null)+'</td><td class="num">'+tePct(sums.gross ? sums.sales/sums.gross : null)+'</td><td class="num">'+teNum(sums.gross)+'</td><td class="num">'+teNum(sums.sales)+'</td><td class="num">'+teNum(sums.total)+'</td><td class="num">'+teNum(sums.profit)+'</td><td colspan="4"></td></tr></tfoot></table></section>';
  if (snap.options.details || snap.options.zones) html += snap.rows.map(function (r,i) {
    var c=r.calc, metrics=[['Мест в продаже',teNum(c.seats)],['Средняя цена билета',teMoney(c.avg)],['Вал площадки',teMoney(c.gross)],['Заполняемость',tePct(c.fillEff/100)],['Сборы',teMoney(c.sales),true],['Итоговые расходы',teMoney(c.total),true],['Прибыль',teMoney(c.profit),true],['Класс',c.cls],['Рентабельность продаж',tePct(c.ros)],['Окупаемость затрат',tePct(c.roi)],['Эффективность слота',tePct(c.eff)],['ТБУ продаж',teMoney(c.beRub)],['ТБУ, билетов',teNum(c.beTickets == null ? null : Math.ceil(c.beTickets))],['ТБУ, % от аншлага',tePct(c.beShare)],['Цель прибыли',teMoney(c.target)],['Продать для цели, билетов',teNum(c.tgTickets == null ? null : Math.ceil(c.tgTickets))]];
    var body='<section class="city"><h2>'+(i+1)+'. '+teEsc(r.city)+'</h2><div>'+teEsc(r.venue)+(r.date?' · '+teEsc(r.date):'')+'</div><table class="metrics-table"><thead><tr><th>Показатель</th><th class="num">Значение</th></tr></thead><tbody>'+metrics.map(function (a) { return '<tr'+(a[2]?' class="key"':'')+'><td>'+teEsc(a[0])+'</td><td class="num">'+teEsc(a[1])+'</td></tr>'; }).join('')+'</tbody></table><table><thead><tr><th colspan="3" class="city-title">'+teEsc(r.city)+' · '+teEsc(r.venue)+'</th></tr><tr><th>Статья</th><th>Ставка / основание</th><th class="num">Сумма, ₽</th></tr></thead><tbody>';
    (snap.options.details ? tourExportGroups(r,snap.cfg) : []).forEach(function (g) {
      body+='<tr class="group"><td colspan="3">'+g.title+'</td></tr>';
      g.items.forEach(function (a) { body+='<tr><td>'+teEsc(a.label)+'</td><td class="muted">'+(a.rate != null ? teRate(a.rate)+' ' : '')+teEsc(a.note || '')+'</td><td class="num">'+teNum(a.sum)+'</td></tr>'; });
      body+='<tr class="group-total"><td colspan="2">Итого '+g.title.toLowerCase()+'</td><td class="num">'+teNum(g.sum)+'</td></tr>';
    });
    body+='<tr class="total"><td colspan="2">Итоговые расходы</td><td class="num">'+teNum(c.total)+'</td></tr><tr class="total"><td colspan="2">Прибыль</td><td class="num">'+teNum(c.profit)+'</td></tr></tbody></table>';
    if(snap.options.zones && c.zones) body+='<table class="zones"><thead><tr><th colspan="6">Распоясовка · '+teEsc(r.city)+' · '+teEsc(r.venue)+'</th></tr><tr><th>Пояс</th><th>Цена, ₽</th><th>Билетов</th><th>Аншлаг, %</th><th>Вал, ₽</th><th>Сборы, ₽</th></tr></thead><tbody>'+c.zones.map(function(z){return '<tr><td>'+teEsc(z.name)+'</td>'+[teNum(z.price),teNum(z.seats),tePct(z.fill/100),teNum(z.gross),teNum(z.sales)].map(function(s){return '<td class="num">'+s+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table>';
    if(r.decision || r.note) body+='<p class="note">'+teEsc([r.decision,r.note].filter(Boolean).join('\n'))+'</p>';
    return body+'</section>';
  }).join('');
  return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>'+teEsc('Смета — '+snap.title)+'</title><style>'+TOUR_EXPORT_CSS+'</style></head><body>'+html+'</body></html>';
}
if(typeof module !== "undefined") module.exports={tourExportSnapshot:tourExportSnapshot,tourExportGroups:tourExportGroups,tourExportHtml:tourExportHtml};
