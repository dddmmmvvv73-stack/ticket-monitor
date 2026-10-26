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
                          "prio" — приоритет: high | mid | low | пусто; "status" — work | wait | пусто (не начата),
                          "log": [{"id", "at" — ГГГГ-ММ-ДДTЧЧ:ММ, "text"}] — журнал задачи (решение 22.10)}},
     "docs":     {номер: {"project", "cp" — номер контрагента или пусто, "kind" (Договор / Счёт / УПД / …), "party" — название
                          контрагента (копия), "status" — DOC_STATUS, "amount", "paid" — оплачено (счёт), "inv" — advance | full (счёт),
                          "orig_out", "orig_in" — оригинал отправили / получили (контрагент без полного ЭДО), "note", "upd"}},
     "parties":  {номер: {"name", "legal", "inn", "city", "service" — PARTY_SERVICE, "edo" — EDO, "contact", "phone", "email", "note",
                          "venue" — номер площадки в справочнике или пусто, "upd"}}   ← контрагенты (решение пользователя 22.10)
     "tags":     {номер: {"name", "color"}},
     "costs":    {номер: {"project", "name" — статья, "party" — кому, "amount", "date", "paid", "note", "upd"}},
     "notes":    {номер: {"project" — или пусто (общая), "title", "created", "fav" — избранная, "upd";
                          быстрая (цветная): "body", "color" — NOTE_COLORS;
                          рабочая (решение 22.10): "type": "work", "task" — или пусто, "doc" — документ редактора (TipTap JSON)}},
     "shows":    {номер: {"project", "date", "venue" — номер в справочнике площадок, "name", "city", "upd",
                          "sale" — выход в продажу (решение 22.10): пусто — ждём площадку | allowed — площадка разрешила |
                          onsale — в продаже у операторов; "sale_ok", "sale_on" — даты разрешения и выхода в продажу}},
     "goals":    {номер: {"month" — ГГГГ-ММ, "text", "done", "order", "upd"}}}   ← цели месяца («Обзор», решение пользователя 26.10)
У проекта — "created" (дата создания: от неё «Обзор» считает, где проект должен быть к дедлайну готовности; у проектов
до 26.10 — дата первой его задачи). У задачи — "pin" (закреплена в «Фокусе» «Обзора») и "remind" (напомнить в Telegram:
утром в день срока и, пока не сделана, каждое утро после — python3 -m competitors.work remind, tm-sync каждый час).
Теги задачи — "tags": [номера]; пока своих нет — DEFAULT_TAGS.

    GET  /api/work                                   всё
    POST /api/work {"op": "put", "kind", "id", "data"}   запись целиком (проверяется)
                   {"op": "del", "kind", "id"}
                   {"op": "media", "kind": "projects", "id", "what": "avatar" | "cover", "data"}   фото проекта
    POST /api/work/nfile {"id" — номер заметки, "name", "data"}   картинка или файл рабочей заметки → {"file", "name", "size"}
    GET  /api/work/file/<файл>                     фото проекта, файлы заметок (config/work_media/, вне git)

    python3 -m competitors.work remind             напоминания о задачах в Telegram (раз в день, с REMIND_HOUR)
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading
from datetime import datetime

