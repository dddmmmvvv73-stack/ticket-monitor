// Оценка гастрольного проекта по шестиугольному профилю (radar chart) — конфиг, определение типа и рисунок (чистый SVG).
// Подключается в index.html до основного скрипта; тест — tests/project-rating.test.js (node --test).
//
// ▸ ЭТАЛОНЫ И ПОРОГ ПРАВЯТСЯ ТОЛЬКО ЗДЕСЬ, в PT_CONFIG: компоненты страницы их не дублируют.
//   Тип проекта не выбирается вручную — это ближайший эталон по евклидову расстоянию; если второй по близости
//   отстоит от первого меньше чем на `between`, показывается «между X и Y».
var PT_CONFIG = {
  max: 3,                                                   // оценка по оси: 0–3
  levels: ["нет", "низкий", "средний", "высокий"],
  axes: [   // порядок осей = номера на вершинах шестиугольника (1 — сверху, дальше по часовой)
    { key: "fame", name: "Известность", hint: "Насколько имя знают: узнают ли на афише без пояснений" },
    { key: "reach", name: "Широта аудитории", hint: "Насколько разная публика: возраст, интересы, города" },
    { key: "self", name: "Самопродажа", hint: "Собирает ли аншлаг без рекламы — за счёт имени и сарафана" },
    { key: "ads", name: "Отклик на рекламу", hint: "Растут ли продажи вместе с рекламным бюджетом" },
    { key: "growth", name: "Потенциал роста", hint: "Может ли проект вырасти: новый, набирает аудиторию, есть куда расти" },
    { key: "core", name: "Ядро фанатов", hint: "Есть ли преданные зрители, которые придут в любом случае" }
  ],
  types: [
    { name: "Популярный артист", v: [3, 3, 3, 1, 1, 3] },
    { name: "Известный, с рекламой", v: [3, 3, 1, 3, 1, 2] },
    { name: "Нишевый", v: [1, 1, 2, 2, 1, 3] },
    { name: "Новый с потенциалом", v: [1, 2, 1, 3, 3, 1] },
    { name: "Слабый проект", v: [2, 2, 1, 1, 1, 1] },
    { name: "Мёртвый проект", v: [1, 1, 0, 0, 0, 0] }
  ],
  between: 0.6   // если второй эталон дальше первого меньше чем на столько — «между X и Y»
};

// Профиль — массив из 6 целых 0–3. Неполный или кривой — null.
function ptValid(s) {
  return Array.isArray(s) && s.length === PT_CONFIG.axes.length && s.every(function (v) { return Number.isInteger(v) && v >= 0 && v <= PT_CONFIG.max; });
}
// Тип по профилю: { name, between: имя второго | null, d1, d2, ranked: [{name, d}] }
function ptTypeOf(s, cfg) {
  cfg = cfg || PT_CONFIG;
  if (!ptValid(s)) return null;
  var ranked = cfg.types.map(function (t) {
    var d = Math.sqrt(t.v.reduce(function (sum, v, i) { return sum + (v - s[i]) * (v - s[i]); }, 0));
    return { name: t.name, d: d };
  }).sort(function (a, b) { return a.d - b.d; });
  var a = ranked[0], b = ranked[1];
  return { name: a.name, between: b && b.d - a.d < cfg.between ? b.name : null, d1: a.d, d2: b ? b.d : null, ranked: ranked };
}
function ptLabel(t) { return !t ? "не оценён" : t.between ? "между «" + t.name + "» и «" + t.between + "»" : t.name; }

// Шестиугольник. s — профиль (или null — пустая сетка), opt: { size, prev (прошлый профиль — пунктиром), mini (без подписей),
// title }. Цвета — от текущего цвета текста (currentColor) и --pt-accent: годится и на светлом, и на тёмном фоне.
function ptRadar(s, opt) {
  opt = opt || {};
  var n = PT_CONFIG.axes.length, max = PT_CONFIG.max, size = opt.size || 220, mini = !!opt.mini;
  var pad = mini ? 2 : 26, r = size / 2 - pad, c = size / 2;
  var pt = function (i, v) { var a = -Math.PI / 2 + i * 2 * Math.PI / n, k = v / max * r; return [c + k * Math.cos(a), c + k * Math.sin(a)]; };
  var poly = function (vals) { return vals.map(function (v, i) { var p = pt(i, v); return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "); };
  var rings = "", axes = "", labels = "";
  for (var lv = 1; lv <= max; lv++) rings += '<polygon points="' + poly(PT_CONFIG.axes.map(function () { return lv; })) + '" fill="none" stroke="currentColor" stroke-opacity="' + (mini ? 0.35 : 0.16) + '" stroke-width="1"/>';
  for (var i = 0; i < n; i++) {
    var e = pt(i, max);
    if (!mini) axes += '<line x1="' + c + '" y1="' + c + '" x2="' + e[0].toFixed(1) + '" y2="' + e[1].toFixed(1) + '" stroke="currentColor" stroke-opacity="0.12"/>';
    if (!mini) { var l = pt(i, max + 0.62); labels += '<text x="' + l[0].toFixed(1) + '" y="' + (l[1] + 4).toFixed(1) + '" text-anchor="middle" font-size="12" fill="currentColor" fill-opacity="0.7">' + (i + 1) + '</text>'; }
  }
  var prev = opt.prev && ptValid(opt.prev) ? '<polygon points="' + poly(opt.prev) + '" fill="none" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.5" stroke-dasharray="4 3"/>' : '';
  var cur = ptValid(s) ? '<polygon points="' + poly(s) + '" fill="var(--pt-accent, #3b82f6)" fill-opacity="0.22" stroke="var(--pt-accent, #3b82f6)" stroke-width="' + (mini ? 1.4 : 2.2) + '" stroke-linejoin="round"/>' +
    (mini ? '' : s.map(function (v, i) { var p = pt(i, v); return '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3.6" fill="var(--pt-accent, #3b82f6)"/>'; }).join("")) : '';
  var title = opt.title || (ptValid(s) ? PT_CONFIG.axes.map(function (a, i) { return (i + 1) + " " + a.name + ": " + PT_CONFIG.levels[s[i]]; }).join("; ") : "Оценки нет");
  return '<svg class="pt-radar" viewBox="0 0 ' + size + ' ' + size + '" width="' + size + '" height="' + size + '" role="img" aria-label="' + title.replace(/"/g, "&quot;") + '">' +
    '<title>' + title.replace(/</g, "&lt;") + '</title>' + rings + axes + prev + cur + labels + '</svg>';
}

if (typeof module !== "undefined") module.exports = { PT_CONFIG: PT_CONFIG, ptValid: ptValid, ptTypeOf: ptTypeOf, ptLabel: ptLabel, ptRadar: ptRadar };
