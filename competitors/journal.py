"""
Журнал изменений (решение пользователя 19.10.2026: «чтобы данные были всегда актуальными и не пропадали»).

Каждая правка с сайта в справочнике площадок (venuebook), «Планировании» (planning), карточках проектов (myprojects) и
разделе «Проекты» — задачи, проекты, документы, гастроли (work)
записывается строкой «когда · где · какая запись · поля: было → стало». Любую правку можно вернуть — записи
возвращаются значения до неё (сам возврат — тоже строка журнала, его можно отменить так же).

Хранится в config/history/changes-ГГГГ-ММ.jsonl (по месяцу на файл, только дописывается) — вне git, в копиях вместе с
config/ (каждые 15 минут и ежедневные / ежемесячные снимки, db/offsite.py).

    GET  /api/journal?area=&key=&limit=   последние правки (новые сверху)
    POST /api/journal/restore {"id"}      вернуть значения до правки

Файлы (фото, технический райдер) журнал отмечает, но не возвращает: прежний файл при замене удаляется.
"""

from __future__ import annotations

import copy
import json
import secrets
from datetime import datetime

from competitors import myprojects, planning, venuebook, work
from competitors.storage import CONFIG_DIR, save_json

DIR = CONFIG_DIR / "history"
NOISE = {"upd", "edited", "at", "snap", "rating_hist"}   # служебное — не показываем и не возвращаем
FILES = {"media", "rider", "pfiles"}                               # файлы: отмечаем, не возвращаем
MONTHS_READ = 13                                         # сколько месячных файлов читать при показе


class JournalError(ValueError):
    pass


# ---------------------------------------------------------------- области: как достать записи и как записать обратно
def _venues_map(d):
    return {r["id"]: r for r in d.get("rows", [])}


def _venues_set(d, key, rec):
    rows = d.setdefault("rows", [])
    for i, r in enumerate(rows):
        if r.get("id") == key:
            if rec is None:
                rows.pop(i)
            else:
                rows[i] = rec
            return
    if rec is not None:
        rows.append(rec)


def _plan_map(d):
    out = {}
    for kind in planning.KINDS:
        v = d.get(kind) or {}
        if kind == "params":
            if v:
                out["params/params"] = v
        else:
            out.update({f"{kind}/{k}": r for k, r in v.items()})
    return out


def _plan_set(d, key, rec):
    kind, oid = key.split("/", 1)
    if kind == "params":
        d["params"] = rec or {}
    elif rec is None:
        d.setdefault(kind, {}).pop(oid, None)
    else:
        d.setdefault(kind, {})[oid] = rec


def _proj_map(d):
    return dict(d.get("projects") or {})


def _proj_set(d, key, rec):
    if rec is None:
        d.setdefault("projects", {}).pop(key, None)
    else:
        d.setdefault("projects", {})[key] = rec


def _work_map(d):
    return {f"{kind}/{k}": r for kind in work.KINDS for k, r in (d.get(kind) or {}).items()}


def _work_set(d, key, rec):
    kind, oid = key.split("/", 1)
    if rec is None:
        d.setdefault(kind, {}).pop(oid, None)
    else:
        d.setdefault(kind, {})[oid] = rec


WORK_KIND = {"projects": "Проект", "tasks": "Задача", "docs": "Документ", "tags": "Тег", "costs": "Расход", "notes": "Заметка", "shows": "Гастроли", "stages": "Статус проекта", "parties": "Контрагент"}
PLAN_KIND = {"params": "Параметры", "projects": "Проект (финмодель)", "regions": "Регион", "cities": "Город",
             "venues": "Площадка (финмодель)", "tours": "Тур", "lists": "Список гастролей", "routes": "Маршрут"}

AREAS = {
    "venues": {"label": "Справочник площадок", "load": venuebook.load, "file": venuebook.FILE, "lock": venuebook._lock,
               "map": _venues_map, "set": _venues_set,
               "title": lambda k, r: ", ".join(x for x in (r.get("name"), r.get("city")) if x) or k},
    "planning": {"label": "Планирование", "load": lambda: planning.load_json(planning.FILE, {}), "file": planning.FILE,
                 "lock": planning._lock, "map": _plan_map, "set": _plan_set,
                 "title": lambda k, r: PLAN_KIND.get(k.split("/")[0], "") + " · " + str(r.get("title") or r.get("venue") or r.get("city")
                                                                                    or k.split("/", 1)[1])},
    "projects": {"label": "Карточки проектов", "load": myprojects.load, "file": myprojects.FILE, "lock": None,
                 "map": _proj_map, "set": _proj_set, "title": lambda k, r: str(r.get("title") or k)},
    "work": {"label": "Проекты: задачи и документы", "load": work.load, "file": work.FILE, "lock": work._lock,
             "map": _work_map, "set": _work_set,
             "title": lambda k, r: WORK_KIND.get(k.split("/")[0], "") + " · " + str(r.get("title") or r.get("text") or r.get("name") or
                                                                              " — ".join(x for x in (r.get("kind"), r.get("party")) if x) or k)},
}


