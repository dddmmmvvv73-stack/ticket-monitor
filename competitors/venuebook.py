"""
Справочник площадок — «Площадки → Площадки» в прототипе (решение пользователя 19.10.2026: новое пространство отдельно от
«Базы площадок РФ», потом соединить). Первая версия — столбцы таблицы пользователя «Площадки База данных с информацией»
(Google Таблица): город, площадка, юрлицо, ИНН, сайт, контакт, телефон, почта, мест, выход в продажу, аренда, агентский %,
директор. Значения — как в таблице (текст), разбор аренды и мест — позже. 19.10 (решения пользователя): правка на сайте —
окном «Редактировать» на странице площадки и прямо в ячейках таблицы; новые поля — ЭДО, размер сцены, административный
ряд; фото (миниатюра и фон шапки) и файл технического райдера.

Хранится в config/venue_book.json — вне git (контакты — персональные данные, репозиторий публичный), в часовой закрытой
копии (db.offsite, весь config/):
    {"imported": ISO-время, "source": имя файла, "rows": [{"id", "city", "name", "legal", "inn", "site", "contact",
                                                          "phone", "email", "seats", "sale", "rent", "agent", "director",
                                                          "edo" — full | in | none, "stage", "admin_row",
                                                          "light", "sound" — специалисты по свету и звуку,
                                                          "media": {"avatar" | "cover": файл?v=метка},
                                                          "rider": {"file", "name" — как назывался у вас, "size", "at"},
                                                          "edited": [поля, исправленные на сайте], "upd",
                                                          "added": true — площадка добавлена на сайте, а не из таблицы}]}
Фото и райдеры — файлами в config/venue_media/ (вне git, в часовой копии вместе с config/).

    python3 -m competitors.venuebook import <файл.xlsx>   загрузить из выгрузки Google Таблицы (Файл → Скачать → xlsx):
                                                         xlsx, а не csv — в csv теряются ссылки за словом «Сайт»
                                                         повторная загрузка не затирает исправленное на сайте
    GET  /proto/venue-book.js                             справочник для прототипа (competitors/market_api.py)
    POST /api/venuebook  {"op": "add", "data": {поле: значение}}   новая площадка (город и название обязательны; 27.10)
                         {"op": "set", "id", "data": {поле: значение}, "undo"?}   правка полей (undo — отмена ⌘Z / Ctrl+Z)
                         {"op": "media", "id", "kind": "avatar" | "cover", "data": data:image/…;base64 | ""}
                         {"op": "rider", "id", "name", "data": data:…;base64 | ""}
    GET  /api/venuebook/file/<файл>                       фото или райдер
"""

from __future__ import annotations

import base64
import json
import re
import sys
import threading
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
EXTRA = ["edo", "stage", "admin_row", "light", "sound"]   # поля, которых нет в таблице пользователя — только на сайте
EDO = {"full": "полное", "in": "только входящий", "none": "не работают"}
TEXT_MAX = 3000
MEDIA_DIR = CONFIG_DIR / "venue_media"
MEDIA_KINDS = ("avatar", "cover")
PHOTO_MAX = 3 * 1024 * 1024        # прототип присылает уже уменьшенное (~100–400 КБ)
RIDER_MAX = 15 * 1024 * 1024
RIDER_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "webp", "rtf", "odt", "txt", "zip"}
PHOTO_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp"}
FILE_NAME = re.compile(r"^v\d{1,6}-(avatar|cover|rider)\.[a-z0-9]{2,5}$")
_lock = threading.Lock()


class VenueBookError(ValueError):
    pass
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
    prev = {_key(r): r for r in load().get("rows", [])}   # исправленное на сайте и поля сайта — не затираем
    used, out = set(), []
    for n, r in enumerate(rows[1:], 1):
        rec = {f: _text(r[i]) if i < len(r) else "" for f, i in idx.items()}
        # «Сайт» в таблице — слово со ссылкой: берём саму ссылку. У почт ссылки не берём — там бывают чужие (mail.ru/compose…)
        site = links.get((n, idx["site"]))
        if site:
            rec["site"] = site
        if not any(rec.values()):
            continue
        old = prev.get(_key(rec))
        if old and old["id"] not in used:
            used.add(old["id"])
            for f in old.get("edited", []):
                rec[f] = old.get(f, "")
            rec = {"id": old["id"], **rec, **{k: old[k] for k in EXTRA + ["media", "rider", "edited", "upd"] if k in old}}
        else:
            rec = {"id": "", **rec}
        out.append(rec)
    # добавленные на сайте, которых в таблице нет, остаются; номер не переиспользуется — на него ссылается «Работа»
    out += [r for r in prev.values() if r.get("added") and r["id"] not in used]
    n_id = max([int(r["id"][1:]) for r in out if r["id"]] + [0])
    for r in out:
        if not r["id"]:
            n_id += 1
            r["id"] = f"v{n_id}"
    data = {"imported": datetime.now().isoformat(timespec="seconds"), "source": Path(path).name, "rows": out}
    save_json(FILE, data)
    return data


def _key(r: dict) -> str:
    norm = lambda v: re.sub(r"[^0-9a-zа-я]", "", (v or "").lower().replace("ё", "е"))
    return norm(r.get("city")) + "|" + norm(r.get("name"))


