"""
Раздел «Проекты» — ведение своих проектов (решение пользователя 19.10.2026: «прям буквально простое», чтобы перенести
и проставить реальные задачи; дальше — CRM ведения гастролей, устройство пропишет пользователь).

Три списка:
- проекты — название, стадия, даты, заметка;
- задачи — что сделать, дедлайн, проект, готово;
- документы — только статусы (файлы у пользователя на компьютере): документ, с кем, статус, сумма, оплата, закрывающие.

Хранится в config/work.json — вне git (деньги, контрагенты), в копиях config/ каждые 15 минут и снимках по дням и месяцам;
каждая правка — в журнале изменений (competitors/journal.py, область «work»), её можно вернуть.
    {"projects": {номер: {"title", "stage", "start", "end", "note", "upd"}},
     "tasks":    {номер: {"text", "due", "project", "done", "done_at", "note", "created", "upd",
                          "desc" — описание, "subs": [{"id", "text", "done"}] — подзадачи,
                          "time" — затрачено, секунд; "run" — таймер идёт с (ISO-время) или пусто; "est" — план, минут}},
     "docs":     {номер: {"project", "kind", "party", "status", "amount", "pay", "closing", "note", "upd"}},
     "tags":     {номер: {"name", "color"}}}   ← с чем связана задача; у задачи — "tags": [номера]; пока своих нет — DEFAULT_TAGS

    GET  /api/work                                   всё
    POST /api/work {"op": "put", "kind", "id", "data"}   запись целиком (проверяется)
                   {"op": "del", "kind", "id"}
"""

from __future__ import annotations

import re
import threading
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "work.json"
KINDS = ("projects", "tasks", "docs", "tags")
COLORS = ("blue", "green", "violet", "orange", "teal", "pink", "amber", "red", "gray")
DEFAULT_TAGS = {"tgcontract": {"name": "Договоры", "color": "blue"}, "tgmoney": {"name": "Финансы", "color": "green"},
                "tgvenue": {"name": "Площадка", "color": "violet"}, "tglogist": {"name": "Логистика", "color": "orange"},
                "tgtech": {"name": "Техника", "color": "teal"}, "tgpromo": {"name": "Реклама", "color": "pink"},
                "tgtickets": {"name": "Билеты", "color": "amber"}, "tgartist": {"name": "Артист", "color": "red"}}
STAGES = ["idea", "talks", "prep", "sales", "live", "closing", "done"]
DOC_STATUS = ["draft", "sent", "signed"]
PAY = ["no", "part", "paid"]
CLOSING = ["no", "got"]
TEXT_MAX = 3000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
SUBS_MAX = 200
_ID = re.compile(r"^[a-z0-9]{3,40}$")
_lock = threading.Lock()


class WorkError(ValueError):
    pass


def load() -> dict:
    d = load_json(FILE, {})
    out = {k: d.get(k) or {} for k in KINDS}
    if "tags" not in d:   # своих тегов ещё не заводили — стандартные (с первой правкой тегов сохраняются в файл)
        out["tags"] = {k: dict(v) for k, v in DEFAULT_TAGS.items()}
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
               "start": _date(d.get("start"), "начало"), "end": _date(d.get("end"), "окончание"), "note": _text(d.get("note"), "заметка")}
        if not out["title"]:
            raise WorkError("у проекта нужно название")
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
               "tags": [t for t in (d.get("tags") or []) if t in data["tags"]][:12]}
        if not out["text"]:
            raise WorkError("у задачи нужен текст")
        if out["done"]:
            out["done_at"] = _date(d.get("done_at"), "сделано") or datetime.now().strftime("%Y-%m-%d")
        return out
    pid = str(d.get("project") or "")
    if pid and pid not in data["projects"]:
        raise WorkError("такого проекта нет")
    amount = d.get("amount")
    if amount in (None, ""):
        amount = None
    else:
        try:
            amount = round(float(str(amount).replace(" ", "").replace("\xa0", "").replace(",", ".")), 2)
        except ValueError:
            raise WorkError("сумма: нужно число") from None
        if not 0 <= amount <= 1e10:
            raise WorkError("сумма: от 0 до 10 млрд")
    out = {"project": pid, "kind": _text(d.get("kind"), "документ", 200), "party": _text(d.get("party"), "с кем", 300),
           "status": _enum(d.get("status"), DOC_STATUS, "статус", "draft"), "amount": amount,
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
            data[kind][oid] = rec
        elif op.get("op") == "del":
            data[kind].pop(oid, None)
            if kind == "tags":   # убрали тег — снимается и с задач
                for r in data["tasks"].values():
                    if oid in (r.get("tags") or []):
                        r["tags"] = [t for t in r["tags"] if t != oid]
            if kind == "projects":   # задачи и документы проекта остаются — «без проекта»
                for k in ("tasks", "docs"):
                    for r in data[k].values():
                        if r.get("project") == oid:
                            r["project"] = ""
        else:
            raise WorkError("неизвестная операция")
        save_json(FILE, data)
        return data
