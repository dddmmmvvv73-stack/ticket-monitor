// «Планирование → Построение гастрольного маршрута» (решения пользователя 16–19.10.2026): свободные даты площадок на месяц
// («Город — Площадка — числа») → варианты маршрута день за днём. Подключается в index.html после tour-parse.js; тест —
// tests/route-plan.test.js (node --test) на примере пользователя (Воронеж, Кострома, Подольск, Электросталь, Выкса).
//
// Правила (решения пользователя):
//   - каждый день — выступление, даты идут подряд; выходные — редкость: отдельный режим (gaps — выходных подряд не больше);
//   - один город — одно выступление; переезд между соседними городами — не больше limit км (600; по прямой × 1,3);
//   - выезд из базы (Москва) и возвращение туда же; к выезду и возвращению лимит не применяется, в км варианта — входят;
//   - лучший не выбираем: сначала полные (все города списка), ниже неполные; внутри — меньше выходных, раньше старт,
//     меньше км; показываем 20;
//   - пары городов, которые подряд не поставить (дальше лимита), — отдельно, с кандидатами «город-связка» посередине.
// Расстояния — снаружи (opts.km): страница считает по координатам городов.
(function (root) {
  var findCity = root.tpFindCity || (typeof require !== "undefined" ? require("./tour-parse.js").tpFindCity : null);
  var MONTHS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"];
  var M_WORD = /(январ|феврал|март|апрел|ма[йяюе]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*/i;
  var SEP = /\s+[-–—]\s*|\s*[–—]\s+|\s*[–—]\s*(?=\d)|\s+-(?=\s|\d)/;   // « - », «—»; дефис внутри названия (Ростов-на-Дону) — не разделитель

  function norm(s) { return String(s || "").toLowerCase().replace(/ё/g, "е"); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function monthNo(w) { var x = norm(w); for (var i = 0; i < 12; i++) if (x.indexOf(MONTHS[i]) === 0 && (i !== 4 || /^ма[йяюе]/.test(x))) return i + 1; return 0; }
  function daysIn(ym) { var d = new Date(Date.UTC(+ym.slice(0, 4), +ym.slice(5, 7), 0)); return d.getUTCDate(); }

  // «58» → [5, 8]; «910» → [9, 10]; «1011» → [10, 11]: пропущенная запятая. Разбиение — на числа 1–31 по возрастанию,
  // меньше всего частей. Число 1–31 само по себе («12») не делим.
  function splitDays(tok) {
    var n = +tok;
    if (tok[0] !== "0" && n >= 1 && n <= 31) return { days: [n], fix: false };
    var best = null;
    (function go(rest, acc) {
      if (!rest) { if (!best || acc.length < best.length) best = acc.slice(); return; }
      for (var k = 1; k <= 2 && k <= rest.length; k++) {
        var part = rest.slice(0, k), v = +part;
        if (part[0] === "0" || v < 1 || v > 31 || (acc.length && v <= acc[acc.length - 1])) continue;
        acc.push(v); go(rest.slice(k), acc); acc.pop();
      }
    })(tok, []);
    return best ? { days: best, fix: true } : { days: [], fix: true, bad: true };
  }
  function parseDays(s) {
    var out = [], fixes = [], bad = [];
    String(s || "").replace(/(\d+)\s*[-–]\s*(\d+)|\d+/g, function (m, a, b) {
      if (a) { var x = +a, y = +b; if (x >= 1 && y <= 31 && x <= y) { for (var d = x; d <= y; d++) out.push(d); } else bad.push(m); return m; }
      var r = splitDays(m);
      if (r.bad) bad.push(m); else { if (r.fix) fixes.push("«" + m + "» → " + r.days.join(", ")); out.push.apply(out, r.days); }
      return m;
    });
    out = out.filter(function (d, i, a) { return a.indexOf(d) === i; }).sort(function (a, b) { return a - b; });
    return { days: out, fixes: fixes, bad: bad };
  }
  function nextYm(mo, today) {   // месяц без года — ближайший: этот год, если месяц ещё не прошёл, иначе следующий
    var ty = +today.slice(0, 4), tm = +today.slice(5, 7);
    return (mo < tm ? ty + 1 : ty) + "-" + pad(mo);
  }

  // Текст → {month: "ГГГГ-ММ" из шапки «Даты по февралю» (или ""), rows: [{city, raw, found, venue, days, fixes, bad, line}],
  //          issues: [строки-предупреждения]}
  function rpParse(text, opts) {
    opts = opts || {};
    var today = opts.today || new Date().toISOString().slice(0, 10), rows = [], issues = [], month = "";
    String(text || "").split(/\r?\n/).forEach(function (line) {
      var raw = line.replace(/\s+/g, " ").trim();
      if (!raw) return;
      var m = M_WORD.exec(raw);
      if (m && !/\d/.test(raw.replace(/\d{4}/, ""))) { if (!month) { var y = /\d{4}/.exec(raw); month = y ? y[0] + "-" + pad(monthNo(m[0])) : nextYm(monthNo(m[0]), today); } return; }   // «Даты по февралю:»
      var parts = raw.split(SEP).map(function (x) { return x.trim(); }).filter(Boolean);
      if (parts.length < 2) { issues.push("не разобрана строка: «" + raw + "»"); return; }
      var dayPart = parts[parts.length - 1], city = parts[0], venue = parts.length > 2 ? parts.slice(1, -1).join(" — ") : "";
      if (!/\d/.test(dayPart)) { issues.push("нет дат: «" + raw + "»"); return; }
      var d = parseDays(dayPart), f = findCity && opts.cities ? findCity(city, opts.cities) : null;
      var r = { city: f ? f.city : city, raw: city, found: !!f, venue: venue.replace(/[.;,]+$/, ""), days: d.days, fixes: d.fixes, bad: d.bad, line: raw };
      if (f && f.fix) r.fixes.unshift("«" + f.raw + "» → " + f.city);
      rows.push(r);
    });
    // одна площадка у двух городов — похоже на ошибку копирования
    var byVenue = {};
    rows.forEach(function (r) { var k = norm(r.venue).replace(/[«»"'.\s]/g, ""); if (!k) return; (byVenue[k] = byVenue[k] || []).push(r); });
    Object.keys(byVenue).forEach(function (k) {
      var l = byVenue[k], cs = l.map(function (r) { return r.city; }).filter(function (c, i, a) { return a.indexOf(c) === i; });
      if (cs.length > 1) { issues.push("одна площадка у разных городов: «" + l[0].venue + "» — " + cs.join(" и ") + " (проверьте)"); l.forEach(function (r) { r.dupVenue = true; }); }
    });
    var seen = {};
    rows.forEach(function (r) { if (seen[r.city]) { issues.push("город дважды: " + r.city + " — даты объединены, одно выступление"); r.dupCity = true; } seen[r.city] = 1; });
    rows.forEach(function (r) { if (!r.found) issues.push("город не найден в справочнике: «" + r.raw + "» — нет на карте и в расчёте км"); });
    return { month: month, rows: rows, issues: issues };
  }

  // Варианты маршрута. rows — из rpParse (выбранный месяц — opts.month); opts: km(a, b) (null — неизвестно), limit, gaps
  // (выходных подряд; 0 — без выходных), onlyOff (только варианты с выходными — режим «С выходными»), base («Москва»),
// top (20), maxNodes.
  function rpRoutes(rows, opts) {
    var km = opts.km, limit = opts.limit || 600, gaps = opts.gaps || 0, base = opts.base || "", top = opts.top || 20, maxNodes = opts.maxNodes || 400000;
    var C = [], byName = {};
    rows.forEach(function (r) {
      if (!r.found || !r.days.length) return;
      var c = byName[r.city];
      if (!c) { c = byName[r.city] = { city: r.city, venue: r.venue, days: {} }; C.push(c); }
      r.days.forEach(function (d) { c.days[d] = 1; });
    });
    var N = C.length, D = daysIn(opts.month), hop = [], avail = [];
    for (var i = 0; i < N; i++) { hop.push([]); for (var j = 0; j < N; j++) { var k = i === j ? null : km(C[i].city, C[j].city); hop[i].push(k != null && k <= limit ? k : null); } }
    for (var d = 1; d <= D; d++) avail[d] = C.map(function (c, i) { return c.days[d] ? i : -1; }).filter(function (i) { return i >= 0; });
    var out = [], nodes = 0, cut = false, used = new Array(N).fill(false);
    function canPrepend(first) {   // цепочку можно начать раньше — значит, это хвост более длинной (её найдём с того старта)
      for (var dd = first.d - 1; dd >= Math.max(1, first.d - 1 - gaps); dd--)
        for (var q = 0; q < (avail[dd] || []).length; q++) { var i2 = avail[dd][q]; if (!used[i2] && hop[i2][first.i] != null) return true; }
      return false;
    }
    function dfs(chain) {
      if (++nodes > maxNodes) { cut = true; return; }
      var last = chain[chain.length - 1], ext = false;
      for (var dd = last.d + 1; dd <= Math.min(D, last.d + 1 + gaps); dd++) {
        for (var q = 0; q < avail[dd].length; q++) {
          var i2 = avail[dd][q];
          if (used[i2] || hop[last.i][i2] == null) continue;
          ext = true; used[i2] = true; chain.push({ i: i2, d: dd }); dfs(chain); chain.pop(); used[i2] = false;
          if (cut) return;
        }
      }
      if (!ext && !canPrepend(chain[0])) out.push(chain.slice());
    }
    for (d = 1; d <= D && !cut; d++) avail[d].forEach(function (i0) { if (cut) return; used[i0] = true; dfs([{ i: i0, d: d }]); used[i0] = false; });
    var res = out.map(function (ch) {
      var stops = ch.map(function (s) { return { city: C[s.i].city, venue: C[s.i].venue, day: s.d, date: opts.month + "-" + pad(s.d) }; });
      var hops = [], kmSum = 0, maxHop = 0, off = 0;
      for (var x = 1; x < ch.length; x++) { var h = hop[ch[x - 1].i][ch[x].i]; hops.push(h); kmSum += h; maxHop = Math.max(maxHop, h); off += ch[x].d - ch[x - 1].d - 1; }
      var out0 = base ? km(base, stops[0].city) : null, back = base ? km(stops[stops.length - 1].city, base) : null;
      return { stops: stops, hops: hops, n: ch.length, full: ch.length === N, off: off, start: ch[0].d, km: kmSum + (out0 || 0) + (back || 0), tourKm: kmSum, maxHop: maxHop, fromBase: out0, toBase: back };
    });
    if (opts.onlyOff) res = res.filter(function (r) { return r.off > 0; });
    res.sort(function (a, b) { return b.n - a.n || a.off - b.off || a.start - b.start || a.km - b.km; });
    return { list: res.slice(0, top), total: res.length, full: res.filter(function (r) { return r.full; }).length, cities: N, cut: cut };
  }

  // Пары городов списка, которые подряд не поставить (дальше лимита), — кандидаты «город-связка» посередине.
  // opts: km, limit, month, candidates (названия городов), pop(c) — жителей, perPair (8), maxPairs (10)
  function rpBridges(rows, opts) {
    var km = opts.km, limit = opts.limit || 600, C = {}, list = [];
    rows.forEach(function (r) { if (r.found && r.days.length) { var c = C[r.city] = C[r.city] || { city: r.city, days: {} }; r.days.forEach(function (d) { c.days[d] = 1; }); } });
    var names = Object.keys(C), own = {}; names.forEach(function (n) { own[n] = 1; }); if (opts.base) own[opts.base] = 1;
    for (var a = 0; a < names.length; a++) for (var b = a + 1; b < names.length; b++) {
      var A = C[names[a]], B = C[names[b]], ab = km(A.city, B.city);
      if (ab == null || ab <= limit) continue;
      var combos = [];   // даты, между которыми 1–3 дня — под город-связку (1 день — связка встаёт ровно подряд)
      Object.keys(A.days).forEach(function (x) { Object.keys(B.days).forEach(function (y) {
        x = +x; y = +y;
        if (y - x >= 2 && y - x <= 4) combos.push({ from: A.city, d1: x, to: B.city, d2: y, between: y - x - 1 });
        else if (x - y >= 2 && x - y <= 4) combos.push({ from: B.city, d1: y, to: A.city, d2: x, between: x - y - 1 });
      }); });
      combos.sort(function (p, q) { return p.between - q.between || p.d1 - q.d1; });
      var cands = [];
      (opts.candidates || []).forEach(function (c) {
        if (own[c]) return;
        var p = km(A.city, c); if (p == null || p > limit) return;
        var q = km(c, B.city); if (q == null || q > limit) return;
        cands.push({ city: c, a: p, b: q, detour: p + q - ab, pop: opts.pop ? opts.pop(c) : null });
      });
      cands.sort(function (p, q) { return p.detour - q.detour || (q.pop || 0) - (p.pop || 0); });
      list.push({ a: A.city, b: B.city, km: ab, combos: combos.slice(0, 6), cands: cands.slice(0, opts.perPair || 8), oneCity: ab <= 2 * limit });
    }
    list.sort(function (p, q) { return (q.combos.length ? 1 : 0) - (p.combos.length ? 1 : 0) || p.km - q.km; });
    return list.slice(0, opts.maxPairs || 10);
  }

  root.rpParse = rpParse; root.rpRoutes = rpRoutes; root.rpBridges = rpBridges; root.rpParseDays = parseDays;
  if (typeof module !== "undefined" && module.exports) module.exports = { rpParse: rpParse, rpRoutes: rpRoutes, rpBridges: rpBridges, rpParseDays: parseDays };
})(typeof window !== "undefined" ? window : this);
