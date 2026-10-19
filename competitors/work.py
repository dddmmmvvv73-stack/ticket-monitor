"""
Раздел «Проекты» — ведение своих проектов (решение пользователя 19.10.2026: «прям буквально простое», чтобы перенести
и проставить реальные задачи; дальше — CRM ведения гастролей, устройство пропишет пользователь).

Три списка:
- проекты — название, стадия, даты, заметка;
- задачи — что сделать, дедлайн, проект, готово;
- документы — только статусы (файлы у пользователя на компьютере): документ, с кем, статус, сумма, оплата, закрывающие.

Хранится в config/work.json — вне git (деньги, контрагенты), в копиях config/ каждые 15 минут и снимках по дням и месяцам;
каждая правка — в журнале изменений (competitors/journal.py, область «work»), её можно вернуть.
    {"projects": {номер: {"title", "stage", "start", "end", "deadline" — дедлайн готовности проекта, "note", "upd",
                          "media": {"avatar" | "cover": файл?v=метка},
                          "pfiles": {"rider" | "logistics" | "timing": {"file", "name", "size", "at"}}}},
     "tasks":    {номер: {"text", "due", "project", "done", "done_at", "note", "created", "upd",
                          "desc" — описание, "subs": [{"id", "text", "done"}] — подзадачи,
                          "time" — затрачено, секунд; "run" — таймер идёт с (ISO-время) или пусто; "est" — план, минут,
                          "prio" — приоритет: high | mid | low | пусто}},
     "docs":     {номер: {"project", "kind", "party", "status", "amount", "pay", "closing", "note", "upd"}},
     "tags":     {номер: {"name", "color"}},
     "costs":    {номер: {"project", "name" — статья, "party" — кому, "amount", "date", "paid", "note", "upd"}},
     "notes":    {номер: {"project", "title", "body", "created", "upd"}}}   ← с чем связана задача; у задачи — "tags": [номера]; пока своих нет — DEFAULT_TAGS

    GET  /api/work                                   всё
    POST /api/work {"op": "put", "kind", "id", "data"}   запись целиком (проверяется)
                   {"op": "del", "kind", "id"}
                   {"op": "media", "kind": "projects", "id", "what": "avatar" | "cover", "data"}   фото проекта
    GET  /api/work/file/<файл>                     фото проекта (config/work_media/, вне git)
"""

from __future__ import annotations

import base64
import re
import threading
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "work.json"
KINDS = ("projects", "tasks", "docs", "tags", "costs", "notes")
# Цвета тегов. Красный и оранжевый — только у приоритета (решение пользователя 19.10: полоса слева — по тегу, и красная
# полоса не должна читаться как «срочно»); прежние теги этих цветов перекрашиваются при чтении (RECOLOR)
COLORS = ("blue", "green", "violet", "teal", "pink", "amber", "indigo", "brown", "gray")
RECOLOR = {"red": "indigo", "orange": "brown"}
DEFAULT_TAGS = {"tgcontract": {"name": "Договоры", "color": "blue"}, "tgmoney": {"name": "Финансы", "color": "green"},
                "tgvenue": {"name": "Площадка", "color": "violet"}, "tglogist": {"name": "Логистика", "color": "brown"},
                "tgtech": {"name": "Техника", "color": "teal"}, "tgpromo": {"name": "Реклама", "color": "pink"},
                "tgtickets": {"name": "Билеты", "color": "amber"}, "tgartist": {"name": "Артист", "color": "indigo"}}