from competitors.storage import BASE_DIR, CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "work.json"
KINDS = ("projects", "tasks", "docs", "tags", "costs", "notes", "shows", "stages", "parties", "goals")
# shows — гастроли проекта (решение пользователя 20.10): дата, площадка, город; площадка — из справочника «Площадки → Площадки»
# (venue — номер записи config/venue_book.json); название и город хранятся копией — строка читается, даже если площадку убрали из справочника
# Цвета тегов. Красный и оранжевый — только у приоритета (решение пользователя 19.10: полоса слева — по тегу, и красная
# полоса не должна читаться как «срочно»); прежние теги этих цветов перекрашиваются при чтении (RECOLOR)
COLORS = ("blue", "green", "violet", "teal", "pink", "amber", "indigo", "brown", "gray")
RECOLOR = {"red": "indigo", "orange": "brown"}
DEFAULT_TAGS = {"tgcontract": {"name": "Договоры", "color": "blue"}, "tgmoney": {"name": "Финансы", "color": "green"},
                "tgvenue": {"name": "Площадка", "color": "violet"}, "tglogist": {"name": "Логистика", "color": "brown"},
                "tgtech": {"name": "Техника", "color": "teal"}, "tgpromo": {"name": "Реклама", "color": "pink"},
                "tgtickets": {"name": "Билеты", "color": "amber"}, "tgartist": {"name": "Артист", "color": "indigo"}}
# Статусы (стадии) проектов — свои у пользователя (решение 20.10: «сам делаю канбан и статусы»): {номер: {"name", "color", "order",
# "done" — проекты в нём считаются завершёнными}}; пока не правили — стандартные. Удалить статус с проектами нельзя — сначала перенести.
STAGE_COLORS = ["gray", "amber", "violet", "blue", "green", "peach", "mint", "pink", "teal"]
DEFAULT_STAGES = {"idea": {"name": "Идея", "color": "gray", "order": 1, "done": False},
                  "talks": {"name": "Переговоры", "color": "amber", "order": 2, "done": False},
                  "prep": {"name": "Подготовка", "color": "violet", "order": 3, "done": False},
                  "sales": {"name": "Продажи", "color": "blue", "order": 4, "done": False},
                  "live": {"name": "Проведение", "color": "green", "order": 5, "done": False},
                  "closing": {"name": "Закрытие", "color": "peach", "order": 6, "done": False},
                  "done": {"name": "Завершён", "color": "mint", "order": 7, "done": True}}
DOC_STATUS = ["wait", "got", "acc", "signed"]   # ожидаем → получен → у бухгалтера → подписан (решение 22.10)
DOC_STATUS_OLD = {"draft": "got", "sent": "acc"}   # до 22.10: черновик / отправлен
INV = ["", "advance", "full"]                     # счёт: аванс | полная оплата
PARTY_SERVICE = ["", "venue", "hotel", "transport", "tech", "promo", "artist", "other"]
EDO = ["", "full", "in", "none"]                  # как у площадок: полное | только входящий | не работают (оригиналы)
PRIO = ["", "low", "mid", "high"]
STATUS = ["", "work", "wait"]
NOTE_COLORS = ["amber", "coral", "lime", "violet", "sky", "pink"]
NOTE_TYPES = ["quick", "work"]   # быстрая (цветная карточка) | рабочая (редактор, привязка к задаче) — решение пользователя 22.10
NOTE_DOC_MAX = 2_000_000         # документ рабочей заметки, знаков JSON (картинки и файлы — отдельно, в work_media)
LOG_MAX = 2000                   # записей в журнале задачи   # цвет карточки заметки (решение пользователя 20.10: 6 базовых)   # статус задачи: не начата | в работе | ждёт ответа («готово» — это done; решение пользователя 20.10)
SALE = ["", "allowed", "onsale"]
TEXT_MAX = 3000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
SUBS_MAX = 200
_ID = re.compile(r"^[a-z0-9]{3,40}$")
_VENUE = re.compile(r"^[a-z0-9]{1,40}$")
_lock = threading.Lock()
MEDIA_DIR = CONFIG_DIR / "work_media"   # фото проектов (миниатюра, фон шапки) — вне git, в копиях config/
MEDIA_KINDS = ("avatar", "cover")
PHOTO_MAX = 3 * 1024 * 1024
PHOTO_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp"}
FILE_NAME = re.compile(r"^[a-z0-9]{3,40}-(avatar|cover|rider|logistics|timing|f[0-9a-f]{8})\.[a-z0-9]{2,5}$")   # f… — файл рабочей заметки
DOC_KINDS = ("rider", "logistics", "timing")   # документы проекта: технический райдер, логистика, тайминг
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "webp", "rtf", "odt", "ods", "txt", "zip"}
DOC_MAX = 15 * 1024 * 1024
NOTE_EXT = DOC_EXT | {"gif", "csv", "ppt", "pptx"}


