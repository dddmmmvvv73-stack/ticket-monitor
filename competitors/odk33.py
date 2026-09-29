"""
Парсер афиши ОДКиИ «Областной Дворец культуры и искусства», Владимир (odk33.ru).

Афиша — обычный HTML, 20 карточек на страницу, страницы ?page=N.
В карточке есть: дата (день + месяц, без года), время, цена «от-до» текстом,
зал, отметка «Пушкинская карта», короткое описание и кнопка «Купить»,
ведущая на vladimirkoncert.ru.

Если кнопка есть — дополнительно открываем схему зала на vladimirkoncert.ru:
оттуда берутся точные цены по категориям и заполняемость зала.
Мероприятия без кнопки (вход по пригласительным, клубные) остаются
только с данными афиши.
"""

from __future__ import annotations

import re
from typing import Callable

from competitors import vladimirkoncert as vk
from competitors.dates import infer_date, month_number
from competitors.fetch import clean_text, fetch_html

BASE_URL = "https://odk33.ru/"
AFISHA_URL = BASE_URL + "afisha/"
VENUE_NAME = "ОДКиИ (Владимир)"
CITY = "Владимир"
VK_VENUE_ID = "2"  # «Областной Дворец культуры и искусства» на vladimirkoncert.ru
MAX_PAGES = 15  # предохранитель от бесконечного цикла при смене разметки

Log = Callable[[str], None]


def _page_count(page: str) -> int:
    numbers = [int(n) for n in re.findall(r'href="afisha/\?page=(\d+)"', page)]
    return min(max(numbers, default=1), MAX_PAGES)


def _parse_price(text: str) -> tuple[int | None, int | None, str]:
    text = text.replace("₽", "").strip()
    numbers = [int(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*\d|\d", text)]
    if not numbers:
        return None, None, text  # «Вход по пригласительным билетам» и т.п.
    return min(numbers), max(numbers), text


def _parse_cards(page: str) -> list[dict]:
    cards = []
    for block in re.split(r'<div class="item">', page)[1:]:
        if 'class="item-title"' not in block or 'class="item-day"' not in block:
            continue

        day = re.search(r'class="item-day">\s*(\d+)', block)
        month = re.search(r'class="item-month">\s*([^<]+)', block)
        time_ = re.search(r'class="item-time">\s*([^<]+)', block)
        price = re.search(r'class="item-price">\s*<span>(.*?)</span>', block, re.S)
        title = re.search(r'class="item-title">\s*<a href="([^"]+)">(.*?)</a>', block, re.S)
        description = re.search(r'class="item-description">(.*?)</div>', block, re.S)
        # Свойства различаются иконкой: scene — зал, clock — длительность, cafe — кафе
        properties = re.findall(
            r'images/([\w-]+)\.svg"[^>]*>\s*</div>\s*<div class="item-property-value">(.*?)</div>',
            block, re.S)
        halls = [value for icon, value in properties if icon == "scene"]
        duration = next((clean_text(v) for icon, v in properties if icon == "clock"), None)
        buy = re.search(r'class="item-btn">\s*<a href="([^"]+)"', block)

        if not (day and month and title):
            continue
        month_num = month_number(month.group(1))
        event_date = infer_date(int(day.group(1)), month_num) if month_num else None
        price_min, price_max, price_text = _parse_price(clean_text(price.group(1)) if price else "")
        slug = title.group(1).rstrip("/").split("/")[-1]

        cards.append({
            "uid": f"odk33:{slug}",
            "source": "odk33",
            "venue": VENUE_NAME,
            "city": CITY,
            "hall": ", ".join(clean_text(h) for h in halls) or None,
            "title": clean_text(title.group(2)),
            "date": event_date,
            "time": clean_text(time_.group(1)) if time_ else None,
            "duration": duration,
            "price_min": price_min,
            "price_max": price_max,
            "price_text": price_text if price_min is None else "",
            "pushkin": "pushkin-sticker" in block,
            "description": clean_text(description.group(1))[:600] if description else "",
            "url": BASE_URL + title.group(1).lstrip("/"),
            "buy_url": buy.group(1) if buy else None,
            "site_types": [],
            "age": None,
            "seats_free": None, "seats_taken": None, "seats_total": None,
            "vk_event_id": None,
        })
    return cards


def _enrich_from_vk(card: dict, site_types_by_show: dict[str, list[str]], log: Log) -> None:
    """Точные цены и заполняемость зала со схемы на vladimirkoncert.ru."""
    try:
        event_urls = vk.resolve_event_urls(card["buy_url"])
        events = [vk.parse_event_page(u) for u in event_urls[:5]]
    except Exception as e:
        log(f"  ⚠ {card['title']}: схема зала на vladimirkoncert.ru не открылась ({e})")
        return
    if not events:
        return

    # У шоу может быть несколько сеансов — берём тот, что совпадает по дате с афишей
    ev = next((e for e in events if e["date"] == card["date"]), events[0])
    card["vk_event_id"] = ev["event_id"]
    card["buy_url"] = ev["url"]
    if ev["price_min"] is not None:
        card["price_min"], card["price_max"] = ev["price_min"], ev["price_max"]
    card["seats_free"] = ev["seats_free"]
    card["seats_taken"] = ev["seats_taken"]
    card["seats_total"] = ev["seats_total"]
    card["_seats"] = ev["seats"]  # уходит в расчёт вала, в events.json не сохраняется
    card["site_types"] = site_types_by_show.get(vk.show_id_from_url(ev["show_url"]), [])
    # На билетном сайте название часто полнее («… Проект студии современного танца»)
    if ev["title"] and ev["title"].lower() not in card["title"].lower():
        card["alt_title"] = ev["title"]
    if not card["time"] and ev["time"]:
        card["time"] = ev["time"]


def _site_types_by_show(log: Log) -> dict[str, list[str]]:
    """Тип мероприятия (Концерт / Спектакль / …) из списка площадки на vladimirkoncert.ru —
    одним запросом на все карточки; помогает классификации без ИИ."""
    try:
        return {vk.show_id_from_url(s["show_url"]): s["site_types"] for s in vk.list_shows(VK_VENUE_ID)}
    except Exception as e:
        log(f"  ⚠ не удалось получить типы мероприятий с vladimirkoncert.ru ({e})")
        return {}


def collect(log: Log) -> list[dict]:
    first = fetch_html(AFISHA_URL)
    pages = [first]
    total_pages = _page_count(first)
    for n in range(2, total_pages + 1):
        pages.append(fetch_html(f"{AFISHA_URL}?page={n}"))

    cards: dict[str, dict] = {}
    for page in pages:
        for card in _parse_cards(page):
            cards.setdefault(card["uid"], card)

    log(f"odk33.ru: {len(cards)} мероприятий на {total_pages} стр. афиши, "
        f"подтягиваю схемы залов с vladimirkoncert.ru…")

    site_types = _site_types_by_show(log)
    for card in cards.values():
        if card["buy_url"] and vk.is_vk_url(card["buy_url"]):
            _enrich_from_vk(card, site_types, log)

    return list(cards.values())