def load() -> dict:
    return load_json(FILE, {"rows": []})


def _find(d: dict, vid: str) -> dict:
    for r in d.get("rows", []):
        if r.get("id") == vid:
            return r
    raise VenueBookError("нет такой площадки")


def _decode(data: str, what: str) -> bytes:
    m = re.match(r"^data:[\w.+/-]*;base64,([A-Za-z0-9+/=]+)$", data or "")
    if not m:
        raise VenueBookError(f"{what}: файл не прочитался")
    return base64.b64decode(m.group(1))


def _drop(vid: str, kind: str) -> None:
    for old in MEDIA_DIR.glob(f"{vid}-{kind}.*"):
        old.unlink()


def _clean(f: str, v, undo: bool = False) -> str:
    if f not in FIELDS + EXTRA:
        raise VenueBookError(f"неизвестное поле: {f}")
    v = _text(str(v if v is not None else ""))
    if len(v) > TEXT_MAX:
        raise VenueBookError(f"слишком длинно: не больше {TEXT_MAX} знаков")
    if f == "edo" and v not in ("", *EDO):
        raise VenueBookError("ЭДО: полное, только входящий или не работают")
    if f in ("city", "name") and not v and not undo:   # отмена (⌘Z) возвращает и пустое, как было
        raise VenueBookError("город и название площадки не могут быть пустыми")
    return v


def _add(d: dict, data) -> dict:
    """Новая площадка с сайта: город и название обязательны, такой же пары город + название в справочнике быть не должно."""
    if not isinstance(data, dict):
        raise VenueBookError("нечего сохранять")
    for f in data:
        _clean(f, "x")   # неизвестное поле — ошибка, как в правке
    rec = {f: _clean(f, data.get(f, "")) for f in FIELDS}
    rec.update({f: _clean(f, data[f]) for f in EXTRA if data.get(f)})
    rows = d.setdefault("rows", [])
    same = next((r for r in rows if _key(r) == _key(rec)), None)
    if same:
        raise VenueBookError(f"«{same.get('name')}» в городе {same.get('city')} уже есть в справочнике")
    n_id = max([int(r["id"][1:]) for r in rows if str(r.get("id", ""))[1:].isdigit()] + [0]) + 1
    rec = {"id": f"v{n_id}", **rec, "added": True}
    rows.append(rec)
    return rec


def apply_op(op: dict) -> dict:
    """Одна правка с сайта → обновлённая запись площадки. Ошибка проверки — VenueBookError (текст — для человека)."""
    kind, vid = op.get("op"), str(op.get("id") or "")
    with _lock:
        d = load()
        if kind == "add":
            rec = _add(d, op.get("data"))
            rec["upd"] = datetime.now().isoformat(timespec="seconds")
            save_json(FILE, d)
            return rec
        rec = _find(d, vid)
        if kind == "set":
            data = op.get("data")
            if not isinstance(data, dict) or not data:
                raise VenueBookError("нечего сохранять")
            for f, v in data.items():
                v = _clean(f, v, bool(op.get("undo")))
                rec[f] = v
                if f in FIELDS and f not in rec.setdefault("edited", []):
                    rec["edited"].append(f)
        elif kind == "media":
            what = str(op.get("kind") or "")
            if what not in MEDIA_KINDS:
                raise VenueBookError("неизвестный вид фото")
            media = rec.setdefault("media", {})
            raw = _decode(op["data"], "фото") if op.get("data") else None
            ext = raw and next((e for sig, e in PHOTO_TYPES.items() if raw.startswith(sig)), None)
            if raw is not None and (len(raw) > PHOTO_MAX or not ext):
                raise VenueBookError("фото: нужен JPEG, PNG или WebP до 3 МБ")
            _drop(vid, what)
            if raw is None:
                media.pop(what, None)
            else:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                (MEDIA_DIR / f"{vid}-{what}.{ext}").write_bytes(raw)
                media[what] = f"{vid}-{what}.{ext}?v={int(datetime.now().timestamp())}"
            if not media:
                rec.pop("media", None)
        elif kind == "rider":
            name = _text(str(op.get("name") or ""))[:200]
            raw = _decode(op["data"], "райдер") if op.get("data") else None
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if raw is not None:
                if ext not in RIDER_EXT:
                    raise VenueBookError("райдер: PDF, Word, Excel, картинка или архив")
                if len(raw) > RIDER_MAX:
                    raise VenueBookError("райдер: не больше 15 МБ")
            _drop(vid, "rider")
            if raw is None:
                rec.pop("rider", None)
            else:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                (MEDIA_DIR / f"{vid}-rider.{ext}").write_bytes(raw)
                rec["rider"] = {"file": f"{vid}-rider.{ext}", "name": name, "size": len(raw),
                                "at": datetime.now().isoformat(timespec="seconds")}
        else:
            raise VenueBookError("неизвестная правка")
        rec["upd"] = datetime.now().isoformat(timespec="seconds")
        save_json(FILE, d)
        return rec


def media_file(name: str):
    """Путь к фото или райдеру для выдачи; None — имя не наше или файла нет."""
    if not FILE_NAME.match(name or ""):
        return None
    path = MEDIA_DIR / name
    return path if path.is_file() else None


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
