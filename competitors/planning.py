"""
«Планирование» — финансовая модель туров (TOUR_PLANNER.md, раздел 3; решения пользователя 12.10.2026).

Ручной ввод: справочники и туры заводит пользователь; автоматика (вместимость, вал, конкуренция) — после утверждения
модели. Формулы — в прототипе (Design/prototype/plan-model.js, тест tests/plan-model.test.js); здесь только хранение и
проверка ввода.

Хранится в config/planning.json — вне git (коммерческие данные: гонорары, аренда), в часовой закрытой копии (db.offsite):
    {"params":   {"tax", "classes": [[класс, порог]…], "scenarios": [%…], "base", "weights": {…}, "ban_months"},
     "projects": {номер: {"title", "key", "fee", "cashless", "per_diem", "crew", "author", "rao_on", "rao", "moscow", "note"}},
     "regions":  {номер: {"title", "logistics", "note"}},
     "cities":   {город: {"region", "kassa", "org": {"transfer"…"other"}, "note"}},
     "venues":   {ключ площадки «город|название»: {"city", "venue", "seats", "gross", "rent", "note",
                  "zones": [{"name", "seats"}] — шаблон поясов зала}},   ← раздел «Площадки»
     "tours":    {номер: {"title", "project", "month", "status", "note", "rows": [строка]}}}
    строка тура: {"id", "city", "venue", "date", "days", "fill", "ads", "agent",
                  "ovr": {поле справочника: значение — правка в этой строке},
                  "scores": {"comp", "ads", "attract", "market", "prep"}, "cannibal", "region_ban", "last_show", "decision", "note",
                  "zmode": вал по распоясовке, "zones": [{"name", "price", "seats", "fill" — своя заполняемость пояса}]}

    GET  /api/planning                      всё хранилище
    POST /api/planning  {"op": "put", "kind", "id", "data"}   запись целиком (проверяется по схеме)
                        {"op": "del", "kind", "id"}
"""

from __future__ import annotations

import re
import threading
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "planning.json"
KINDS = ("params", "projects", "regions", "cities", "venues", "tours")
ORG = ("transfer", "hotel", "tech", "catering", "loaders", "security", "services", "other")
SCORES = ("comp", "ads", "attract", "market", "prep")
STATUSES = ("Черновик", "Планируется", "В процессе", "Подтверждён", "Отменён")
DECISIONS = ("", "В работу", "Отмена", "Замена города", "Перенос месяца", "Замена площадки")
MONEY = 1e10
_lock = threading.Lock()
_ID = re.compile(r"^[a-z0-9]{1,24}$")
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


class PlanningError(ValueError):
    pass


def load() -> dict:
    d = load_json(FILE, {})
    return {k: d.get(k) or {} for k in KINDS}


# ---------------------------------------------------------------- проверка ввода

def _num(v, what: str, lo: float = 0, hi: float = MONEY, empty_ok: bool = True):
    if v is None or v == "":
        if empty_ok:
            return None
        raise PlanningError(f"{what}: нужно число")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlanningError(f"{what}: нужно число")
    if not lo <= v <= hi:
        raise PlanningError(f"{what}: от {lo:g} до {hi:g}")
    return round(float(v), 4)


def _text(v, what: str, limit: int = 300) -> str:
    s = str(v or "").strip()
    if len(s) > limit:
        raise PlanningError(f"{what}: не длиннее {limit} знаков")
    return s


def _pct(v, what):
    return _num(v, what, 0, 100)


def _clean(d: dict, fields: dict, what: str) -> dict:
    """Только известные поля нужного вида; пустые — не храним."""
    if not isinstance(d, dict):
        raise PlanningError(f"{what}: неверный формат")
    out = {}
    for k, kind in fields.items():
        if k not in d:
            continue
        v = d[k]
        if kind == "money":
            v = _num(v, what)
        elif kind == "pct":
            v = _pct(v, what)
        elif kind == "int":
            v = _num(v, what, 0, 100000)
        elif kind == "bool":
            v = bool(v)
        elif kind == "date":
            v = _text(v, what, 10)
            if v and not _DATE.match(v):
                raise PlanningError(f"{what}: дата ГГГГ-ММ-ДД или месяц ГГГГ-ММ")
        elif kind == "score":
            v = _num(v, what, 1, 5)
        elif isinstance(kind, tuple):
            v = _text(v, what)
            if v not in kind:
                raise PlanningError(f"{what}: неизвестное значение «{v}»")
        else:
            v = _text(v, what, kind if isinstance(kind, int) else 300)
        if v not in (None, ""):
            out[k] = v
    return out


PROJECT = {"title": 200, "key": 300, "fee": "money", "cashless": "pct", "per_diem": "money", "crew": "int", "author": "money",
           "rao_on": "bool", "rao": "pct", "moscow": "money", "note": 2000}
