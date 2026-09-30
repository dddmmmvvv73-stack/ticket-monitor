"""
Парсер региональных билетных сайтов на одном движке: vladimirkoncert.ru,
ivanovokoncert.ru, kostromakoncert.ru, yarkoncert.ru, kovrovkoncert.ru.
Сайт — параметр площадки (source["site"]), по умолчанию vladimirkoncert.ru.

Устройство сайта (всё отдаётся готовым HTML, без JavaScript):

  /shows?venue=ID          список «шоу» площадки: название, дата, цена от-до,
                           тип (Спектакль / Концерт / Балет… — CSS-классы filterTypeN)
  /shows/NNN-slug          страница шоу: возраст, описание, ссылки на сеансы
  /shows/event/NNN-slug    страница сеанса: дата/время, легенда цен
                           (data-filter-price) и схема зала целиком:
                             <a  data-content="seat" value="2900">       — свободное место
                             <span data-content="seat" class="nonfree-place"> — занято/недоступно

В отличие от Яндекс Афиши, занятые места видны сразу, поэтому заполняемость
зала считается с первого же снимка.
"""

from __future__ import annotations

import re
from typing import Callable

from competitors import seatmap
from competitors.dates import parse_day_month, parse_time
from competitors.fetch import clean_text, fetch_html

BASE_URL = "https://vladimirkoncert.ru"
CITY_BY_DEFAULT = "Владимир"
DEFAULT_SITE = "vladimirkoncert.ru"

# Известные сайты на этом движке: адрес -> (подпись, город по умолчанию)
SITES = {
    "vladimirkoncert.ru": ("Владимир и область", "Владимир"),
    "ivanovokoncert.ru": ("Иваново, Кинешма", "Иваново"),
    "kostromakoncert.ru": ("Кострома", "Кострома"),
    "yarkoncert.ru": ("Ярославль, Рыбинск", "Ярославль"),
    "kovrovkoncert.ru": ("Ковров", "Ковров"),
}

Log = Callable[[str], None]


def site_base(site: str) -> str:
    return "https://" + site


def uid_prefix(site: str) -> str:
    """vk — у vladimirkoncert.ru (так уже сохранены история и схемы залов), у остальных — имя сайта."""
    return "vk" if site == DEFAULT_SITE else site.split(".")[0]


def _base_of(url: str) -> str:
    m = re.match(r"https?://[^/]+", url or "")
    return m.group(0) if m else BASE_URL


def absolute_url(href: str, base: str = BASE_URL) -> str:
    if href.startswith("http"):
        return href
    return base + "/" + href.lstrip("/")


def event_id_from_url(url: str) -> str | None:
    m = re.search(r"/shows/event/(\d+)", url or "")
    return m.group(1) if m else None


def show_id_from_url(url: str | None) -> str | None:
    m = re.search(r"/shows/(\d+)", url or "")
    return m.group(1) if m else None


def is_event_url(url: str) -> bool:
    return event_id_from_url(url) is not None


def is_vk_url(url: str) -> bool:
    return "vladimirkoncert.ru" in (url or "")


