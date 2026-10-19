"""
Справочник площадок — «Площадки → Площадки» в прототипе (решение пользователя 19.10.2026: новое пространство отдельно от
«Базы площадок РФ», потом соединить). Первая версия — столбцы таблицы пользователя «Площадки База данных с информацией»
(Google Таблица): город, площадка, юрлицо, ИНН, сайт, контакт, телефон, почта, мест, выход в продажу, аренда, агентский %,
директор. Значения — как в таблице (текст), разбор аренды и мест — позже.

Хранится в config/venue_book.json — вне git (контакты — персональные данные, репозиторий публичный), в часовой закрытой
копии (db.offsite, весь config/):
    {"imported": ISO-время, "source": имя файла, "rows": [{"id", "city", "name", "legal", "inn", "site", "contact",
                                                          "phone", "email", "seats", "sale", "rent", "agent", "director"}]}

    python3 -m competitors.venuebook import <файл.xlsx>   загрузить из выгрузки Google Таблицы (Файл → Скачать → xlsx):
                                                         xlsx, а не csv — в csv теряются ссылки за словом «Сайт»
    GET /proto/venue-book.js                              справочник для прототипа (competitors/market_api.py)
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "venue_book.json"
# Заголовок столбца таблицы пользователя → поле записи (порядок столбцов в таблице может меняться — ищем по названию)
HEAD = {"город": "city", "площадка": "name", "юр лицо": "legal", "инн": "inn", "сайт": "site", "имя": "contact",
        "телефон": "phone", "почта": "email", "кол-во мест": "seats", "выход в продажу": "sale", "аренда": "rent",
        "агентский %": "agent", "директор": "director"}
FIELDS = list(HEAD.values())
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_EMPTY = {"", "-", "—", "–", "\\-"}


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(v: str) -> str:
    v = (v or "").replace("\r\n", "\n").replace("\xa0", " ")
    v = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in v.split("\n")).strip()
    return "" if v in _EMPTY else v


def _num(v: str, fmt: str) -> str:
    """Число ячейки — как его показывает таблица: 7.9130590677E10 → 79130590677; процентная ячейка 0.07 → 7%;
    денежная 100000 → 100 000 ₽."""
    try:
        x = float(v)
    except ValueError:
        return v
    if fmt == "pct":
        x = round(x * 100, 2)
    s = str(int(x)) if x == int(x) else f"{x:g}".replace(".", ",")
    if fmt == "money":
        s = (f"{int(x):,}" if x == int(x) else f"{x:,.2f}").replace(",", " ").replace(".", ",")
    return s + {"pct": "%", "money": " ₽"}.get(fmt, "")


def read_xlsx(path: Path) -> tuple[list[list[str]], dict]:
    """Первый лист xlsx → строки ячеек (текст как в таблице) и ссылки ячеек {(строка, столбец): url}."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    style = {}   # номер стиля ячейки → pct | money: xlsx хранит 7% как 0.07, «р.80 000» как 80000
    if "xl/styles.xml" in z.namelist():
        st = ET.fromstring(z.read("xl/styles.xml"))
        fmts = {f.get("numFmtId"): f.get("formatCode", "") for f in st.iter(f"{{{_NS['m']}}}numFmt")}
        xfs = st.find("m:cellXfs", _NS)
        for i, xf in enumerate(xfs.findall("m:xf", _NS) if xfs is not None else []):
            fid = xf.get("numFmtId", "0")
            code = fmts.get(fid, "")
            if fid in ("9", "10") or "%" in code:
                style[str(i)] = "pct"
            elif fid in ("5", "6", "7", "8") or re.search(r"р\.|₽|\[\$", code):
                style[str(i)] = "money"
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    links = {}
    rels = "xl/worksheets/_rels/sheet1.xml.rels"
    if rels in z.namelist():
        target = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(rels))}
        for h in sheet.iter(f"{{{_NS['m']}}}hyperlink"):
            url = target.get(h.get(f"{{{_NS['r']}}}id"))
            if url:
                links[h.get("ref")] = url
    rows, cell_links = [], {}
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", _NS):
            ref, kind = c.get("r"), c.get("t")
            v = c.find("m:v", _NS)
            if kind == "s" and v is not None:
                val = shared[int(v.text)]
            elif kind == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                val = _num(v.text if v is not None else "", style.get(c.get("s"), ""))
            cells[_col(ref)] = val
            if ref in links:
                cell_links[(len(rows), _col(ref))] = links[ref]
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows, cell_links


def import_xlsx(path: Path) -> dict:
    rows, links = read_xlsx(path)
    head = [_text(h).lower() for h in rows[0]]
    idx = {HEAD[h]: i for i, h in enumerate(head) if h in HEAD}
    missing = [h for h, f in HEAD.items() if f not in idx]
    if missing:
        raise SystemExit(f"в таблице нет столбцов: {', '.join(missing)}")
    out = []
    for n, r in enumerate(rows[1:], 1):
        rec = {f: _text(r[i]) if i < len(r) else "" for f, i in idx.items()}
        # «Сайт» в таблице — слово со ссылкой: берём саму ссылку. У почт ссылки не берём — там бывают чужие (mail.ru/compose…)
        site = links.get((n, idx["site"]))
        if site:
            rec["site"] = site
        if not any(rec.values()):
            continue
        rec = {"id": f"v{len(out) + 1}", **rec}
        out.append(rec)
    data = {"imported": datetime.now().isoformat(timespec="seconds"), "source": Path(path).name, "rows": out}
    save_json(FILE, data)
    return data


def load() -> dict:
    return load_json(FILE, {"rows": []})


def export_js() -> str:
    d = load()
    out = {"imported": d.get("imported"), "source": d.get("source"), "rows": d.get("rows", [])}
    return ("// Справочник площадок (competitors/venuebook.py, config/venue_book.json — вне git: контакты)\n"
            f"var VBOOK = {json.dumps(out, ensure_ascii=False, separators=(',', ':'))};\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "import":
        d = import_xlsx(Path(sys.argv[2]))
        print(f"загружено площадок: {len(d['rows'])} → {FILE}")
    else:
        print(__doc__)