STAGES = ["idea", "talks", "prep", "sales", "live", "closing", "done"]
DOC_STATUS = ["draft", "sent", "signed"]
PAY = ["no", "part", "paid"]
PRIO = ["", "low", "mid", "high"]
CLOSING = ["no", "got"]
TEXT_MAX = 3000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
SUBS_MAX = 200
_ID = re.compile(r"^[a-z0-9]{3,40}$")
_lock = threading.Lock()
MEDIA_DIR = CONFIG_DIR / "work_media"   # фото проектов (миниатюра, фон шапки) — вне git, в копиях config/
MEDIA_KINDS = ("avatar", "cover")
PHOTO_MAX = 3 * 1024 * 1024
PHOTO_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp"}
FILE_NAME = re.compile(r"^[a-z0-9]{3,40}-(avatar|cover|rider|logistics|timing)\.[a-z0-9]{2,5}$")
DOC_KINDS = ("rider", "logistics", "timing")   # документы проекта: технический райдер, логистика, тайминг
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "webp", "rtf", "odt", "ods", "txt", "zip"}
DOC_MAX = 15 * 1024 * 1024


class WorkError(ValueError):
    pass


def load() -> dict:
    d = load_json(FILE, {})
    out = {k: d.get(k) or {} for k in KINDS}
    if "tags" not in d:   # своих тегов ещё не заводили — стандартные (с первой правкой тегов сохраняются в файл)
        out["tags"] = {k: dict(v) for k, v in DEFAULT_TAGS.items()}
    for t in out["tags"].values():
        t["color"] = RECOLOR.get(t.get("color"), t.get("color"))
    return out


def _text(v, what: str, limit: int = TEXT_MAX) -> str:
    v = str(v if v is not None else "").replace("\r\n", "\n").strip()
    if len(v) > limit:
        raise WorkError(f"{what}: не больше {limit} знаков")
    return v


def _date(v, what: str) -> str:
    v = str(v or "").strip()
    if v and (not _DATE.match(v) or not _valid_date(v)):
        raise WorkError(f"{what}: дата вида ГГГГ-ММ-ДД")
    return v


def _valid_date(v: str) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _amount(v):
    if v in (None, ""):
        return None
    try:
        v = round(float(str(v).replace(" ", "").replace("\xa0", "").replace(",", ".")), 2)
    except ValueError:
        raise WorkError("сумма: нужно число") from None
    if not 0 <= v <= 1e10:
        raise WorkError("сумма: от 0 до 10 млрд")
    return v


def _int(v, what: str, lo: int, hi: int) -> int:
    if v in (None, ""):
        return 0
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        raise WorkError(f"{what}: нужно число") from None
    if not lo <= v <= hi:
        raise WorkError(f"{what}: вне допустимого")
    return v


def _stamp(v) -> str:
    v = str(v or "").strip()
    if v and not _STAMP.match(v):
        raise WorkError("таймер: неверное время")
    return v


def _subs(v) -> list:
    """Подзадачи: [{"id", "text", "done"}] — пустые строки отбрасываются."""
    if not v:
        return []
    if not isinstance(v, list) or len(v) > SUBS_MAX:
        raise WorkError(f"подзадачи: не больше {SUBS_MAX}")
    out = []
    for s in v:
        if not isinstance(s, dict):
            raise WorkError("подзадачи: неверный формат")
        text = _text(s.get("text"), "подзадача", 500)
        sid = str(s.get("id") or "")
        if not text:
            continue
        if not _ID.match(sid):
            raise WorkError("подзадачи: неверный номер")
        out.append({"id": sid, "text": text, "done": bool(s.get("done"))})
    return out


def _enum(v, allowed: list, what: str, default: str) -> str:
    v = str(v or default)
    if v not in allowed:
        raise WorkError(f"{what}: неизвестное значение")
    return v


