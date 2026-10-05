"""
Ручная разметка «Афиши рынка»: гастроль или местное, тип площадки, правки мероприятий, фильтры.

Всё хранится в config/market_curation.json (ветка main) — интерфейс сохраняет туда через
app.py и сразу отправляет на GitHub, сбор рынка на сервере применяет разметку каждый вечер.
При переходе на базу данных файл переносится в таблицу как есть.

    {"projects": {ключ проекта: {"type": "tour"|"local", "title", "at"}},
     "venues":   {"город|ключ площадки": {"type": "rental"|"repertory"|"mixed", "name", "city", "at"}},
     "edits":    {номер строки: {"fields": {поле: значение}, "at"}},
     "filters":  {"show": "tour"|"local"|"all", "pmin": число|null, "pmax": число|null, "noprice": bool}}

Гастроль или местное — по порядку: пометка проекта → пометка площадки → автоматические признаки.
Те же правила повторены в прототипе (Design/prototype/index.html, mClassify) — менять вместе.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "market_curation.json"
DEFAULT = {"projects": {}, "venues": {}, "edits": {}, "filters": {"show": "tour", "pmin": None, "pmax": None, "noprice": False}}
TYPES = {"tour", "local"}
VENUE_TYPES = {"rental", "repertory", "mixed"}
EDIT_FIELDS = {"title", "date", "time", "city", "venue", "sphere", "format", "genre", "pmin", "pmax"}
THEATRE_FORMATS = {"Спектакль", "Балет", "Опера", "Мюзикл", "Музыкальный спектакль"}
# Репертуарные сцены: у них свой коллектив и спектакли по многу раз
REPERTORY = re.compile(r"драм|тюз|юного зрител|кукол|молод[её]жн\w* театр|оперы и балета|опера балет|музыкальн\w* театр|"
                       r"камерн\w* театр|академическ|театр-студ|театр на |государственн\w* театр|гостеатр|театр драмы|театр им", re.I)
RENTAL = re.compile(r"(?<![а-яё])дк(?![а-яё])|дом культуры|дворец|концертн|арена|холл|hall|клуб|club|центр культуры|цко|бар(?![а-яё])", re.I)
# Одинаковое название в разных городах, но это местные вечера (решение пользователя 05.10): 1) общие названия;
# 2) разные организаторы в разных городах и дешёвые билеты. Ваша пометка проекта / площадки — сильнее этих правил.
GENERIC_LOCAL = re.compile(r"открыт\w*\s+микрофон|open[\s-]?mic|проверк\w*\s+(нового\s+)?материал|тестирован\w*\s+материал", re.I)
CHEAP_MAX = 700   # ₽: максимальная цена билета, при которой «разные организаторы» считаются местными вечерами
_STOP = set("концерт шоу тур tour группа гр спектакль балет мюзикл опера stand up standup стендап программа при и в на с со the".split())


def project_key(title: str) -> str:
    """Проект = программа: слова названия без скобок и служебных слов, по алфавиту (как projKey в прототипе)."""
    words = re.split(r"[^a-zа-я0-9]+", re.sub(r"\([^)]*\)", " ", (title or "").lower().replace("ё", "е")))
    words = sorted({w for w in words if len(w) >= 2 and w not in _STOP})
    return " ".join(words) if any(len(w) >= 3 for w in words) else ""


def venue_key(city: str, venue: str) -> str:
    return city + "|" + re.sub(r"[«»\"'.,\s-]", "", (venue or "").lower().replace("ё", "е"))


def auto_venue_type(name: str) -> str:
    return "repertory" if REPERTORY.search(name or "") else "rental" if RENTAL.search(name or "") else "mixed"


def load() -> dict:
    cur = load_json(FILE, {})
    return {k: {**DEFAULT[k], **cur.get(k, {})} if isinstance(DEFAULT[k], dict) else cur.get(k, DEFAULT[k]) for k in DEFAULT}


class CurationError(ValueError):
    pass


def _num(v):
    if v in (None, ""):
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise CurationError("цена — число рублей")
    if n < 0 or n > 1_000_000:
        raise CurationError("цена вне разумных пределов")
    return n


def apply_op(op: dict) -> tuple[dict, str]:
    """Одна правка из интерфейса. Возвращает (разметка, подпись для коммита)."""
    cur, now, kind = load(), datetime.now().isoformat(timespec="seconds"), op.get("op")
    if kind == "project":
        key = project_key(op.get("title", "")) or op.get("key", "")
        if not key:
            raise CurationError("не удалось определить проект по названию")
        if op.get("type") in TYPES:
            cur["projects"][key] = {"type": op["type"], "title": op.get("title", ""), "at": now}
        else:
            cur["projects"].pop(key, None)
        note = f"проект «{op.get('title', key)}» — {({'tour': 'гастроль', 'local': 'местное'}).get(op.get('type'), 'авто')}"
    elif kind == "venue":
        key = venue_key(op.get("city", ""), op.get("venue", ""))
        if op.get("type") in VENUE_TYPES:
            cur["venues"][key] = {"type": op["type"], "name": op.get("venue", ""), "city": op.get("city", ""), "at": now}
        else:
            cur["venues"].pop(key, None)
        note = f"площадка {op.get('city')} · {op.get('venue')} — {op.get('type') or 'авто'}"
    elif kind == "edit":
        key, fields = op.get("key"), op.get("fields") or {}
        if not key:
            raise CurationError("нет номера мероприятия")
        bad = set(fields) - EDIT_FIELDS
        if bad:
            raise CurationError("нельзя править: " + ", ".join(sorted(bad)))
        clean = {}
        for f, v in fields.items():
            clean[f] = _num(v) if f in ("pmin", "pmax") else str(v or "").strip()
        if "title" in clean and not clean["title"]:
            raise CurationError("название не может быть пустым")
        if "date" in clean and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean["date"]):
            raise CurationError("дата — в виде ГГГГ-ММ-ДД")
        if clean.get("pmin") and clean.get("pmax") and clean["pmin"] > clean["pmax"]:
            raise CurationError("цена «от» больше цены «до»")
        if clean:
            cur["edits"][key] = {"fields": clean, "at": now}
        else:
            cur["edits"].pop(key, None)
        note = f"правка мероприятия {key}"
    elif kind == "revert":
        cur["edits"].pop(op.get("key"), None)
        note = f"вернуть данные парсера {op.get('key')}"
    elif kind == "filters":
        f = op.get("filters") or {}
        cur["filters"] = {"show": f.get("show") if f.get("show") in ("tour", "local", "all") else "tour",
                          "pmin": _num(f.get("pmin")), "pmax": _num(f.get("pmax")), "noprice": bool(f.get("noprice"))}
        note = "фильтры рынка"
    else:
        raise CurationError("неизвестная правка")
    save_json(FILE, cur)
    return cur, note


def apply_edits(rows: list[dict], cur: dict) -> None:
    """Ручные правки мероприятий поверх данных парсера (исходные значения — в row["orig"])."""
    for r in rows:
        e = next((cur["edits"][k] for k in r["keys"] if k in cur["edits"]), None)  # строка могла склеиться с другой
        if e:
            r["orig"] = {f: r.get(f) for f in e["fields"]}
            r.update(e["fields"])


def classify(rows: list[dict], cur: dict) -> None:
    """row["tour"] = "tour"|"local", row["tour_src"] = project|venue|auto, row["tour_why"] — причина словами."""
    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        # Проект — по названию парсера: переименование правкой не выводит мероприятие из его тура (копия — mClassify / curApply)
        r["pk"] = project_key((r.get("orig") or {}).get("title") or r["title"])
        groups[r["pk"]][r["city"]].append(r)
    for r in rows:
        mark = cur["projects"].get(r["pk"])
        if mark:
            r["tour"], r["tour_src"], r["tour_why"] = mark["type"], "project", "отмечено вручную"
            continue
        vmark = cur["venues"].get(venue_key(r["city"], r["venue"]))
        if vmark and vmark["type"] in ("rental", "repertory"):
            r["tour"] = "tour" if vmark["type"] == "rental" else "local"
            r["tour_src"], r["tour_why"] = "venue", ("прокатная площадка" if vmark["type"] == "rental" else "репертуарный театр") + " (вручную)"
            continue
        r["tour_src"] = "auto"
        r["tour"], r["tour_why"] = _auto(r, groups)


def _local_lookalike(g: dict) -> bool:
    """Одно название в 2+ городах, но у каждого города свой организатор (известны хотя бы два) и все билеты до CHEAP_MAX."""
    rows = [x for c in g.values() for x in c]
    if not rows or not all(x.get("pmax") and x["pmax"] <= CHEAP_MAX for x in rows):
        return False
    orgs_by_city = {c: {x["org"] for x in xs if x.get("org")} for c, xs in g.items()}
    seen: dict[str, int] = {}
    for orgs in orgs_by_city.values():
        for o in orgs:
            seen[o] = seen.get(o, 0) + 1
    return len(seen) >= 2 and all(n == 1 for n in seen.values())


def _auto(r: dict, groups) -> tuple[str, str]:
    if GENERIC_LOCAL.search((r.get("orig") or {}).get("title") or r["title"]):
        return "local", "общее название — местные вечера в каждом городе (открытый микрофон и т. п.)"
    if r.get("ytour"):
        return "tour", "«Тур артиста» на Яндекс Афише"
    g = groups.get(r["pk"]) if r["pk"] else None
    if not g or len(g) < 2:
        return "local", "есть только в этом городе"
    here = g[r["city"]]
    if len(here) >= 3 and len({x["venue"] for x in here}) == 1:
        return "local", f"репертуар: {len(here)} дат на одной сцене"
    if r["format"] in THEATRE_FORMATS:
        venues = [x["venue"] for c in g.values() for x in c]
        if all(REPERTORY.search(v) for v in venues):
            return "local", "одноимённые постановки в репертуарных театрах"
        if max(len(c) for c in g.values()) >= 4:
            return "local", "репертуар: 4+ даты в одном городе"
    if _local_lookalike(g):
        return "local", f"одно название, но в каждом городе свой организатор и билеты до {CHEAP_MAX} ₽"
    return "tour", f"в {len(g)} городах"