def _prices_from_text(text: str) -> tuple[int | None, int | None]:
    """«1000 - 2200», «Цена: 450 руб. - 600 руб.», «500 руб.» -> (min, max)."""
    numbers = [int(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*\d|\d", text or "")]
    numbers = [n for n in numbers if n >= 50]  # отсекаем «0+», номера и т.п.
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def list_venues(site: str = DEFAULT_SITE) -> list[dict]:
    """Все площадки из выпадающего списка «Показывать мероприятия только этой площадки»."""
    page = fetch_html(site_base(site) + "/")
    select = re.search(r'<select[^>]*name="venue"[^>]*>(.*?)</select>', page, re.S)
    if not select:
        return []
    return [
        {"venue_id": vid, "name": clean_text(name)}
        for vid, name in re.findall(r'<option value="(\d+)">(.*?)</option>', select.group(1), re.S)
    ]


def _parse_type_labels(page: str) -> dict[str, str]:
    """filterType12 -> «Концерт» (метки берём прямо со страницы, а не хардкодим)."""
    return {
        cls: clean_text(label)
        for cls, label in re.findall(
            r'data-filter="\.(filterType\d+)"[^>]*>\s*<strong>(.*?)</strong>', page, re.S)
    }


def list_shows(venue_id: str, site: str = DEFAULT_SITE) -> list[dict]:
    base = site_base(site)
    page = fetch_html(f"{base}/shows?venue={venue_id}")
    type_labels = _parse_type_labels(page)

    shows: list[dict] = []
    seen: set[str] = set()
    blocks = re.split(r'(?=<div[^>]*itemtype="http://schema.org/Event")', page)
    for block in blocks[1:]:
        classes = re.search(r'class="([^"]*)"', block)
        link = re.search(r'href="(/shows/[^"]+)"\s+title="([^"]*)"', block)
        if not link:
            continue
        url = absolute_url(link.group(1), base)
        if url in seen:
            continue
        seen.add(url)

        type_classes = re.findall(r"filterType\d+", classes.group(1) if classes else "")
        price = re.search(r'class="gallery-text-down">\s*<h6>(.*?)<span', block, re.S)
        when = re.search(r'class="date-index-shows">(.*?)</h5>', block, re.S)

        shows.append({
            "show_url": url,
            "title": clean_text(link.group(2)),
            "price_text": clean_text(price.group(1)) if price else "",
            "date_text": clean_text(when.group(1)) if when else "",
            "site_types": [type_labels[c] for c in type_classes if c in type_labels],
        })
    return shows


def parse_show_page(url: str) -> dict:
    page = fetch_html(url)

    title = re.search(r'<h3 itemprop="name">(.*?)</h3>', page, re.S)
    place = re.search(r'itemprop="location".*?<p itemprop="name">(.*?)</p>', page, re.S)
    card = re.search(r'id="cart-entertem"(.*?)(?:Поделиться|<footer)', page, re.S)
    card_text = clean_text(card.group(1)) if card else ""

    age = re.search(r"(?<![\d+])(\d{1,2}\+)(?=\s)", card_text)
    price = re.search(r"Цена:\s*((?:[\d\s.\-–]|руб)+)", card_text)

    description = card_text
    if age:
        description = card_text[age.end():]
    description = re.split(r"Цена:", description)[0].strip()

    event_urls = list(dict.fromkeys(
        absolute_url(href, _base_of(url)) for href in re.findall(r'href="([^"]*/shows/event/[^"]+)"', page)
    ))

    return {
        "title": clean_text(title.group(1)) if title else "",
        "venue_name": clean_text(place.group(1)) if place else "",
        "age": age.group(1) if age else None,
        "price_text": price.group(1).strip() if price else "",
        "description": description[:600],
        "pushkin": "pushkin-adv" in page,
        "event_urls": event_urls,
    }


def parse_event_page(url: str) -> dict:
    """Страница сеанса: дата, легенда цен и подсчёт свободных/занятых мест."""
    page = fetch_html(url)

    title = re.search(r'class="checkout-header1">(.*?)</h1>', page, re.S)
    show_link = re.search(r'href="(/shows/[^"]+)"\s+class="back-link-checkout"', page)
    when = re.search(r'class="checkout-date">(.*?)</p>', page, re.S)
    place = re.search(r'class="checkout-palce">(.*?)</p>', page, re.S)
    when_text = clean_text(when.group(1)) if when else ""

    legend_prices = {int(p) for p in re.findall(r'data-filter-price="(\d+)"', page)}

    # Схема зала по местам — для подсчёта вала и выручки (см. seatmap.py)
    seats = seatmap.parse_seats(page)
    taken = sum(1 for s in seats if s["taken"])
    free = len(seats) - taken
    free_prices = {s["price"] for s in seats if s["price"]}

    prices = sorted(legend_prices | free_prices)
    has_map = bool(seats)

    return {
        "event_id": event_id_from_url(url),
        "url": url,
        "show_url": absolute_url(show_link.group(1), _base_of(url)) if show_link else None,
        "title": clean_text(title.group(1)) if title else "",
        "date": parse_day_month(when_text),
        "time": parse_time(when_text),
        "venue_name": clean_text(place.group(1)).split(" / ")[0] if place else "",
        "price_min": prices[0] if prices else None,
        "price_max": prices[-1] if prices else None,
        "seats_free": free if has_map else None,
        "seats_taken": taken if has_map else None,
        "seats_total": free + taken if has_map else None,
        "seats": seats,
    }


def resolve_event_urls(url: str) -> list[str]:
    """Ссылка может вести на сеанс (/shows/event/…) или на страницу шоу (/shows/…)."""
    if is_event_url(url):
        return [url]
    return parse_show_page(url)["event_urls"]


def collect_venue(venue_id: str, venue_name: str, log: Log, city: str = CITY_BY_DEFAULT,
                  site: str = DEFAULT_SITE) -> list[dict]:
    """Все сеансы одной площадки -> строки общей таблицы конкурентов."""
    shows = list_shows(venue_id, site)
    prefix = uid_prefix(site)
    log(f"{site.split('.')[0]} / {venue_name}: найдено {len(shows)} мероприятий, разбираю сеансы…")

    rows: dict[str, dict] = {}
    for show in shows:
        try:
            info = parse_show_page(show["show_url"])
        except Exception as e:
            log(f"  ⚠ {show['title']}: не открылась страница мероприятия ({e})")
            continue

        base = {
            "source": "vladimirkoncert" if site == DEFAULT_SITE else prefix,
            "site": site,
            "venue": venue_name,
            "city": city,
            "hall": None,
            "title": info["title"] or show["title"],
            "age": info["age"],
            "pushkin": info["pushkin"],
            "description": info["description"],
            "site_types": show["site_types"],
            "show_url": show["show_url"],
        }

        if not info["event_urls"]:
            # Продажа ещё не открыта — сеанса нет, берём то, что есть в списке
            price_min, price_max = _prices_from_text(show["price_text"] or info["price_text"])
            uid = f"{prefix}-show:" + re.sub(r"\D", "", show["show_url"].split("/shows/")[-1].split("-")[0])
            rows[uid] = {
                **base, "uid": uid, "url": show["show_url"],
                "date": parse_day_month(show["date_text"]), "time": parse_time(show["date_text"]),
                "price_min": price_min, "price_max": price_max,
                "seats_free": None, "seats_taken": None, "seats_total": None,
                "vk_event_id": None,
            }
            continue

        for event_url in info["event_urls"]:
            event_id = event_id_from_url(event_url)
            uid = f"{prefix}:{event_id}"
            if uid in rows:
                continue
            try:
                ev = parse_event_page(event_url)
            except Exception as e:
                log(f"  ⚠ {base['title']}: не открылась схема зала ({e})")
                continue
            if ev["price_min"] is None:
                ev["price_min"], ev["price_max"] = _prices_from_text(show["price_text"] or info["price_text"])
            rows[uid] = {
                **base, "uid": uid, "url": event_url, "vk_event_id": event_id,
                "date": ev["date"] or parse_day_month(show["date_text"]),
                "time": ev["time"],
                "price_min": ev["price_min"], "price_max": ev["price_max"],
                "seats_free": ev["seats_free"], "seats_taken": ev["seats_taken"],
                "seats_total": ev["seats_total"],
                "_seats": ev["seats"],  # уходит в расчёт вала, в events.json не сохраняется
            }

    return list(rows.values())