class WorkError(ValueError):
    pass


def load() -> dict:
    d = load_json(FILE, {})
    out = {k: d.get(k) or {} for k in KINDS}
    if "tags" not in d:   # своих тегов ещё не заводили — стандартные (с первой правкой тегов сохраняются в файл)
        out["tags"] = {k: dict(v) for k, v in DEFAULT_TAGS.items()}
    if not d.get("stages"):   # статусы проектов ещё не правили — стандартные
        out["stages"] = {k: dict(v) for k, v in DEFAULT_STAGES.items()}
    for t in out["tags"].values():
        t["color"] = RECOLOR.get(t.get("color"), t.get("color"))
    for pid, p in out["projects"].items():   # проекты до 26.10 — без даты создания: дата первой задачи (иначе — последней правки)
        if not p.get("created"):
            first = min((t.get("created") or "9" for t in out["tasks"].values() if t.get("project") == pid), default="9")
            p["created"] = first if first != "9" else (p.get("upd") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    for d in out["docs"].values():   # документы до 22.10: прежние статусы и «оплачено полностью» — в новые поля
        d["status"] = DOC_STATUS_OLD.get(d.get("status"), d.get("status"))
        if d.pop("pay", None) == "paid" and not d.get("paid"):
            d["paid"] = d.get("amount")
        d.pop("closing", None)
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


def _log(v) -> list:
    """Журнал задачи: [{"id", "at", "text"}] — пустые записи отбрасываются."""
    if not v:
        return []
    if not isinstance(v, list) or len(v) > LOG_MAX:
        raise WorkError(f"журнал: не больше {LOG_MAX} записей")
    out = []
    for e in v:
        if not isinstance(e, dict):
            raise WorkError("журнал: неверный формат")
        text, eid, at = _text(e.get("text"), "запись журнала", 2000), str(e.get("id") or ""), str(e.get("at") or "")
        if not text:
            continue
        if not _ID.match(eid) or not _STAMP.match(at):
            raise WorkError("журнал: неверная запись")
        out.append({"id": eid, "at": at, "text": text})
    return out


def _doc(v) -> dict:
    """Текст рабочей заметки — документ редактора; сервер проверяет только вид и размер (показывает его редактор по своей схеме)."""
    if not v:
        return {}
    if not isinstance(v, dict) or v.get("type") != "doc":
        raise WorkError("заметка: неверный формат текста")
    if len(json.dumps(v, ensure_ascii=False)) > NOTE_DOC_MAX:
        raise WorkError("заметка слишком большая — разделите её на несколько")
    return v


def _enum(v, allowed: list, what: str, default: str) -> str:
    v = str(v or default)
    if v not in allowed:
        raise WorkError(f"{what}: неизвестное значение")
    return v


def _validate(kind: str, d: dict, data: dict) -> dict:
    if kind == "projects":
        stages = sorted(data["stages"], key=lambda k: data["stages"][k].get("order", 0))
        out = {"title": _text(d.get("title"), "название", 300), "stage": _enum(d.get("stage"), stages, "статус", stages[0]),
               "start": _date(d.get("start"), "начало"), "end": _date(d.get("end"), "окончание"),
               "deadline": _date(d.get("deadline"), "дедлайн"), "note": _text(d.get("note"), "заметка"), "fav": bool(d.get("fav")),   # fav — избранный (звезда в карточках, 20.10)
               "created": _date(d.get("created"), "создан")}   # пусто — сегодня или прежняя (apply_op)
        if not out["title"]:
            raise WorkError("у проекта нужно название")
        return out
    if kind in ("costs", "notes"):
        pid = str(d.get("project") or "")
        if pid and pid not in data["projects"]:
            raise WorkError("такого проекта нет")
        if kind == "notes":
            out = {"project": pid, "title": _text(d.get("title"), "название", 200),
                   "created": _date(d.get("created"), "создана") or datetime.now().strftime("%Y-%m-%d"), "fav": bool(d.get("fav"))}
            if _enum(d.get("type"), NOTE_TYPES, "тип заметки", "quick") == "quick":   # у быстрых поля type нет — как было до 22.10
                out.update(body=_text(d.get("body"), "заметка", 50000), color=_enum(d.get("color"), NOTE_COLORS, "цвет", "amber"))
                return out
            tid = str(d.get("task") or "")
            if tid and tid not in data["tasks"]:
                raise WorkError("такой задачи нет")
            if tid and data["tasks"][tid].get("project"):
                out["project"] = data["tasks"][tid]["project"]   # проект — из задачи (решение 22.10)
            out.update(type="work", task=tid, doc=_doc(d.get("doc")))
            return out
        out = {"project": pid, "name": _text(d.get("name"), "статья", 300), "party": _text(d.get("party"), "кому", 300),
               "amount": _amount(d.get("amount")), "date": _date(d.get("date"), "дата"), "paid": bool(d.get("paid")),
               "note": _text(d.get("note"), "заметка")}
        if not (out["name"] or out["party"]):
            raise WorkError("у расхода нужна статья или получатель")
        return out
    if kind == "shows":
        pid = str(d.get("project") or "")
        if pid not in data["projects"]:
            raise WorkError("гастроли: такого проекта нет")
        venue = str(d.get("venue") or "")
        if venue and not _VENUE.match(venue):
            raise WorkError("гастроли: неверный номер площадки")
        out = {"project": pid, "date": _date(d.get("date"), "дата"), "venue": venue,
               "name": _text(d.get("name"), "площадка", 300), "city": _text(d.get("city"), "город", 120),
               "sale": _enum(d.get("sale"), SALE, "продажи", ""), "sale_ok": _date(d.get("sale_ok"), "разрешено"), "sale_on": _date(d.get("sale_on"), "в продаже с")}
        if not (out["name"] or out["city"]):
            raise WorkError("у гастролей нужна площадка или город")
        return out
    if kind == "stages":
        out = {"name": _text(d.get("name"), "статус", 40), "color": _enum(d.get("color"), STAGE_COLORS, "цвет", "gray"),
               "order": _int(d.get("order"), "порядок", 0, 1000), "done": bool(d.get("done"))}
        if not out["name"]:
            raise WorkError("у статуса нужно название")
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
               "prio": _enum(d.get("prio"), PRIO, "приоритет", ""), "status": _enum(d.get("status"), STATUS, "статус", ""),
               "log": _log(d.get("log")), "pin": bool(d.get("pin")), "remind": bool(d.get("remind"))}
        if not out["text"]:
            raise WorkError("у задачи нужен текст")
        if out["done"]:
            out["done_at"] = _date(d.get("done_at"), "сделано") or datetime.now().strftime("%Y-%m-%d")
        return out
    if kind == "goals":
        month = str(d.get("month") or "")
        if not _MONTH.match(month):
            raise WorkError("цель: месяц вида ГГГГ-ММ")
        out = {"month": month, "text": _text(d.get("text"), "цель", 300), "done": bool(d.get("done")), "order": _int(d.get("order"), "порядок", 0, 10000)}
        if not out["text"]:
            raise WorkError("у цели нужен текст")
        return out
    if kind == "parties":
        inn = re.sub(r"\s", "", str(d.get("inn") or ""))
        if inn and not re.fullmatch(r"\d{10}|\d{12}", inn):
            raise WorkError("ИНН — 10 или 12 цифр")
        venue = str(d.get("venue") or "")
        if venue and not _VENUE.match(venue):
            raise WorkError("неверный номер площадки")
        out = {"name": _text(d.get("name"), "название", 300), "legal": _text(d.get("legal"), "юрлицо", 300), "inn": inn,
               "city": _text(d.get("city"), "город", 120), "service": _enum(d.get("service"), PARTY_SERVICE, "услуга", ""),
               "edo": _enum(d.get("edo"), EDO, "ЭДО", ""), "contact": _text(d.get("contact"), "контакт", 300),
               "phone": _text(d.get("phone"), "телефон", 200), "email": _text(d.get("email"), "почта", 200),
               "note": _text(d.get("note"), "заметка"), "venue": venue}
        if not out["name"]:
            raise WorkError("у контрагента нужно название")
        return out
    pid = str(d.get("project") or "")
    if pid and pid not in data["projects"]:
        raise WorkError("такого проекта нет")
    cp = str(d.get("cp") or "")
    if cp and cp not in data["parties"]:
        raise WorkError("такого контрагента нет")
    out = {"project": pid, "cp": cp, "kind": _text(d.get("kind"), "документ", 200),
           "party": data["parties"][cp]["name"] if cp else _text(d.get("party"), "с кем", 300),   # название — копией: строка читается и без контрагента
           "status": _enum(DOC_STATUS_OLD.get(d.get("status"), d.get("status")), DOC_STATUS, "статус", "wait"),
           "amount": _amount(d.get("amount")), "paid": _amount(d.get("paid")), "inv": _enum(d.get("inv"), INV, "счёт", ""),
           "orig_out": bool(d.get("orig_out")), "orig_in": bool(d.get("orig_in")), "note": _text(d.get("note"), "заметка")}
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
            if kind == "projects":   # дата создания не меняется правками; новый проект — сегодня
                rec["created"] = (data[kind].get(oid) or {}).get("created") or rec["created"] or datetime.now().strftime("%Y-%m-%d")
            for keep in ("media", "pfiles"):   # фото и документы проекта меняются отдельно — правка полей их не трогает
                if kind == "projects" and (data[kind].get(oid) or {}).get(keep):
                    rec[keep] = data[kind][oid][keep]
                elif kind == "projects" and oid not in data[kind] and isinstance((op.get("data") or {}).get(keep), dict):
                    rec[keep] = _own_files(oid, op["data"][keep], keep)   # «Вернуть» удалённый проект: его файлы остались на диске
            if kind == "tasks" and rec["project"] != (data["tasks"].get(oid) or {}).get("project", rec["project"]):
                for n in data["notes"].values():   # задачу перенесли в другой проект — её рабочие заметки следом
                    if n.get("task") == oid:
                        n["project"] = rec["project"]
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
            if kind == "stages" and oid in data["stages"]:
                n = sum(1 for p in data["projects"].values() if p.get("stage") == oid)
                if n:
                    raise WorkError(f"в этом статусе проектов: {n} — сначала перенесите их в другой")
                if len(data["stages"]) == 1:
                    raise WorkError("нужен хотя бы один статус")
            data[kind].pop(oid, None)
            if kind == "tags":   # убрали тег — снимается и с задач
                for r in data["tasks"].values():
                    if oid in (r.get("tags") or []):
                        r["tags"] = [t for t in r["tags"] if t != oid]
            if kind == "parties":   # документы контрагента остаются — с его названием, без связи
                for r in data["docs"].values():
                    if r.get("cp") == oid:
                        r["cp"] = ""
            if kind == "tasks":   # рабочие заметки задачи остаются — в проекте, без задачи
                for n in data["notes"].values():
                    if n.get("task") == oid:
                        n["task"] = ""
            if kind == "projects":   # задачи и документы проекта остаются — «без проекта»; гастроли — тоже (вернётся проект — вернутся и они)
                for k in ("tasks", "docs", "costs", "notes", "shows"):
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