def _validate(kind: str, d: dict, data: dict) -> dict:
    if kind == "projects":
        out = {"title": _text(d.get("title"), "название", 300), "stage": _enum(d.get("stage"), STAGES, "стадия", "idea"),
               "start": _date(d.get("start"), "начало"), "end": _date(d.get("end"), "окончание"),
               "deadline": _date(d.get("deadline"), "дедлайн"), "note": _text(d.get("note"), "заметка")}
        if not out["title"]:
            raise WorkError("у проекта нужно название")
        return out
    if kind in ("costs", "notes"):
        pid = str(d.get("project") or "")
        if pid and pid not in data["projects"]:
            raise WorkError("такого проекта нет")
        if kind == "notes":
            out = {"project": pid, "title": _text(d.get("title"), "название", 200), "body": _text(d.get("body"), "заметка", 50000),
                   "created": _date(d.get("created"), "создана") or datetime.now().strftime("%Y-%m-%d")}
            return out
        out = {"project": pid, "name": _text(d.get("name"), "статья", 300), "party": _text(d.get("party"), "кому", 300),
               "amount": _amount(d.get("amount")), "date": _date(d.get("date"), "дата"), "paid": bool(d.get("paid")),
               "note": _text(d.get("note"), "заметка")}
        if not (out["name"] or out["party"]):
            raise WorkError("у расхода нужна статья или получатель")
        return out
    if kind == "tags":
        out = {"name": _text(d.get("name"), "тег", 40), "color": _enum(d.get("color"), list(COLORS), "цвет", "gray")}
        if not out["name"]:
            raise WorkError("у тега нужно название")
        return out
    if kind == "tasks":
        pid = str(d.get("project") or "")
        if pid and pid not in data["projects"]:
            raise WorkError("такого проекта нет")
        out = {"text": _text(d.get("text"), "задача", 1000), "due": _date(d.get("due"), "дедлайн"), "project": pid,
               "done": bool(d.get("done")), "note": _text(d.get("note"), "заметка"),
               "created": _date(d.get("created"), "создана") or datetime.now().strftime("%Y-%m-%d"),
               "desc": _text(d.get("desc"), "описание", 20000), "subs": _subs(d.get("subs")),
               "time": _int(d.get("time"), "время", 0, 10 ** 8), "run": _stamp(d.get("run")), "est": _int(d.get("est"), "план", 0, 10 ** 6),
               "tags": [t for t in (d.get("tags") or []) if t in data["tags"]][:12],
               "prio": _enum(d.get("prio"), PRIO, "приоритет", "")}
        if not out["text"]:
            raise WorkError("у задачи нужен текст")
        if out["done"]:
            out["done_at"] = _date(d.get("done_at"), "сделано") or datetime.now().strftime("%Y-%m-%d")
        return out
    pid = str(d.get("project") or "")
    if pid and pid not in data["projects"]:
        raise WorkError("такого проекта нет")
    out = {"project": pid, "kind": _text(d.get("kind"), "документ", 200), "party": _text(d.get("party"), "с кем", 300),
           "status": _enum(d.get("status"), DOC_STATUS, "статус", "draft"), "amount": _amount(d.get("amount")),
           "pay": _enum(d.get("pay"), PAY, "оплата", "no"), "closing": _enum(d.get("closing"), CLOSING, "закрывающие", "no"),
           "note": _text(d.get("note"), "заметка")}
    if not (out["kind"] or out["party"]):
        raise WorkError("у документа нужно название или контрагент")
    return out


