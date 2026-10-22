"""
Официальные сайты проектов — даты с афиши сайта (раздел «Аналитика → Официальный сайт», решения пользователя 12.10.2026).

    python3 -m competitors.officialsite            проверить сайты, у которых подошёл срок (раз в сутки; tm-sync зовёт каждый час)
    python3 -m competitors.officialsite --all      проверить все сайты сейчас
    python3 -m competitors.officialsite <ключ>     один проект (ключ проекта — как в прототипе: слова названия по алфавиту)

Зачем: на сайте артиста — вся его афиша, а кассы, которые мы собираем, видят не все даты (Intickets, Kassy.ru, сайты
филармоний, свои страницы продажи). Пример — группа «Рондо», rondotour.ru: 24 даты, из них 5 нет ни в одной нашей кассе.

Откуда ссылка — config/my_projects.json → projects[*].site (вставляет пользователь в «Аналитике» проекта; myprojects.py):
    {"key": ключ проекта, "url", "title", "confirmed": первый разбор подтверждён, "at": когда,
     "choices": {дата: "site" | "kassa"} — выбор при расхождении (тот же день, у касс другой город)}
Что получается — data/competitors/official_sites.json:
    {ключ: {"url", "title", "checked": последняя попытка, "ok_at": последний удачный разбор, "error": текст или "",
            "hash": отпечаток текста страницы, "via": "http" | "browser", "model",
            "rows": [{"date", "city", "venue", "pmin", "buy", "first_seen", "last_seen"}],   ← будущие даты на сайте
            "gone": [{…, "gone": дата}],    ← были на сайте и исчезли до своей даты («снята с сайта»)
            "past": [{…}]}}                 ← прошли, пока были на сайте (архив проекта)

Как:
1. Одна страница, как браузер покупателя (пауза, канал блокировок site/<сайт>: 403 / капча — не опрашиваем до срока).
   На странице есть скрипты — та же страница в браузере (Playwright), один раз; дат там больше — разбираем её.
   Не только когда текста нет: у leonidkulakov.ru (Tilda) осенний тур — в HTML, весенний дорисовывает скрипт.
2. Текст страницы с адресами ссылок → GigaChat: строки «ДД.ММ.ГГГГ | город | площадка | цена | ссылка».
   Текст не изменился с прошлого удачного разбора — GigaChat не спрашиваем.
3. Проверка ответа (модель не должна ничего выдумать): дата — в будущем и есть в тексте (день + месяц словом или
   числом); город — есть в тексте и известен (список рынка, карта прототипа, иначе OpenStreetMap — кэш
   site_geo.json); ссылка — только с этой страницы. Не прошло — строка отбрасывается.
4. История: исчезла до даты — «снята с сайта»; прошла — в архив. Дат вдвое меньше прошлого разбора — подозрительно
   (сайт переделали, страница не догрузилась): прошлые даты не снимаем, пишем ошибку, проверим завтра.

Сверка с кассами — compare(): совпало (тот же день, тот же город или до 50 км), нет у нас, расхождение (в этот день
у касс другой город). То же правило в прототипе (siteCompare в Design/prototype/index.html) — менять вместе.
В базу (db/sync.py) даты сайта идут карточками оператора «site»: совпавшие — к сеансу кассы, остальные — своими сеансами.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from competitors import blocks, collector, curation, myprojects
from competitors.fetch import USER_AGENT
from competitors.storage import BASE_DIR, CONFIG_DIR, DATA_DIR, load_json, save_json

FILE = DATA_DIR / "official_sites.json"
GEO_FILE = DATA_DIR / "site_geo.json"           # города с сайтов, которых нет на карте прототипа: {город: [широта, долгота] | null}
LOCK_FILE = DATA_DIR / ".official_sites.lock"
MARKET_GEO = BASE_DIR / "Design" / "prototype" / "market-geo.js"
CITIES_FILE = CONFIG_DIR / "market.json"

DUE = timedelta(hours=20)       # раз в сутки (tm-sync зовёт каждый час — сайт проверяется, когда срок подошёл)
RETRY = timedelta(hours=3)      # после ошибки — не раньше чем через 3 ч
NEAR_KM = 50                    # «тот же город»: Ессентуки ↔ Пятигорск у Яндекса (как SITE_NEAR_KM в прототипе)
FRESH = timedelta(hours=30)     # для базы: разбор свежее этого — исчезнувшая дата значит «снята с сайта»
TEXT_MAX = 14000                # знаков текста в одном запросе к GigaChat; длиннее — частями
TIMEOUT = 30
PARSER = 3                      # версия разбора: поменялись подсказка GigaChat или проверка — страница разбирается заново

# начала названий месяцев: и «марта», и «мар» (афиши-виджеты пишут «10 / мар / ср»)
MONTHS = ["янв", "фев", "мар", "апр", "ма[йя]", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_DATE_IN_TEXT = re.compile(r"(?<!\d)([0-3]?\d)\s*(?:(" + "|".join(MONTHS) + r")|[./]\s*([01]?\d)(?!\d))", re.I)
_LINE = re.compile(r"^\W*([0-3]?\d)[./]([01]?\d)[./](\d{4})\s*\|(.*)$")

def _log(msg: str) -> None:
    print(msg, flush=True)


def _today() -> date:
    return date.today()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def host(url: str) -> str:
    return re.sub(r"^www\.", "", urllib.parse.urlsplit(url or "").netloc.lower())


def project_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def ext_key(key: str, row: dict) -> str:
    """Номер карточки даты сайта в базе (оператор «site»): s:<проект>:<дата>:<город>."""
    return f"s:{project_hash(key)}:{row['date']}:{row['city']}"


@contextmanager
def _locked():
    """Один разбор за раз: кнопка «Проверить» на сайте и сбор по расписанию пишут один файл."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------- настройки проектов (config/my_projects.json)