def note_file(op: dict) -> dict:
    """Картинка или файл рабочей заметки: сохраняется в work_media как «номер заметки-fXXXXXXXX.расш»; в текст заметки
    редактор вставляет ссылку. Заметки может ещё не быть на сервере (новая сохраняется с первым текстом) — нужен только номер."""
    oid, name = str(op.get("id") or ""), _text(op.get("name"), "имя файла", 200)
    m = re.match(r"^data:[\w.+/-]*;base64,([A-Za-z0-9+/=]+)$", str(op.get("data") or ""))
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not _ID.match(oid):
        raise WorkError("неверный номер заметки")
    if not m or ext not in NOTE_EXT:
        raise WorkError("файл: PDF, Word, Excel, PowerPoint, картинка, текст или архив")
    raw = base64.b64decode(m.group(1))
    if len(raw) > DOC_MAX:
        raise WorkError("файл: не больше 15 МБ")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{oid}-f{secrets.token_hex(4)}.{ext}"
    (MEDIA_DIR / fname).write_bytes(raw)
    return {"file": fname, "name": name, "size": len(raw)}


def _doc_files(node):
    """Файлы и картинки в тексте рабочей заметки: (файл, имя)."""
    if isinstance(node, dict):
        a = node.get("attrs") or {}
        if a.get("file"):
            yield a["file"], a.get("name") or a.get("alt") or ""
        for c in node.get("content") or []:
            yield from _doc_files(c)


