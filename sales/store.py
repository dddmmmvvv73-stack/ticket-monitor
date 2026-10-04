"""
Запись сбора продаж в базу (DATA_MODEL.md, 3.4–3.6): запас кассы → наблюдение (только при изменении) → продажи
по местам и по ценам. «Весь зал занят» (seatmap.is_flip) — наблюдение с anomaly, без продаж; следующее сравнивается
с последним нормальным.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from psycopg2.extras import Json, execute_values

from competitors.seatmap import is_flip

# Частота по близости даты (решение 04.10): до 7 дней — 3 раза в день, 8–30 — раз в день, 31–90 — раз в 3 дня, дальше — раз в неделю
TIERS = [(7, timedelta(hours=8)), (30, timedelta(hours=24)), (90, timedelta(hours=72))]
FAR = timedelta(days=7)
SHARED_RECHECK = timedelta(days=7)   # общий ли запас Кассира и Яндекса — перепроверять раз в неделю


def interval(local_date: date, today: date) -> timedelta:
    days = (local_date - today).days
    return next((iv for limit, iv in TIERS if days <= limit), FAR)


def pool(cur, operator: str, listing_key: str, session_id: int | None) -> dict:
    cur.execute("SELECT id, ext, next_check FROM pools WHERE source = 'live' AND operator_id = %s AND listing_key = %s AND service = ''",
                (operator, listing_key))
    row = cur.fetchone()
    if row:
        if session_id:
            cur.execute("UPDATE pools SET session_id = %s WHERE id = %s", (session_id, row[0]))
        return {"id": row[0], "ext": row[1] or {}, "next_check": row[2]}
    cur.execute("INSERT INTO pools (session_id, operator_id, service, listing_key, source) VALUES (%s,%s,'',%s,'live') RETURNING id",
                (session_id, operator, listing_key))
    return {"id": cur.fetchone()[0], "ext": {}, "next_check": None}


def save_ext(cur, p: dict) -> None:
    cur.execute("UPDATE pools SET ext = %s WHERE id = %s", (Json(p["ext"]), p["id"]))


def schedule(cur, pool_id: int, local_date: date, now: datetime, retry: bool = False) -> None:
    """Следующий снимок: по близости даты; после ошибки — через час."""
    nxt = now + (timedelta(hours=1) if retry else interval(local_date, now.date()))
    cur.execute("UPDATE pools SET next_check = %s WHERE id = %s", (nxt, pool_id))


def _last(cur, pool_id: int, normal_with_seats: bool = False):
    q = "SELECT ts, free, free_by_price, seat_prices, sale_status, anomaly FROM observations WHERE pool_id = %s"
    if normal_with_seats:
        q += " AND NOT anomaly AND seat_prices IS NOT NULL"
    cur.execute(q + " ORDER BY ts DESC LIMIT 1", (pool_id,))
    r = cur.fetchone()
    return dict(zip(("ts", "free", "by_price", "seats", "sale", "anomaly"), r)) if r else None


def record(cur, pool_id: int, now: datetime, *, free: int | None, by_price: dict | None, total: int | None,
           seats: dict | None = None, sale_status: str | None = None, hidden: bool = False, summary: dict | None = None,
           raw_ref: str | None = None, gross: dict | None = None) -> dict:
    """
    Пишет наблюдение, если что-то изменилось, и продажи с прошлого нормального наблюдения.
    seats — свободные места схемы {место: цена} (если скачана); by_price — свободно по ценам.
    """
    if seats is not None and by_price is None:
        by_price = {str(p): n for p, n in Counter(seats.values()).items()}
    if seats is not None and free is None:
        free = len(seats)
    last = _last(cur, pool_id)
    same = last and last["free"] == free and (last["by_price"] or {}) == (by_price or {}) and last["sale"] == sale_status \
        and (seats is None or (last["seats"] or {}) == seats)
    if same:
        cur.execute("UPDATE observations SET checked_at = %s WHERE pool_id = %s AND ts = %s", (now, pool_id, last["ts"]))
        return {"changed": False}
    normal = last if last and not last["anomaly"] else None
    if last and last["anomaly"]:  # сравниваем с последним нормальным
        cur.execute("SELECT ts, free, free_by_price, seat_prices, sale_status, anomaly FROM observations "
                    "WHERE pool_id = %s AND NOT anomaly ORDER BY ts DESC LIMIT 1", (pool_id,))
        r = cur.fetchone()
        normal = dict(zip(("ts", "free", "by_price", "seats", "sale", "anomaly"), r)) if r else None
    prev_seats = None
    if seats is not None:
        ps = _last(cur, pool_id, normal_with_seats=True)
        prev_seats = ps["seats"] if ps else None
    # «Весь зал занят» — не продажи
    if prev_seats is not None and seats is not None:
        anomaly = is_flip(len(prev_seats), len(set(prev_seats) - set(seats)))
    else:
        anomaly = bool(normal and normal["free"] is not None and free is not None and is_flip(normal["free"], max(0, normal["free"] - free)))
    if gross:
        summary = {**(summary or {}), "gross": gross}
    cur.execute("INSERT INTO observations (pool_id, ts, checked_at, free, free_by_price, total, sale_status, hidden, anomaly, summary, seat_prices, raw_ref, gross) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (pool_id, now, now, free, Json(by_price) if by_price is not None else None, total, sale_status, hidden, anomaly,
                 Json(summary) if summary else None, Json(seats) if seats is not None else None, raw_ref, (gross or {}).get("gross")))
    out = {"changed": True, "anomaly": anomaly, "sold": 0, "returned": 0}
    if anomaly or not normal:
        return out
    if prev_seats is not None and seats is not None:
        sold = [(pool_id, k, now, prev_seats[k], "sale") for k in set(prev_seats) - set(seats)]
        back = [(pool_id, k, now, seats[k], "return") for k in set(seats) - set(prev_seats)]
        if sold or back:
            execute_values(cur, "INSERT INTO seat_sales (pool_id, seat_key, ts, price, kind) VALUES %s ON CONFLICT DO NOTHING", sold + back)
        out["sold"], out["returned"] = len(sold), len(back)
    if by_price is not None and normal.get("by_price") is not None:
        rows = []
        for p in set(normal["by_price"]) | set(by_price):
            d = normal["by_price"].get(p, 0) - by_price.get(p, 0)
            if d and p not in ("None", ""):
                rows.append((pool_id, normal["ts"], now, float(p), d))
        if rows:
            execute_values(cur, "INSERT INTO price_sales (pool_id, ts_from, ts_to, price, qty) VALUES %s ON CONFLICT DO NOTHING", rows)
        if prev_seats is None:
            out["sold"] = sum(r[4] for r in rows if r[4] > 0)
            out["returned"] = -sum(r[4] for r in rows if r[4] < 0)
    return out


def save_hall(cur, key: str, city: str, venue: str, seats: list) -> None:
    cur.execute("INSERT INTO live_halls (key, city, venue, capacity, seats, updated) VALUES (%s,%s,%s,%s,%s,now()) "
                "ON CONFLICT (key) DO UPDATE SET capacity = EXCLUDED.capacity, seats = EXCLUDED.seats, updated = now()",
                (key, city, venue, len(seats), Json(seats)))


def hall_keys(cur, key: str) -> list[str]:
    cur.execute("SELECT seats FROM live_halls WHERE key = %s", (key,))
    r = cur.fetchone()
    return [s[0] for s in r[0]] if r else []


def hall_capacity(cur, key: str) -> int | None:
    cur.execute("SELECT capacity FROM live_halls WHERE key = %s", (key,))
    r = cur.fetchone()
    return r[0] if r else None
