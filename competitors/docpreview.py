"""
Предпросмотр документов проекта прямо на странице (решение пользователя 20.10.2026): браузер сам показывает только PDF и
картинки, а Word / Excel — нет. Здесь документ переводится в страницу HTML; оригинал не меняется, «Скачать» отдаёт его.

  Word и похожие (.docx .doc .rtf .odt) — встроенным в macOS конвертером textutil (сервер — ноутбук; на Linux его нет,
      там понадобится LibreOffice — тогда available() скажет «нет», и сайт предложит скачать).
  Excel (.xlsx) — openpyxl: каждый лист таблицей, переключатель листов сверху (без скриптов — на CSS).
  Текст (.txt) — как есть, UTF-8 или Windows-1251.

Страница отдаётся с запретом скриптов и внешних загрузок (Content-Security-Policy) и открывается в изолированном iframe.
Готовая страница держится в памяти, пока файл не заменят.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import threading

WORD = {"docx", "doc", "rtf", "odt"}
EXCEL = {"xlsx"}
TEXT = {"txt"}
MAX_ROWS, MAX_COLS = 3000, 80          # больше в окне всё равно не читается — дальше «скачайте»
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"

_cache: dict = {}                      # имя файла → (mtime, html)
_lock = threading.Lock()

PAGE_CSS = """
html { background: #f4f3f1; }
body { background: #fff; max-width: 860px; margin: 18px auto; padding: 40px 48px; box-sizing: border-box;
       box-shadow: 0 1px 3px rgba(0,0,0,.08); border-radius: 6px; }
img { max-width: 100%; height: auto; }
table { max-width: 100%; }
@media (max-width: 640px) { body { margin: 0; padding: 18px 16px; border-radius: 0; box-shadow: none; } }
"""

SHEET_CSS = """
html, body { margin: 0; background: #fff; font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1d1d1f; }
.tabs { position: sticky; top: 0; z-index: 2; display: flex; gap: 6px; flex-wrap: wrap; padding: 10px 12px; background: #f4f3f1;
        border-bottom: 1px solid #e3e1dc; }
.tabs label { padding: 4px 12px; border-radius: 999px; background: #fff; border: 1px solid #e3e1dc; cursor: pointer; white-space: nowrap; }
input[name=sh] { display: none; }
.sh { display: none; padding: 12px; }
.cap { color: #8a8780; margin: 0 0 8px; }
table { border-collapse: collapse; }
td, th { border: 1px solid #e3e1dc; padding: 4px 8px; vertical-align: top; white-space: pre-wrap; max-width: 420px; }
th { background: #f7f6f3; color: #8a8780; font-weight: 500; position: sticky; left: 0; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
"""


def kind(ext: str) -> str:
    ext = (ext or "").lower()
    return "word" if ext in WORD else "excel" if ext in EXCEL else "text" if ext in TEXT else ""


def available(ext: str) -> bool:
    k = kind(ext)
    return bool(k) and (k != "word" or shutil.which("textutil") is not None)


def _word(path) -> str:
    out = subprocess.run(["textutil", "-convert", "html", "-stdout", str(path)],
                         capture_output=True, timeout=60, check=True).stdout.decode("utf-8", "replace")
    tag = "<style>" + PAGE_CSS + "</style>"
    return out.replace("</head>", tag + "</head>", 1) if "</head>" in out else tag + out


def _text(path) -> str:
    raw = path.read_bytes()
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp1251", "replace")
    return ('<!doctype html><meta charset="utf-8"><style>' + PAGE_CSS + "</style>"
            '<pre style="white-space:pre-wrap;font:13px/1.5 Menlo,monospace">' + html.escape(s) + "</pre>")


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", " ").rstrip("0").rstrip(".").replace(".", ",")   # 1 250 000,5
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}".replace(",", " ")
    if hasattr(v, "strftime"):
        return v.strftime("%d.%m.%Y %H:%M").replace(" 00:00", "")
    return str(v)


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _excel(path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    radios, tabs, sheets, css = [], [], [], []
    try:
        for i, ws in enumerate(wb.worksheets):
            rows = []
            for r in ws.iter_rows(max_row=MAX_ROWS + 1, max_col=MAX_COLS, values_only=True):
                rows.append(list(r))
            while rows and not any(v not in (None, "") for v in rows[-1]):
                rows.pop()                                     # пустой хвост листа
            cut = len(rows) > MAX_ROWS
            rows = rows[:MAX_ROWS]
            width = max((max((j + 1 for j, v in enumerate(r) if v not in (None, "")), default=0) for r in rows), default=0)
            body = []
            for n, r in enumerate(rows, 1):
                tds = "".join(f'<td class="n">{html.escape(_cell(v))}</td>' if isinstance(v, (int, float)) and not isinstance(v, bool)
                              else f"<td>{html.escape(_cell(v))}</td>" for v in (r + [None] * width)[:width])
                body.append(f"<tr><th>{n}</th>{tds}</tr>")
            head = "<tr><th></th>" + "".join(f"<th>{_col(j)}</th>" for j in range(1, width + 1)) + "</tr>"
            cap = (f"Показаны первые {MAX_ROWS} строк — весь лист в скачанном файле." if cut else "")
            radios.append(f'<input type="radio" name="sh" id="s{i}"{" checked" if i == 0 else ""}>')
            tabs.append(f'<label for="s{i}">{html.escape(ws.title)}</label>')
            sheets.append(f'<div class="sh" id="v{i}">' + (f'<p class="cap">{cap}</p>' if cap else "")
                          + (f"<table>{head}{''.join(body)}</table>" if width else '<p class="cap">Лист пустой.</p>') + "</div>")
            css.append(f"#s{i}:checked ~ #v{i} {{ display: block; }} #s{i}:checked ~ .tabs label[for=s{i}] "
                       "{ background: #1d1d1f; color: #fff; border-color: #1d1d1f; }")
    finally:
        wb.close()
    tabbar = f'<div class="tabs">{"".join(tabs)}</div>' if len(tabs) > 1 else ""
    return ('<!doctype html><meta charset="utf-8"><style>' + SHEET_CSS + "".join(css) + "</style>"
            + "".join(radios) + tabbar + "".join(sheets))


def message(text: str) -> str:
    return ('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#f4f3f1;'
            'font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#8a8780}'
            'body{display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box;text-align:center}</style>'
            + html.escape(text))


def render(path) -> str | None:
    """Страница предпросмотра для файла или None (вид не поддерживается / конвертер недоступен)."""
    ext = path.suffix.lower().lstrip(".")
    if not available(ext):
        return None
    mt = path.stat().st_mtime
    with _lock:
        hit = _cache.get(path.name)
        if hit and hit[0] == mt:
            return hit[1]
    k = kind(ext)
    page = _word(path) if k == "word" else _excel(path) if k == "excel" else _text(path)
    with _lock:
        _cache[path.name] = (mt, page)
    return page
