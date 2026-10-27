// «Рабочие заметки» (решение пользователя 22.10): редактор на TipTap (vendor/tiptap-3.30.0.min.js) — заголовки, списки,
// чек-листы, выноски, разделители, таблицы, ссылки, картинки, файлы; и чистые функции для карточек, окна задачи и журнала
// задачи. Данные — общий WK (work.json → notes, tasks.log); запись и загрузка файлов — в index.html (/api/work).
(function (root) {
  'use strict';
  var MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var TEXT_BLOCKS = { paragraph: 1, heading: 1, tableCell: 1, tableHeader: 1 };

  // ---------- чистые функции (проверка — tests/work-notes.test.js)
  // Текст документа: блоки — с новой строки; файлы — их именами. limit — хватит стольких знаков (превью карточки).
  function docText(doc, limit) {
    var out = [], len = 0;
    (function walk(n) {
      if (!n || typeof n !== 'object' || (limit && len > limit)) return;
      if (n.type === 'text') { out.push(n.text || ''); len += (n.text || '').length; return; }
      if (n.type === 'hardBreak') { out.push('\n'); return; }
      if (n.type === 'fileBlock') { out.push('\n' + ((n.attrs && n.attrs.name) || '') + '\n'); return; }
      (n.content || []).forEach(walk);
      if (TEXT_BLOCKS[n.type]) out.push('\n');
    })(doc);
    return out.join('').replace(/[ \t]+\n/g, '\n').replace(/\n{2,}/g, '\n').trim();
  }
  // Чек-лист (пунктов, отмечено), картинки и файлы — для значков на карточке
  function docStats(doc) {
    var s = { checks: 0, done: 0, images: 0, files: 0 };
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (n.type === 'taskItem') { s.checks++; if (n.attrs && n.attrs.checked) s.done++; }
      else if (n.type === 'image') s.images++;
      else if (n.type === 'fileBlock') s.files++;
      (n.content || []).forEach(walk);
    })(doc);
    return s;
  }
  function docEmpty(doc) {
    var s = docStats(doc);
    return !docText(doc) && !s.images && !s.files && !s.checks && !hasType(doc, { table: 1, horizontalRule: 1, callout: 1 });
  }
  function hasType(n, types) {
    if (!n || typeof n !== 'object') return false;
    return !!types[n.type] || (n.content || []).some(function (c) { return hasType(c, types); });
  }
  // Журнал задачи: новые сверху
  function logSorted(list) {
    return (list || []).slice().sort(function (a, b) { return (b.at || '').localeCompare(a.at || '') || (b.id || '').localeCompare(a.id || ''); });
  }
  function dayShift(iso, n) {
    var d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  // «сегодня, 14:30» · «вчера, 09:05» · «18 окт, 11:00» · «18 окт 2025, 11:00»
  function stampText(at, today) {
    if (!at) return '';
    var day = at.slice(0, 10), time = at.slice(11, 16), d;
    if (day === today) d = 'сегодня';
    else if (today && day === dayShift(today, -1)) d = 'вчера';
    else d = +day.slice(8) + ' ' + MON[+day.slice(5, 7) - 1] + (today && day.slice(0, 4) !== today.slice(0, 4) ? ' ' + day.slice(0, 4) : '');
    return time ? d + ', ' + time : d;
  }
  // Задачи для выбора в заметке: проекта (если выбран) или все; открытые — по сроку, готовые — в конце
  function taskOptions(work, project) {
    var tasks = work.tasks || {}, projects = work.projects || {};
    return Object.keys(tasks).filter(function (id) { return !project || (project.indexOf('proc:') === 0 ? tasks[id].proc === project.slice(5) : tasks[id].project === project); }).map(function (id) {
      var t = tasks[id], p = !project && projects[t.project] ? projects[t.project].title : '';
      return { id: id, done: !!t.done, due: t.due || '', label: (t.text || '').replace(/\s+/g, ' ').slice(0, 90) + (p ? ' · ' + p : '') + (t.done ? ' (готово)' : '') };
    }).sort(function (a, b) {
      return (a.done ? 1 : 0) - (b.done ? 1 : 0) || (a.due || '9999').localeCompare(b.due || '9999') || a.label.localeCompare(b.label, 'ru');
    });
  }
  function isImage(name, type) { return /^image\/(png|jpe?g|webp|gif)$/.test(type || '') || /\.(png|jpe?g|webp|gif)$/i.test(name || ''); }
  function sizeText(b) { return !b ? '' : b < 1024 ? b + ' Б' : b < 1048576 ? Math.round(b / 1024) + ' КБ' : (b / 1048576).toFixed(1).replace('.', ',') + ' МБ'; }
  function normUrl(v) {
    v = String(v || '').trim();
    if (!v) return '';
    if (/^(https?:|mailto:|tel:)/i.test(v)) return v;
    if (/^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(v)) return 'mailto:' + v;
    if (/^\+?[\d\s()-]{7,}$/.test(v)) return 'tel:' + v.replace(/[^\d+]/g, '');
    return /^[a-z][a-z0-9+.-]*:/i.test(v) ? '' : 'https://' + v;   // другие схемы (javascript: и т. п.) — нельзя
  }

  // ---------- редактор
  var IC = {
    bold: '<path d="M4.5 2.5h4.2a2.8 2.8 0 0 1 0 5.6H4.5zM4.5 8.1h4.9a2.9 2.9 0 0 1 0 5.8H4.5z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>',
    italic: '<path d="M10.5 2.5H6.8M9.2 13.5H5.5M8.9 2.5L7.1 13.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    strike: '<path d="M2.5 8h11M11 4.6c-.4-1.3-1.6-2-3.1-2-1.8 0-3.1.9-3.1 2.3 0 .8.4 1.4 1.3 1.8M5 11.3c.4 1.4 1.7 2.2 3.3 2.2 1.9 0 3.2-1 3.2-2.5 0-.5-.1-.9-.4-1.3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    ul: '<circle cx="3" cy="4" r="1.1" fill="currentColor"/><circle cx="3" cy="8" r="1.1" fill="currentColor"/><circle cx="3" cy="12" r="1.1" fill="currentColor"/><path d="M6 4h8M6 8h8M6 12h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    ol: '<path d="M2.2 2.8h1.2v3M2 6h2.6M2 10.2c.3-.6 1.9-.7 1.9.3 0 .8-1.9 1.4-1.9 2.2h2.1M6.5 4h7.5M6.5 8h7.5M6.5 12h7.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
    todo: '<rect x="1.8" y="2.3" width="4.6" height="4.6" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2.9 4.6l1 1 1.6-1.9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><rect x="1.8" y="9.1" width="4.6" height="4.6" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8.8 4.6h5.4M8.8 11.4h5.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    callout: '<rect x="1.8" y="2.5" width="12.4" height="11" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5 5.7v4.6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M7.8 6.2h3.6M7.8 9.8h3.6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
    hr: '<path d="M1.8 8h12.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M4 4.2h8M4 11.8h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity=".4"/>',
    table: '<rect x="1.8" y="2.5" width="12.4" height="11" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M1.8 6.2h12.4M1.8 9.8h12.4M6 6.2v7.3M10 6.2v7.3" stroke="currentColor" stroke-width="1.2"/>',
    link: '<path d="M6.8 9.2a2.9 2.9 0 0 0 4.1 0l2.1-2.1a2.9 2.9 0 0 0-4.1-4.1l-.9.9M9.2 6.8a2.9 2.9 0 0 0-4.1 0L3 8.9A2.9 2.9 0 0 0 7.1 13l.9-.9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    image: '<rect x="1.8" y="2.5" width="12.4" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="5.6" cy="6" r="1.2" fill="currentColor"/><path d="M2.2 12l3.6-3.4 2.4 2.2 2.4-2.6 3.4 3.4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
    file: '<path d="M10.6 7.2l-4.1 4.1a2.1 2.1 0 0 1-3-3l4.9-4.9a1.4 1.4 0 0 1 2 2L5.7 10.2a.7.7 0 0 1-1-1L9 4.9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" transform="translate(1 .6)"/>',
    undo: '<path d="M5.5 4L2.5 7l3 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.8 7h6.7a4 4 0 0 1 0 8H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" transform="translate(0 -2)"/>',
    redo: '<path d="M10.5 4l3 3-3 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M13.2 7H6.5a4 4 0 0 0 0 8H9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" transform="translate(0 -2)"/>',
    text: '<path d="M3 3.5h10M8 3.5v9.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
  };
  function svg(k) { return '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">' + IC[k] + '</svg>'; }
  function hx(n) { return '<span class="wn-hx">H<small>' + n + '</small></span>'; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  // Действия: панель и меню «/» — одни и те же. a — {ed, pick(kind), link()}
  var ACT = {
    text: { t: 'Текст', d: 'Обычный абзац', s: 'текст абзац text', i: svg('text'), run: function (a) { a.ed.chain().focus().setParagraph().run(); } },
    h1: { t: 'Заголовок 1', d: 'Крупный раздел', s: 'заголовок h1 heading', i: hx(1), run: function (a) { a.ed.chain().focus().toggleHeading({ level: 1 }).run(); }, on: function (e) { return e.isActive('heading', { level: 1 }); } },
    h2: { t: 'Заголовок 2', d: 'Подраздел', s: 'заголовок h2 heading', i: hx(2), run: function (a) { a.ed.chain().focus().toggleHeading({ level: 2 }).run(); }, on: function (e) { return e.isActive('heading', { level: 2 }); } },
    h3: { t: 'Заголовок 3', d: 'Небольшой заголовок', s: 'заголовок h3 heading', i: hx(3), run: function (a) { a.ed.chain().focus().toggleHeading({ level: 3 }).run(); }, on: function (e) { return e.isActive('heading', { level: 3 }); } },
    bold: { t: 'Жирный', k: 'Ctrl+B', i: svg('bold'), run: function (a) { a.ed.chain().focus().toggleBold().run(); }, on: function (e) { return e.isActive('bold'); } },
    italic: { t: 'Курсив', k: 'Ctrl+I', i: svg('italic'), run: function (a) { a.ed.chain().focus().toggleItalic().run(); }, on: function (e) { return e.isActive('italic'); } },
    strike: { t: 'Зачеркнуть', i: svg('strike'), run: function (a) { a.ed.chain().focus().toggleStrike().run(); }, on: function (e) { return e.isActive('strike'); } },
    ul: { t: 'Список', d: 'С точками; «- » в начале строки', s: 'список маркированный bullet', i: svg('ul'), run: function (a) { a.ed.chain().focus().toggleBulletList().run(); }, on: function (e) { return e.isActive('bulletList'); } },
    ol: { t: 'Нумерованный список', d: '«1. » в начале строки', s: 'нумерованный список номер ordered', i: svg('ol'), run: function (a) { a.ed.chain().focus().toggleOrderedList().run(); }, on: function (e) { return e.isActive('orderedList'); } },
    todo: { t: 'Чек-лист', d: 'Пункты с галочками; «[] » в начале строки', s: 'чек-лист чеклист галочка todo check задачи пункты', i: svg('todo'), run: function (a) { a.ed.chain().focus().toggleTaskList().run(); }, on: function (e) { return e.isActive('taskList'); } },
    callout: { t: 'Выноска', d: 'Важное — на цветном фоне; «> » в начале строки', s: 'выноска важно callout примечание внимание', i: svg('callout'), run: function (a) { a.ed.chain().focus().toggleWrap('callout').run(); }, on: function (e) { return e.isActive('callout'); } },
    hr: { t: 'Разделитель', d: 'Линия; «---» в начале строки', s: 'разделитель линия divider hr', i: svg('hr'), run: function (a) { a.ed.chain().focus().setHorizontalRule().run(); } },
    table: { t: 'Таблица', d: '3 × 3 со строкой заголовков', s: 'таблица table', i: svg('table'), run: function (a) { a.ed.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(); } },
    link: { t: 'Ссылка', k: 'Ctrl+K', d: 'Адрес сайта, почта или телефон', s: 'ссылка link url адрес', i: svg('link'), run: function (a) { a.link(); }, on: function (e) { return e.isActive('link'); } },
    image: { t: 'Картинка', d: 'С компьютера или телефона; можно вставить Ctrl+V', s: 'картинка фото изображение скриншот image', i: svg('image'), run: function (a) { a.pick('image'); } },
    file: { t: 'Файл', d: 'PDF, Word, Excel… — откроется прямо здесь', s: 'файл документ вложение pdf word excel file', i: svg('file'), run: function (a) { a.pick('file'); } },
    undo: { t: 'Отменить', k: 'Ctrl+Z', i: svg('undo'), run: function (a) { a.ed.chain().focus().undo().run(); } },
    redo: { t: 'Повторить', k: 'Ctrl+Shift+Z', i: svg('redo'), run: function (a) { a.ed.chain().focus().redo().run(); } }
  };
  var BAR = ['h1', 'h2', 'h3', '|', 'bold', 'italic', 'strike', '|', 'ul', 'ol', 'todo', '|', 'callout', 'hr', 'table', '|', 'link', 'image', 'file', '|', 'undo', 'redo'];
  var SLASH = ['text', 'h1', 'h2', 'h3', 'ul', 'ol', 'todo', 'callout', 'hr', 'table', 'image', 'file', 'link'];
  var FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.webp,.gif,.rtf,.odt,.ods,.txt,.csv,.zip';

  function slashItems(q) {
    q = String(q || '').toLowerCase().replace(/ё/g, 'е');
    return SLASH.filter(function (k) { var a = ACT[k]; return !q || (a.t + ' ' + (a.s || '')).toLowerCase().replace(/ё/g, 'е').indexOf(q) >= 0; });
  }

  // o: {doc, onChange(), upload(file) → Promise<{file, name, size}>, fileUrl(file), openFile({file, name, size}), toast(msg)}
  function mount(o) {
    var T = root.Tiptap;
    var wrap = document.createElement('div'); wrap.className = 'wn-edwrap';
    wrap.innerHTML = '<div class="wn-tbox"><div class="wn-tb" role="toolbar" aria-label="Оформление текста">' + BAR.map(function (k) {
        if (k === '|') return '<i class="wn-sep" aria-hidden="true"></i>';
        var a = ACT[k];
        return '<button type="button" class="wn-b" data-wn-act="' + k + '" title="' + esc(a.t + (a.k ? ' · ' + a.k : '')) + '" aria-label="' + esc(a.t) + '">' + a.i + '</button>';
      }).join('') + '</div><div class="wn-ctx" hidden></div></div><div class="wn-ed"></div>';
    var tbox = wrap.querySelector('.wn-tbox'), tb = wrap.querySelector('.wn-tb'), ctx = wrap.querySelector('.wn-ctx');
    var pick = document.createElement('input'); pick.type = 'file'; pick.hidden = true; pick.multiple = true; wrap.appendChild(pick);
    var api = { pick: function (kind) { pick.accept = kind === 'image' ? 'image/png,image/jpeg,image/webp,image/gif' : FILE_ACCEPT; pick.click(); }, link: function () { linkForm(); } };

    function insertFiles(files, pos) {
      files.forEach(function (f) {
        o.upload(f).then(function (r) {
          var node = isImage(r.name, f.type) ? { type: 'image', attrs: { src: o.fileUrl(r.file), file: r.file, alt: r.name } }
            : { type: 'fileBlock', attrs: { file: r.file, name: r.name, size: r.size } };
          var sel = ed.state.selection, at = pos != null ? pos : sel.node ? sel.to : null;   // выделена картинка или файл — новый встаёт после, а не вместо
          var ch = ed.chain().focus();
          (at != null ? ch.insertContentAt(at, node) : ch.insertContent(node)).run();
        }, function () { /* сообщение — в upload */ });
      });
    }
    pick.addEventListener('change', function () { var l = Array.prototype.slice.call(pick.files || []); pick.value = ''; insertFiles(l); });

    var Callout = T.Node.create({
      name: 'callout', group: 'block', content: 'block+', defining: true,
      parseHTML: function () { return [{ tag: 'div[data-callout]' }]; },
      renderHTML: function (p) { return ['div', T.mergeAttributes(p.HTMLAttributes, { 'data-callout': '', class: 'wn-callout' }), 0]; },
      addInputRules: function () { return [T.wrappingInputRule({ find: /^\s*>\s$/, type: this.type })]; },
      addKeyboardShortcuts: function () {   // как в Notion: Enter на пустой строке и Backspace в начале — выйти из выноски
        var lift = function (e, atStart) {
          var sel = e.state.selection, $f = sel.$from;
          if (!sel.empty || $f.depth < 2 || $f.node(-1).type.name !== 'callout' || $f.parent.type.name !== 'paragraph') return false;
          if (atStart ? $f.parentOffset !== 0 || $f.index(-1) !== 0 : $f.parent.content.size !== 0) return false;
          return e.commands.lift('callout');
        };
        return { Enter: function (p) { return lift(p.editor, false); }, Backspace: function (p) { return lift(p.editor, true); } };
      }
    });
    var FileBlock = T.Node.create({
      name: 'fileBlock', group: 'block', atom: true, draggable: true, selectable: true,
      addAttributes: function () {
        return {
          file: { default: null, parseHTML: function (el) { return el.getAttribute('data-file'); }, renderHTML: function (a) { return { 'data-file': a.file }; } },
          name: { default: '', parseHTML: function (el) { return el.getAttribute('data-name') || ''; }, renderHTML: function (a) { return { 'data-name': a.name }; } },
          size: { default: 0, parseHTML: function (el) { return +el.getAttribute('data-size') || 0; }, renderHTML: function (a) { return { 'data-size': a.size }; } }
        };
      },
      parseHTML: function () { return [{ tag: 'div[data-file]' }]; },
      renderHTML: function (p) { return ['div', T.mergeAttributes(p.HTMLAttributes, { class: 'wn-file' })]; },
      addNodeView: function () {
        return function (p) {
          var a = p.node.attrs, ext = (String(a.name || a.file || '').split('.').pop() || '').slice(0, 4).toUpperCase(), url = o.fileUrl(a.file);
          var dom = document.createElement('div'); dom.className = 'wn-file'; dom.contentEditable = 'false';
          dom.innerHTML = '<span class="wn-file-ic" aria-hidden="true">' + esc(ext || 'ФАЙЛ') + '</span><span class="wn-file-n"><b>' + esc(a.name || a.file) + '</b><span>' + esc(sizeText(a.size)) + '</span></span>' +
            '<button type="button" class="wn-file-b" data-a="open">Открыть</button><a class="wn-file-b" href="' + esc(url) + '?dl=1" download>Скачать</a>';
          dom.querySelector('[data-a=open]').addEventListener('click', function (ev) { ev.preventDefault(); o.openFile({ file: a.file, name: a.name, size: a.size }); });
          return { dom: dom, stopEvent: function (ev) { return !!(ev.target.closest && ev.target.closest('button,a')); }, ignoreMutation: function () { return true; } };
        };
      }
    });
    var Img = T.Image.extend({
      addAttributes: function () {
        var at = this.parent ? this.parent() : {};
        at.file = { default: null, parseHTML: function (el) { return el.getAttribute('data-file'); }, renderHTML: function (a) { return a.file ? { 'data-file': a.file } : {}; } };
        return at;
      }
    }).configure({ allowBase64: false, HTMLAttributes: { class: 'wn-img' } });
    var Keys = T.Extension.create({
      name: 'wnKeys',
      addKeyboardShortcuts: function () { return { 'Mod-k': function () { linkForm(); return true; } }; }
    });

    // Меню «/»: список блоков у курсора; стрелки, Enter, Esc; набранное после «/» — поиск
    var menu = null;
    function menuClose() { if (menu) { menu.el.remove(); menu = null; } }
    function menuDraw() {
      if (!menu) return;
      var l = menu.items;
      menu.el.innerHTML = l.length ? l.map(function (k, i) {
        var a = ACT[k];
        return '<button type="button" class="wn-sl-i' + (i === menu.sel ? ' on' : '') + '" data-i="' + i + '" role="option" aria-selected="' + (i === menu.sel) + '"><span class="wn-sl-ic">' + a.i + '</span><span><b>' + esc(a.t) + '</b>' + (a.d ? '<small>' + esc(a.d) + '</small>' : '') + '</span></button>';
      }).join('') : '<div class="wn-sl-none">Ничего не нашлось</div>';
      var r = menu.rect && menu.rect(); if (!r) return;
      var w = menu.el.offsetWidth, h = menu.el.offsetHeight, vv = root.visualViewport, vh = vv ? vv.height + vv.offsetTop : innerHeight;
      var left = Math.max(8, Math.min(r.left, innerWidth - w - 8)), top = r.bottom + 6;
      if (top + h > vh - 8 && r.top - h - 6 > 8) top = r.top - h - 6;
      menu.el.style.left = left + 'px'; menu.el.style.top = top + 'px';
      var on = menu.el.querySelector('.on'); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
    }
    var Slash = T.Extension.create({
      name: 'wnSlash',
      addProseMirrorPlugins: function () {
        return [T.Suggestion({
          editor: this.editor, char: '/', pluginKey: new T.PluginKey('wnSlash'),
          items: function (p) { return slashItems(p.query); },
          command: function (p) { p.editor.chain().focus().deleteRange(p.range).run(); ACT[p.props].run(api); },
          render: function () {
            return {
              onStart: function (p) {
                menuClose();
                var el = document.createElement('div'); el.className = 'wn-slash'; el.setAttribute('role', 'listbox'); el.setAttribute('aria-label', 'Вставить блок');
                document.body.appendChild(el);
                menu = { el: el, items: p.items, sel: 0, rect: p.clientRect, cmd: p.command };
                el.addEventListener('mousedown', function (ev) { ev.preventDefault(); });
                el.addEventListener('click', function (ev) { var b = ev.target.closest('[data-i]'); if (b && menu) menu.cmd(menu.items[+b.getAttribute('data-i')]); });
                menuDraw();
              },
              onUpdate: function (p) { if (!menu) return; menu.items = p.items; menu.rect = p.clientRect; menu.cmd = p.command; menu.sel = Math.min(menu.sel, Math.max(0, p.items.length - 1)); menuDraw(); },
              onKeyDown: function (p) {
                if (!menu) return false;
                var k = p.event.key, n = menu.items.length;
                if (k === 'Escape') { menuClose(); return true; }
                if (k === 'ArrowDown' && n) { menu.sel = (menu.sel + 1) % n; menuDraw(); return true; }
                if (k === 'ArrowUp' && n) { menu.sel = (menu.sel - 1 + n) % n; menuDraw(); return true; }
                if (k === 'Enter' && n) { menu.cmd(menu.items[menu.sel]); return true; }
                return false;
              },
              onExit: menuClose
            };
          }
        })];
      }
    });

    var host = wrap.querySelector('.wn-ed'), ed;
    var exts = [
      T.StarterKit.configure({ heading: { levels: [1, 2, 3] }, code: false, codeBlock: false, blockquote: false, underline: false,
        link: { openOnClick: false, autolink: true, linkOnPaste: true, defaultProtocol: 'https', HTMLAttributes: { target: '_blank', rel: 'noopener noreferrer' } } }),
      T.TaskList, T.TaskItem.configure({ nested: true, a11y: { checkboxLabel: function (node, checked) { return (checked ? 'Отмечено: ' : 'Отметить: ') + node.textContent; } } }),
      T.TableKit.configure({ table: { resizable: false, renderWrapper: true } }),
      T.Placeholder.configure({ placeholder: function (p) { return p.node.type.name === 'heading' ? 'Заголовок' : 'Пишите здесь. «/» — заголовок, чек-лист, таблица, картинка…'; } }),
      Callout, FileBlock, Img, Keys, Slash
    ];
    var props = {
      attributes: { class: 'wn-pm', 'aria-label': 'Текст заметки', spellcheck: 'true' },
      handlePaste: function (view, ev) {
        var l = Array.prototype.slice.call((ev.clipboardData && ev.clipboardData.files) || []);
        if (!l.length) return false;
        ev.preventDefault(); insertFiles(l); return true;
      },
      handleDrop: function (view, ev, slice, moved) {
        var l = Array.prototype.slice.call((ev.dataTransfer && ev.dataTransfer.files) || []);
        if (moved || !l.length) return false;
        var at = view.posAtCoords({ left: ev.clientX, top: ev.clientY });
        ev.preventDefault(); insertFiles(l, at ? at.pos : null); return true;
      },
      handleClick: function (view, pos, ev) {   // Ctrl / Cmd + нажатие на ссылку — открыть
        var a = ev.target.closest && ev.target.closest('a[href]');
        if (a && (ev.metaKey || ev.ctrlKey)) { root.open(a.href, '_blank', 'noopener'); return true; }
        return false;
      }
    };
    var content = o.doc && o.doc.type === 'doc' && (o.doc.content || []).length ? o.doc : '';
    try {
      ed = new T.Editor({ element: host, extensions: exts, content: content, editorProps: props });
    } catch (e) {
      if (o.toast) o.toast('Часть заметки не прочиталась — показан пустой лист, прежний текст остался в журнале изменений');
      host.innerHTML = '';
      ed = new T.Editor({ element: host, extensions: exts, content: '', editorProps: props });
    }
    ed.on('update', function () { o.onChange(); });
    ed.on('transaction', state);

    // Панель: кнопки не забирают фокус у текста (на телефоне клавиатура не прячется)
    tbox.addEventListener('pointerdown', function (ev) { if (!ev.target.closest('input')) ev.preventDefault(); });
    api.ed = ed;
    tb.addEventListener('click', function (ev) { var b = ev.target.closest('[data-wn-act]'); if (b) ACT[b.getAttribute('data-wn-act')].run(api); });

    // Строка под панелью: в таблице — строки и столбцы; на ссылке — открыть, изменить, убрать; ввод адреса ссылки
    var ctxMode = '';
    function state() {
      tb.querySelectorAll('[data-wn-act]').forEach(function (b) {
        var a = ACT[b.getAttribute('data-wn-act')], on = !!(a.on && a.on(ed));
        b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
        if (a === ACT.undo) b.disabled = !ed.can().undo(); else if (a === ACT.redo) b.disabled = !ed.can().redo();
      });
      if (ctxMode === 'form') return;
      var mode = ed.isActive('link') ? 'link' : ed.isActive('table') ? 'table' : '';
      if (mode === 'link') {
        var href = ed.getAttributes('link').href || '';
        if (ctxMode !== 'link' || ctx.getAttribute('data-href') !== href) {
          ctx.setAttribute('data-href', href);
          ctx.innerHTML = svg('link') + '<a class="wn-ctx-url" href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(href.replace(/^(https?:\/\/|mailto:|tel:)/, '')) + '</a>' +
            '<button type="button" class="wn-cb" data-c="edit">Изменить</button><button type="button" class="wn-cb" data-c="unlink">Убрать ссылку</button>';
        }
      } else if (mode === 'table' && ctxMode !== 'table') {
        ctx.innerHTML = svg('table') + '<span class="wn-ctx-l">Таблица</span>' +
          '<button type="button" class="wn-cb" data-c="row+">+ строка</button><button type="button" class="wn-cb" data-c="col+">+ столбец</button>' +
          '<button type="button" class="wn-cb" data-c="row-">− строка</button><button type="button" class="wn-cb" data-c="col-">− столбец</button>' +
          '<button type="button" class="wn-cb wn-cb-del" data-c="tdel">Удалить таблицу</button>';
      }
      ctxMode = mode; ctx.hidden = !mode;
    }
    function linkForm() {
      var cur = ed.getAttributes('link').href || '';
      ctxMode = 'form'; ctx.hidden = false;
      ctx.innerHTML = svg('link') + '<input class="wn-ctx-in" type="text" inputmode="url" placeholder="Адрес сайта, почта или телефон" aria-label="Адрес ссылки" value="' + esc(cur) + '">' +
        '<button type="button" class="wn-cb wn-cb-ok" data-c="lset">Готово</button><button type="button" class="wn-cb" data-c="lcancel">Отмена</button>';
      var inp = ctx.querySelector('input'); inp.focus(); inp.select();
    }
    function linkApply() {
      var inp = ctx.querySelector('.wn-ctx-in'), raw = inp ? inp.value : '', href = normUrl(raw);
      if (raw.trim() && !href) { if (o.toast) o.toast('Такой адрес не подходит — нужен сайт, почта или телефон'); return; }
      ctxMode = '';
      var ch = ed.chain().focus().extendMarkRange('link');
      if (!href) ch.unsetLink().run();
      else if (ed.state.selection.empty && !ed.isActive('link')) ch.insertContent({ type: 'text', text: raw.trim(), marks: [{ type: 'link', attrs: { href: href } }] }).run();
      else ch.setLink({ href: href }).run();
      state();
    }
    ctx.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-c]'); if (!b) return;
      var c = b.getAttribute('data-c'), ch = ed.chain().focus();
      if (c === 'edit') linkForm();
      else if (c === 'unlink') ch.extendMarkRange('link').unsetLink().run();
      else if (c === 'lset') linkApply();
      else if (c === 'lcancel') { ctxMode = ''; ch.run(); state(); }
      else if (c === 'row+') ch.addRowAfter().run();
      else if (c === 'col+') ch.addColumnAfter().run();
      else if (c === 'row-') ch.deleteRow().run();
      else if (c === 'col-') ch.deleteColumn().run();
      else if (c === 'tdel') ch.deleteTable().run();
    });
    ctx.addEventListener('keydown', function (ev) {
      if (!ev.target.classList.contains('wn-ctx-in')) return;
      if (ev.key === 'Enter') { ev.preventDefault(); linkApply(); }
      else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); ctxMode = ''; ed.chain().focus().run(); state(); }
    });

    // Телефон: панель над клавиатурой, пока пишут (visualViewport — видимая часть экрана без клавиатуры)
    var narrow = root.matchMedia ? root.matchMedia('(max-width: 720px)') : { matches: false };
    function place() {
      if (!wrap.classList.contains('wn-float')) return;
      var vv = root.visualViewport, gap = vv ? innerHeight - vv.height - vv.offsetTop : 0;
      tbox.style.bottom = Math.max(0, Math.round(gap)) + 'px';
    }
    function floatOff() { wrap.classList.remove('wn-float'); tbox.style.bottom = ''; }
    ed.on('focus', function () { if (narrow.matches) { wrap.classList.add('wn-float'); place(); } });
    ed.on('blur', function () { setTimeout(function () { if (!ed.isDestroyed && !ed.isFocused && !tbox.contains(document.activeElement)) floatOff(); }, 200); });
    if (root.visualViewport) { root.visualViewport.addEventListener('resize', place); root.visualViewport.addEventListener('scroll', place); }
    state();

    return {
      el: wrap, editor: ed,
      json: function () { return ed.getJSON(); },
      focus: function (where) { ed.view.focus(); ed.commands.focus(where || null); },   // view.focus — сразу: следующая буква уже в тексте
      hasFocus: function () { return ed.isFocused || tbox.contains(document.activeElement); },
      destroy: function () {
        menuClose(); floatOff();
        if (root.visualViewport) { root.visualViewport.removeEventListener('resize', place); root.visualViewport.removeEventListener('scroll', place); }
        ed.destroy();
      }
    };
  }

  var api = { docText: docText, docStats: docStats, docEmpty: docEmpty, logSorted: logSorted, stampText: stampText,
    taskOptions: taskOptions, isImage: isImage, sizeText: sizeText, normUrl: normUrl, slashItems: slashItems, mount: mount };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.WorkNotes = api;
})(typeof window !== 'undefined' ? window : globalThis);