def configs() -> dict[str, dict]:
    """Проекты со ссылкой на сайт: {ключ: site}."""
    out = {}
    for p in myprojects.load()["projects"].values():
        s = p.get("site") or {}
        if s.get("url") and s.get("key"):
            out[s["key"]] = {**s, "keys": p.get("keys") or [s["key"]], "title": s.get("title") or p.get("title") or s["key"]}
    return out


# ---------------------------------------------------------------- города: список рынка, карта прототипа, OpenStreetMap

def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"^(г\.|город)\s*", "", s.strip())
    return re.sub(r"[\s\-]+", " ", s).strip()


_GEO: dict | None = None


def geo() -> dict[str, tuple[float, float]]:
    """Координаты известных городов: карта прототипа (344 города рынка) + города с сайтов (кэш OpenStreetMap)."""
    global _GEO
    if _GEO is None:
        _GEO = {}
        try:
            txt = MARKET_GEO.read_text(encoding="utf-8")
            data = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
            _GEO = {c: (v[2], v[3]) for c, v in data["cities"].items()}
        except (OSError, ValueError, KeyError):
            pass
        for c, v in load_json(GEO_FILE, {}).items():
            if v:
                _GEO.setdefault(c, (v[0], v[1]))
    return _GEO


def km(a: str, b: str) -> int | None:
    if not a or not b:
        return None
    if _norm(a) == _norm(b):
        return 0
    g = geo()
    p, q = g.get(a), g.get(b)
    if not p or not q:
        return None
    r = math.pi / 180
    x = (q[1] - p[1]) * r * math.cos((p[0] + q[0]) / 2 * r)
    y = (q[0] - p[0]) * r
    return round(math.hypot(x, y) * 6371)


def _cap(s: str) -> str:
    """«нижневартовск» → «Нижневартовск», «ростов-на-дону» → «Ростов-на-Дону»."""
    out = re.sub(r"(^|[\s-])(\w)", lambda m: m.group(1) + m.group(2).upper(), s.strip().lower())
    return re.sub(r"-(На|Над|Под|У)-", lambda m: "-" + m.group(1).lower() + "-", out)


