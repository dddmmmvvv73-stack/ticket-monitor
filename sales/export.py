"""
Сводка продаж для прототипа: по каждой карточке (listing_key = номер у оператора, как ключи в афише рынка)
последние цифры и продажи за время слежения. Пишется после каждого прогона сбора в data/sales_snapshot.json.gz;
ноутбук забирает её по SSH (./pull_data.sh) — в публичный репозиторий данные продаж не попадают.

    python3 -m sales.export

Поля строки: op (k — Кассир, y — Яндекс), free — свободно сейчас, exp — выставлено (схема кассы), hall — мест в зале
(схема Яндекса), g / glo / ghi / gx — вал, диапазон, доля точных цен, sold / rev — продано и выручка по
подтверждённым продажам с начала слежения (since), at — последний снимок, shared — общий запас с другой кассой,
nt — Яндекс сам не продаёт.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

from db import connect

OUT = Path(__file__).resolve().parent.parent / "data" / "sales_snapshot.json.gz"

SQL = """
WITH last AS (
  SELECT DISTINCT ON (o.pool_id) o.pool_id, o.free, o.total, o.gross, o.summary, coalesce(o.checked_at, o.ts) AS at
    FROM observations o JOIN pools p ON p.id = o.pool_id
   WHERE p.source = 'live' AND NOT o.anomaly
   ORDER BY o.pool_id, o.ts DESC),
withgross AS (
  SELECT DISTINCT ON (o.pool_id) o.pool_id, o.gross, o.summary->'gross' AS g, o.total
    FROM observations o JOIN pools p ON p.id = o.pool_id
   WHERE p.source = 'live' AND NOT o.anomaly AND o.gross IS NOT NULL
   ORDER BY o.pool_id, o.ts DESC),
first AS (SELECT pool_id, min(ts) AS since FROM observations GROUP BY pool_id),
seat AS (SELECT pool_id, sum(CASE WHEN kind = 'sale' THEN 1 ELSE -1 END) AS n,
                sum(CASE WHEN kind = 'sale' THEN price ELSE -price END) AS rub FROM seat_sales GROUP BY pool_id),
price AS (SELECT pool_id, sum(qty) AS n, sum(qty * price) AS rub FROM price_sales WHERE NOT anomaly GROUP BY pool_id)
SELECT p.operator_id, p.listing_key, p.ext, l.free, l.total, w.g, w.total, f.since, l.at,
       coalesce(s.n, pr.n, 0), coalesce(s.rub, pr.rub, 0), lh.capacity
  FROM pools p
  LEFT JOIN last l ON l.pool_id = p.id
  LEFT JOIN withgross w ON w.pool_id = p.id
  LEFT JOIN first f ON f.pool_id = p.id
  LEFT JOIN seat s ON s.pool_id = p.id
  LEFT JOIN price pr ON pr.pool_id = p.id
  LEFT JOIN live_halls lh ON lh.key = p.ext->>'hall'
 WHERE p.source = 'live'
"""


def build(conn) -> dict:
    cur = conn.cursor()
    cur.execute(SQL)
    rows = {}
    for op, key, ext, free, total, g, gtotal, since, at, sold, rev, hall in cur.fetchall():
        ext = ext or {}
        r = {"op": "k" if op == "kassir" else "y"}
        if ext.get("no_tickets"):
            r["nt"] = 1
        if free is not None:
            r["free"] = free
        exposed = (g or {}).get("exposed") if op == "kassir" else None
        if exposed or (op == "kassir" and (total or ext.get("total"))):
            r["exp"] = exposed or total or ext.get("total")
        if hall:
            r["hall"] = hall
        if g:
            r.update(g=g["gross"], glo=g["gross_lo"], ghi=g["gross_hi"], gx=g["exact_share"])
        if since:
            r.update(since=since.isoformat(timespec="minutes"), sold=int(sold or 0), rev=int(rev or 0))
        if at:
            r["at"] = at.isoformat(timespec="minutes")
        if ext.get("shared"):
            r["shared"] = 1
        rows[key] = r
    return {"at": datetime.now().astimezone().isoformat(timespec="minutes"), "rows": rows}


def main() -> None:
    data = build(connect.connect())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()))
    tmp.replace(OUT)
    print("Сводка продаж: %d карточек → %s" % (len(data["rows"]), OUT))


if __name__ == "__main__":
    main()
