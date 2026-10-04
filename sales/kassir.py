"""
Кассир для сбора продаж (TICKET_PLATFORMS.md, 2 и 8.2): номер сеанса — со страницы карточки, остаток по ценам —
order-kit, схема мест — order-kit/…/scheme (все места кассы + свободные с ценой). 500 — «предохранитель» в net.py.
"""

from __future__ import annotations

import json
import re
import time

from sales.net import Net

API = "https://api.kassir.ru/api"


def _h(domain: str) -> dict:
    return {"Content-Type": "application/json", "Accept": "application/json", "Referer": "https://%s/" % domain, "Origin": "https://%s" % domain}


def _json(body: bytes):
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def event_id(net: Net, listing_key: str, url: str, date: str, page_cache: dict) -> str | None:
    """k:event:N — номер уже в ключе; k:activity:N — со страницы карточки: «<slug>#<номер>», дата рядом."""
    if listing_key.startswith("k:event:"):
        return listing_key.split(":")[2]
    if not url:
        return None
    if url not in page_cache:
        st, body = net.req(url, kind="page")
        page_cache[url] = body.decode("utf-8", "ignore") if st == 200 else ""
    h = page_cache[url]
    slug = url.rstrip("/").split("/")[-1]
    ids = list(dict.fromkeys(re.findall(re.escape(slug) + r"#(\d+)\"", h)))
    for sid in ids:
        i = h.find("#" + sid + '"')
        if date in h[i:i + 400]:
            return sid
    return ids[0] if len(ids) == 1 else None


def remaining(net: Net, sid: str, domain: str) -> tuple[dict | None, bytes]:
    """Остаток: {free, by_price: {цена: штук}, prices: {группа: цена}, scheme, hidden, sectors}. None — ошибка."""
    st, body = net.req("%s/events/%s/order-kit?domain=%s&platformState=website" % (API, sid, domain), data=b"{}", headers=_h(domain), kind="kit")
    kit = _json(body) if st == 200 else None
    if not isinstance(kit, dict) or "quotas" not in kit:
        return None, body
    price = {t["id"]: t["tariffs"][0]["price"] for t in kit.get("tariffGroups", []) if t.get("tariffs")}
    by_price: dict[str, int] = {}
    for q in kit["quotas"]:
        for tg, n in (q.get("ticketCountByTariffGroupId") or {}).items():
            p = price.get(int(tg))
            by_price[str(p)] = by_price.get(str(p), 0) + n
    return {"free": sum(q.get("ticketsCount") or 0 for q in kit["quotas"]), "by_price": by_price, "prices": price,
            "scheme": bool(kit.get("isSchemeAvailable")), "sectors": [[s["name"], s["type"]] for s in kit.get("sectors", [])],
            "hidden": any(s.get("hideSeatsCount") for s in kit.get("sectors", []))}, body


def seats(net: Net, sid: str, domain: str, prices: dict) -> tuple[dict | None, bytes]:
    """Схема: {all: [«сектор|ряд|место»], free: {место: цена}, geo: [[место, сектор, ряд, номер, x, y]]}.
    204 — схема ещё готовится (повтор в следующий раз)."""
    for attempt in range(2):
        st, body = net.req("%s/order-kit/%s/scheme?domain=%s&platformState=website" % (API, sid, domain), data=b"{}", headers=_h(domain), kind="scheme")
        if st != 204:
            break
        time.sleep(3)
    d = (_json(body) or {}).get("data") if st == 200 else None
    if not isinstance(d, dict):
        return None, body
    quota = {int(k): v for k, v in (d.get("seatQuota") or {}).items()}
    all_keys, free, geo = [], {}, []
    for e in d.get("entities", []):
        if e.get("type") != "rowBlock":
            continue
        for row in e.get("rows", []):
            for s in row.get("seats", []):
                k = "%s|%s|%s" % (e.get("name"), row.get("name"), s.get("name"))
                all_keys.append(k)
                pos = s.get("position") or {}
                geo.append([k, e.get("name"), row.get("name"), s.get("name"), pos.get("x"), pos.get("y")])
                if s["id"] in quota:
                    free[k] = prices.get(quota[s["id"]])
    return {"all": all_keys, "free": free, "geo": geo}, body