def _geocode(name: str) -> tuple[float, float] | None:
    """OpenStreetMap Nominatim: один запрос, правила сервиса — 1 в секунду, свой User-Agent. Ответ кэшируется (и «нет»)."""
    q = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1, "accept-language": "ru", "featuretype": "city"})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q,
                                 headers={"User-Agent": "ticket-monitor/1.0 (official sites; github.com/dddmmmvvv73-stack)"})
    time.sleep(1.1)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if not data:
        return None
    kind = data[0].get("addresstype") or data[0].get("type")
    # Москва, Петербург, Севастополь — города федерального значения: у OpenStreetMap это «регион» с тем же названием
    if kind not in ("city", "town", "village", "municipality", "hamlet", "suburb") and not (kind == "state" and _norm(data[0].get("name", "")) == _norm(name)):
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def resolve_city(raw: str, log=_log) -> str | None:
    """Название города как в нашей системе; неизвестный — ищем в OpenStreetMap (кэш). None — не город."""
    n = _norm(raw)
    if not n or len(n) < 2:
        return None
    market = load_json(CITIES_FILE, {}).get("cities", [])
    for c in list(market) + list(geo()):
        if _norm(c) == n:
            return c
    name = _cap(n)
    cache = load_json(GEO_FILE, {})
    if name not in cache:
        cache[name] = list(_geocode(name) or []) or None
        save_json(GEO_FILE, cache)
        global _GEO
        _GEO = None
        log(f"  город «{name}» — {'найден в OpenStreetMap' if cache[name] else 'не найден в OpenStreetMap: строка отброшена'}")
    return name if cache.get(name) else None


# ---------------------------------------------------------------- страница → текст с адресами ссылок