def doc_name(name: str) -> str:
    """Под каким именем отдавать документ проекта или файл заметки при скачивании — как его загружали."""
    d = load()
    for p in d["projects"].values():
        for f in (p.get("pfiles") or {}).values():
            if f.get("file") == name:
                return f.get("name") or name
    for n in d["notes"].values():
        for f, fname in _doc_files(n.get("doc")):
            if f == name and fname:
                return fname
    return name


def media_file(name: str):
    if not FILE_NAME.match(name or ""):
        return None
    path = MEDIA_DIR / name
    return path if path.is_file() else None


# ---------------------------------------------------------------- напоминания в Telegram (колокольчик у задачи, «Обзор» 26.10)

REMIND_HOUR = 9                                    # утром: первый запуск tm-sync после 9:00
REMIND_FILE = BASE_DIR / "data" / "work_remind.json"   # {"day": ГГГГ-ММ-ДД} — в этот день уже отправлено


def remind(now: datetime | None = None, send=None) -> int:
    """Раз в день: задачи с колокольчиком, срок которых сегодня или прошёл, а задача не сделана, — одним сообщением.
    Telegram не настроен — ничего не отправляется и день не отмечается (настроят — придёт в тот же день)."""
    from competitors import telegram
    now, send = now or datetime.now(), send or telegram.send
    today = now.strftime("%Y-%m-%d")
    if now.hour < REMIND_HOUR or load_json(REMIND_FILE, {}).get("day") == today:
        return 0
    d = load()
    due = sorted((t for t in d["tasks"].values() if t.get("remind") and not t.get("done") and t.get("due") and t["due"] <= today),
                 key=lambda t: (t["due"], t.get("text", "")))
    if not due:
        save_json(REMIND_FILE, {"day": today})
        return 0
    lines = []
    for t in due:
        p = d["projects"].get(t.get("project") or "") or {}
        when = "сегодня" if t["due"] == today else "просрочено с " + ".".join(reversed(t["due"].split("-")[1:]))
        lines.append(f"• {t['text']}" + (f" — {p['title']}" if p.get("title") else "") + f" ({when})")
    if not send(f"🔔 Задачи на сегодня — {len(due)}:\n" + "\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else "")):
        return 0
    save_json(REMIND_FILE, {"day": today})
    return len(due)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["remind"]:
        n = remind()
        print(f"напоминания: отправлено задач {n}" if n else "напоминания: нечего отправлять, рано или уже отправлено сегодня")
