"""
Qtickets (qtickets.events) — третий сайт афиши рынка (TICKET_PLATFORMS.md, 9.3).

Только афиша: название, тип, дата и время, площадка, цена «от»; со страницы мероприятия — организатор и город по
адресу площадки. Схему мест не берём: окно покупки (/widget/seats) закрыто в robots.txt и требует «доказательства
работы» (ответ 428) — это защита (7.3), не обходим. Значит, у Qtickets нет продаж.

Город — поддомен (`penza.qtickets.events`); словарь «поддомен → город» — со ссылок главной, кэш в qtickets_cities.json.
Страница города — 9 карточек, дальше `/?page=N` до кнопки «Ещё мероприятия!».

Нагрузка: пауза MARKET_QTICKETS_PAUSE (2,5 с), за сбор — не больше MARKET_QTICKETS_BUDGET запросов (афиша первой,
остаток — на страницы мероприятий: сначала не проверенные и ближайшие, перепроверка раз в месяц). Отказ сайта (403,
428, капча) — канал qtickets/afisha закрывается (competitors/blocks.py), сбор сегодня не засчитывается: мероприятия
Qtickets переносятся из прошлого (competitors/market.py, carry_source).

Разбор карточек в строки афиши и склейка с Кассиром и Яндексом — в competitors/market.py (parse, merge_extra).
"""

from __future__ import annotations

import html as html_lib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Callable

from competitors import blocks
from competitors.storage import DATA_DIR, load_json, save_json

MARKET_DIR = DATA_DIR / "market"
CITIES_CACHE = MARKET_DIR / "qtickets_cities.json"   # поддомен → город, как на сайте
PAGES_FILE = MARKET_DIR / "qtickets_pages.json"      # номер мероприятия → [организатор, город по адресу площадки, дата проверки]
CHANNEL = "qtickets/afisha"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
PAUSE = float(os.environ.get("MARKET_QTICKETS_PAUSE", 2.5))
BUDGET = int(os.environ.get("MARKET_QTICKETS_BUDGET", 1500))   # запросов за сбор — афиша ~300–500, остальное — страницы
MAX_PAGES = 40           # страниц афиши на город — с запасом (Казань 09.10 — 10)
RECHECK_DAYS = 30        # организатор и адрес мероприятия перепроверяются раз в месяц
PAGES_MIN = 20           # страницы мероприятий — не дольше стольких минут за сбор (первый проход растянется на несколько вечеров)

Log = Callable[[str], None]


class Denied(Exception):
    """Сайт отказал (403, 428 — «докажи, что не робот», капча): дальше не спрашиваем."""


def norm(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е").replace("г.", "").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


class Client:
    """Запросы к Qtickets с паузой и счётчиком: бюджет сбора общий для афиши и страниц мероприятий."""

    def __init__(self, budget: int = BUDGET, pause: float = PAUSE):
        self.left, self.pause, self.used, self.errors = budget, pause, 0, 0

    def get(self, url: str) -> str | None:
        """Текст страницы; None — ошибка сети или 404 (пропускаем); Denied — отказ сайта."""
        if self.left <= 0:
            return None
        self.left -= 1
        self.used += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
                if blocks.is_denied(r.status, r.geturl(), body):
                    raise Denied(url)
                return body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 428, 429):
                raise Denied(url) from e
            self.errors += 1
            return None
        except (OSError, http.client.HTTPException):
            self.errors += 1
            return None
        finally:
            time.sleep(self.pause)


# ---------------------------------------------------------------- разбор страниц

def parse_cities(page: str) -> dict[str, str]:
    """Ссылки на города с любой страницы афиши: {поддомен: «Пенза»}."""
    out: dict[str, str] = {}
    for sub, name in re.findall(r'href="https://([a-z0-9-]+)\.qtickets\.events/?"[^>]*>\s*([^<]{2,40}?)\s*<', page):
        if name.strip():   # ссылка на текущий город бывает без подписи
            out.setdefault(sub, html_lib.unescape(name).strip())
    return out


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ")).strip()