class SiteDenied(RuntimeError):
    pass


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9",
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw, final = r.read(), r.geturl()
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        if blocks.is_denied(e.code, e.geturl() or url, body) or e.code == 429:
            raise SiteDenied(f"сайт отказал: HTTP {e.code}")
        raise RuntimeError(f"сайт ответил HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise RuntimeError(f"сайт не открылся: {getattr(e, 'reason', e)}")
    if blocks.is_denied(200, final, raw):
        raise SiteDenied("сайт показал капчу")
    return raw.decode(charset, errors="replace")


def render(url: str) -> str:
    """Та же страница в браузере (страница рисует афишу скриптами). Без Playwright — исключение."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            page = b.new_page(user_agent=USER_AGENT, locale="ru-RU")
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(1500)
            return page.content()
        finally:
            b.close()


_BLOCK = re.compile(r"</?(p|div|li|ul|ol|tr|td|th|table|section|article|header|footer|h[1-6]|br|time|span)\b[^>]*>", re.I)


def page_text(src: str, base: str) -> tuple[str, set[str]]:
    """Видимый текст страницы; у ссылок — адрес в ⟦…⟧ (так GigaChat видит, какая кнопка «купить билет» у какой даты)."""
    s = re.sub(r"<(script|style|noscript|svg|template|head)\b.*?</\1>", " ", src, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    links: set[str] = set()

    def link(m):
        href = html.unescape(m.group(1) or m.group(2) or "").strip()
        inner = m.group(3)
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return inner
        u = urllib.parse.urljoin(base, href)
        if not u.startswith(("http://", "https://")):
            return inner
        links.add(u)
        return f"{inner} ⟦{html.escape(u, quote=False)}⟧"   # текст ниже раскодируется ещё раз: «&regionId» не должен стать «®ionId»
    s = re.sub(r"<a\b[^>]*?href\s*=\s*(?:\"([^\"]*)\"|'([^']*)')[^>]*>(.*?)</a>", link, s, flags=re.S | re.I)
    s = _BLOCK.sub("\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines, prev = [], None
    for line in s.split("\n"):
        line = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if line and line != prev:
            lines.append(line)
        prev = line or prev
    return "\n".join(lines), links


def dates_in_text(text: str) -> int:
    return sum(1 for m in _DATE_IN_TEXT.finditer(text) if not m.group(3) or 1 <= int(m.group(3)) <= 12)


# ---------------------------------------------------------------- GigaChat

SYSTEM = ("Ты помощник аналитика концертного рынка. Ты выписываешь из текста страницы официального сайта артиста "
          "или коллектива его афишу — даты выступлений. Ничего не придумываешь: только то, что есть в тексте.")
INSTR = """Ниже — текст страницы официального сайта проекта «{title}» ({url}). Адреса ссылок даны в скобках ⟦…⟧.
Выпиши все будущие выступления этого проекта, перечисленные на странице. Ответ — только строки вида:
ДД.ММ.ГГГГ | город | площадка | цена | ссылка
по одной строке на дату, без пояснений и без заголовка.
- Год: если у даты его нет — ближайший, при котором дата не раньше {today}.
- Город — как на странице, без «г.»; если город не указан, но понятен по площадке — назови его.
- Площадка — как на странице; «-», если её нет.
- Цена — наименьшая цена билета числом в рублях, без пробелов; «-», если цены нет.
- Ссылка — адрес из ⟦…⟧ у кнопки билетов этой даты («купить билет», «билеты» и т. п.); «-», если её нет.
- Не выписывай прошедшие даты, новости, видео, туры других артистов.
Если на странице нет ни одной даты выступления — ответь строкой: НЕТ ДАТ

Текст страницы:
{text}"""


def _unquote(s: str) -> str:
    """Кавычки вокруг поля ответа — долой, свои кавычки названия — на месте: «Кинотеатр «Заря»», а не «Кинотеатр «Заря»."""
    s = s.strip().strip("«»\"'").strip()
    if s.count("«") > s.count("»"):
        s += "»"
    if s.count('"') % 2:
        s += '"'
    return s


def ask_gigachat(text: str, title: str, url: str, log=_log) -> tuple[list[dict], str]:
    """Строки ответа как есть (проверка — validate). Длинная страница — частями по TEXT_MAX знаков."""
    from competitors import gigachat_ai
    from gigachat.exceptions import AuthenticationError, RateLimitError, ResponseError
    from gigachat.models import Chat, Messages, MessagesRole

    st = collector.load_settings()
    if st.get("ai_provider") == "off" or not st.get("gigachat_auth_key"):
        raise RuntimeError("GigaChat не настроен — ключ вставляется в «Настройках»")
    model = st.get("gigachat_model") or gigachat_ai.DEFAULT_MODEL
    parts, cur = [], []
    for line in text.split("\n"):
        if cur and sum(len(x) + 1 for x in cur) + len(line) > TEXT_MAX:
            parts.append("\n".join(cur))
            cur = cur[-3:]   # немного нахлёста: дата и город не разорвутся между частями
        cur.append(line)
    if cur:
        parts.append("\n".join(cur))
    out: list[dict] = []
    with gigachat_ai._client(st["gigachat_auth_key"], st.get("gigachat_scope"), model, log) as giga:
        for part in parts:
            prompt = INSTR.format(title=title, url=url, today=_today().strftime("%d.%m.%Y"), text=part)
            for _ in range(2):
                try:
                    r = giga.chat(Chat(model=model, temperature=0.05, max_tokens=4000,
                                       messages=[Messages(role=MessagesRole.SYSTEM, content=SYSTEM), Messages(role=MessagesRole.USER, content=prompt)]))
                    break
                except AuthenticationError:
                    raise RuntimeError("GigaChat не принял ключ — проверьте ключ в «Настройках»")
                except RateLimitError:
                    raise RuntimeError("GigaChat: слишком много запросов — попробую позже")
                except ResponseError as e:
                    if e.status_code == 402 and model != gigachat_ai.FALLBACK_MODEL:
                        log(f"GigaChat: закончился лимит {model} — переключаюсь на {gigachat_ai.FALLBACK_MODEL}")
                        model = gigachat_ai.FALLBACK_MODEL
                        continue
                    raise RuntimeError(f"GigaChat ответил ошибкой {e.status_code}")
            else:
                raise RuntimeError("GigaChat: лимит токенов исчерпан")
            for line in r.choices[0].message.content.splitlines():
                m = _LINE.match(line.strip())
                if not m:
                    continue
                f = [_unquote(x) for x in m.group(4).split("|")]
                f += ["-"] * (4 - len(f))
                out.append({"d": int(m.group(1)), "m": int(m.group(2)), "y": int(m.group(3)), "city": f[0], "venue": f[1], "price": f[2], "buy": f[3]})
    return out, model


# ---------------------------------------------------------------- проверка ответа

def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е"))


def _date_in(flat: str, d: int, m: int) -> bool:
    pat = rf"(?<!\d)0?{d}\s*(?:{MONTHS[m - 1]}|[./\-]\s*0?{m}(?!\d))"
    return re.search(pat, flat) is not None


def _city_in(flat: str, city: str) -> bool:
    n = _norm(city)
    stem = n[:max(4, len(n) - 2)] if len(n) > 5 else n   # «в Пензе», «Ростове-на-Дону»
    return stem.replace(" ", "") in flat.replace(" ", "").replace("-", "")


def validate(raw: list[dict], text: str, links: set[str], log=_log) -> list[dict]:
    flat, today, rows, seen = _flat(text), _today(), [], set()
    lk = lambda u: re.sub(r"^https?://(www\.)?", "", (u or "").strip().strip("⟦⟧[]()<>«»\"' ").lower()).rstrip("/")
    norm_links = {lk(u): u for u in links}   # ссылка ответа — только одна из ссылок страницы (скобки ⟦…⟧ модель иногда оставляет)
    for r in raw:
        try:
            d = date(r["y"], r["m"], r["d"])
        except ValueError:
            continue
        why = None
        if d < today or d > today + timedelta(days=800):
            why = "дата не впереди"
        elif not _date_in(flat, r["d"], r["m"]):
            why = "даты нет в тексте"
        elif not r["city"] or r["city"] == "-" or not _city_in(flat, r["city"]):
            why = "города нет в тексте"
        city = None if why else resolve_city(r["city"], log)
        if not why and not city:
            why = "неизвестный город"
        if why:
            log(f"  отброшено: {r['d']:02d}.{r['m']:02d}.{r['y']} {r['city']} — {why}")
            continue
        k = (d.isoformat(), city)
        if k in seen:
            continue
        seen.add(k)
        price = re.sub(r"\D", "", r["price"] or "")
        venue = "" if r["venue"] in ("-", "—") else r["venue"][:200]
        rows.append({"date": d.isoformat(), "city": city, "venue": venue[:1].upper() + venue[1:],
                     "pmin": int(price) if price and 0 < int(price) < 1_000_000 else None,
                     "buy": norm_links.get(lk(r["buy"])) if lk(r["buy"]) else None})
    return sorted(rows, key=lambda x: (x["date"], x["city"]))


# ---------------------------------------------------------------- один проект

def _row_id(r: dict) -> str:
    return r["date"] + "|" + r["city"]


def merge_history(prev: dict, rows: list[dict]) -> dict:
    """Новые даты — first_seen сегодня; исчезнувшие — «сняты с сайта» (до даты) или в архив (дата прошла)."""
    today = _today().isoformat()
    old = {_row_id(r): r for r in prev.get("rows", [])}
    gone = {_row_id(r): r for r in prev.get("gone", [])}
    past = {_row_id(r): r for r in prev.get("past", [])}
    out = []
    for r in rows:
        rid = _row_id(r)
        was = old.get(rid) or gone.pop(rid, None) or {}
        out.append({**r, "first_seen": was.get("first_seen") or today, "last_seen": today})
    now_ids = {_row_id(r) for r in out}
    for rid, r in old.items():
        if rid in now_ids:
            continue
        if r["date"] < today:
            past[rid] = r
        else:
            gone[rid] = {**r, "gone": today}
    return {"rows": out, "gone": sorted(gone.values(), key=lambda x: x["date"]), "past": sorted(past.values(), key=lambda x: x["date"])}


def _age_rows(entry: dict) -> None:
    """Даты, прошедшие с прошлого разбора, — в архив (без нового запроса к сайту)."""
    today = _today().isoformat()
    past = {_row_id(r): r for r in entry.get("past", [])}
    for r in entry.get("rows", []):
        if r["date"] < today:
            past.setdefault(_row_id(r), r)
    entry["rows"] = [r for r in entry.get("rows", []) if r["date"] >= today]
    entry["past"] = sorted(past.values(), key=lambda x: x["date"])


def check(key: str, cfg: dict, data: dict, log=_log) -> dict:
    """Разобрать сайт одного проекта; результат — в data[key]. Ошибка не стирает прошлые даты."""
    url = cfg["url"]
    prev = data.get(key) or {}
    if prev.get("url") and host(prev["url"]) != host(url):
        prev = {}   # другой сайт — история заново
    entry = {**prev, "url": url, "title": cfg.get("title") or key, "checked": _now()}
    channel = "site/" + (host(url) or "?")
    if blocks.state(channel) == "blocked":
        entry["error"] = f"сайт закрыл доступ — проверка после {(blocks.until(channel) or '')[:16].replace('T', ' ')}"
        data[key] = entry
        return entry
    try:
        try:
            src, via = fetch(url), "http"
        except SiteDenied as e:
            blocks.trip(channel, 403, str(e), {"project": key})
            raise RuntimeError(str(e) + " — не опрашиваем до срока")
        if blocks.state(channel) == "probe":
            blocks.clear(channel)
        text, links = page_text(src, url)
        if re.search(r"<script", src, re.I):
            try:   # часть афиши (или вся) может рисоваться скриптами — та же страница в браузере
                text2, links2 = page_text(render(url), url)
                if dates_in_text(text2) > dates_in_text(text):
                    text, links, via = text2, links2, "browser"
            except Exception as e:  # noqa: BLE001 — без браузера разбираем то, что есть
                log(f"  браузер не помог: {e}")
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        if h == prev.get("hash") and prev.get("parser") == PARSER and prev.get("ok_at") and not prev.get("error"):
            _age_rows(entry)   # текст тот же — даты те же; GigaChat не спрашиваем
            entry.update(error="", via=via)
            log(f"  {host(url)}: страница не изменилась — {len(entry.get('rows', []))} дат")
            data[key] = entry
            return entry
        raw, model = ask_gigachat(text, entry["title"], url, log)
        rows = validate(raw, text, links, log)
        before = len([r for r in prev.get("rows", []) if r["date"] >= _today().isoformat()])
        if before >= 4 and len(rows) < before / 2:
            raise RuntimeError(f"дат {len(rows)} вместо {before} в прошлый раз — прошлые не снимаю, проверю ещё раз")
        if not rows and not prev.get("rows"):
            entry.update(merge_history(prev, []), hash=h, parser=PARSER, via=via, model=model, ok_at=_now(), error="на странице не нашлось дат — проверьте ссылку (нужна страница с афишей)")
        else:
            entry.update(merge_history(prev, rows), hash=h, parser=PARSER, via=via, model=model, ok_at=_now(), error="")
        log(f"  {host(url)}: {len(rows)} дат (GigaChat — {len(raw)} строк, через {via})")
    except Exception as e:  # noqa: BLE001 — ошибка одного сайта не останавливает остальные
        _age_rows(entry)
        entry["error"] = str(e)[:300]
        log(f"  {host(url)}: ошибка — {entry['error']}")
    data[key] = entry
    return entry


def due(cfg: dict, entry: dict | None) -> bool:
    if not entry or host(entry.get("url", "")) != host(cfg["url"]) or entry.get("url") != cfg["url"]:
        return True
    last = entry.get("checked")
    if not last:
        return True
    age = datetime.now().astimezone() - datetime.fromisoformat(last)
    return age >= (RETRY if entry.get("error") else DUE)


def run(only: str | None = None, force: bool = False, log=_log) -> dict:
    """Проверить сайты (срок подошёл / все / один). Проекты без ссылки — убрать из файла."""
    with _locked():
        cfgs, data = configs(), load_json(FILE, {})
        for k in [k for k in data if k not in cfgs]:
            del data[k]   # ссылку убрали — даты сайта больше не учитываются
        todo = [k for k in cfgs if (only is None or k == only) and (force or only or due(cfgs[k], data.get(k)))]
        if todo:
            log(f"Официальные сайты: проверяю {len(todo)} из {len(cfgs)}")
        for k in todo:
            log(f"«{cfgs[k].get('title') or k}» — {cfgs[k]['url']}")
            check(k, cfgs[k], data, log)
            save_json(FILE, data)   # после каждого — чтобы сайт видел результат сразу
        for k in data:
            if k not in todo:
                _age_rows(data[k])
        save_json(FILE, data)
        return data


# ---------------------------------------------------------------- для прототипа и базы

def export(data: dict | None = None) -> dict:
    """Для прототипа: MSITE (как site-data.js) и координаты городов, которых нет на карте (x, y досчитывает прототип)."""
    data = load_json(FILE, {}) if data is None else data
    g = load_json(GEO_FILE, {})
    cities = {r["city"] for e in data.values() for part in ("rows", "gone", "past") for r in e.get(part, [])}
    mgeo = _mgeo_names()
    extra = {c: [None, None, g[c][0], g[c][1]] for c in cities if c not in mgeo and g.get(c)}
    msite = {k: {kk: e.get(kk) for kk in ("url", "title", "checked", "ok_at", "error", "via", "rows", "gone", "past")} for k, e in data.items()}
    for e in msite.values():
        e["rows"], e["gone"], e["past"] = e.get("rows") or [], e.get("gone") or [], e.get("past") or []
    return {"MSITE": msite, "MSITE_GEO": extra}


def _mgeo_names() -> set[str]:
    try:
        txt = MARKET_GEO.read_text(encoding="utf-8")
        return set(json.loads(txt[txt.index("{"):txt.rindex("}") + 1])["cities"])
    except (OSError, ValueError, KeyError):
        return set()


def export_js() -> str:
    x = export()
    return ("// Официальные сайты проектов — из data/competitors/official_sites.json (competitors/officialsite.py)\n"
            f"var MSITE = {json.dumps(x['MSITE'], ensure_ascii=False)};\nvar MSITE_GEO = {json.dumps(x['MSITE_GEO'], ensure_ascii=False)};\n")


def _like(pk: str, k: str) -> bool:
    """Строка кассы — того же проекта: тот же ключ или 2+ общих слова, не меньше 2/3 слов проекта (siteLike в прототипе)."""
    if not pk or not k:
        return False
    if pk == k:
        return True
    w, v = k.split(), set(pk.split())
    n = sum(1 for x in w if x in v)
    return n >= 2 and n * 3 >= len(w) * 2


def compare(key: str, cfg: dict, entry: dict, market_rows: list[dict], cur: dict) -> dict:
    """Сверка дат сайта с афишей рынка (строки events.json): как siteCompare в прототипе.
    Возвращает {"rows": [{"r", "st": match|new|conflict, "e": [строки рынка], "pick"}], "only": [строки рынка]}."""
    keys = cfg.get("keys") or [key]
    today = _today().isoformat()

    def pk(r):
        return curation.canonical(cur, curation.project_key((r.get("orig") or {}).get("title") or r["title"]))
    kassa = [r for r in market_rows if r.get("date", "") >= today and any(_like(pk(r), k) for k in keys)]
    used, out = set(), []
    choices = cfg.get("choices") or {}
    for r in entry.get("rows", []):
        same = [m for m in kassa if m["date"] == r["date"]]
        hit = [m for m in same if (lambda d: d is not None and d <= NEAR_KM)(km(r["city"], m["city"]))]
        if hit:
            o = {"r": r, "st": "match", "e": hit}
        elif same:
            o = {"r": r, "st": "conflict", "e": same, "pick": choices.get(r["date"], "")}
        else:
            o = {"r": r, "st": "new", "e": []}
        used.update(id(m) for m in o["e"])
        out.append(o)
    only = [m for m in kassa if id(m) not in used and pk(m) in keys]
    return {"rows": out, "only": only}


def db_rows(market_rows: list[dict], cur: dict) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Для db.sync: (строки-сеансы дат «только на сайте», привязки дат сайта к строкам касс, свежесть по проектам).
    Неподтверждённый первый разбор в базу не идёт."""
    data, cfgs = load_json(FILE, {}), configs()
    extra, attach, fresh = [], [], {}
    now = datetime.now().astimezone()
    for key, cfg in cfgs.items():
        e = data.get(key)
        if not e or not cfg.get("confirmed"):
            continue
        ok = e.get("ok_at")
        fresh[project_hash(key)] = bool(ok) and not e.get("error") and now - datetime.fromisoformat(ok) < FRESH
        c = compare(key, cfg, e, market_rows, cur)
        own = [m for m in market_rows if any(_like(curation.canonical(cur, curation.project_key((m.get("orig") or {}).get("title") or m["title"])), k) for k in cfg["keys"])]
        top = lambda f: max((m.get(f) for m in own if m.get(f)), key=lambda v: sum(1 for m in own if m.get(f) == v), default=None)
        title = top("title") or cfg.get("title") or key
        for o in c["rows"]:
            r, ek = o["r"], ext_key(key, o["r"])
            card = {"ext": ek, "url": r.get("buy") or cfg["url"], "title": title, "pmin": r.get("pmin"),
                    "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen")}
            if o["st"] == "match":
                attach.append({**card, "keys": [k for m in o["e"] for k in m["keys"]]})
            elif o["st"] == "new" or o.get("pick") == "site":
                extra.append({"city": r["city"], "venue": r.get("venue") or "—", "title": title, "date": r["date"], "time": "",
                              "keys": [ek], "url_s": card["url"], "pmin": r.get("pmin"), "pmax": r.get("pmin"),
                              "format": top("format"), "sphere": top("sphere"), "genre": top("genre"),
                              "first_seen": r.get("first_seen"), "last_seen": r.get("last_seen"), "site": True})
    return extra, attach, fresh


def main(argv: list[str]) -> None:
    if argv[:1] == ["--all"]:
        run(force=True)
    elif argv:
        run(only=" ".join(argv))
    else:
        run()


if __name__ == "__main__":
    main(sys.argv[1:])
