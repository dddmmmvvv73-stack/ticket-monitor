"""
«Афиша рынка»: что идёт в 98 городах — по Кассиру (kassir.ru) и Яндекс Афише.

Только афиша: название, дата, площадка, город, ниша, цены — без схем залов и
денег. Сбор раз в сутки (21:00 МСК, запускает cron-job.org → market.yml).
«Новое» — мероприятие, которого не было ни в одном прошлом сборе.

Запуск:
    python3 -m competitors.market            сбор
    python3 -m competitors.market export     снимок для прототипа (Design/prototype/market-data.js)
    MARKET_ONLY="Владимир,Иваново" …         сбор только по этим городам (проверка)

Что где лежит:
    config/market.json                 города списка и их федеральные округа
    config/market_kassir_regions.json  справочник Кассира: регионы (поддомены) и города внутри них
    data/competitors/market/events.json    текущая афиша (строка = мероприятие в одну дату)
    data/competitors/market/seen.json      все когда-либо виденные номера мероприятий → дата первого появления
    data/competitors/market/days/Д.json    что появилось и что исчезло в этот день
    data/competitors/market/status.json    итог последнего сбора
    data/competitors/market/market.log     журнал
Ниши — те же правила, ручные правки и кэш нейросети, что у сбора конкурентов.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from competitors.classifier import GENRES, classify_by_rules, classify_with_ai, title_key
from competitors.storage import BASE_DIR, CONFIG_DIR, DATA_DIR, load_json, save_json

MARKET_DIR = DATA_DIR / "market"
EVENTS_FILE = MARKET_DIR / "events.json"
SEEN_FILE = MARKET_DIR / "seen.json"
STATUS_FILE = MARKET_DIR / "status.json"
DAYS_DIR = MARKET_DIR / "days"
LOG_FILE = MARKET_DIR / "market.log"
CITIES_FILE = CONFIG_DIR / "market.json"
KASSIR_REGIONS_FILE = CONFIG_DIR / "market_kassir_regions.json"
YANDEX_CITIES_CACHE = MARKET_DIR / "yandex_cities.json"
OVERRIDES_FILE = CONFIG_DIR / "classification_overrides.json"
AI_CACHE_FILE = DATA_DIR / "ai_cache.json"
PROTOTYPE_DATA = BASE_DIR / "Design" / "prototype" / "market-data.js"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
KASSIR_PAUSE = 0.8      # пауза между запросами — сайты не нагружаем
YANDEX_PAUSE = 1.2
BIG_DOMAINS = ("msk.kassir.ru", "spb.kassir.ru")   # Москву и Петербург не собираем — только города списка вокруг них
LONG_RUN_DAYS = 12      # идёт больше 12 дней — одна строка с периодом, а не строка на каждый день
AI_PER_RUN = 600        # нейросети за сбор — не больше стольких новых названий (остальные — в следующие дни)
MIN_SHARE_OF_PREVIOUS = 0.5  # источник вернул меньше половины прошлого — считаем сбой и афишу не перезаписываем


# ---------------------------------------------------------------- журнал

def log(message: str) -> None:
    line = f"{datetime.now().strftime('%d.%m %H:%M:%S')}  {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _save_lines(path, data) -> None:
    """Как save_json, но строка на запись: файл меньше, а ежедневные коммиты в ветку data — компактные правки."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dump = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    if isinstance(data, dict):
        body = "{\n" + ",\n".join(f"{dump(k)}:{dump(v)}" for k, v in sorted(data.items())) + "\n}\n"
    else:
        body = "[\n" + ",\n".join(dump(x) for x in data) + "\n]\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def _trim_log(keep: int = 3000) -> None:
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > keep:
            LOG_FILE.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- HTTP

