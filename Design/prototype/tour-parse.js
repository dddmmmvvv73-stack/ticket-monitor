// Разбор списка гастролей от продюсера («Планирование → Построение гастролей», запрос пользователя 13.10.2026):
// текст как есть — из письма, мессенджера, таблицы — в строки «город · дата · статус». Подключается в index.html до основного
// скрипта; тест — tests/tour-parse.test.js (node --test) на примере пользователя («Призрак Оперы»).
//
// Строка списка → { line, city, raw (как написан город), fix ("опечатка" | "район"), date, date2 (конец «2–9 января»),
//                   time, status, other (другой спектакль), note }
// status: ok — выступление; maybe — под вопросом («?», «ждём подтверждения»); nodate — город без даты («есть под Старый
//         Оскол дата»); transit — переезд («Переезд через Ярославль»); other — другой спектакль того же продюсера
//         («Летучая Мышь»); note — заметка без города («Апрель Казахстан», «2–3 марта — достроить»); title — название.
// Год не указан — ближайший будущий (дата раньше «сегодня − 60 дней» — следующий год).
// Город — по справочнику (market-pop.js + города рынка): точное совпадение 1–3 слов; опечатка — по похожести
// («Сергиев Пассаж» → «Сергиев Посад»), отмечается; районы — по списку TP_ALIAS («Академгородок» → Новосибирск).
// Название спектакля — самая частая «лишняя» фраза строк с городом и датой (или заданное); другая фраза — другой спектакль.
(function (root) {
  var MONTHS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"];
  var M_RE = "(январ[а-яё]*|феврал[а-яё]*|март[а-яё]*|апрел[а-яё]*|ма[йяе]|июн[а-яё]*|июл[а-яё]*|август[а-яё]*|сентябр[а-яё]*|октябр[а-яё]*|ноябр[а-яё]*|декабр[а-яё]*)";
  var D_TEXT = new RegExp("(?:^|[^0-9а-яё])(?:со?\\s+)?(\\d{1,2})(?:\\s*[-–—]\\s*(\\d{1,2}))?\\s+" + M_RE + "\\.?(?:\\s+(\\d{4}))?(?:\\s*г(?:ода|\\.)?)?(?![а-яё])", "i");
  var D_NUM = /(?:^|[^0-9.\/])(\d{1,2})[.\/](\d{1,2})(?:[.\/](\d{4}|\d{2}))?(?![0-9]|[.\/]\d)/;
  var TIME = /(?:^|[^0-9])(\d{1,2}):(\d{2})(?!\s*(?:am|pm))/i;
  var STAMP = /^\s*\d{1,2}:\d{2}\s*(am|pm)?\s*(ред\.?)?\s*$/i;          // «01:06 PM ред.» — время сообщения в чате
  var MAYBE = /\?|жд[её]м|подтвержд|под вопросом|предварит|не точно|уточня/i;
  var TRANSIT = /переезд|транзит/i;
  // Слова, которые не название спектакля и не город
  var FILLER = ("с со по до и в на через переезд транзит театр театре ждем ждём подтверждения подтверждение подтвердят поставить город " +
    "дата даты есть под второй первый третий состав составом ред pm am достроить формируется формируем конец начало середина " +
    "площадка площадке зал зале выезд день дня дней вечер утро число числа уже тоже также ориентировочно вопрос г гор").split(" ");
  var TP_ALIAS = { "академгородок": "Новосибирск", "питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "мск": "Москва", "екб": "Екатеринбург",
    "нск": "Новосибирск", "нн": "Нижний Новгород", "н.новгород": "Нижний Новгород", "ростов": "Ростов-на-Дону", "петербург": "Санкт-Петербург" };

  function norm(s) { return String(s || "").toLowerCase().replace(/ё/g, "е"); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function lev(a, b) {
    if (a === b) return 0;
    var m = a.length, n = b.length, prev = [], cur = [];
    for (var j = 0; j <= n; j++) prev[j] = j;
    for (var i = 1; i <= m; i++) {
      cur = [i];
      for (j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = cur;
    }
    return prev[n];
  }
  function iso(y, m, d) {
    if (!(m >= 1 && m <= 12 && d >= 1 && d <= 31)) return null;
    var t = new Date(Date.UTC(y, m - 1, d));
    return t.getUTCMonth() === m - 1 ? y + "-" + pad(m) + "-" + pad(d) : null;
  }
  function withYear(m, d, y, today) {
    if (y) return iso(y < 100 ? 2000 + y : y, m, d);
    var ty = +today.slice(0, 4), v = iso(ty, m, d);
    if (!v) return null;
    var back = new Date(Date.parse(today) - 60 * 864e5).toISOString().slice(0, 10);
    return v < back ? iso(ty + 1, m, d) : v;
  }
  function monthNo(word) { var w = norm(word); for (var i = 0; i < 12; i++) if (w.indexOf(MONTHS[i]) === 0 && (i !== 4 || /^ма[йяе]$/.test(w))) return i + 1; return 0; }

  // Справочник городов: нормализованное название → как писать
  function makeDict(names) {
    var d = { exact: {}, list: [] };
    (names || []).forEach(function (c) { var k = norm(c).replace(/\s+/g, " ").trim(); if (k && !d.exact[k]) { d.exact[k] = c; d.list.push({ k: k, c: c, w: k.split(/[\s-]+/).length }); } });
    return d;
  }
  function words(s) { return (norm(s).match(/[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*/g) || []); }

  function findCity(rest, dict, skip) {
    var ws = words(rest).filter(function (w) { return !skip[w]; }), best = null;
    for (var n = Math.min(3, ws.length); n >= 1 && !best; n--) {
      for (var i = 0; i + n <= ws.length; i++) {
        var k = ws.slice(i, i + n).join(" ");
        if (TP_ALIAS[k]) { best = { city: TP_ALIAS[k], raw: k, fix: "район" }; break; }
        if (dict.exact[k]) { best = { city: dict.exact[k], raw: k }; break; }
        var kd = k.replace(/ /g, "-");   // «ростов на дону» = «ростов-на-дону»
        if (dict.exact[kd]) { best = { city: dict.exact[kd], raw: k }; break; }
      }
    }
    if (best) return best;
    // опечатка: 2–3 слова или одно длинное слово; первая буква совпадает, отличие — не больше четверти букв
    var cand = null;
    for (n = Math.min(3, ws.length); n >= 1; n--) {
      for (i = 0; i + n <= ws.length; i++) {
        k = ws.slice(i, i + n).join(" ");
        if (n === 1 && k.length < 7) continue;
        var lim = n === 1 ? 1 : Math.floor(k.length * 0.25);
        dict.list.forEach(function (x) {
          if (x.w !== n || x.k[0] !== k[0] || Math.abs(x.k.length - k.length) > lim) return;
          var dd = lev(k, x.k);
          if (dd <= lim && (!cand || dd < cand.d)) cand = { city: x.c, raw: k, fix: "опечатка", d: dd };
        });
      }
      if (cand) break;
    }
    return cand;
  }

  function tpParse(text, opts) {
    opts = opts || {};
    var today = opts.today || new Date().toISOString().slice(0, 10), dict = makeDict(opts.cities), titleWords = {};
    words(opts.title).forEach(function (w) { titleWords[w] = 1; });
    var filler = {}; FILLER.forEach(function (w) { filler[norm(w)] = 1; });
    var rows = [], pendingTransit = false;
    String(text || "").split(/\r?\n/).forEach(function (line, ln) {
      var raw = line.replace(/\s+/g, " ").trim();
      if (!raw || STAMP.test(raw)) return;
      var r = { n: ln, line: raw, city: "", date: "", status: "" }, rest = raw, m;
      if ((m = D_TEXT.exec(rest))) {
        var mo = monthNo(m[3]);
        r.date = withYear(mo, +m[1], m[4] ? +m[4] : 0, today) || "";
        if (m[2]) r.date2 = withYear(mo, +m[2], m[4] ? +m[4] : 0, today) || "";
        rest = rest.replace(m[0], " ");
      } else if ((m = D_NUM.exec(rest))) {
        r.date = withYear(+m[2], +m[1], m[3] ? +m[3] : 0, today) || "";
        rest = rest.replace(m[0], " ");
      }
      if ((m = TIME.exec(rest))) { r.time = pad(+m[1]) + ":" + m[2]; rest = rest.replace(m[1] + ":" + m[2], " "); }
      rest = rest.replace(/\b(am|pm)\b/ig, " ");
      var c = findCity(rest, dict, titleWords);
      if (c) { r.city = c.city; if (c.fix) { r.fix = c.fix; r.raw = c.raw; } }
      // что осталось кроме даты, времени, города и служебных слов — название спектакля (или другого)
      var ws = words(rest), drop = {};
      if (c) c.raw.split(" ").forEach(function (w) { drop[w] = (drop[w] || 0) + 1; });   // сам город — не название
      var left = ws.filter(function (w) { if (drop[w]) { drop[w]--; return false; } return true; });
      r.rest = left.filter(function (w) { return !filler[w] && !/^\d+$/.test(w) && monthNo(w) === 0; });
      r.maybe = MAYBE.test(raw);
      r.transit = TRANSIT.test(raw);
      r.second = /втор[а-яё]* состав/i.test(raw);
      rows.push(r);
    });
    // Название спектакля: заданное или самая частая «лишняя» фраза среди строк с городом и датой
    var freq = {}, title = "";
    rows.forEach(function (r) { var k = r.rest.filter(function (w) { return !titleWords[w]; }).join(" "); if (r.city && r.date && k) freq[k] = (freq[k] || 0) + 1; });
    var top = Object.keys(freq).sort(function (a, b) { return freq[b] - freq[a]; })[0];
    var main = {}; Object.keys(titleWords).forEach(function (w) { main[w] = 1; });
    if (top && (!Object.keys(titleWords).length || freq[top] >= 2)) top.split(" ").forEach(function (w) { main[w] = 1; });
    rows.forEach(function (r, i) {
      var other = r.rest.filter(function (w) { return !main[w]; });
      if (!r.city && !r.date) {
        if (r.transit) { pendingTransit = true; r.status = "note"; r.note = "переезд"; return; }
        if (!title && i === rows.indexOf(rows.filter(function (x) { return !x.city && !x.date; })[0]) && r.rest.length && r.rest.length <= 5 && i < 3) { r.status = "title"; title = r.line.replace(/[.:]+$/, ""); return; }
        r.status = "note"; return;
      }
      if (r.city && !r.date && (pendingTransit || r.transit)) { r.status = "transit"; pendingTransit = false; return; }
      pendingTransit = false;
      if (!r.city) { r.status = "note"; if (other.length) r.other = other.join(" "); return; }
      if (other.length) { r.status = "other"; r.other = other.join(" "); return; }
      r.status = !r.date ? "nodate" : r.maybe ? "maybe" : "ok";
    });
    rows.forEach(function (r) {
      if (r.other) r.other = r.other.replace(/(^|\s)\S/g, function (s) { return s.toUpperCase(); });   // «летучая мышь» → «Летучая Мышь»
      if (r.second) r.note = (r.note ? r.note + "; " : "") + "второй состав";
      delete r.rest; delete r.maybe; delete r.transit; delete r.second;
    });
    return { title: title || opts.title || "", rows: rows };
  }

  // Город в строке по справочнику (для «Построения гастрольного маршрута», route-plan.js): {city, raw, fix} или null
  var DICT_CACHE = { names: null, dict: null };
  function tpFindCity(text, cities) {
    if (DICT_CACHE.names !== cities) DICT_CACHE = { names: cities, dict: makeDict(cities) };
    return findCity(text, DICT_CACHE.dict, {});
  }

  root.tpParse = tpParse;
  root.tpFindCity = tpFindCity;
  root.TP_ALIAS = TP_ALIAS;
  if (typeof module !== "undefined" && module.exports) module.exports = { tpParse: tpParse, tpFindCity: tpFindCity, TP_ALIAS: TP_ALIAS };
})(typeof window !== "undefined" ? window : this);
