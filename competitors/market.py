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
    data/competitors/market/archive.json   архив гастролей: каждое гастрольное выступление навсегда (и прошедшее)
    data/competitors/market/status.json    итог последнего сбора
    data/competitors/market/market.log     журнал
Ниши — те же правила, ручные правки и кэш нейросети, что у сбора конкурентов.
Гастроль или местное, правки мероприятий — config/market_curation.json (competitors/curation.py).
"""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import re
import sys
import time
import gzip
import html as html_lib
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from competitors import curation
from competitors.classifier import GENRES, classify_by_rules, classify_with_ai, title_key
from competitors.storage import BASE_DIR, CONFIG_DIR, DATA_DIR, load_json, save_json

MARKET_DIR = DATA_DIR / "market"
EVENTS_FILE = MARKET_DIR / "events.json"
SALES_SNAPSHOT = BASE_DIR / "data" / "sales_snapshot.json.gz"   # продажи гастролей с сервера (sales/export.py, ./pull_data.sh)
ARCHIVE_FILE = MARKET_DIR / "archive.json"
SEEN_FILE = MARKET_DIR / "seen.json"
STATUS_FILE = MARKET_DIR / "status.json"
DAYS_DIR = MARKET_DIR / "days"
LOG_FILE = MARKET_DIR / "market.log"
CITIES_FILE = CONFIG_DIR / "market.json"
KASSIR_REGIONS_FILE = CONFIG_DIR / "market_kassir_regions.json"
YANDEX_CITIES_CACHE = MARKET_DIR / "yandex_cities.json"
KASSIR_TITLES_FILE = MARKET_DIR / "kassir_titles.json"     # заголовки страниц Кассира для спорных склеек: адрес → [название, дата]
VENUE_ALIASES_FILE = MARKET_DIR / "venue_aliases.json"     # одна площадка под разными названиями: {город: [[a, b], …]}
ORGANIZERS_FILE = MARKET_DIR / "organizers.json"   # карточка Кассира → [организатор, дата проверки]
ORG_BUDGET_MIN = 30     # страниц Кассира за сбор — не дольше стольких минут (первый проход растягивается на несколько вечеров)
ORG_RECHECK_DAYS = 30   # организатор карточки перепроверяется раз в месяц
ORG_THREADS = 3         # страницы разных региональных сайтов Кассира — в три потока (~90 страниц в минуту)
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


# ---------------------------------------------------------------- склейка Кассир ↔ Яндекс

_LAT = [("zz", "цц"), ("shch", "щ"), ("sch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ya", "я"), ("yu", "ю"),
        ("yo", "ё"), ("ph", "ф"), ("th", "т"), ("ck", "к"), ("x", "кс"), ("w", "в"), ("q", "к")]
_LAT1 = dict(zip("abcdefghijklmnoprstuvyz", "абкдефгхийклмнопрстувиз"))
TITLE_STOP = {"концерт", "спектакль", "шоу", "программа", "оркестр", "оркестра", "симфония", "симфонический", "свечах", "при",
              "абонемент", "вечер", "музыка", "музыки", "тур", "группа", "новая", "новый", "show", "the", "and", "live", "фестиваль",
              "праздник", "детский", "сольный", "юбилейный", "творческий", "театр", "трибьют", "tribute", "cagmo", "кагмо",
              "новогодний", "новогоднее", "новогодняя", "рождественский", "стендап", "standup", "квартет", "хиты", "лучшее"}
VENUE_STOP = {"театр", "дворец", "культуры", "центр", "концертный", "зал", "клуб", "дом", "имени", "государственный",
              "областной", "городской", "краевой", "краевая", "областная", "сцена", "основная", "искусств", "искусства",
              "народного", "творчества", "музыкальный", "драматический", "академический", "уральский", "культурное", "пространство"}


def _lat2cyr(t: str) -> str:
    for a, b in _LAT:
        t = t.replace(a, b)
    return "".join(_LAT1.get(ch, ch) for ch in t)


def _words(t: str, stop: set) -> set:
    """Значимые слова по основе — первые 5 букв: «Богдана Лисевского» и «Богдан Лисевский», Scorpions и «Скорпионс»."""
    t = (t or "").lower().replace("ё", "е")
    out = set()
    for w in re.findall(r"[^\W_]+", t):  # любые буквы: «Дөр», «Мӑнаккасем»
        c = _lat2cyr(w)
        if len(w) >= 3 and w not in stop and c not in stop:
            out.add(c[:5] if len(c) >= 7 else c[:4] if len(c) >= 5 else c)  # «Коцкой» и «Коцкая» → «коцк»
    return out


def _sorted_key(t: str) -> str:
    """Слова по алфавиту и в кириллице — для сравнения без учёта порядка («Симфония Queen…» и «…Квин…»)."""
    return " ".join(sorted(_lat2cyr(w) for w in re.findall(r"[^\W_]+", (t or "").lower().replace("ё", "е"))))


def similar_title(a: str, b: str) -> bool:
    """Одно мероприятие под разными названиями: общие слова, перестановка, транслит, опечатка («Гуф/Guf» и «Guf»)."""
    ka, kb = tour_key(a), tour_key(b)
    if not ka or not kb:  # название из одних служебных слов («Мюзикл-шоу») — сравниваем как есть
        return bool(_sorted_key(a)) and _sorted_key(a) == _sorted_key(b)
    if ka == kb or (min(len(ka), len(kb)) >= 4 and (ka in kb or kb in ka)):
        return True
    if _words(a, TITLE_STOP) & _words(b, TITLE_STOP):
        return True
    # Короткое название — первое слово длинного: «NЮ» и «NЮ. Юрий Николаенко»
    fa, fb = re.findall(r"[^\W_]+", a.lower()), re.findall(r"[^\W_]+", b.lower())
    if fa and fb and (len(fa) == 1 or len(fb) == 1) and fa[0] == fb[0] and len(fa[0]) >= 2:
        return True
    ca, cb = _lat2cyr(ka), _lat2cyr(kb)
    return ca == cb or SequenceMatcher(None, ca, cb).ratio() >= 0.8 or SequenceMatcher(None, _sorted_key(a), _sorted_key(b)).ratio() >= 0.85


VENUE_ABBR = {"дк": "дворец культуры", "ккз": "киноконцертный зал", "кз": "концертный зал", "гкз": "государственный концертный зал",
              "бкз": "большой концертный зал", "дкж": "дворец культуры железнодорожников", "дс": "дворец спорта",
              "лдс": "ледовый дворец спорта", "дзис": "дворец зрелищ и спорта", "кдц": "культурно досуговый центр",
              "скк": "спортивно концертный комплекс", "ск": "спортивный комплекс", "тюз": "театр юного зрителя",
              "цко": "центр культуры и отдыха", "цкио": "центр культуры и отдыха", "мтс": "мтс"}


def venue_core(v: str, city: str = "") -> tuple[str, set]:
    """Название площадки без служебных слов и города, с раскрытыми сокращениями и в кириллице: «ККЗ Пенза» → «киноконцертный»."""
    town = _lat2cyr((city or "").lower().replace("ё", "е"))[:4]
    words = []
    for w in re.findall(r"[^\W_]+", (v or "").lower().replace("ё", "е")):
        words += VENUE_ABBR.get(w, w).split()
    core = [c for c in (_lat2cyr(w) for w in words) if c not in VENUE_STOP and len(c) > 1 and not (town and c.startswith(town))]
    return "".join(core), {w for w in core if w.isdigit()}


class Aliases:
    """Одна площадка под разными названиями — выученные пары (город, ядро, ядро) из уверенных склеек."""

    def __init__(self, data: dict | None = None):
        self.pairs = {c: [list(p) for p in v] for c, v in (data or {}).items()}
        self.group: dict[tuple, str] = {}
        for c, pairs in self.pairs.items():
            for x, y in pairs:
                self._join(c, x, y)

    def _find(self, c: str, x: str) -> str:
        g = self.group.get((c, x), x)
        return g if g == x else self._find(c, g)

    def _join(self, c: str, x: str, y: str) -> None:
        gx, gy = self._find(c, x), self._find(c, y)
        if gx != gy:
            self.group[(c, gx)] = gy

    def same(self, c: str, x: str, y: str) -> bool:
        return bool(x and y) and self._find(c, x) == self._find(c, y)

    def learn(self, c: str, a: str, b: str) -> bool:
        x, y = venue_core(a, c)[0], venue_core(b, c)[0]
        if not x or not y or x == y or self.same(c, x, y):
            return False
        self.pairs.setdefault(c, []).append([x, y])
        self._join(c, x, y)
        return True

    def dump(self) -> dict:
        return self.pairs


def same_venue(a: str, b: str, city: str = "", aliases: Aliases | None = None) -> bool:
    """«Окружной Дом Офицеров» и «Дом офицеров», «ККЗ Пенза» и «Киноконцертный зал «Пенза»», «ДКЖ» и «Дворец культуры
    железнодорожников», «Алькатрас» и Alcatraz; школа № 56 и школа № 19 — разные; выученные пары — одна площадка."""
    (ca, na), (cb, nb) = venue_core(a, city), venue_core(b, city)
    if aliases and aliases.same(city, ca, cb):
        return True
    if na and nb and not (na & nb):
        return False
    if not ca or not cb:  # одни служебные слова («Филармония», «ДК Барнаула») — целиком, с раскрытыми сокращениями
        full = lambda v: "".join(_lat2cyr(x) for w in re.findall(r"[^\W_]+", (v or "").lower().replace("ё", "е"))
                                 for x in VENUE_ABBR.get(w, w).split())
        fa, fb = full(a), full(b)
        return bool(fa and fb) and (fa in fb or fb in fa or SequenceMatcher(None, fa, fb).ratio() >= 0.9)
    if ca == cb or (min(len(ca), len(cb)) >= 4 and (ca in cb or cb in ca)):
        return True
    town = _lat2cyr((city or "").lower().replace("ё", "е"))[:4]
    wa = {w for w in _words(a, VENUE_STOP) if not (town and w.startswith(town)) and not w.isdigit()}
    wb = {w for w in _words(b, VENUE_STOP) if not (town and w.startswith(town)) and not w.isdigit()}
    return bool(wa & wb) or SequenceMatcher(None, ca, cb).ratio() >= 0.75


def strict_title(a: str, b: str) -> bool:
    """Строже similar_title — когда нет времени или оба с одного сайта: то же название с точностью до порядка слов и опечаток."""
    ka, kb = tour_key(a), tour_key(b)
    if ka and kb and (ka == kb or (min(len(ka), len(kb)) >= 5 and (ka in kb or kb in ka))):
        return True
    sa, sb = _sorted_key(a), _sorted_key(b)
    return bool(sa) and (sa == sb or SequenceMatcher(None, sa, sb).ratio() >= 0.9)


def _merge(hit: dict, r: dict) -> None:
    """Строка Кассира r — в строку Яндекса hit: название и ссылка Яндекса, ссылка и Пушкинская — с Кассира."""
    hit["src"] = "ky" if {hit["src"], r["src"]} != {hit["src"]} else hit["src"]  # дубль с того же сайта — источник прежний
    hit["keys"] = hit["keys"] + r["keys"]
    hit["url_k"] = hit["url_k"] or r["url_k"]
    hit["url_y"] = hit["url_y"] or r["url_y"]
    hit["pushkin"] = hit["pushkin"] or r["pushkin"]
    hit["time"] = hit["time"] or r["time"]
    if hit["pmin"] is None:
        hit["pmin"], hit["pmax"] = r["pmin"], r["pmax"]
    hit["genre"] = hit["genre"] or r["genre"]
    hit["org"] = hit.get("org") or r.get("org") or ""


def dedupe_source(rows: list[dict], aliases: Aliases | None = None) -> list[dict]:
    """Дубли внутри одного сайта: Кассир продаёт концерт с нескольких региональных доменов, Яндекс заводит две карточки.
    Тот же город, дата, время, площадка и то же название (строгое сравнение) — одна строка."""
    keep, merged, slot = [], 0, defaultdict(list)
    for r in rows:
        if not r["time"]:
            keep.append(r)
            continue
        twin = next((x for x in slot[(r["src"], r["city"], r["date"], r["time"])]
                     if strict_title(x["title"], r["title"]) and same_venue(x["venue"], r["venue"], r["city"], aliases)), None)
        if twin:
            _merge(twin, r)
            merged += 1
        else:
            slot[(r["src"], r["city"], r["date"], r["time"])].append(r)
            keep.append(r)
    log(f"Дубли внутри сайта: склеено {merged}")
    return keep


def merge_by_slot(rows: list[dict], aliases: Aliases | None = None) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """
    Вторая склейка: тот же город, дата, время и площадка, а название записано по-разному. Если названия совсем
    разные — спорный случай (бывает и два зала в один час): его проверяет resolve_kassir_titles по странице Кассира.
    """
    slot = defaultdict(list)
    for y in rows:
        if y["src"] == "y" and y["time"]:
            slot[(y["city"], y["date"], y["time"])].append(y)
    keep, conflicts, merged = [], [], 0
    for r in rows:
        if r["src"] != "k" or not r["time"]:
            keep.append(r)
            continue
        cands = [y for y in slot.get((r["city"], r["date"], r["time"]), []) if y["src"] == "y" and same_venue(r["venue"], y["venue"], r["city"], aliases)]
        hit = next((y for y in cands if similar_title(r["title"], y["title"])), None)
        if hit:
            if aliases:
                aliases.learn(r["city"], r["venue"], hit["venue"])
            _merge(hit, r)
            merged += 1
            continue
        keep.append(r)
        if len(cands) == 1:
            conflicts.append((r, cands[0]))
    # Время есть только у одного сайта (у Яндекса часто нет): та же площадка и то же название — строгое сравнение
    day = defaultdict(list)
    for y in keep:
        if y["src"] == "y":
            day[(y["city"], y["date"])].append(y)
    rest, no_time = [], 0
    for r in keep:
        if r["src"] != "k":
            rest.append(r)
            continue
        cands = [y for y in day.get((r["city"], r["date"]), []) if y["src"] == "y" and not (r["time"] and y["time"])
                 and same_venue(r["venue"], y["venue"], r["city"], aliases) and strict_title(r["title"], y["title"])]
        if len(cands) == 1:
            _merge(cands[0], r)
            no_time += 1
        else:
            rest.append(r)
    conflicts = [(r, y) for r, y in conflicts if y["src"] == "y" and any(x is r for x in rest)]
    log(f"Склейка по месту и времени: {merged} мероприятий Кассира — те же, что на Яндексе, ещё {no_time} — без времени "
        f"у одного из сайтов; спорных {len(conflicts)}")
    return rest, conflicts


def merge_unique_strict(rows: list[dict], aliases: Aliases | None = None) -> tuple[list[dict], int]:
    """Одно и то же название (строго: порядок слов, опечатки) в городе в ту же дату и час, и такое у Яндекса одно —
    одно мероприятие, даже если площадка записана непохоже («ОЦКНТ» и «Центр культуры, народного творчества и кино»):
    артист не выступает в двух местах города одновременно. Пара площадок запоминается для следующих склеек."""
    slot = defaultdict(list)
    for y in rows:
        if y["src"] == "y" and y["time"]:
            slot[(y["city"], y["date"], y["time"])].append(y)
    keep, merged = [], 0
    for r in rows:
        if r["src"] == "k" and r["time"]:
            cands = [y for y in slot.get((r["city"], r["date"], r["time"]), []) if y["src"] == "y" and strict_title(r["title"], y["title"])]
            if len(cands) == 1:
                if aliases:
                    aliases.learn(r["city"], r["venue"], cands[0]["venue"])
                _merge(cands[0], r)
                merged += 1
                continue
        keep.append(r)
    log(f"Склейка «то же название в тот же час, площадка записана иначе»: {merged}")
    return keep, merged


def _kassir_page_title(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=40) as r:
            page = r.read().decode("utf-8", errors="ignore")
    except (OSError, http.client.HTTPException) as e:
        log(f"✖ {url[:110]} — {e}")
        return None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    title = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else ""
    if len(title) > 2 and title[0] + title[-1] in ('""', "«»"):  # «"Чудо в большом городе"» — кавычки вокруг всего названия
        title = title[1:-1].strip()
    return title or None


def resolve_kassir_titles(rows: list[dict], conflicts: list[tuple[dict, dict]], today: str) -> list[dict]:
    """
    Спорные склейки: Кассир и Яндекс в один час на одной площадке под совсем разными названиями. Кассир бывает
    отдаёт в поиске старое название карточки, а на странице — новое («Чудо в большом городе» →
    «Жениться нельзя расстаться»). Сверяем заголовок страницы: совпал с Яндексом — одно мероприятие; иначе
    оставляем две строки, но у Кассира — название со страницы.
    """
    if not conflicts:
        return rows
    cache = load_json(KASSIR_TITLES_FILE, {})
    fresh_from = (datetime.fromisoformat(today) - timedelta(days=3)).date().isoformat()
    drop, merged, renamed = set(), 0, 0
    for r, y in conflicts:
        url = r.get("url_k")
        if not url:
            continue
        got = cache.get(url)
        if not got or got[1] < fresh_from:
            title = _kassir_page_title(url)
            time.sleep(KASSIR_PAUSE)
            if title is None:
                continue
            got = cache[url] = [title, today]
        title = got[0]
        if similar_title(title, y["title"]) and y["src"] == "y":
            _merge(y, r)
            drop.add(id(r))
            merged += 1
        elif title and tour_key(title) != tour_key(r["title"]):
            r["title_api"], r["title"] = r["title"], title
            renamed += 1
    cache = {u: v for u, v in cache.items() if v[1] >= fresh_from}
    _save_lines(KASSIR_TITLES_FILE, cache)
    log(f"Страницы Кассира для спорных склеек: проверено {len(conflicts)}, склеено {merged}, название исправлено {renamed}")
    return [r for r in rows if id(r) not in drop]


# ---------------------------------------------------------------- организатор (Кассир)

def _org_from_page(page: str) -> str:
    """Строка после «Организатор мероприятия:» — без ИНН, ОГРН и адреса. На части страниц она только во всплывающей
    подсказке «Организатор: … ИНН/ ОГРН: …/ …» (у рекламных блоков внизу вместо второго номера «Токен» — их не берём)."""
    text = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", page)))
    m = (re.search(r"Организатор мероприятия:\s*(.+?)\s*ИНН", text)
         or re.search(r"Организатор:\s*(.+?)\s*ИНН/\s*ОГРН:\s*[\d-]+\s*/", text))
    return m.group(1).strip()[:200] if m else ""


def fetch_organizers(rows: list[dict], today: str) -> None:
    """Организатор карточек Кассира: страница открывается один раз и перепроверяется раз в месяц; за сбор — не
    дольше ORG_BUDGET_MIN минут, остальное — в следующие вечера. Сначала новые карточки и ближайшие даты."""
    cache = load_json(ORGANIZERS_FILE, {})
    stale = (datetime.fromisoformat(today) - timedelta(days=ORG_RECHECK_DAYS)).date().isoformat()
    need: dict[str, str] = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        acts = [k for k in r["keys"] if k.startswith("k:activity:")]
        if len(acts) == 1 and r.get("url_k") and (acts[0] not in cache or cache[acts[0]][1] < stale):
            need.setdefault(acts[0], r["url_k"])
    order = sorted(need, key=lambda k: k in cache)  # ещё не проверенные — первыми
    by_host = defaultdict(list)
    for k in order:
        by_host[need[k].split("/")[2]].append(k)
    queues = [[k for host in sorted(by_host)[n::ORG_THREADS] for k in by_host[host]] for n in range(ORG_THREADS)]
    deadline = time.time() + ORG_BUDGET_MIN * 60
    done = Counter()

    def work(keys: list[str]) -> None:
        for k in keys:
            if time.time() > deadline:
                return
            try:
                req = urllib.request.Request(need[k], headers={"User-Agent": UA, "Accept": "text/html", "Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=40) as resp:  # сжатая страница — ~120 КБ вместо ~500
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    page = body.decode("utf-8", errors="ignore")
            except (OSError, http.client.HTTPException):
                done["error"] += 1
                time.sleep(KASSIR_PAUSE)
                continue
            org = _org_from_page(page)
            cache[k] = [org, today]
            done["found" if org else "empty"] += 1
            time.sleep(KASSIR_PAUSE)

    with ThreadPoolExecutor(max_workers=ORG_THREADS) as pool:
        list(pool.map(work, queues))
    _save_lines(ORGANIZERS_FILE, cache)
    left = len(need) - sum(done.values())
    log(f"Организаторы Кассира: страниц {sum(done.values())} — найдено {done['found']}, без организатора {done['empty']}, "
        f"ошибок {done['error']}; осталось {max(0, left)} на следующие сборы, всего известно {sum(1 for v in cache.values() if v[0])}")


def apply_organizers(rows: list[dict]) -> None:
    cache = load_json(ORGANIZERS_FILE, {})
    for r in rows:
        if not r.get("org"):
            r["org"] = next((cache[k][0] for k in r["keys"] if k in cache and cache[k][0]), "")


def _clean_venue(v: str, city: str) -> str:
    return re.sub(r"\s*\((%s)\)\s*$" % re.escape(city), "", v or "").strip() or "—"


def parse(kassir: list[dict], yandex: list[dict], cities: list[str], today: str, overrides: dict,
          aliases: Aliases | None = None) -> tuple[list[dict], Counter, list]:
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
                         # У сеанса организатор есть прямо в поиске; у карточки — только на странице (fetch_organizers)
                         "org": ((o.get("eventPlanners") or [{}])[0] or {}).get("title", "").strip() if it["type"] == "event" else "",
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
            ytour = any(t.get("code") == "artist-tour" for t in ev.get("tags") or [])
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
                    "url_y": "https://afisha.yandex.ru" + ev["url"], "more": 0, "until": "", "ytour": ytour, "org": ""}
            # Номер строки — с городом: у Яндекса тур бывает одним событием сразу на несколько городов
            if len(dates) > LONG_RUN_DAYS:
                rows.append({**base, "keys": [f"y:{ev['id']}@{city}"], "date": dates[0], "time": "",
                             "more": len(dates) - 1, "until": dates[-1]})
            else:
                for x in dates:
                    rows.append({**base, "keys": [f"y:{ev['id']}:{x}@{city}"], "date": x, "time": one[11:16] if one[:10] == x else ""})

    # --- Склейка: сначала дубли внутри сайта, потом одно мероприятие на обоих сайтах — город, дата и похожее название
    rows = dedupe_source(rows, aliases)
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
            if aliases is not None and r["time"] and r["time"] == hit["time"]:
                aliases.learn(r["city"], r["venue"], hit["venue"])  # то же название в тот же час — площадки одни и те же
            _merge(hit, r)
        else:
            out.append(r)
    out += [r for r in rows if r["src"] != "k"]
    out, conflicts = merge_by_slot(out, aliases)
    out, strict_merged = merge_unique_strict(out, aliases)
    if strict_merged:  # выученные пары площадок склеивают и остальные мероприятия на них
        out, conflicts = merge_by_slot(out, aliases)
    out.sort(key=lambda r: (r["date"], r["time"] or "99", r["city"], r["title"]))
    return out, dropped, conflicts


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

        aliases = Aliases(load_json(VENUE_ALIASES_FILE, {}))
        rows, dropped, conflicts = parse(kassir, yandex, cities, today, load_json(OVERRIDES_FILE, {}), aliases)
        rows = resolve_kassir_titles(rows, conflicts, today)
        try:
            fetch_organizers(rows, today)
        except Exception as e:  # организатор — дополнение: сбор афиши из-за него не прерываем
            log(f"✖ Организаторы Кассира: {e}")
        apply_organizers(rows)
        previous = load_json(EVENTS_FILE, [])
        by_src_now = Counter(s for r in rows for s in r["src"])
        by_src_before = Counter(s for r in previous for s in r["src"])
        broken = [n for s, n in (("k", "Кассир"), ("y", "Яндекс Афиша"))
                  if by_src_before[s] and by_src_now[s] < by_src_before[s] * MIN_SHARE_OF_PREVIOUS]
        if broken:  # иначе всё его мероприятия попали бы в «исчезли», а завтра — обратно
            raise RuntimeError(f"меньше половины прошлого сбора вернули: {', '.join(broken)} — афиша не обновлена")

        asked = classify_missing(rows, _ai_settings())
        cur = curation.load()
        curation.apply_edits(rows, cur)   # ручные правки мероприятий
        curation.classify(rows, cur)      # гастроль или местное: пометки проекта и площадки, потом автоматические признаки

        # «Новое» — ни один номер строки (у Яндекса — событие и дата, у Кассира — событие) раньше не встречался
        seen = load_json(SEEN_FILE, {})
        first_run = status.get("first_run") or today
        new_rows = []
        legacy = lambda k: k.split("@")[0]  # до 30.09 номера Яндекса были без города
        for r in rows:
            known = [seen[k] for k in r["keys"] if k in seen] or [seen[legacy(k)] for k in r["keys"] if legacy(k) in seen]
            r["first_seen"] = min(known) if known else today
            if not known and first_run != today:
                new_rows.append(r)
            for k in r["keys"]:
                seen.setdefault(k, today)

        now_keys = {k for r in rows for k in r["keys"]}
        now_legacy = {legacy(k) for k in now_keys}
        gone = [p for p in previous if p["date"] >= today
                and not any(k in now_keys or ("@" not in k and k in now_legacy) for k in p["keys"])]

        _save_lines(EVENTS_FILE, rows)
        _save_lines(SEEN_FILE, seen)
        save_json(VENUE_ALIASES_FILE, aliases.dump())
        archived = update_archive(rows, cur, today)
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
        tours = sum(r["tour"] == "tour" for r in rows)
        summary = (f"мероприятий {len(rows)} в {len(cities) - len(no_data)} городах (гастрольных {tours}), новых {len(new_rows)}, "
                   f"исчезло {len(gone)}, в архиве гастролей {archived}, нейросеть {asked}, за {took / 60:.0f} мин")
        status.update(first_run=first_run, last_run_at=now_iso, last_ok=True, last_error=None, summary=summary,
                      rows=len(rows), tours=tours, new=len(new_rows), gone=len(gone), by_src=dict(Counter(r["src"] for r in rows)),
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


def _next_day(iso: str) -> str:
    return (datetime.fromisoformat(iso[:10]) + timedelta(days=1)).date().isoformat()


def update_archive(rows: list[dict], cur: dict, today: str) -> int:
    """Архив гастролей: каждое гастрольное выступление остаётся навсегда — с последними ценами и тем,
    чем закончилось: «прошло» (дата наступила) или «снято» (пропало из продажи до даты: распродано или отменено)."""
    arch = load_json(ARCHIVE_FILE, {})
    now = set()
    for r in rows:
        if r.get("tour") != "tour":
            continue
        k = r["keys"][0]
        now.add(k)
        e = arch.get(k) or {"first_seen": r.get("first_seen") or today}
        e.update({f: r.get(f) for f in ("pk", "title", "city", "venue", "date", "time", "format", "sphere", "genre",
                                         "pmin", "pmax", "url_k", "url_y", "tour_why")})
        e["last_seen"], e["status"] = today, "on_sale"
        arch[k] = e
    local = {k for k, m in cur["projects"].items() if m["type"] == "local"}
    on_sale = {k for r in rows for k in r["keys"]}  # в афише, но уже не отдельная гастроль: склеилась с другой строкой
    for k in list(arch):                             # или признак сменился на «местное» — это не «снято»
        e = arch[k]
        if e.get("pk") in local or (k in on_sale and k not in now):  # отмечен местным, склеен или больше не гастроль
            del arch[k]
        elif k not in now and e["status"] == "on_sale":
            # Сбор в 21:00: дневные и вечерние события этого дня уже сняты с продажи — это «прошло», не «снято»
            e["status"] = "past" if e["date"] <= today else "gone"
        elif e["status"] == "gone" and e["date"] <= _next_day(e.get("last_seen") or e["date"]):
            e["status"] = "past"  # записанные до 02.10 по старому правилу: пропали в день даты
    _save_lines(ARCHIVE_FILE, arch)
    return len(arch)


# ---------------------------------------------------------------- снимок для прототипа

def _row_key(r: dict) -> str:
    k = r["keys"][0]  # данные до 30.09: номер Яндекса без города — добавляем, как в новых сборах
    return f"{k}@{r['city']}" if k.startswith("y:") and "@" not in k else k


def _arch_now(e: dict) -> dict:
    """Статус для прототипа: дата прошла, а сбор рынка (21:00) ещё не отметил — уже «прошло»."""
    if e.get("status") == "on_sale" and e["date"] < datetime.now().date().isoformat():
        return {**e, "status": "past"}
    if e.get("status") == "gone" and e["date"] <= _next_day(e.get("last_seen") or e["date"]):
        return {**e, "status": "past"}  # до исправления 02.10: пропали в день даты
    return e


def export_js() -> str:
    """Снимок для прототипа (market-data.js): афиша, архив гастролей. Правки и разметку прототип
    накладывает сам из config/market_curation.json — поэтому здесь данные парсера (до правок)."""
    rows, status = load_json(EVENTS_FILE, []), load_json(STATUS_FILE, {})
    if not rows:
        raise RuntimeError("Нет данных рынка — сначала ./pull_data.sh или сбор")
    cfg = load_json(CITIES_FILE, {})
    all_cities, fo = cfg.get("cities", []), cfg.get("fo", {})
    lists = {"venues": [], "spheres": [], "formats": [], "genres": []}
    cities = list(all_cities)

    def idx(lst, v):
        if v not in lst:
            lst.append(v)
        return lst.index(v)
    # Продажи гастролей (сводка с сервера) и связка с площадками прямого сбора — одна строка «Мероприятий» на сеанс
    from competitors import collector, direct_match  # здесь, а не наверху: protodata → collector
    snap = {}
    if SALES_SNAPSHOT.exists():
        try:
            snap = json.loads(gzip.decompress(SALES_SNAPSHOT.read_bytes()))
        except (OSError, ValueError):
            snap = {}
    sales_rows = snap.get("rows", {})
    events = collector.load_events()
    direct = direct_match.match(rows, events, Aliases(load_json(MARKET_DIR / "venue_aliases.json", {})))
    today = datetime.now().date().isoformat()
    direct_only = sorted(uid for uid, e in events.items() if uid not in set(direct.values()) and (e.get("date") or "") >= today)

    def best_sales(keys):
        """Из касс сеанса — самая полная: Кассир со схемой (известно «выставлено») → Яндекс со схемой → любая с остатком."""
        c = [sales_rows[k] for k in keys if k in sales_rows]
        return next((x for x in c if x.get("exp")), None) or next((x for x in c if x.get("op") == "y" and "free" in x), None) \
            or next((x for x in c if "free" in x), None) or next((x for x in c if x.get("nt")), None)
    packed = []
    for i, r in enumerate(rows):
        r = {**r, **(r.get("orig") or {})}
        packed.append([idx(cities, r["city"]), idx(lists["venues"], r["venue"]), r["title"], r["date"], r["time"] or "",
                       idx(lists["spheres"], r["sphere"] or ""), idx(lists["formats"], r["format"]), idx(lists["genres"], r["genre"] or ""),
                       r["pmin"] or 0, r["pmax"] or 0, 1 if r["pushkin"] else 0, r["src"], r["url_k"] or "", r["url_y"] or "",
                       r["more"] or 0, r["until"] or "", r["first_seen"], r["age"] or "", 1 if r.get("ytour") else 0, _row_key(r),
                       r.get("org") or "", best_sales(r["keys"]) or 0, direct.get(i, "")])
    arch = [[e["city"], e["venue"], e["title"], e["date"], e.get("format") or "", e.get("genre") or "", e.get("pmin") or 0,
             e.get("pmax") or 0, e["status"], e.get("first_seen") or "", e.get("last_seen") or "", e.get("url_y") or e.get("url_k") or ""]
            for e in (_arch_now(x) for x in load_json(ARCHIVE_FILE, {}).values()) if e["status"] != "on_sale"]
    at = datetime.fromisoformat(status["last_run_at"])
    months = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."]
    label = f"{at.day} {months[at.month - 1]}, {at:%H:%M}"
    data = {"at": label, "first": status.get("first_run"), "cities": cities, "fo": fo, **lists, "rows": packed, "arch": arch,
            "salesAt": snap.get("at"), "directOnly": direct_only,
            "stats": {"merged": Counter(r["src"] for r in rows)["ky"], "dropped": status.get("dropped", {}), "bySrc": status.get("by_src", {})}}
    return (f"// Снимок «Афиши рынка»: Кассир + Яндекс Афиша по {len(all_cities)} городам, сбор {label}.\n"
            "// Пересобрать: ./pull_data.sh && python3 -m competitors.market export (через app.py — собирается сам)\n"
            "// Строка: [город, площадка, название, дата, время, сфера, формат, жанр, цена от, цена до, Пушкинская,\n"
            "//  источник k/y/ky, ссылка Кассир, ссылка Яндекс, ещё дат, до, впервые замечено, возраст, «Тур артиста», номер, организатор,\n"
            "//  продажи (сводка с сервера, sales/export.py) или 0, uid мероприятия площадки прямого сбора (тот же сеанс) или \"\"]\n"
            "// directOnly — мероприятия площадок прямого сбора, которых нет в афише рынка (строки — из competitors-data.js)\n"
            "// Архив (arch): [город, площадка, название, дата, формат, жанр, цена от, цена до, итог past|gone, впервые, в последний раз, ссылка]\n"
            "var MK = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")


def export_prototype() -> None:
    try:
        js = export_js()
    except RuntimeError as e:
        sys.exit(str(e))
    PROTOTYPE_DATA.write_text(js, encoding="utf-8")
    print(f"{PROTOTYPE_DATA.relative_to(BASE_DIR)}: {js.count('],[') + 1} строк")


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        export_prototype()
    else:
        sys.exit(0 if run() else 1)
