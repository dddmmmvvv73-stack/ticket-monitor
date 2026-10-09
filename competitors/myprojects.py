"""
«Проекты → Избранные» и ваши записи о проектах (заметка, свои ссылки, контакты).

Хранится только на этом компьютере — config/my_projects.json исключён из git: репозиторий публичный,
а здесь контакты и рабочие заметки. При переходе на базу файл переносится в таблицу как есть.

    {"projects": {номер: {"title", "keys": [ключи проекта], "fav": bool,
                          "note", "links": [{"label", "url"}], "contacts", "skip": [ключи «не то»],
                          "snap": {"at", "dates": [[дата, город, площадка, цена от, цена до], …]},
                          "profile": {"sub", "about", "crew", "contact", "phone", "site", "vk", "instagram", "tg", "fee", "riders": [{"label", "url"}]},
                          "media": {"avatar" | "cover": имя файла в config/project_media/ с ?v=метка},
                          "cover_y": положение фона по вертикали, 0–100 % (как background-position-y),
                          "at", "upd"}}}

Профиль и фото — страница проекта (вид как у Яндекс Афиши, 09.10): подзаголовок, описание, состав на выезде,
контакт, телефон, сайт, гонорар, райдеры. Фото — файлами в config/project_media/ (вне git, как и сам файл);
прототип уменьшает их до отправки. Профиль сам в избранное не добавляет (в отличие от заметки).

Номер постоянный: проект в избранном не теряется, если его название в афише изменилось — к записи
добавляется ещё один ключ («связать»). Ключ — как curation.project_key (слова названия по алфавиту).
«Снимок» — даты проекта в момент добавления в избранное или последнего «Просмотрено»: от него
прототип считает «Что изменилось». Те же правила повторены в прототипе (myApply) — менять вместе.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "my_projects.json"
MEDIA_DIR = CONFIG_DIR / "project_media"
MEDIA_KINDS = ("avatar", "cover")
MEDIA_MAX = 3 * 1024 * 1024   # байт после декодирования — прототип присылает уже уменьшенное (~100–400 КБ)
MEDIA_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp"}
MEDIA_NAME = re.compile(r"^p[0-9a-z]{1,20}-(avatar|cover)\.(jpg|png|webp)$")
_ID = re.compile(r"^p[0-9a-z]{1,20}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIMITS = {"title": 300, "key": 300, "note": 5000, "contacts": 2000, "label": 120, "url": 1000, "links": 30, "dates": 3000,
          "sub": 200, "about": 10000, "crew": 200, "contact": 200, "phone": 60, "fee": 300}


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
    return not (p.get("note") or p.get("links") or p.get("contacts") or any((p.get("profile") or {}).values()) or p.get("media"))


def _url(v) -> str:
    u = _text(v, LIMITS["url"], "ссылка")
    if u and not re.match(r"^https?://", u, re.I):
        raise MyProjectsError("ссылка должна начинаться с http:// или https://")
    return u


def _profile(op: dict) -> dict:
    return {"sub": _text(op.get("sub"), LIMITS["sub"], "подзаголовок"), "about": _text(op.get("about"), LIMITS["about"], "описание"),
            "crew": _text(op.get("crew"), LIMITS["crew"], "состав на выезде"), "contact": _text(op.get("contact"), LIMITS["contact"], "контакт"),
            "phone": _text(op.get("phone"), LIMITS["phone"], "телефон"), "site": _url(op.get("site")),
            "vk": _url(op.get("vk")), "instagram": _url(op.get("instagram")), "tg": _url(op.get("tg")),
            "fee": _text(op.get("fee"), LIMITS["fee"], "гонорар"), "riders": _links(op.get("riders") or [])}


def _media(pid: str, p: dict, kind: str, data: str) -> None:
    """Фото проекта: data — data:image/…;base64,… (пусто — убрать). Файл — config/project_media/<номер>-<вид>.<тип>."""
    if kind not in MEDIA_KINDS:
        raise MyProjectsError("неизвестный вид фото")
    media = p.setdefault("media", {})
    raw = ext = None
    if data:   # сначала проверка: неудачная загрузка не должна стирать прежнее фото
        m = re.match(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$", data)
        if not m:
            raise MyProjectsError("фото: нужен JPEG, PNG или WebP")
        raw = base64.b64decode(m.group(2))
        if len(raw) > MEDIA_MAX:
            raise MyProjectsError("фото: не больше 3 МБ")
        ext = next((e for sig, e in MEDIA_TYPES.items() if raw.startswith(sig)), None)
        if not ext:
            raise MyProjectsError("фото: файл не похож на изображение")
    for old in MEDIA_DIR.glob(f"{pid}-{kind}.*"):
        old.unlink()
    if not data:
        media.pop(kind, None)
        return
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{pid}-{kind}.{ext}"
    (MEDIA_DIR / name).write_bytes(raw)
    media[kind] = f"{name}?v={int(datetime.now().timestamp())}"


def media_file(name: str):
    """Путь к фото для выдачи по адресу; None — имя не наше или файла нет."""
    if not MEDIA_NAME.match(name or ""):
        return None
    path = MEDIA_DIR / name
    return path if path.is_file() else None


def apply_op(op: dict) -> tuple[dict, str]:
    """Одна правка от прототипа; возвращает всё хранилище и подпись для журнала."""
    data, kind = load(), op.get("op")
    projects = data["projects"]
    if kind in ("fav", "notes", "profile", "media", "coverpos"):
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
        elif kind in ("profile", "media", "coverpos"):
            if kind == "coverpos":   # положение фона шапки — отдельно от профиля, чтобы не перезаписывать остальное
                y = op.get("y")
                if not isinstance(y, (int, float)) or isinstance(y, bool) or not 0 <= y <= 100:
                    raise MyProjectsError("положение фона — от 0 до 100")
                p["cover_y"] = round(float(y), 1)
                note = f"«{p['title']}» — положение фона"
            elif kind == "profile":   # профиль страницы проекта + прежние записи (заметка, ссылки, контакты) — одной правкой
                p["profile"] = _profile(op)
                p["note"] = _text(op.get("note"), LIMITS["note"], "заметка")
                p["contacts"] = _text(op.get("contacts"), LIMITS["contacts"], "контакты")
                p["links"] = _links(op.get("links") or [])
                note = f"«{p['title']}» — страница проекта сохранена"
            else:
                _media(pid, p, str(op.get("kind") or ""), str(op.get("data") or ""))
                note = f"«{p['title']}» — фото " + ("обновлено" if op.get("data") else "убрано")
            if not p["fav"] and _empty(p):
                del projects[pid]
                save_json(FILE, data)
                return data, note
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