def apply_op(op: dict) -> dict:
    kind, oid = op.get("kind"), str(op.get("id") or "")
    if kind not in KINDS:
        raise WorkError("неизвестный список")
    if not _ID.match(oid):
        raise WorkError("неверный номер записи")
    with _lock:
        data = load()
        if op.get("op") == "put":
            rec = _validate(kind, op.get("data") or {}, data)
            rec["upd"] = datetime.now().isoformat(timespec="seconds")
            for keep in ("media", "pfiles"):   # фото и документы проекта меняются отдельно — правка полей их не трогает
                if kind == "projects" and (data[kind].get(oid) or {}).get(keep):
                    rec[keep] = data[kind][oid][keep]
                elif kind == "projects" and oid not in data[kind] and isinstance((op.get("data") or {}).get(keep), dict):
                    rec[keep] = _own_files(oid, op["data"][keep], keep)   # «Вернуть» удалённый проект: его файлы остались на диске
            data[kind][oid] = rec
        elif op.get("op") == "media":   # фото проекта: what — avatar | cover; data — data:image/…;base64 (пусто — убрать)
            p = data["projects"].get(oid)
            what = str(op.get("what") or "")
            if kind != "projects" or not p or what not in MEDIA_KINDS:
                raise WorkError("фото: нет такого проекта")
            raw = ext = None
            if op.get("data"):
                m = re.match(r"^data:image/[\w.+-]+;base64,([A-Za-z0-9+/=]+)$", str(op["data"]))
                raw = base64.b64decode(m.group(1)) if m else b""
                ext = next((e for sig, e in PHOTO_TYPES.items() if raw.startswith(sig)), None)
                if not ext or len(raw) > PHOTO_MAX:
                    raise WorkError("фото: нужен JPEG, PNG или WebP до 3 МБ")
            for old in MEDIA_DIR.glob(f"{oid}-{what}.*"):
                old.unlink()
            media = p.setdefault("media", {})
            if raw is None:
                media.pop(what, None)
            else:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                (MEDIA_DIR / f"{oid}-{what}.{ext}").write_bytes(raw)
                media[what] = f"{oid}-{what}.{ext}?v={int(datetime.now().timestamp())}"
            if not media:
                p.pop("media", None)
            p["upd"] = datetime.now().isoformat(timespec="seconds")
        elif op.get("op") == "pfile":   # документ проекта: what — rider | logistics | timing; name — имя файла; data — base64 (пусто — убрать)
            p = data["projects"].get(oid)
            what = str(op.get("what") or "")
            if kind != "projects" or not p or what not in DOC_KINDS:
                raise WorkError("документ: нет такого проекта")
            name = _text(op.get("name"), "имя файла", 200)
            raw = ext = None
            if op.get("data"):
                m = re.match(r"^data:[\w.+/-]*;base64,([A-Za-z0-9+/=]+)$", str(op["data"]))
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if not m or ext not in DOC_EXT:
                    raise WorkError("документ: PDF, Word, Excel, картинка или архив")
                raw = base64.b64decode(m.group(1))
                if len(raw) > DOC_MAX:
                    raise WorkError("документ: не больше 15 МБ")
            for old in MEDIA_DIR.glob(f"{oid}-{what}.*"):
                old.unlink()
            files = p.setdefault("pfiles", {})
            if raw is None:
                files.pop(what, None)
            else:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                (MEDIA_DIR / f"{oid}-{what}.{ext}").write_bytes(raw)
                files[what] = {"file": f"{oid}-{what}.{ext}", "name": name, "size": len(raw), "at": datetime.now().isoformat(timespec="seconds")}
            if not files:
                p.pop("pfiles", None)
            p["upd"] = datetime.now().isoformat(timespec="seconds")
        elif op.get("op") == "del":
            data[kind].pop(oid, None)
            if kind == "tags":   # убрали тег — снимается и с задач
                for r in data["tasks"].values():
                    if oid in (r.get("tags") or []):
                        r["tags"] = [t for t in r["tags"] if t != oid]
            if kind == "projects":   # задачи и документы проекта остаются — «без проекта»
                for k in ("tasks", "docs", "costs", "notes"):
                    for r in data[k].values():
                        if r.get("project") == oid:
                            r["project"] = ""
        else:
            raise WorkError("неизвестная операция")
        save_json(FILE, data)
        return data


def _own_files(oid: str, given: dict, keep: str) -> dict:
    """Ссылки на файлы проекта из возвращаемой записи — только свои (имя начинается с номера проекта) и только если файл есть."""
    out = {}
    for k, v in given.items():
        name = (v.split("?")[0] if keep == "media" else (v or {}).get("file", "")) if v else ""
        if name.startswith(oid + "-") and FILE_NAME.match(name) and (MEDIA_DIR / name).is_file():
            out[k] = v
    return out


def doc_name(name: str) -> str:
    """Под каким именем отдавать документ проекта при скачивании — как его загружали."""
    for p in load()["projects"].values():
        for f in (p.get("pfiles") or {}).values():
            if f.get("file") == name:
                return f.get("name") or name
    return name


def media_file(name: str):
    if not FILE_NAME.match(name or ""):
        return None
    path = MEDIA_DIR / name
    return path if path.is_file() else None
