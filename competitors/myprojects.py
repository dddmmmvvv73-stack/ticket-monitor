"""
«Проекты → Избранные» и ваши записи о проектах (заметка, свои ссылки, контакты).

Хранится только на этом компьютере — config/my_projects.json исключён из git: репозиторий публичный,
а здесь контакты и рабочие заметки. При переходе на базу файл переносится в таблицу как есть.

    {"projects": {номер: {"title", "keys": [ключи проекта], "fav": bool,
                          "note", "links": [{"label", "url"}], "contacts", "skip": [ключи «не то»],
                          "snap": {"at", "dates": [[дата, город, площадка, цена от, цена до], …]},
                          "profile": {"sub", "about", "crew", "contact", "phone", "site", "vk", "instagram", "tg", "fee",
                                      "riders": [{"label", "url"} | {"label", "file"} — файл в config/project_media/]},
                          "media": {"avatar" | "cover": имя файла в config/project_media/ с ?v=метка},
                          "cover_y": положение фона по вертикали, 0–100 % (как background-position-y),
                          "rating": {"s": [6 целых 0–3], "at"}, "rating_hist": [прошлые {"s", "at"}, новые в конце],
                          "site": {"key", "url", "title", "confirmed", "at", "choices": {дата: "site" | "kassa"}},
                          "at", "upd"}}}

«Официальный сайт» (раздел «Аналитики», 12.10.2026): ссылка на страницу афиши, подтверждение первого разбора и выбор
при расхождениях — здесь; сами даты с сайта собирает competitors/officialsite.py (data/competitors/official_sites.json).

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
import secrets
from datetime import datetime

from competitors.storage import CONFIG_DIR, JsonLock, load_json, save_json

FILE = CONFIG_DIR / "my_projects.json"
_lock = JsonLock(lambda: FILE)
MEDIA_DIR = CONFIG_DIR / "project_media"
MEDIA_KINDS = ("avatar", "cover")
MEDIA_MAX = 3 * 1024 * 1024   # байт после декодирования — прототип присылает уже уменьшенное (~100–400 КБ)
MEDIA_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp"}
MEDIA_NAME = re.compile(r"^p[0-9a-z]{1,20}-(avatar|cover)(-[0-9a-f]{8})?\.(jpg|png|webp)$|^p[0-9a-z]{1,20}-r[0-9a-f]{8}\.[a-z0-9]{2,5}$")
RIDER_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "webp", "rtf", "odt", "ods", "txt", "zip"}
RIDER_MAX = 15 * 1024 * 1024   # райдер файлом — из карточки записи воронки «Процессов» (PROCESSES_PLAN.md, 10.7)
_ID = re.compile(r"^p[0-9a-z]{1,20}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIMITS = {"title": 300, "key": 300, "note": 5000, "contacts": 2000, "label": 120, "url": 1000, "links": 30, "dates": 3000,
          "sub": 200, "about": 10000, "crew": 200, "contact": 200, "phone": 60, "fee": 300}


class MyProjectsError(ValueError):
    pass


class MyProjectsConflict(MyProjectsError):
    pass


def load() -> dict:
    data = load_json(FILE, {})
    return {**data, "projects": data.get("projects") or {}}


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


def _linked(pid: str) -> bool:
    """Карточка связана с записью воронки «Процессов» — её не удаляем, даже если в ней ничего нет (связь — leads.pj)."""
    from competitors import work
    return any(r.get("pj") == pid for r in work.load()["leads"].values())


def _rider_file(pid: str, op: dict) -> dict:
    name = _text(op.get("name"), LIMITS["label"], "имя файла")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    m = re.match(r"^data:[\w.+/-]*;base64,([A-Za-z0-9+/=]+)$", str(op.get("data") or ""))
    if ext not in RIDER_EXT or not m:
        raise MyProjectsError("райдер: нужен файл PDF, Word, Excel, картинка или архив")
    raw = base64.b64decode(m.group(1))
    if not raw or len(raw) > RIDER_MAX:
        raise MyProjectsError("райдер: файл до 15 МБ")
    kind = op.get("rider_kind") or "other"
    if kind not in ("technical", "hospitality", "other"):
        raise MyProjectsError("неизвестный вид райдера")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{pid}-r{secrets.token_hex(4)}.{ext}"
    (MEDIA_DIR / fname).write_bytes(raw)
    return {"label": name, "file": fname, "kind": kind}


def _empty(p: dict) -> bool:
    return not (p.get("saved") or p.get("note") or p.get("links") or p.get("contacts") or any((p.get("profile") or {}).values()) or p.get("media")
                or p.get("rating") or p.get("site"))


RATING_AXES, RATING_MAX, RATING_HIST = 6, 3, 50   # оценка по шестиугольнику: 6 осей 0–3 (Design/prototype/project-rating.js)


def _rating(v) -> list[int]:
    if not isinstance(v, list) or len(v) != RATING_AXES or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= RATING_MAX for x in v):
        raise MyProjectsError(f"оценка — {RATING_AXES} целых чисел от 0 до {RATING_MAX}")
    return v


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
            "fee": _text(op.get("fee"), LIMITS["fee"], "гонорар"), "format": _text(op.get("format"), 120, "формат"), "riders": _links(op.get("riders") or [])}


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
    # Прежние версии остаются для журнала и резервных копий.
    if not data:
        media.pop(kind, None)
        return
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{pid}-{kind}-{secrets.token_hex(4)}.{ext}"
    (MEDIA_DIR / name).write_bytes(raw)
    media[kind] = f"{name}?v={int(datetime.now().timestamp())}"


def media_file(name: str):
    """Путь к фото для выдачи по адресу; None — имя не наше или файла нет."""
    if not MEDIA_NAME.match(name or ""):
        return None
    path = MEDIA_DIR / name
    return path if path.is_file() else None


def _site(p: dict, op: dict, key: str) -> str:
    """Официальный сайт проекта: ссылка (другой сайт — первый разбор снова с подтверждением), подтверждение, выбор, «убрать»."""
    kind, s = op.get("op"), p.get("site") or {}
    if kind == "site":
        url = _url(op.get("url"))
        if not url or not re.match(r"^https?://[^\s/]+\.[^\s/]+", url):
            raise MyProjectsError("нужен адрес страницы сайта, например https://rondotour.ru/")
        host = lambda u: re.sub(r"^https?://(www\.)?", "", u.lower()).split("/")[0]
        same = s.get("url") and host(s["url"]) == host(url)
        p["site"] = {"key": s.get("key") or key, "url": url, "title": _text(op.get("title"), LIMITS["title"], "название") or p["title"],
                     "confirmed": bool(same and s.get("confirmed")), "at": s.get("at") if same else None,
                     "choices": s.get("choices", {}) if same else {}}
        return f"«{p['title']}» — официальный сайт {host(url)}"
    if not s:
        raise MyProjectsError("у проекта нет ссылки на сайт")
    if kind == "siteconfirm":
        s["confirmed"], s["at"] = True, s.get("at") or _now()
        return f"«{p['title']}» — даты с сайта подтверждены"
    if kind == "sitepick":
        d, v = str(op.get("date") or ""), str(op.get("v") or "")
        if not _DATE.match(d) or v not in ("site", "kassa", ""):
            raise MyProjectsError("выбор: дата ГГГГ-ММ-ДД и «site» / «kassa»")
        ch = s.setdefault("choices", {})
        if v:
            ch[d] = v
        else:
            ch.pop(d, None)
        return f"«{p['title']}» — расхождение {d}: " + ({"site": "верно на сайте", "kassa": "верно в кассах"}.get(v) or "снова не решено")
    p.pop("site", None)   # siteoff
    return f"«{p['title']}» — официальный сайт убран"


def apply_op(op: dict) -> tuple[dict, str]:
    with _lock:
        return _apply_op(op)


def _apply_op(op: dict) -> tuple[dict, str]:
    """Одна правка от прототипа; возвращает всё хранилище и подпись для журнала."""
    data, kind = load(), op.get("op")
    projects = data["projects"]
    current_id = find(projects, str(op.get("key") or "")) or str(op.get("id") or "")
    current = projects.get(current_id)
    if current and kind == "profile" and "expected" not in op:
        raise MyProjectsConflict("Карточка обновлена. Перечитайте данные перед сохранением; ваш черновик останется.")
    if current and "expected" in op and op["expected"] != current.get("rev", 0):
        raise MyProjectsConflict("Карточку изменили в другом окне. Перечитайте данные и примените ваш черновик повторно.")
    if kind in ("fav", "notes", "profile", "media", "coverpos", "rating", "site", "siteconfirm", "sitepick", "siteoff"):
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
            note = f"«{p['title']}» — " + ("в избранном" if p["fav"] else "убрано из избранного")
        elif kind in ("profile", "media", "coverpos", "rating", "site", "siteconfirm", "sitepick", "siteoff"):
            if kind.startswith("site"):
                note = _site(p, op, key)
            elif kind == "rating":   # оценка по шестиугольнику; прошлая уходит в историю — её можно наложить на текущую
                scores = _rating(op.get("s"))
                old = p.get("rating")
                if old and old.get("s") != scores:
                    p.setdefault("rating_hist", []).append(old)
                    p["rating_hist"] = p["rating_hist"][-RATING_HIST:]
                p["rating"] = {"s": scores, "at": _now()}
                note = f"«{p['title']}» — оценка проекта"
            elif kind == "coverpos":   # положение фона шапки — отдельно от профиля, чтобы не перезаписывать остальное
                y = op.get("y")
                if not isinstance(y, (int, float)) or isinstance(y, bool) or not 0 <= y <= 100:
                    raise MyProjectsError("положение фона — от 0 до 100")
                p["cover_y"] = round(float(y), 1)
                note = f"«{p['title']}» — положение фона"
            elif kind == "profile":   # профиль страницы проекта + прежние записи (заметка, ссылки, контакты) — одной правкой
                name = _text(op.get("name", p["title"]), LIMITS["title"], "название")
                if not name:
                    raise MyProjectsError("нужно название проекта")
                if name != p["title"]:
                    from competitors.curation import project_key
                    new_key = project_key(name)
                    other = find(projects, new_key)
                    if other and other != pid:
                        raise MyProjectsError("Карточка с таким названием уже существует")
                    if new_key and new_key not in p["keys"]:
                        p["keys"].append(new_key)
                    p["title"] = name
                p["saved"] = True
                files = [r for r in (p.get("profile") or {}).get("riders", []) if r.get("file")]   # райдеры-файлы правятся отдельно
                p["profile"] = {**(p.get("profile") or {}), **_profile(op)}
                p["profile"]["riders"] += files
                p["note"] = _text(op.get("note"), LIMITS["note"], "заметка")
                p["contacts"] = _text(op.get("contacts"), LIMITS["contacts"], "контакты")
                p["links"] = _links(op.get("links") or [])
                note = f"«{p['title']}» — страница проекта сохранена"
            else:
                _media(pid, p, str(op.get("kind") or ""), str(op.get("data") or ""))
                note = f"«{p['title']}» — фото " + ("обновлено" if op.get("data") else "убрано")
        else:
            p["note"] = _text(op.get("note"), LIMITS["note"], "заметка")
            p["contacts"] = _text(op.get("contacts"), LIMITS["contacts"], "контакты")
            p["links"] = _links(op.get("links") or [])
            if created and not _empty(p):  # начали записи о проекте — он сам попадает в избранное
                p["fav"] = True
                p["snap"] = _snap(op.get("snap") or [])
            note = f"«{p['title']}» — записи сохранены"
    elif kind == "create":   # из воронки или непосредственно из «Моей базы»
        from competitors.curation import project_key
        title = _text(op.get("title"), LIMITS["title"], "название")
        if op.get("manual") and not title:
            raise MyProjectsError("нужно название проекта")
        key = _key((project_key(title) or "manual:" + str(op.get("id") or "")) if op.get("manual") else op.get("key"))
        pid = find(projects, key)
        if not pid:
            pid = str(op.get("id") or "")
            if not _ID.match(pid) or pid in projects:
                raise MyProjectsError("неверный номер новой записи")
            projects[pid] = {"title": _text(op.get("title"), LIMITS["title"], "название") or key, "keys": [key], "fav": False,
                             "note": "", "links": [], "contacts": "", "snap": None, "at": _now()}
        p = projects[pid]
        if op.get("manual"):
            p["saved"] = True
        note = f"«{p['title']}» — карточка проекта создана"
    elif kind in ("register", "connections"):
        key = _key(op.get("key"))
        pid = find(projects, key)
        if not pid:
            pid = str(op.get("id") or "")
            if not _ID.match(pid) or pid in projects:
                raise MyProjectsError("неверный номер карточки")
            projects[pid] = {"title": _text(op.get("title"), LIMITS["title"], "название") or key, "keys": [key], "at": _now()}
        p = projects[pid]
        p["saved"] = True
        if kind == "connections":
            target, oid, on = op.get("kind"), str(op.get("target") or ""), op.get("on", True)
            if target not in ("lists", "tours", "work") or not re.fullmatch(r"[a-z0-9]{1,24}", oid):
                raise MyProjectsError("неверная связь проекта")
            links = p.setdefault("connections", {}).setdefault(target, [])
            if on:
                from competitors import planning, work
                records = work.load()["projects"] if target == "work" else planning.load()[target]
                if oid not in records:
                    raise MyProjectsError("связанная запись больше не существует")
                if oid not in links:
                    if len(links) >= 300:
                        raise MyProjectsError("до 300 связей каждого вида")
                    links.append(oid)
            elif oid in links:
                links.remove(oid)
        note = f"«{p['title']}» — " + ("связи обновлены" if kind == "connections" else "в моей базе")
    elif kind in ("fee", "rider", "rider-del"):
        pid = str(op.get("id") or "")
        if pid not in projects:
            raise MyProjectsError("нет такой карточки проекта")
        p = projects[pid]
        pr = p.setdefault("profile", _profile({}))
        if kind == "fee":
            pr["fee"] = _text(op.get("fee"), LIMITS["fee"], "гонорар")
            note = f"«{p['title']}» — гонорар из воронки"
        elif kind == "rider":
            if len(pr.setdefault("riders", [])) >= LIMITS["links"] and not op.get("replace"):
                raise MyProjectsError(f"райдеры: не больше {LIMITS['links']}")
            replace = str(op.get("replace") or "")
            if replace and not any(r.get("file") == replace for r in pr["riders"]):
                raise MyProjectsError("заменяемый райдер больше не существует")
            new = _rider_file(pid, op)
            if replace:
                pr["riders"] = [new if r.get("file") == replace else r for r in pr["riders"]]
            else:
                pr["riders"].append(new)
            note = f"«{p['title']}» — райдер загружен"
        else:
            f = str(op.get("file") or "")
            if not MEDIA_NAME.match(f) or not any(r.get("file") == f for r in pr.get("riders", [])):
                raise MyProjectsError("нет такого файла райдера")
            pr["riders"] = [r for r in pr["riders"] if r.get("file") != f]
            # Файл остаётся на диске: возврат через журнал восстанавливает и рабочую ссылку.
            note = f"«{p['title']}» — райдер удалён"
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
    p["rev"] = p.get("rev", 0) + 1
    save_json(FILE, data)
    return data, note


def connect_existing(write: bool = False) -> list[dict]:
    """Связи без повторного ввода: только однозначные ключи артиста или уже заданная воронка. Сначала dry run."""
    import copy
    from competitors import curation, journal, planning, work
    with _lock:
        data, plan, wk = load(), planning.load(), work.load()
        before = copy.deepcopy(data["projects"])
        owners = {}
        for pid, p in data["projects"].items():
            for key in p.get("keys", []):
                owners.setdefault(key, set()).add(pid)
        def match(name):
            ids = owners.get(curation.project_key(name), set())
            return next(iter(ids)) if len(ids) == 1 else None
        additions = []
        def add(pid, kind, oid):
            if pid not in data["projects"]:
                return
            p = data["projects"][pid]
            ids = p.setdefault("connections", {}).setdefault(kind, [])
            if oid not in ids:
                ids.append(oid)
                additions.append({"card": pid, "title": p["title"], "kind": kind, "id": oid})
        for oid, item in plan["lists"].items():
            pid = match(item.get("project") or item.get("title", ""))
            if pid:
                add(pid, "lists", oid)
        for oid, tour in plan["tours"].items():
            econ = plan["projects"].get(tour.get("project"), {})
            ids = owners.get(econ.get("key"), set())
            pid = next(iter(ids)) if len(ids) == 1 else match(econ.get("title", ""))
            if pid:
                add(pid, "tours", oid)
        for lead in wk["leads"].values():
            pid = lead.get("pj")
            if lead.get("list") in plan["lists"]:
                add(pid, "lists", lead["list"])
            if lead.get("project") in wk["projects"]:
                add(pid, "work", lead["project"])
        for oid, project in wk["projects"].items():
            lead = wk["leads"].get(project.get("lead"), {})
            if lead.get("pj"):
                add(lead["pj"], "work", oid)
        if write and additions:
            affected = {a["card"] for a in additions}
            for pid in affected:
                data["projects"][pid]["rev"] = data["projects"][pid].get("rev", 0) + 1
            save_json(FILE, data)
            journal.record("projects", before, note="Связи существующих проектов: однозначные названия и воронка")
        return additions
