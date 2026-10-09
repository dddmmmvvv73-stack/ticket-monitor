"""
ОрелКонцерт (орелконцерт.рф) — своя билетная система Орла и Мценска (TICKET_PLATFORMS.md, 9.1).
Отдельный модуль: остальные источники сбора он не трогает.

Устройство сайта (проверено 09.10.2026):

  /hall/<зал>        афиша зала — карточки: /event/<номер>-<slug>, название, дата «09.10.2026», время, цены «от - до»
                     (без сервисного сбора)
  POST /ajax/api     api=schemeLoad&scheme=<номер> — схема зала JSON, как её грузит страница покупателя:
                     _OBJECTS[ObjectType = place]: ID, Sector, Row, Seat, CX/CY, Price, Free
                     Цена в схеме — с сервисным сбором 10% (6 600 = 6 000 × 1,1); у занятых мест — 0.

Источник в config/competitors.json — один зал: {"type": "orelkoncert", "hall": "grinn_tsentr", "name": …, "city": "Орел"}.
Строки — в формате vladimirkoncert.collect_venue, места — в формате seatmap.parse_seats (зона = сектор схемы),
поэтому вал, подтверждённые продажи, бронь зала и рассадки считаются общим кодом без изменений.

Бережно (TICKET_PLATFORMS.md, 7.3): пауза PAUSE с между запросами, один запрос схемы на сеанс; отказ сайта
(403 / капча) — канал orelkoncert/direct закрывается (competitors/blocks.py), сбор зала пропускается до срока.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from competitors import blocks, seatmap
from competitors.fetch import USER_AGENT, clean_text

SITE = "орелконцерт.рф"
BASE = "https://xn--e1aaodlcdmgu5b.xn--p1ai"   # орелконцерт.рф в записи для запросов
CHANNEL = "orelkoncert/direct"
PAUSE = 2.0
SERVICE_FEE = 1.10   # цены схемы — с сервисным сбором; вал считаем без него (TICKET_PLATFORMS.md, правило 12)
HALLS = {   # залы сайта (страницы /hall/…): адрес → (название, город). Стадион не берём — там спорт.
    "grinn_tsentr": ("Гринн Центр", "Орел"),
    "kongress_kholl": ("Конгресс-Холл", "Орел"),
    "kdts": ("КДЦ Металлург", "Орел"),
    "ogat-im-turgeneva": ("ОГАТ им. Тургенева", "Орел"),
    "mbuk_ogtsk": ("МБУК «ОГЦК»", "Орел"),
    "dk_gmcensk": ("ДК г. Мценск", "Мценск"),
}

Log = Callable[[str], None]
_last = 0.0


class Denied(Exception):
    """Сайт отказал адресу — канал закрыт до срока."""


def _req(path: str, data: dict | None = None, referer: str = "") -> bytes:
    global _last
    if blocks.state(CHANNEL) == "blocked":
        raise Denied("сайт закрыл доступ — не опрашиваем до %s" % (blocks.until(CHANNEL) or "")[:16].replace("T", " "))
    wait = _last + PAUSE - time.time()
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers.update({"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Referer": referer or BASE + "/"})
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=body, headers=headers), timeout=30) as r:
            raw, url, status = r.read(), r.geturl(), r.status
    except urllib.error.HTTPError as e:
        raw, url, status = e.read() or b"", BASE + path, e.code
        if not blocks.is_denied(status, url, raw):
            raise
    finally:
        _last = time.time()
    if blocks.is_denied(status, url, raw):
        rec = blocks.trip(CHANNEL, status, "%s: отказ сайта (%s)" % (CHANNEL, status))
        raise Denied("сайт отказал (%s) — не опрашиваем до %s" % (status, rec["until"][:16].replace("T", " ")))
    blocks.clear(CHANNEL)
    return raw


def _text(s: str) -> str:
    return clean_text(html.unescape(s or ""))


def clean_title(t: str) -> str:
    """Сайт дописывает к названию город и дату («Султан Лагучев г. Орел», «10.12.26 Сопрано Турецкого Орел») —
    без них проект склеивается с тем же туром в других городах."""
    t = re.sub(r"^\d{2}\.\d{2}\.\d{2,4}\s+", "", t.strip())
    t = re.sub(r"(?:\s+\d{1,2}\s+[а-я]+)?\s+(?:г\.\s*)?(?:Ор[её]л|Мценск)\s*$", "", t, flags=re.I)
    return t.strip(" .,-–") or t


def list_events(hall: str) -> list[dict]:
    """Карточки афиши зала: номер, ссылка, название, дата (ISO), время, цены без сбора."""
    page = _req("/hall/%s" % hall).decode("utf-8", errors="replace")
    out, seen = [], set()
    # Карточка для широкого экрана: «event_card d-none d-md-block» … до следующей карточки
    for block in re.split(r'(?=<div class="event_card d-none d-md-block">)', page)[1:]:
        link = re.search(r'class="event_card_hover_div_title">\s*<a href="(/event/(\d+)-[^"]+)">(.*?)</a>', block, re.S)
        if not link or link.group(2) in seen:
            continue
        seen.add(link.group(2))
        when = re.search(r'<span>(\d{2})\.(\d{2})\.(\d{4})</span>', block)
        tm = re.search(r'date_text">\s*(\d{1,2}:\d{2})\s*</div>', block)
        prices = [int(p) for p in re.findall(r'event_card_bottom_price_num">\s*(\d+)\s*<', block)]
        out.append({
            "event_id": link.group(2), "url": BASE + link.group(1), "title": clean_title(_text(link.group(3))),
            "date": "%s-%s-%s" % (when.group(3), when.group(2), when.group(1)) if when else None,
            "time": tm.group(1) if tm else None,
            "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
        })
    return out


def load_scheme(event_id: str, url: str) -> list[dict] | None:
    """Места схемы в формате seatmap.parse_seats; None — схемы нет (продажа закрыта, входные билеты)."""
    raw = _req("/ajax/api", {"api": "schemeLoad", "scheme": event_id, "scheme_sub": "", "designer": ""},
               referer=url.replace("/event/", "/scheme/"))
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    if not (data.get("_SETTING") or {}).get("_STATUS"):
        return None
    seats = []
    for o in data.get("_OBJECTS") or []:
        if o.get("ObjectType") != "place":
            continue
        free = bool(o.get("Free"))
        price = int(round((o.get("Price") or 0) / SERVICE_FEE)) if free and o.get("Price") else None
        seats.append({"id": str(o.get("ID")), "x": int(round(o.get("CX") or 0)), "y": int(round(o.get("CY") or 0)),
                      "place": str(o.get("Seat") or "?"), "row": str(o.get("Row") or "?"),
                      "zone": (o.get("Sector") or "").strip() or "?", "price": price, "taken": not free})
    seatmap.normalize(seats)
    return seats or None


def collect_hall(source: dict, log: Log) -> list[dict]:
    """Все мероприятия одного зала → строки общей таблицы конкурентов (как vladimirkoncert.collect_venue)."""
    hall = source["hall"]
    name, city = HALLS.get(hall, (source.get("name") or hall, source.get("city") or "Орел"))
    events = list_events(hall)
    log(f"орелконцерт / {source.get('name') or name}: найдено {len(events)} мероприятий, разбираю схемы залов…")
    rows = []
    for ev in events:
        if not ev["date"] or "сертификат" in ev["title"].lower():
            continue
        seats = None
        try:
            seats = load_scheme(ev["event_id"], ev["url"])
        except Denied:
            raise
        except Exception as e:  # одно мероприятие не должно останавливать зал
            log(f"  ⚠ {ev['title']}: схема зала не открылась ({e})")
        taken = sum(1 for s in seats if s["taken"]) if seats else None
        rows.append({
            "source": "orelkoncert", "site": SITE, "venue": source.get("name") or name, "city": source.get("city") or city,
            "hall": None, "title": ev["title"], "age": None, "pushkin": False, "description": "", "site_types": [],
            "show_url": ev["url"], "uid": "orel:%s" % ev["event_id"], "url": ev["url"], "vk_event_id": None,
            "date": ev["date"], "time": ev["time"], "price_min": ev["price_min"], "price_max": ev["price_max"],
            "seats_free": len(seats) - taken if seats else None, "seats_taken": taken,
            "seats_total": len(seats) if seats else None, "_seats": seats or [],
        })
    return rows