def parse_cards(page: str) -> list[dict]:
    """Карточки страницы города: номер, адрес, название, тип, дата и время (местные), площадка, цена «от»."""
    out = []
    for it in page.split('<li class="item">')[1:]:
        a = re.search(r'href="(https://[a-z0-9-]+\.qtickets\.events/(\d+)[^"]*)"', it)
        dt = re.search(r'datetime="([^"]+)"', it)
        if not a or not dt:
            continue
        title = re.search(r"<h2>(.*?)</h2>", it, re.S)
        kind = re.search(r'<div class="type">(.*?)</div>', it, re.S)
        place = re.search(r'class="place-name">(.*?)</span>', it, re.S)
        price = re.search(r"от\s*([\d\s]+)\s*руб", it)
        out.append({"id": int(a.group(2)), "url": a.group(1), "title": _text(title.group(1)) if title else "",
                    "type": _text(kind.group(1)) if kind else "", "dt": dt.group(1),
                    "venue": _text(place.group(1)) if place else "",
                    "pmin": int(re.sub(r"\s", "", price.group(1))) if price else None})
    return out


def parse_event(page: str, city_names: set[str]) -> tuple[str, str]:
    """Со страницы мероприятия (разметка schema.org/Event): организатор и город из адреса площадки («…, Пенза, Россия»)."""
    org, city = "", ""
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for x in data if isinstance(data, list) else [data]:
            if not isinstance(x, dict) or x.get("@type") != "Event":
                continue
            org = ((x.get("organizer") or {}).get("name") or "").strip()[:200]
            addr = ((x.get("location") or {}).get("address") or "")
            addr = addr if isinstance(addr, str) else (addr.get("addressLocality") or "")
            parts = [p.strip() for p in addr.split(",")]
            city = next((p for p in reversed(parts) if norm(p) in city_names), "")
            return org, city
    return org, city


# ---------------------------------------------------------------- сбор

def channel_open(log: Log) -> bool:
    if blocks.state(CHANNEL) == "blocked":
        log(f"✖ Qtickets: сайт закрыл доступ серверу — не опрашиваем до {(blocks.until(CHANNEL) or '')[:16].replace('T', ' ')}")
        return False
    return True


def fetch(cities: list[str], log: Log, today: str, client: Client | None = None) -> list[dict] | None:
    """
    Афиша Qtickets по городам списка: [{city, sub, items}] — items как parse_cards. None — сайт отказал (не собирали).
    Потом, в остатке бюджета, — страницы мероприятий (организатор и город по адресу) в PAGES_FILE.
    """
    if not channel_open(log):
        return None
    client = client or Client()
    try:
        out = _fetch(cities, log, today, client)
    except Denied as e:
        rec = blocks.trip(CHANNEL, 403, f"{CHANNEL}: отказ сайта при сборе афиши ({str(e)[:80]})")
        log(f"✖ Qtickets: сайт отказал (403 / 428 / капча) — не опрашиваем до {rec['until'][:16].replace('T', ' ')}")
        return None
    if out and blocks.clear(CHANNEL):
        log("Qtickets: доступ снова открыт")
    return out


def _fetch(cities: list[str], log: Log, today: str, client: Client) -> list[dict]:
    known = load_json(CITIES_CACHE, {})
    home = client.get("https://qtickets.events/")
    fresh = parse_cities(home or "")
    if len(fresh) >= 100:   # главная открылась целиком — словарь обновляем
        known = fresh
        save_json(CITIES_CACHE, known)
    sub_of = {norm(name): sub for sub, name in known.items()}
    out, missing, seen = [], [], set()
    for city in cities:
        sub = sub_of.get(norm(city))
        if not sub:
            missing.append(city)
            continue
        items, page = [], 1
        while page <= MAX_PAGES:
            body = client.get(f"https://{sub}.qtickets.events/" + (f"?page={page}" if page > 1 else ""))
            if body is None:
                break
            cards = [c for c in parse_cards(body) if c["id"] not in seen]
            seen.update(c["id"] for c in cards)
            items += cards
            if 'id="next_page"' not in body or not cards:
                break
            page += 1
        out.append({"city": city, "sub": sub, "items": items})
    got = sum(len(p["items"]) for p in out)
    log(f"Qtickets: {len(out)} городов, карточек {got}, запросов {client.used}, ошибок {client.errors}"
        + (f"; на сайте нет: {', '.join(missing)}" if missing else ""))
    if client.left <= 0:
        log("✖ Qtickets: бюджет запросов кончился на афише — часть городов не собрана")
    fetch_pages(out, set(sub_of), log, today, client)
    return out


