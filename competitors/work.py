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
     "tasks":    {номер: {"text", "due", "project", "done", "done_at", "note", "created", "upd"}},
     "docs":     {номер: {"project", "kind", "party", "status", "amount", "pay", "closing", "note", "upd"}}}

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
KINDS = ("projects", "tasks", "docs")
STAGES = ["idea", "talks", "prep", "sales", "live", "closing", "done"]
DOC_STATUS = ["draft", "sent", "signed"]
PAY = ["no", "part", "paid"]
CLOSING = ["no", "got"]
TEXT_MAX = 3000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[a-z0-9]{3,40}$")
_lock = threading.Lock()


class WorkError(ValueError):
    pass


def load() -> dict:
    d = load_json(FILE, {})
    return {k: d.get(k) or {} for k in KINDS}


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
    if kind == "tasks":
        pid = str(d.get("project") or "")
        if pid and pid not in data["projects"]:
            raise WorkError("такого проекта нет")
        out = {"text": _text(d.get("text"), "задача", 1000), "due": _date(d.get("due"), "дедлайн"), "project": pid,
               "done": bool(d.get("done")), "note": _text(d.get("note"), "заметка"),
               "created": _date(d.get("created"), "создана") or datetime.now().strftime("%Y-%m-%d")}
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
            if kind == "projects":   # задачи и документы проекта остаются — «без проекта»
                for k in ("tasks", "docs"):
                    for r in data[k].values():
                        if r.get("project") == oid:
                            r["project"] = ""
        else:
            raise WorkError("неизвестная операция")
        save_json(FILE, data)
        return data
