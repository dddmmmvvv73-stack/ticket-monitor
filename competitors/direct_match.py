"""
Связка мероприятий площадок прямого сбора (vladimirkoncert, odk33) с теми же сеансами в афише рынка (Кассир / Яндекс).

Правило DATA_MODEL.md, 4.1: тот же город, дата и время + та же площадка (по словарю написаний) + похожее название.
Одно и то же правило — в базе (db.migrate) и в прототипе (market.export_js): одна строка «Мероприятий» на сеанс.
"""

from __future__ import annotations

from collections import defaultdict

from competitors import curation, market, protodata

# Площадки прямого сбора: как они пишутся в афише рынка
DIRECT_VENUE_ALIASES = {
    ("Владимир", "ОДКиИ"): ["Областной Дворец культуры и искусства", "Дворец культуры и искусства"],
    ("Иваново", "Центр культуры и отдыха"): ["ЦКиО"],
    ("Иваново", "Ивановский музыкальный театр"): ["Музыкальный театр"],
}
ALIAS_TO = {(city, curation.venue_key(city, a)): name for (city, name), al in DIRECT_VENUE_ALIASES.items() for a in al}


def canonical(events: dict) -> dict[str, dict]:
    """uid → мероприятие с городом и названием площадки из словаря прототипа («Арт Холл» — Владимир, не «Владимирская обл.»)."""
    known = protodata._venues(list(events.values()))
    out = {}
    for uid, e in events.items():
        _code, vname, vcity = known.get(e.get("source_id") or e.get("source"), ("", e.get("venue") or "", e.get("city") or ""))
        out[uid] = {**e, "venue": vname or e.get("venue") or "", "city": vcity or e.get("city") or ""}
    return out


def same_session(market_row: dict, e: dict, aliases) -> bool:
    city = e["city"]
    venue_ok = market.same_venue(market_row["venue"], e["venue"], city, aliases) \
        or ALIAS_TO.get((city, curation.venue_key(city, market_row["venue"]))) == e["venue"]
    return venue_ok and market.similar_title(market_row["title"], e["title"])


def match(market_rows: list[dict], events: dict, aliases) -> dict[int, str]:
    """Номер строки афиши рынка → uid мероприятия площадки прямого сбора (тот же сеанс)."""
    slot: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(market_rows):
        slot[(r["city"], r["date"], r.get("time") or "")].append(i)
    out = {}
    for uid, e in canonical(events).items():
        date = (e.get("date") or "")[:10]
        for i in slot.get((e["city"], date, e.get("time") or ""), []):
            if i not in out and same_session(market_rows[i], e, aliases):
                out[i] = uid
                break
    return out