def fetch_pages(parts: list[dict], city_names: set[str], log: Log, today: str, client: Client) -> None:
    """Страницы мероприятий: организатор и город площадки. Ещё не проверенные и ближайшие — первыми; раз в месяц — заново."""
    cache = load_json(PAGES_FILE, {})
    stale = (datetime.fromisoformat(today) - timedelta(days=RECHECK_DAYS)).date().isoformat()
    todo = sorted(((str(c["id"]) in cache, c["dt"][:10], c) for p in parts for c in p["items"]
                   if str(c["id"]) not in cache or cache[str(c["id"])][2] < stale), key=lambda x: x[:2])
    deadline, done, found = time.time() + PAGES_MIN * 60, 0, 0
    for _, _, c in todo:
        if time.time() > deadline or client.left <= 0:
            break
        body = client.get(c["url"])
        if body is None:
            continue
        org, city = parse_event(body, city_names)
        cache[str(c["id"])] = [org, city, today]
        done += 1
        found += bool(org)
    # Прошедшие мероприятия из кэша убираем — файл не растёт бесконечно
    alive = {str(c["id"]) for p in parts for c in p["items"]}
    cache = {k: v for k, v in cache.items() if k in alive or v[2] >= stale}
    save_json(PAGES_FILE, cache)
    log(f"Qtickets, страницы мероприятий: {done} — организатор найден у {found}; осталось {max(0, len(todo) - done)} на следующие сборы")


def pages() -> dict:
    return load_json(PAGES_FILE, {})


def known_cities() -> dict[str, str]:
    return load_json(CITIES_CACHE, {})


# ---------------------------------------------------------------- название без города и даты

_MONTHS = r"(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*"
_DATE = re.compile(r"(?<![\d.,])\d{1,2}\s*[./]\s*(?:0[1-9]|1[0-2])(?:\s*[./]\s*(?:20)?\d\d)?(?![\d])"
                   r"|(?<![\d])\d{1,2}\s+" + _MONTHS + r"(?:\s+20\d\d(?:\s*г(?:ода|\.)?)?)?", re.I)
_AGE = re.compile(r"\(\s*\d{1,2}\s*\+\s*\)|(?<![\w])\d{1,2}\+(?![\w])")
_SEP = re.compile(r"(\s*[|/•]\s*|\s+[-–—]\s+)")


def _city_re(city: str) -> str:
    """«Пенза» → «пенз\\w*» (в Пензе), «Нижний Новгород» → «нижн\\w*[\\s-]+новгоро\\w*»."""
    stems = [re.escape(w[:-2] if len(w) >= 6 else w[:-1]) + r"\w*" for w in re.findall(r"[^\W_]+", city.lower().replace("ё", "е"))]
    return r"[\s-]+".join(stems)


def clean_title(title: str, city: str) -> str:
    """
    Название без города, даты и возраста — иначе оно не склеится с Кассиром, Яндексом и туром проекта:
    «AdrenalinHouse в Пензе 18 октября» → «AdrenalinHouse», «CODE80 | 23 Октября | Оренбург» → «CODE80»,
    «СТАНЦИОННЫЙ СМОТРИТЕЛЬ/Пенза/11.10/Хэ» → «СТАНЦИОННЫЙ СМОТРИТЕЛЬ/Хэ». Разделители и всё прочее — как на сайте.
    """
    t = (title or "").replace("ё", "е").replace("Ё", "Е")
    cre, name = _city_re(city), re.escape(city.replace("ё", "е"))
    t = _AGE.sub(" ", _DATE.sub(" ", t))
    t = re.sub(r"\(\s*(?:г\.?\s*)?" + cre + r"\s*\)", " ", t, flags=re.I)
    t = re.sub(r"(?<![\w])(?:во?\s+г\.?\s*|во?\s+|г\.\s*|г\s+)" + cre + r"(?![\w])", " ", t, flags=re.I)
    parts = _SEP.split(t)
    segs = []
    for n in range(0, len(parts), 2):
        seg = parts[n]
        seg = re.sub(r"^\s*" + name + r"\s*[.,:]?\s+(?=\S)|[\s.,]+" + name + r"[.!]?\s*$", " ", seg, flags=re.I)  # «… в кино. Пенза»
        seg = re.sub(r"^\s*" + cre + r"[\s.,!]*$", "", seg, flags=re.I)                                          # сегмент — только город
        seg = re.sub(r"\s+([,.!?:;\]\)»])", r"\1", re.sub(r"\s+", " ", seg))
        seg = re.sub(r"[,\s]+([!?.])", r"\1", seg).replace("[]", "").replace("()", "")
        seg = re.sub(r",\s*,", ",", seg).strip(" ,.:;-–—")
        segs.append((parts[n - 1] if n else "", seg if re.search(r"\w", seg) else ""))
    out, first = "", True
    for sep, seg in segs:
        if seg:
            mark = sep.strip()
            out += ("" if first else sep if mark == "/" else f" {mark} ") + seg
            first = False
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out if len(out) >= 2 else (title or "").strip()
