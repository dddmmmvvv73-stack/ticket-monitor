"""
Яндекс Афиша для сбора продаж (TICKET_PLATFORMS.md, 2 и 8.1).

Сводке сеанса верить нельзя (складывает кассы, бывает больше зала) — она только чтобы найти сеанс, узнать кассы
и заметить изменение. Свободные места — по схеме (hallplan, уникальные места), зал — по геометрии схемы.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

from sales.net import Net

CLIENT = "bb40c7f4-11ee-4f00-9804-18ee56565c87"   # публичный ключ виджета (есть в каждой странице Яндекс Афиши)
WIDGET = "https://widget.afisha.yandex.ru"
WH = {"Accept": "application/json", "Referer": WIDGET + "/", "Origin": WIDGET, "x-force-cors-preflight": "1",
      "Content-Type": "application/json; charset=UTF-8"}
SERVICE_LEVEL = 998   # уровни схемы с id ≥ 998 — услуги вроде «Meet & Greet», не кресла


def _json(body: bytes):
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def key_parts(key: str) -> list[str]:
    """Ключ сеанса = base64 «площадка|событие|зал|время в мс»."""
    try:
        return base64.b64decode(key + "===").decode().split("|")
    except Exception:
        return []


def session_keys(net: Net, url: str, page_cache: dict) -> list[str]:
    if url not in page_cache:
        st, body = net.req(url, headers={"Accept-Language": "ru-RU"}, kind="page")
        text = body.decode("utf-8", "ignore") if st == 200 else ""
        page_cache[url] = list(dict.fromkeys(re.findall(r"Ticket:([A-Za-z0-9+/=]{20,})", text)))
    return page_cache[url]


def summary(net: Net, key: str) -> tuple[dict | None, bytes]:
    st, body = net.req("%s/api/tickets/v1/sessions/%s?clientKey=%s" % (WIDGET, urllib.parse.quote(key, safe=""), CLIENT), headers=WH, kind="summary")
    d = _json(body) if st == 200 else None
    return (((d or {}).get("result") or {}).get("session") if isinstance(d, dict) else None), body


def find_session(net: Net, url: str, date: str, time_: str | None, page_cache: dict) -> tuple[str | None, dict | None, bytes]:
    """Ключ сеанса по дате и времени: кандидаты по времени из ключа (±14 ч — пояса), подтверждение сводкой."""
    want = datetime.fromisoformat(date + "T" + (time_ or "12:00")).replace(tzinfo=timezone.utc).timestamp()
    cands = []
    for k in session_keys(net, url, page_cache):
        p = key_parts(k)
        if len(p) >= 4 and p[3].isdigit() and abs(int(p[3]) / 1000 - want) < 14 * 3600:
            cands.append(k)
    fallback = None
    for k in cands:
        s, body = summary(net, k)
        if not s:
            continue
        if s.get("sessionDate", "").startswith(date + ("T" + time_ if time_ else "")):
            return k, s, body
        if s.get("sessionDate", "").startswith(date) and fallback is None:
            fallback = (k, s, body)   # время у сайтов бывает разным — тогда по дате
    return fallback or (None, None, b"")


def free_seats(net: Net, key: str, widget_cookie: list) -> tuple[dict | None, bytes]:
    """Свободные места схемы: {«уровень|ряд|место»: цена в ₽}. None — не получилось (антибот, нет схемы)."""
    qk = urllib.parse.quote(key, safe="")
    if not widget_cookie[0]:
        net.req("%s/w/sessions/%s?widgetName=w1&clientKey=%s&embed=true" % (WIDGET, qk, CLIENT), kind="widget")
        widget_cookie[0] = True
    st, body = net.req(WIDGET + "/api/antibot/check", data=json.dumps({"sessionKey": key}).encode(), headers=WH, kind="antibot")
    ab = _json(body) if st == 200 else None
    if not isinstance(ab, dict) or not ab.get("jwt") or ab.get("captchaRequired"):
        return None, b""
    h = dict(WH, **{"x-antibot-token": ab["jwt"]})
    for _ in range(6):
        st, body = net.req("%s/api/tickets/v4/sessions/%s/hallplan?clientKey=%s" % (WIDGET, qk, CLIENT), headers=h, kind="hallplan")
        r = _json(body) if st == 200 else None
        if isinstance(r, dict) and r.get("status") == "completed" and r.get("url"):
            st, body = net.req(r["url"], kind="hallplan_cdn")
            hp = ((_json(body) or {}).get("result") or {}).get("hallplan")
            if not hp:
                return None, body
            out = {}
            for lv in hp.get("levels", []):
                if (lv.get("id") or 0) >= SERVICE_LEVEL:
                    continue
                for s in lv.get("seats", []):
                    seat = s.get("seat") or {}
                    price = ((s.get("priceInfo") or {}).get("price") or {}).get("value")
                    out["%s|%s|%s" % (lv.get("name"), seat.get("row"), seat.get("place"))] = (price or 0) / 100
            return out, body
        if not isinstance(r, dict) or r.get("status") not in ("running", None):
            return None, body
        time.sleep(1.5)
    return None, b""


def hall(net: Net, scheme_url: str) -> tuple[list | None, bytes]:
    """Все места зала по геометрии схемы: [[«уровень|ряд|место», уровень, ряд, место, x, y], …] без «не кресел»."""
    st, body = net.req(scheme_url, kind="scheme")
    d = _json(body) if st == 200 else None
    if not isinstance(d, dict):
        return None, body
    seats = []
    for lv in d.get("levels", []):
        if (lv.get("id") or 0) >= SERVICE_LEVEL or "meet" in (lv.get("name") or "").lower():
            continue
        for s in lv.get("seats", []):
            seats.append(["%s|%s|%s" % (lv.get("name"), s.get("row"), s.get("place")), lv.get("name"), s.get("row"), s.get("place"),
                          s.get("x_coord"), s.get("y_coord")])
    return seats, body