def snapshot(area: str) -> dict:
    """Записи области до правки (глубокая копия)."""
    a = AREAS[area]
    return copy.deepcopy(a["map"](a["load"]()))


def _diff(old: dict | None, new: dict | None):
    keys = set(old or {}) | set(new or {})
    before, after = {}, {}
    for k in sorted(keys - NOISE):
        o, n = (old or {}).get(k), (new or {}).get(k)
        if o is None and n in ("", 0, [], {}, False):   # поле появилось пустым (новая версия записи) — не правка
            continue
        if o != n:
            before[k], after[k] = o, n
    return before, after


def _write(entry: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / f"changes-{entry['at'][:7]}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record(area: str, before_map: dict, note: str = "", restored: str = "") -> int:
    """После правки: сравнить с тем, что было, и дописать по строке на каждую изменённую запись. → сколько записано."""
    a = AREAS[area]
    after_map = a["map"](a["load"]())
    at = datetime.now().isoformat(timespec="seconds")
    n = 0
    for key in sorted(set(before_map) | set(after_map)):
        o, nw = before_map.get(key), after_map.get(key)
        if o == nw:
            continue
        b, af = _diff(o, nw)
        if not b and not af and o is not None and nw is not None:
            continue   # изменилось только служебное (время правки)
        entry = {"id": at.replace("-", "").replace(":", "") + "-" + secrets.token_hex(3), "at": at, "area": area, "key": key,
                 "title": a["title"](key, nw or o or {}), "kind": "new" if o is None else "del" if nw is None else "edit",
                 "before": b if o is not None else None, "after": af if nw is not None else None}
        if note:
            entry["note"] = note
        if restored:
            entry["restored"] = restored
        _write(entry)
        n += 1
    return n


def read(area: str = "", key: str = "", limit: int = 200) -> list:
    files = sorted(DIR.glob("changes-*.jsonl"))[-MONTHS_READ:] if DIR.exists() else []
    out = []
    for fp in reversed(files):
        lines = fp.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if (area and e.get("area") != area) or (key and e.get("key") != key):
                continue
            out.append(e)
            if len(out) >= limit:
                return out
    return out


def _find(eid: str) -> dict:
    for fp in sorted(DIR.glob("changes-*.jsonl"), reverse=True) if DIR.exists() else []:
        for line in fp.read_text(encoding="utf-8").splitlines():
            if f'"{eid}"' in line:
                e = json.loads(line)
                if e.get("id") == eid:
                    return e
    raise JournalError("правка не найдена в журнале")


def restore(eid: str) -> dict:
    """Вернуть записи значения до правки eid: изменённые поля — прежние; новая запись — убрать; удалённая — вернуть целиком.
    Файлы (фото, райдер) не возвращаются. Возврат — тоже строка журнала. → {"area", "key", "record" (после возврата)}"""
    e = _find(eid)
    a = AREAS.get(e["area"])
    if not a:
        raise JournalError("неизвестный раздел журнала")
    lock = a["lock"]
    if lock:
        lock.acquire()
    try:
        before_map = copy.deepcopy(a["map"](a["load"]()))
        d = a["load"]()
        cur = a["map"](d).get(e["key"])
        if e["kind"] == "new":
            new = None
        elif e["kind"] == "del":
            new = copy.deepcopy(e["before"])
            if cur:
                raise JournalError("запись уже существует — возвращать нечего")
        else:
            if cur is None:
                raise JournalError("записи больше нет — сначала верните её удаление")
            new = copy.deepcopy(cur)
            for k, v in (e["before"] or {}).items():
                if k in FILES:
                    continue
                if v is None:
                    new.pop(k, None)
                else:
                    new[k] = v
                if e["area"] == "venues" and k in venuebook.FIELDS and k not in new.setdefault("edited", []):
                    new["edited"].append(k)   # возвращённое значение — тоже правка сайта: повторный импорт его не затрёт
            new["upd"] = datetime.now().isoformat(timespec="seconds")
        a["set"](d, e["key"], new)
        save_json(a["file"], d)
    finally:
        if lock:
            lock.release()
    record(e["area"], before_map, note="возврат", restored=eid)
    return {"area": e["area"], "key": e["key"], "record": new}