REGION = {"title": 120, "logistics": "money", "note": 1000}
CITY = {"region": 24, "kassa": "pct", "note": 1000}
VENUE = {"city": 100, "venue": 200, "seats": "int", "gross": "money", "rent": "money", "note": 1000}
OVR = {"seats": "int", "gross": "money", "rent": "money", "logistics": "money", "kassa": "pct", "fee": "money", "cashless": "pct",
       "per_diem": "money", "crew": "int", "author": "money", "rao": "pct", "moscow": "money", **{o: "money" for o in ORG}}
ROW = {"id": 24, "city": 100, "venue": 300, "date": "date", "days": "int", "fill": "pct", "ads": "money", "agent": "pct",
       "cannibal": "bool", "region_ban": "bool", "last_show": "date", "decision": DECISIONS, "note": 1000, "zmode": "bool", "target": "money", "avg": "money"}
ZONE = {"name": 60, "price": "money", "seats": "int", "fill": "pct"}
ZONE_T = {"name": 60, "seats": "int"}


def _zones(v, fields: dict, what: str) -> list:
    """Пояса распоясовки: до 40, пустые строки (без названия, цены и мест) не храним."""
    if not isinstance(v, list) or len(v) > 40:
        raise PlanningError(f"{what}: до 40 поясов")
    return [z for z in (_clean(x or {}, fields, what) for x in v) if z]
TOUR = {"title": 200, "project": 24, "month": "date", "status": STATUSES, "note": 2000}


def _params(d: dict) -> dict:
    out = _clean(d, {"tax": "pct", "base": "int", "ban_months": "int", "target": "money"}, "параметры")
    if "classes" in d:
        cls = d["classes"]
        if not isinstance(cls, list) or not 1 <= len(cls) <= 6:
            raise PlanningError("классы: список порогов")
        out["classes"] = [[_text(c[0], "класс", 2), _num(c[1], "порог класса", -MONEY, MONEY, False)] for c in cls]
    if "scenarios" in d:
        sc = d["scenarios"]
        if not isinstance(sc, list) or not 1 <= len(sc) <= 5:
            raise PlanningError("сценарии: от 1 до 5 значений")
        out["scenarios"] = [_pct(x, "сценарий") for x in sc]
    if "weights" in d:
        out["weights"] = {k: _num(v, "вес", 0, 1, False) for k, v in (d["weights"] or {}).items() if k in ("fin",) + SCORES}
    return out


def _row(r: dict) -> dict:
    out = _clean(r, ROW, "строка тура")
    if not _ID.match(out.get("id", "")):
        raise PlanningError("строка тура: нет номера")
    ovr = _clean(r.get("ovr") or {}, OVR, "правка строки")
    if ovr:
        out["ovr"] = ovr
    sc = _clean(r.get("scores") or {}, {k: "score" for k in SCORES}, "оценка")
    if sc:
        out["scores"] = sc
    if r.get("zones"):
        out["zones"] = _zones(r["zones"], ZONE, "распоясовка")
    return out


def _validate(kind: str, data: dict) -> dict:
    if kind == "params":
        return _params(data)
    if kind == "projects":
        out = _clean(data, PROJECT, "проект")
        if not out.get("title"):
            raise PlanningError("проект: нужно название")
        return out
    if kind == "regions":
        out = _clean(data, REGION, "регион")
        if not out.get("title"):
            raise PlanningError("регион: нужно название")
        return out
    if kind == "cities":
        out = _clean(data, CITY, "город")
        org = _clean(data.get("org") or {}, {o: "money" for o in ORG}, "организационные затраты")
        if org:
            out["org"] = org
        return out
    if kind == "venues":
        out = _clean(data, VENUE, "площадка")
        if not out.get("city") or not out.get("venue"):
            raise PlanningError("площадка: нужны город и название")
        if data.get("zones"):
            out["zones"] = _zones(data["zones"], ZONE_T, "пояса площадки")
        return out
    out = _clean(data, TOUR, "тур")
    if not out.get("title"):
        raise PlanningError("тур: нужно название")
    rows = data.get("rows") or []
    if not isinstance(rows, list) or len(rows) > 300:
        raise PlanningError("тур: до 300 городов")
    out["rows"] = [_row(r) for r in rows]
    return out


def apply_op(op: dict) -> dict:
    kind, oid = op.get("kind"), str(op.get("id") or "")
    if kind not in KINDS:
        raise PlanningError("неизвестный справочник")
    if kind == "params":
        oid = "params"
    elif not oid or len(oid) > 300 or re.search(r"[\x00-\x1f]", oid):
        raise PlanningError("неверный номер записи")
    with _lock:
        data = load()
        if op.get("op") == "put":
            rec = _validate(kind, op.get("data") or {})
            rec["upd"] = datetime.now().isoformat(timespec="seconds")
            if kind == "params":
                data["params"] = rec
            else:
                data[kind][oid] = rec
        elif op.get("op") == "del":
            if kind == "params":
                data["params"] = {}
            else:
                data[kind].pop(oid, None)
        else:
            raise PlanningError("неизвестная операция")
        save_json(FILE, data)
        return data
