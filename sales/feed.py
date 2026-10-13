"""
Продажи по кассам для разделов «История продаж» и «Динамика продаж» (запрос пользователя 13.10.2026: фильтр по кассам —
Кассир, Qtickets, ОрелКонцерт, vladimirkoncert; видеть, где идёт сбор и как идут продажи).

    python3 -m sales.feed [дней]          JSON (по умолчанию 14 дней) — то, что отдаёт /api/sales/feed

Из базы (все кассы одинаково):
  - продажи по местам (seat_sales: sale +1, return −1; «открыли места» — не возвраты, не считаем);
  - продажи по ценам там, где у кассы нет схемы мест (price_sales: qty > 0 — продано, < 0 — вернулось; без сбоев и без
    «открыли места»);
  - слежение: сеансов в продаже под слежением, снимков за сутки, первый и последний снимок.
«Занято» ≠ «продано»: продажа — место было свободно в прошлом снимке и стало занятым (TICKET_PLATFORMS, правила 1–8);
пачки снятых с продажи мест пока считаются продажами (QUESTIONS 27).
"""

from __future__ import annotations

import json
import sys

from db import connect

SALES = """
WITH s AS (
  SELECT x.pool_id, x.ts, CASE x.kind WHEN 'sale' THEN 1 ELSE -1 END AS n, CASE x.kind WHEN 'sale' THEN coalesce(x.price, 0) ELSE -coalesce(x.price, 0) END AS rub
    FROM seat_sales x WHERE x.kind IN ('sale', 'return') AND x.ts > now() - make_interval(days => %(days)s)
  UNION ALL
  SELECT x.pool_id, x.ts_to, x.qty, x.qty * x.price FROM price_sales x
   WHERE NOT x.anomaly AND NOT x.released AND x.ts_to > now() - make_interval(days => %(days)s))
SELECT date_trunc('hour', s.ts) AS at, p.operator_id, p.listing_key, coalesce(se.title, pr.title), c.name, v.name, se.local_date, se.local_time,
       sum(s.n) FILTER (WHERE s.n > 0), coalesce(-sum(s.n) FILTER (WHERE s.n < 0), 0), sum(s.rub)
  FROM s JOIN pools p ON p.id = s.pool_id JOIN sessions se ON se.id = p.session_id
  JOIN venues v ON v.id = se.venue_id JOIN cities c ON c.id = v.city_id LEFT JOIN projects pr ON pr.id = se.project_id
 GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
 ORDER BY 1 DESC
"""
TOTALS = """
WITH s AS (
  SELECT x.pool_id, x.ts, CASE x.kind WHEN 'sale' THEN 1 ELSE -1 END AS n, CASE x.kind WHEN 'sale' THEN coalesce(x.price, 0) ELSE -coalesce(x.price, 0) END AS rub
    FROM seat_sales x WHERE x.kind IN ('sale', 'return')
  UNION ALL
  SELECT x.pool_id, x.ts_to, x.qty, x.qty * x.price FROM price_sales x WHERE NOT x.anomaly AND NOT x.released)
SELECT p.operator_id, sum(s.n) FILTER (WHERE s.n > 0), sum(s.rub), min(s.ts),
       sum(s.n) FILTER (WHERE s.n > 0 AND s.ts > now() - interval '24 hours'), sum(s.rub) FILTER (WHERE s.ts > now() - interval '24 hours'),
       sum(s.n) FILTER (WHERE s.n > 0 AND s.ts > now() - interval '7 days'), sum(s.rub) FILTER (WHERE s.ts > now() - interval '7 days')
  FROM s JOIN pools p ON p.id = s.pool_id GROUP BY 1
"""
TRACK = """
SELECT p.operator_id, count(DISTINCT p.id) FILTER (WHERE se.status = 'on_sale' AND se.local_date >= current_date),
       count(o.id) FILTER (WHERE o.ts > now() - interval '24 hours'), count(DISTINCT o.pool_id) FILTER (WHERE o.ts > now() - interval '24 hours'),
       min(o.ts), max(coalesce(o.checked_at, o.ts))
  FROM pools p JOIN sessions se ON se.id = p.session_id LEFT JOIN observations o ON o.pool_id = p.id
 GROUP BY 1
"""


def build(conn, days: int = 14) -> dict:
    cur = conn.cursor()
    iso = lambda v: v.isoformat(timespec="minutes") if v else None
    ops: dict[str, dict] = {}
    cur.execute(TRACK)
    for op, tracked, snaps, pools24, first, last in cur.fetchall():
        ops[op] = {"tracked": tracked or 0, "snaps24": snaps or 0, "pools24": pools24 or 0, "first": iso(first), "last": iso(last)}
    cur.execute(TOTALS)
    for op, n, rub, first, n24, r24, n7, r7 in cur.fetchall():
        o = ops.setdefault(op, {"tracked": 0, "snaps24": 0, "pools24": 0, "first": None, "last": None})
        o.update(sold=int(n or 0), rub=int(rub or 0), since=iso(first), sold24=int(n24 or 0), rub24=int(r24 or 0), sold7=int(n7 or 0), rub7=int(r7 or 0))
    cur.execute(SALES, {"days": days})
    rows = []
    for at, op, key, title, city, venue, d, t, n, ret, rub in cur.fetchall():
        rows.append({"at": iso(at), "op": op, "key": key, "t": title or "", "c": city, "v": venue, "d": d.isoformat() if d else "",
                     "tm": t.strftime("%H:%M") if t else "", "n": int(n or 0), "ret": int(ret or 0), "rub": int(rub or 0)})
    return {"days": days, "ops": ops, "rows": rows}


def main(argv: list[str]) -> None:
    days = int(argv[0]) if argv and argv[0].isdigit() else 14
    conn = connect.connect()
    try:
        print(json.dumps(build(conn, max(1, min(days, 120))), ensure_ascii=False, separators=(",", ":")))
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1:])