def _get_json(url: str, opener=None, data: bytes | None = None, headers: dict | None = None, tries: int = 3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                         headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
            with (opener or urllib.request.build_opener()).open(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError, http.client.HTTPException) as e:  # сеть, обрыв ответа, не JSON
            if attempt == tries - 1:
                log(f"✖ {url[:110]} — {e}")
                return None
            time.sleep(5 * (attempt + 1))


# ---------------------------------------------------------------- города

def norm_city(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е").replace("г.", "").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def load_cities() -> tuple[list[str], dict[str, str]]:
    cfg = load_json(CITIES_FILE, {})
    cities = cfg.get("cities", [])
    only = [c.strip() for c in os.environ.get("MARKET_ONLY", "").split(",") if c.strip()]
    if only:
        cities = [c for c in cities if c in only]
    return cities, cfg.get("fo", {})


def kassir_plan(cities: list[str]) -> tuple[list[tuple[str, str, int | None, str]], dict]:
    """Какие запросы делать к Кассиру: [(поддомен, город региона, id города внутри региона или None, подпись)]."""
    regions = load_json(KASSIR_REGIONS_FILE, [])
    wanted = {norm_city(c) for c in cities}
    domains: dict[str, dict] = {}
    for reg in regions:
        if norm_city(reg["name"]) in wanted:
            domains[reg["domain"]] = reg
        for sub in reg["suburbs"]:
            if norm_city(sub["name"]) in wanted and sub["isActive"]:
                domains[reg["domain"]] = reg
    plan = []
    for domain, reg in sorted(domains.items()):
        big = domain in BIG_DOMAINS
        if not big:
            plan.append((domain, reg["name"], None, reg["name"]))
        # Все города внутри региона: иначе мероприятие без адреса площадки не отличить от столицы региона
        for sub in reg["suburbs"]:
            if sub["isActive"] and (not big or norm_city(sub["name"]) in wanted):
                plan.append((domain, reg["name"], sub["id"], sub["name"].replace("г. ", "").strip()))
    return plan, {r["domain"]: r for r in regions}


# ---------------------------------------------------------------- сбор

def fetch_kassir(plan) -> list[dict]:
    """Ответы поиска Кассира как есть: [{domain, region, suburb, items}]."""
    out = []
    for domain, region, sub_id, label in plan:
        items, page = [], 1
        while True:
            extra = f"&suburbId={sub_id}" if sub_id else ""
            d = _get_json(f"https://api.kassir.ru/api/search?domain={domain}&pageSize=100&currentPage={page}{extra}")
            time.sleep(KASSIR_PAUSE)
            if not d:
                break
            items += d.get("items", [])
            if page >= d.get("pagination", {}).get("pagesCount", 1):
                break
            page += 1
        out.append({"domain": domain, "region": region, "suburb": label if sub_id else None, "items": items})
    return out


YANDEX_QUERY = """query RubricEventsQuery($paging: PagingInput){ rubricEvents(paging:$paging){
 items{ event{ id url title contentRating type{ code name } tags{ code name type } }
   scheduleInfo{ dates placePreview placesTotal prices{ value } regularity{ singleShowtime }
     onlyPlace{ id title address city{ id name } } } }
 paging{ total } } }"""


def _yandex_headers(city_id: str) -> dict:
    # Заголовки, с которыми GraphQL Яндекс Афиши отвечает (как у самого сайта); без них — 405
    return {"Content-Type": "application/json", "Accept": "*/*", "Origin": "https://afisha.yandex.ru",
            "Referer": f"https://afisha.yandex.ru/{city_id}", "x-csrf-token": "", "X-Parent-Request-Id": "1",
            "x-force-cors-preflight": "1"}


def fetch_yandex(cities: list[str]) -> list[dict]:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:  # cookie сессии — со страницы любого города
        opener.open(urllib.request.Request("https://afisha.yandex.ru/vladimir", headers={"User-Agent": UA}), timeout=40).read()
    except Exception as e:
        log(f"✖ Яндекс Афиша не открылась: {e}")
        return []
    listed = _get_json("https://afisha.yandex.ru/api/cities?city=vladimir", opener=opener, headers=_yandex_headers("vladimir"))
    if listed and listed.get("data"):
        save_json(YANDEX_CITIES_CACHE, listed["data"])
    ids: dict[str, str] = {}
    for c in load_json(YANDEX_CITIES_CACHE, []):
        ids.setdefault(norm_city(c["name"]), c["id"])   # «Дубна» — первая из двух одноимённых, как на сайте
    out = []
    for city in cities:
        cid = ids.get(norm_city(city))
        if not cid:
            continue
        items, off = [], 0
        while True:
            body = json.dumps({"operationName": "RubricEventsQuery", "query": YANDEX_QUERY,
                               "variables": {"paging": {"limit": 100, "offset": off}}}).encode()
            d = _get_json(f"https://afisha.yandex.ru/api/graphql?city={cid}&version=601.0.0&query_name=RubricEventsQuery",
                          opener=opener, data=body, headers=_yandex_headers(cid))
            time.sleep(YANDEX_PAUSE)
            if not d or not d.get("data"):
                if d:
                    log(f"✖ Яндекс Афиша, {city}: {str(d)[:200]}")
                break
            r = d["data"]["rubricEvents"]
            items += r["items"]
            off += 100
            if off >= r["paging"]["total"]:
                break
        out.append({"city": city, "id": cid, "items": items})
    return out


# ---------------------------------------------------------------- разбор и чистка

NOISE_VENUE = re.compile(r"филиал|библиотек|сельск|(?<![а-яё])(сдк|црб|рдк|мбук|мкук|мбу|мау)(?![а-яё])", re.I)
NOISE_TITLE = re.compile(r"познавательн\w* программ|молодежн\w* программ|игров\w* программ|мастер-класс|квест|"
                         r"экскурси|аудиогид|выставк|экспозици", re.I)
# Категория сайта -> «тип на сайте» для classify_by_rules (как у vladimirkoncert.ru)
SITE_TYPE = {"koncert": "Концерт", "teatr": "Спектакль", "standup": "Стендапы", "detyam": "Для детей",
             "concert": "Концерт", "theatre": "Спектакль", "kids": "Для детей"}
# Не рынок мероприятий: кино, музеи, экскурсии, квесты, спорт
DROP_CAT = {"film", "kino", "muzey", "muzei", "ekskursii", "excursion", "excursions", "sport", "kvesty", "quest",
            "cinema", "art", "turizm", "sertifikaty", "certificates"}
EXTRA_FORMAT = {"shou": ("Шоу", "Шоу"), "show": ("Шоу", "Шоу"), "festival": ("", "Фестиваль"), "festivali": ("", "Фестиваль")}
GENRE_BY_NAME = {g.lower(): g for g in GENRES}
YANDEX_GENRE = {"хип-хоп и рэп": "Рэп / хип-хоп", "рэп": "Рэп / хип-хоп", "поп": "Поп", "поп-музыка": "Поп", "рок": "Рок",
                "джаз": "Джаз", "блюз": "Блюз", "классическая музыка": "Классическая музыка", "классика": "Классическая музыка",
                "шансон": "Шансон", "электронная музыка": "Электронная музыка", "электроника": "Электронная музыка",
                "инди": "Инди", "метал": "Метал", "панк": "Панк", "фолк": "Фолк / этника", "этно": "Фолк / этника",
                "альтернатива": "Альтернатива", "r&b": "R&B", "соул": "Соул", "фанк": "Фанк", "эстрада": "Эстрада",
                "комедия": "Комедия", "драма": "Драма", "мелодрама": "Мелодрама", "трагедия": "Трагедия",
                "трагикомедия": "Трагикомедия", "неоклассика": "Неоклассика", "стендап": "Стендап"}
YANDEX_FORMAT_TAG = {"мюзикл": ("Театр", "Мюзикл"), "балет": ("Танец", "Балет"), "опера": ("Музыка", "Опера"),
                     "стендап": ("Комедия и юмор", "Стендап"), "фестиваль": ("", "Фестиваль"), "шоу": ("Шоу", "Шоу"),
                     "спектакль": ("Театр", "Спектакль"), "концерт": ("Музыка", "Концерт"),
                     "лекция": ("Разговорный жанр", "Лекция"), "танцевальное шоу": ("Танец", "Танцевальное шоу"),
                     "иммерсивный спектакль": ("Театр", "Иммерсивный спектакль")}
SPHERE_OF_FORMAT = {"Концерт": "Музыка", "Фестиваль": "Музыка", "Спектакль": "Театр", "Шоу": "Шоу",
                    "Стендап": "Комедия и юмор", "Лекция": "Разговорный жанр"}


def niche(title: str, site_types: list[str], overrides: dict, extra=(), genre_hint: str = "") -> dict:
    """Сфера / формат / жанр: ручная правка → правила по названию и типу на сайте → теги сайта."""
    res = {f: v for f, v in overrides.get(title_key(title), {}).items() if v}
    rules, _ = classify_by_rules(title, site_types)
    for f, v in rules.items():
        res.setdefault(f, v)
    for sphere, fmt in extra:
        if fmt:
            res.setdefault("format", fmt)
        if sphere:
            res.setdefault("sphere", sphere)
    if genre_hint:
        res.setdefault("genre", genre_hint)
    if res.get("format") and not res.get("sphere"):
        res["sphere"] = SPHERE_OF_FORMAT.get(res["format"], "")
    return res


def tour_key(t: str) -> str:
    """Название для склейки источников и гастролей: без скобок, кавычек и слов «концерт», «шоу», «тур»…"""
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\b(концерт|спектакль|шоу|группа|гр\.|stand ?up|стендап|tour|тур|балет|мюзикл|опера)\b", " ", t)
    return re.sub(r"[^a-zа-я0-9]", "", t)


def _clean_venue(v: str, city: str) -> str:
    return re.sub(r"\s*\((%s)\)\s*$" % re.escape(city), "", v or "").strip() or "—"


def parse(kassir: list[dict], yandex: list[dict], cities: list[str], today: str, overrides: dict) -> tuple[list[dict], Counter]:
    city_by_norm = {norm_city(c): c for c in cities}
    dropped: Counter = Counter()
    rows: list[dict] = []

    # --- Кассир. Город — по адресу площадки («г. X»), иначе — город, в выдаче которого мероприятие,
    # иначе — поле города в адресе, иначе — столица региона. Поддомен не годится: Кассир Иванова продаёт концерт в Ярославле.
    suburb_of: dict[tuple, set] = defaultdict(set)
    for part in kassir:
        if part["suburb"]:
            for it in part["items"]:
                suburb_of[(it["type"], it["object"]["id"])].add(part["suburb"])
    seen_ids = set()
    for part in kassir:
        for it in part["items"]:
            o, key = it["object"], (it["type"], it["object"]["id"])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            cat = (o.get("urlSlug") or "").split("/")[0]
            if cat in DROP_CAT:
                dropped["Кассир: кино, музеи, экскурсии, спорт"] += 1
                continue
            venues = o.get("venues") or []
            vname = venues[0]["name"] if venues else (o.get("venueName") or "")
            if NOISE_VENUE.search(vname) or NOISE_TITLE.search(o["title"]):
                dropped["Кассир: сельские филиалы, библиотеки, программы"] += 1
                continue
            addr = (venues[0].get("address") or {}) if venues else {}
            m = re.search(r"(?:^|[\s,])г\.\s*([А-ЯЁ][а-яё]+(?:[\s\-][А-ЯЁа-яё][а-яё]+)?)", addr.get("addressString") or "")
            if m:
                city = m.group(1)
            elif suburb_of.get(key):
                city = sorted(suburb_of[key])[0]
            elif addr.get("city"):
                city = addr["city"]
            elif not part["suburb"] and part["domain"] not in BIG_DOMAINS:
                city = part["region"]
            else:
                city = None
            city = city_by_norm.get(norm_city(city))
            if not city:
                dropped["Кассир: город не из списка"] += 1
                continue
            dr = o.get("dateRange") or {}
            begins = o.get("beginsAt") or dr.get("beginsAt") or ""   # время местное, хотя помечено +00:00
            date, tm = begins[:10], begins[11:16]
            if not date or (dr.get("endsAt") or begins)[:10] < today:
                dropped["Кассир: прошло"] += 1
                continue
            if date < today:
                date, tm = today, ""
            nc = niche(o["title"], [SITE_TYPE[cat]] if cat in SITE_TYPE else [], overrides,
                       [EXTRA_FORMAT[cat]] if cat in EXTRA_FORMAT else [])
            if not nc.get("format"):
                dropped["Кассир: формат не из справочника"] += 1
                continue
            pr = o.get("priceRange") or {}
            more = max(0, (o.get("activeEventsCount") or 1) - 1)
            rows.append({"src": "k", "keys": [f"k:{it['type']}:{o['id']}"], "city": city, "venue": _clean_venue(vname, city),
                         "title": o["title"].strip(), "date": date, "time": tm, "sphere": nc.get("sphere", ""),
                         "format": nc["format"], "genre": nc.get("genre", ""),
                         "pmin": int(pr["min"]) if pr.get("min") else None, "pmax": int(pr["max"]) if pr.get("max") else None,
                         "pushkin": bool(o.get("isPushkin")),
                         "age": (o.get("ageGroup") or (o.get("ageGroups") or [{}])[0] or {}).get("name", ""),
                         "url_k": o.get("url"), "url_y": None, "more": more,
                         "until": (dr.get("endsAt") or "")[:10] if more else ""})

    # --- Яндекс Афиша: строка на каждую дату; если дат больше 12 — одна строка с периодом
    for part in yandex:
        for it in part["items"]:
            ev, sc = it["event"], it.get("scheduleInfo") or {}
            code = (ev.get("type") or {}).get("code", "")
            if code in DROP_CAT:
                dropped["Яндекс: кино, музеи, экскурсии, спорт"] += 1
                continue
            place = sc.get("onlyPlace") or {}
            vname = place.get("title") or sc.get("placePreview") or ""
            if NOISE_VENUE.search(vname) or NOISE_TITLE.search(ev["title"]):
                dropped["Яндекс: сельские филиалы, библиотеки, программы"] += 1
                continue
            city = city_by_norm.get(norm_city((place.get("city") or {}).get("name") or part["city"]))
            if not city:
                dropped["Яндекс: город не из списка"] += 1
                continue
            tags = [t["name"].lower() for t in ev.get("tags") or []]
            genre = next((YANDEX_GENRE.get(t) or GENRE_BY_NAME.get(t) for t in tags if YANDEX_GENRE.get(t) or GENRE_BY_NAME.get(t)), "")
            nc = niche(ev["title"], [SITE_TYPE[code]] if code in SITE_TYPE else [], overrides,
                       [YANDEX_FORMAT_TAG[t] for t in tags if t in YANDEX_FORMAT_TAG], genre)
            if not nc.get("format"):
                dropped["Яндекс: формат не из справочника"] += 1
                continue
            dates = sorted(x for x in (sc.get("dates") or []) if x >= today)
            if not dates:
                dropped["Яндекс: прошло"] += 1
                continue
            prices = [p["value"] / 100 for p in sc.get("prices") or [] if p.get("value")]
            one = (sc.get("regularity") or {}).get("singleShowtime") or ""
            base = {"src": "y", "city": city,
                    "venue": _clean_venue(vname if (sc.get("placesTotal") or 1) == 1 else (sc.get("placePreview") or vname), city),
                    "title": ev["title"].strip(), "sphere": nc.get("sphere", ""), "format": nc["format"], "genre": nc.get("genre", ""),
                    "pmin": int(min(prices)) if prices else None, "pmax": int(max(prices)) if prices else None,
                    "pushkin": False, "age": ev.get("contentRating") or "", "url_k": None,
                    "url_y": "https://afisha.yandex.ru" + ev["url"], "more": 0, "until": ""}
            if len(dates) > LONG_RUN_DAYS:
                rows.append({**base, "keys": [f"y:{ev['id']}"], "date": dates[0], "time": "",
                             "more": len(dates) - 1, "until": dates[-1]})
            else:
                for x in dates:
                    rows.append({**base, "keys": [f"y:{ev['id']}:{x}"], "date": x, "time": one[11:16] if one[:10] == x else ""})

    # --- Склейка: одно мероприятие на обоих сайтах — город, дата и похожее название
    by_day = defaultdict(list)
    for r in rows:
        if r["src"] == "y":
            by_day[(r["city"], r["date"])].append(r)
    out = []
    for r in rows:
        if r["src"] != "k":
            continue
        nk, hit = tour_key(r["title"]), None
        for y in by_day.get((r["city"], r["date"]), []):
            ny = tour_key(y["title"])
            if nk and ny and (nk == ny or (min(len(nk), len(ny)) >= 5 and (nk in ny or ny in nk))):
                hit = y
                break
        if hit:
            hit["src"] = "ky"
            hit["keys"] = hit["keys"] + r["keys"]
            hit["url_k"] = r["url_k"]
            hit["pushkin"] = hit["pushkin"] or r["pushkin"]
            hit["time"] = hit["time"] or r["time"]
            if hit["pmin"] is None:
                hit["pmin"], hit["pmax"] = r["pmin"], r["pmax"]
            hit["genre"] = hit["genre"] or r["genre"]
        else:
            out.append(r)
    out += [r for r in rows if r["src"] != "k"]
    out.sort(key=lambda r: (r["date"], r["time"] or "99", r["city"], r["title"]))
    return out, dropped


def classify_missing(rows: list[dict], ai: dict | None) -> int:
    """Нейросеть — только для названий без сферы или жанра и только тех, что ещё не спрашивали (кэш общий со сбором конкурентов)."""
    cache = load_json(AI_CACHE_FILE, {})
    ask: dict[str, dict] = {}
    for r in rows:
        k = title_key(r["title"])
        if (not r["genre"] or not r["sphere"]) and k not in cache and k not in ask:
            ask[k] = {"id": k, "title": r["title"], "venue": r["venue"], "site_types": [r["format"]], "description": "",
                      "known": {f: r[f] for f in ("sphere", "format", "genre") if r[f]}}
    asked = 0
    if ask and ai and ai.get("provider") in ("gigachat", "claude"):
        batch = list(ask.values())[:AI_PER_RUN]
        log(f"Нейросеть: {len(batch)} новых названий из {len(ask)} без сферы или жанра")
        answers = classify_with_ai(batch, ai, log)
        asked = len(answers)
        if answers:
            cache.update(answers)
            save_json(AI_CACHE_FILE, cache)
    elif ask:
        log(f"Нейросеть выключена — {len(ask)} названий без сферы или жанра")
    for r in rows:  # ответ нейросети заполняет только пустое; формат не трогаем — по нему уже отобрали
        for f, v in cache.get(title_key(r["title"]), {}).items():
            if f in ("sphere", "genre") and v and not r[f]:
                r[f] = v
    return asked


# ---------------------------------------------------------------- сбор целиком

def _ai_settings() -> dict | None:
    stored = load_json(CONFIG_DIR / "settings.json", {}).get("competitors", {})
    provider = stored.get("ai_provider", "gigachat")
    if provider not in ("gigachat", "claude"):
        return None
    keys = ("gigachat_auth_key", "gigachat_scope", "gigachat_model", "anthropic_api_key")
    return {"provider": provider, **{k: stored.get(k, "") for k in keys}}


def run() -> bool:
    started = time.time()
    now = datetime.now()
    today, now_iso = now.strftime("%Y-%m-%d"), now.isoformat(timespec="seconds")
    cities, _ = load_cities()
    status = load_json(STATUS_FILE, {})
    log(f"=== Сбор рынка начат: городов {len(cities)} ===")
    try:
        plan, _ = kassir_plan(cities)
        with ThreadPoolExecutor(max_workers=2) as pool:  # сайты разные — опрашиваем одновременно, паузы у каждого свои
            kassir_job, yandex_job = pool.submit(fetch_kassir, plan), pool.submit(fetch_yandex, cities)
            kassir, yandex = kassir_job.result(), yandex_job.result()
        log(f"Кассир: {len(plan)} запросов по {len({p[0] for p in plan})} регионам, записей {sum(len(p['items']) for p in kassir)}")
        log(f"Яндекс Афиша: {len(yandex)} городов, записей {sum(len(p['items']) for p in yandex)}")

        rows, dropped = parse(kassir, yandex, cities, today, load_json(OVERRIDES_FILE, {}))
        previous = load_json(EVENTS_FILE, [])
        by_src_now = Counter(s for r in rows for s in r["src"])
        by_src_before = Counter(s for r in previous for s in r["src"])
        broken = [n for s, n in (("k", "Кассир"), ("y", "Яндекс Афиша"))
                  if by_src_before[s] and by_src_now[s] < by_src_before[s] * MIN_SHARE_OF_PREVIOUS]
        if broken:  # иначе всё его мероприятия попали бы в «исчезли», а завтра — обратно
            raise RuntimeError(f"меньше половины прошлого сбора вернули: {', '.join(broken)} — афиша не обновлена")

        asked = classify_missing(rows, _ai_settings())

        # «Новое» — ни один номер строки (у Яндекса — событие и дата, у Кассира — событие) раньше не встречался
        seen = load_json(SEEN_FILE, {})
        first_run = status.get("first_run") or today
        new_rows = []
        for r in rows:
            known = [seen[k] for k in r["keys"] if k in seen]
            r["first_seen"] = min(known) if known else today
            if not known and first_run != today:
                new_rows.append(r)
            for k in r["keys"]:
                seen.setdefault(k, today)

        now_keys = {k for r in rows for k in r["keys"]}
        gone = [p for p in previous if p["date"] >= today and not any(k in now_keys for k in p["keys"])]

        _save_lines(EVENTS_FILE, rows)
        _save_lines(SEEN_FILE, seen)
        brief = lambda r: {k: r[k] for k in ("keys", "city", "venue", "title", "date", "time", "format", "sphere", "genre",
                                             "pmin", "pmax", "url_k", "url_y")}
        # Если за день сбор был не один (запуск вручную), списки дня дополняются, а не перезаписываются
        day = load_json(DAYS_DIR / f"{today}.json", {"new": [], "gone": []})
        for part, found in (("new", new_rows), ("gone", gone)):
            have = {x["keys"][0] for x in day[part]}
            day[part] += [brief(r) for r in found if r["keys"][0] not in have]
        day["at"] = now_iso
        save_json(DAYS_DIR / f"{today}.json", day)
        took = time.time() - started
        no_data = [c for c in cities if c not in {r["city"] for r in rows}]
        summary = (f"мероприятий {len(rows)} в {len(cities) - len(no_data)} городах, новых {len(new_rows)}, "
                   f"исчезло {len(gone)}, нейросеть {asked}, за {took / 60:.0f} мин")
        status.update(first_run=first_run, last_run_at=now_iso, last_ok=True, last_error=None, summary=summary,
                      rows=len(rows), new=len(new_rows), gone=len(gone), by_src=dict(Counter(r["src"] for r in rows)),
                      dropped=dict(dropped), no_data=no_data)
        log(f"=== Сбор рынка завершён: {summary} ===")
        return True
    except Exception as e:
        status.update(last_run_at=now_iso, last_ok=False, last_error=str(e))
        log(f"✖ Сбор рынка прерван: {e}")
        return False
    finally:
        save_json(STATUS_FILE, status)
        _trim_log()


# ---------------------------------------------------------------- снимок для прототипа

def export_prototype() -> None:
    """data/competitors/market → Design/prototype/market-data.js (формат — в заголовке файла)."""
    rows, status = load_json(EVENTS_FILE, []), load_json(STATUS_FILE, {})
    if not rows:
        sys.exit("Нет данных рынка — сначала ./pull_data.sh или сбор")
    all_cities, fo = load_json(CITIES_FILE, {}).get("cities", []), load_json(CITIES_FILE, {}).get("fo", {})
    lists = {"venues": [], "spheres": [], "formats": [], "genres": []}
    cities = list(all_cities)

    def idx(lst, v):
        if v not in lst:
            lst.append(v)
        return lst.index(v)
    packed = [[idx(cities, r["city"]), idx(lists["venues"], r["venue"]), r["title"], r["date"], r["time"] or "",
               idx(lists["spheres"], r["sphere"] or ""), idx(lists["formats"], r["format"]), idx(lists["genres"], r["genre"] or ""),
               r["pmin"] or 0, r["pmax"] or 0, 1 if r["pushkin"] else 0, r["src"], r["url_k"] or "", r["url_y"] or "",
               r["more"] or 0, r["until"] or "", r["first_seen"], r["age"] or ""] for r in rows]
    at = datetime.fromisoformat(status["last_run_at"])
    months = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."]
    label = f"{at.day} {months[at.month - 1]}, {at:%H:%M}"
    merged = Counter(r["src"] for r in rows)["ky"]
    data = {"at": label, "first": status.get("first_run"), "cities": cities, "fo": fo, **lists, "rows": packed,
            "stats": {"merged": merged, "dropped": status.get("dropped", {}), "bySrc": status.get("by_src", {})}}
    PROTOTYPE_DATA.write_text(
        f"// Снимок «Афиши рынка»: Кассир + Яндекс Афиша по {len(all_cities)} городам, сбор {label}.\n"
        "// Пересобрать: ./pull_data.sh && python3 -m competitors.market export\n"
        "// Строка: [город, площадка, название, дата, время, сфера, формат, жанр, цена от, цена до, Пушкинская,\n"
        "//  источник k/y/ky, ссылка Кассир, ссылка Яндекс, ещё дат, до, впервые замечено, возраст]\n"
        "var MK = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"{PROTOTYPE_DATA.relative_to(BASE_DIR)}: {len(packed)} строк, сбор {label}")


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        export_prototype()
    else:
        sys.exit(0 if run() else 1)
