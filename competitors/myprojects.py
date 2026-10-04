"""
«Проекты → Избранные» и ваши записи о проектах (заметка, свои ссылки, контакты).

Хранится только на этом компьютере — config/my_projects.json исключён из git: репозиторий публичный,
а здесь контакты и рабочие заметки. При переходе на базу файл переносится в таблицу как есть.

    {"projects": {номер: {"title", "keys": [ключи проекта], "fav": bool,
                          "note", "links": [{"label", "url"}], "contacts", "skip": [ключи «не то»],
                          "snap": {"at", "dates": [[дата, город, площадка, цена от, цена до], …]},
                          "at", "upd"}}}

Номер постоянный: проект в избранном не теряется, если его название в афише изменилось — к записи
добавляется ещё один ключ («связать»). Ключ — как curation.project_key (слова названия по алфавиту).
«Снимок» — даты проекта в момент добавления в избранное или последнего «Просмотрено»: от него
прототип считает «Что изменилось». Те же правила повторены в прототипе (myApply) — менять вместе.
"""

from __future__ import annotations

import re
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "my_projects.json"
_ID = re.compile(r"^p[0-9a-z]{1,20}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIMITS = {"title": 300, "key": 300, "note": 5000, "contacts": 2000, "label": 120, "url": 1000, "links": 30, "dates": 3000}


class MyProjectsError(ValueError):
    pass


def load() -> dict:
    data = load_json(FILE, {})
    return {"projects": data.get("projects") or {}}


def _text(v, limit: int, what: str) -> str:
    s = str(v or "").strip()
    if len(s) > limit:
        raise MyProjectsError(f"{what}: не длиннее {limit} знаков")
    return s


def _key(v) -> str:
    k = _text(v, LIMITS["key"], "ключ проекта")
    if not k:
        raise MyProjectsError("нет ключа проекта")
    return k


def _links(v) -> list[dict]:
    if not isinstance(v, list) or len(v) > LIMITS["links"]:
        raise MyProjectsError(f"ссылки: список до {LIMITS['links']}")
    out = []
    for x in v:
        url = _text((x or {}).get("url"), LIMITS["url"], "ссылка")
        if not url:
            continue
        if not re.match(r"^https?://", url, re.I):
            raise MyProjectsError("ссылка должна начинаться с http:// или https://")
        out.append({"label": _text(x.get("label"), LIMITS["label"], "подпись ссылки"), "url": url})
    return out


def _snap(v) -> dict:
    if not isinstance(v, list) or len(v) > LIMITS["dates"]:
        raise MyProjectsError("снимок дат: неверный формат")
    dates = []
    for d in v:
        if not isinstance(d, list) or len(d) != 5 or not _DATE.match(str(d[0])):
            raise MyProjectsError("снимок дат: неверная строка")
        price = lambda p: p if isinstance(p, (int, float)) and not isinstance(p, bool) and p >= 0 else None
        dates.append([d[0], str(d[1])[:100], str(d[2])[:200], price(d[3]), price(d[4])])
    return {"at": _now(), "dates": dates}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def find(projects: dict, key: str) -> str | None:
    return next((pid for pid, p in projects.items() if key in p.get("keys", [])), None)


def _empty(p: dict) -> bool:
    return not (p.get("note") or p.get("links") or p.get("contacts"))


def apply_op(op: dict) -> tuple[dict, str]:
    """Одна правка от прототипа; возвращает всё хранилище и подпись для журнала."""
    data, kind = load(), op.get("op")
    projects = data["projects"]
    if kind in ("fav", "notes"):
        key = _key(op.get("key"))
        pid = find(projects, key)
        if not pid:
            pid = str(op.get("id") or "")
            if not _ID.match(pid) or pid in projects:
                raise MyProjectsError("неверный номер новой записи")
            projects[pid] = {"title": _text(op.get("title"), LIMITS["title"], "название") or key, "keys": [key], "fav": False,
                             "note": "", "links": [], "contacts": "", "snap": None, "at": _now()}
            created = True
        else:
            created = False
        p = projects[pid]
        if kind == "fav":
            p["fav"] = bool(op.get("fav"))
            if p["fav"]:
                p["snap"] = _snap(op.get("snap") or [])
            elif _empty(p):
                del projects[pid]
                save_json(FILE, data)
                return data, f"«{p['title']}» — убрано из избранного"
            note = f"«{p['title']}» — " + ("в избранном" if p["fav"] else "убрано из избранного")
        else:
            p["note"] = _text(op.get("note"), LIMITS["note"], "заметка")
            p["contacts"] = _text(op.get("contacts"), LIMITS["contacts"], "контакты")
            p["links"] = _links(op.get("links") or [])
            if created and not _empty(p):  # начали записи о проекте — он сам попадает в избранное
                p["fav"] = True
                p["snap"] = _snap(op.get("snap") or [])
            if not p["fav"] and _empty(p):
                del projects[pid]
                save_json(FILE, data)
                return data, f"«{p['title']}» — записи удалены"
            note = f"«{p['title']}» — записи сохранены"
    elif kind in ("seen", "link", "skip"):
        pid = str(op.get("id") or "")
        if pid not in projects:
            raise MyProjectsError("нет такой записи")
        p = projects[pid]
        if kind == "seen":
            p["snap"] = _snap(op.get("snap") or [])
            note = f"«{p['title']}» — просмотрено"
        elif kind == "skip":  # подсказка «похоже» оказалась не тем проектом — больше не предлагать
            key = _key(op.get("key"))
            p.setdefault("skip", [])
            if key not in p["skip"]:
                p["skip"].append(key)
            note = f"«{p['title']}» — подсказка скрыта"
        else:
            key = _key(op.get("key"))
            other = find(projects, key)
            if other and other != pid:
                raise MyProjectsError("это название уже связано с другой записью")
            if key not in p["keys"]:
                p["keys"].append(key)
            note = f"«{p['title']}» — связано ещё одно название"
    else:
        raise MyProjectsError("неизвестная операция")
    p["upd"] = _now()
    save_json(FILE, data)
    return data, note
