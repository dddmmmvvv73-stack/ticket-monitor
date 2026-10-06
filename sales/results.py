"""
Итог сеанса (DATA_MODEL.md, 3.7): цифры по последнему снимку до начала — и больше не меняются. Это и есть архив.

    python3 -m sales.results          # зафиксировать итоги начавшихся и снятых сеансов (tm-sync, каждый час)

Итог пишется в sessions.result:
    {"at": когда зафиксирован, "cut": по какой момент взяты снимки, "st": "past" (прошло) | "gone" (снято до даты),
     "pools": {номер карточки: строка как в сводке продаж (sales.export.sales_row)}, "best": номер самой полной кассы}
У площадок прямого сбора (vladimirkoncert, odk33) строка — по схеме зала: op «d», выставлено = мест в схеме, вал — по снимку.
Сеанс без слежения тоже получает итог (пустые pools) — чтобы не пересчитывать его каждый час.
Снятый до даты сеанс вернулся в продажу — итог стирается и будет зафиксирован заново.
"""

from __future__ import annotations

import json
from datetime import datetime

from db import connect
from sales.export import sales_row

# Начало сеанса; без времени — конец дня. Снятый до даты — по последнему снимку вообще.
NEED_SQL = """
CREATE TEMP TABLE need ON COMMIT DROP AS
SELECT s.id, s.status,
       CASE WHEN s.status IN ('removed', 'cancelled') AND coalesce(s.starts_at, (s.local_date + 1)::timestamptz) > now() THEN now()
            ELSE coalesce(s.starts_at, (s.local_date + 1)::timestamptz) END AS cut
  FROM sessions s
 WHERE s.result IS NULL
   AND (coalesce(s.starts_at, (s.local_date + 1)::timestamptz) <= now() OR s.status IN ('removed', 'cancelled'))
"""

POOLS_SQL = """
WITH np AS (SELECT p.id, p.session_id, p.operator_id, p.listing_key, p.source, p.ext, n.cut
              FROM pools p JOIN need n ON n.id = p.session_id),
last AS (
  SELECT DISTINCT ON (o.pool_id) o.pool_id, o.free, o.total, o.taken, o.gross AS gnum, coalesce(o.checked_at, o.ts) AS at
    FROM observations o JOIN np ON np.id = o.pool_id
   WHERE NOT o.anomaly AND o.ts <= np.cut
   ORDER BY o.pool_id, o.ts DESC),
withgross AS (
  SELECT DISTINCT ON (o.pool_id) o.pool_id, o.summary->'gross' AS g
    FROM observations o JOIN np ON np.id = o.pool_id
   WHERE NOT o.anomaly AND o.gross IS NOT NULL AND o.ts <= np.cut
   ORDER BY o.pool_id, o.ts DESC),
first AS (SELECT o.pool_id, min(o.ts) AS since FROM observations o JOIN np ON np.id = o.pool_id WHERE o.ts <= np.cut GROUP BY o.pool_id),
seat AS (SELECT ss.pool_id, sum(CASE kind WHEN 'sale' THEN 1 WHEN 'return' THEN -1 ELSE 0 END) AS n,
                sum(CASE kind WHEN 'sale' THEN price WHEN 'return' THEN -price ELSE 0 END) AS rub
           FROM seat_sales ss JOIN np ON np.id = ss.pool_id WHERE ss.ts <= np.cut GROUP BY ss.pool_id),
price AS (SELECT ps.pool_id, sum(qty) AS n, sum(qty * price) AS rub
            FROM price_sales ps JOIN np ON np.id = ps.pool_id
           WHERE NOT ps.anomaly AND NOT ps.released AND ps.ts <= np.cut GROUP BY ps.pool_id)
SELECT np.session_id, np.operator_id, np.listing_key, np.source, np.ext, l.free, l.total, l.taken, l.gnum, w.g, f.since, l.at,
       coalesce(s.n, pr.n, 0), coalesce(s.rub, pr.rub, 0), lh.capacity, np.id
  FROM np
  LEFT JOIN last l ON l.pool_id = np.id
  LEFT JOIN withgross w ON w.pool_id = np.id
  LEFT JOIN first f ON f.pool_id = np.id
  LEFT JOIN seat s ON s.pool_id = np.id
  LEFT JOIN price pr ON pr.pool_id = np.id
  LEFT JOIN live_halls lh ON lh.key = np.ext->>'hall'
"""


def _direct_row(free, total, taken, gnum, since, at, sold, rev) -> dict:
    """Площадка прямого сбора: схема зала целиком — выставлено и свободно известны с первого снимка."""
    r = {"op": "d"}
    if total:
        r["exp"] = int(total)
        r["free"] = int(free if free is not None else max(0, total - (taken or 0)))
    if gnum:
        r["g"] = int(gnum)
    if since:
        r.update(since=since.isoformat(timespec="minutes"), sold=int(sold or 0), rev=int(rev or 0))
    if at:
        r["at"] = at.isoformat(timespec="minutes")
    return r


def _best(pools: dict) -> str | None:
    """Самая полная касса — как best_sales в афише рынка: прямой сбор и Кассир со схемой → Яндекс → любая с остатком."""
    order = [k for k, r in pools.items() if r.get("op") == "d" and "free" in r] + \
            [k for k, r in pools.items() if r.get("exp")] + \
            [k for k, r in pools.items() if r.get("op") == "y" and "free" in r] + \
            [k for k, r in pools.items() if "free" in r] + [k for k, r in pools.items() if r.get("nt")]
    return order[0] if order else None


def fix(conn) -> dict:
    """Фиксирует итоги; возвращает, сколько записано и сколько стёрто (снятый вернулся в продажу)."""
    cur = conn.cursor()
    # Снято до даты, а потом вернулось в продажу и дата ещё впереди — итог «снято» больше не верен
    cur.execute("""UPDATE sessions SET result = NULL
                    WHERE result->>'st' = 'gone' AND status NOT IN ('removed', 'cancelled')
                      AND coalesce(starts_at, (local_date + 1)::timestamptz) > now()""")
    reopened = cur.rowcount
    cur.execute(NEED_SQL)
    cur.execute("SELECT id, status, cut FROM need")
    need = {sid: (status, cut) for sid, status, cut in cur.fetchall()}
    pools: dict[int, dict] = {sid: {} for sid in need}
    cur.execute(POOLS_SQL)
    for (sid, op, key, source, ext, free, total, taken, gnum, g, since, at, sold, rev, hall, pid) in cur.fetchall():
        if source == "json":
            row = _direct_row(free, total, taken, gnum, since, at, sold, rev)
        else:
            row = sales_row(op, ext, free, total, g, since, at, sold, rev, hall)
        pools[sid][key or f"pool:{pid}"] = row
    now = datetime.now().astimezone().isoformat(timespec="minutes")
    values = []
    for sid, (status, cut) in need.items():
        p = pools[sid]
        res = {"at": now, "cut": cut.isoformat(timespec="minutes"), "st": "gone" if status in ("removed", "cancelled") else "past", "pools": p}
        best = _best(p)
        if best:
            res["best"] = best
        values.append((json.dumps(res, ensure_ascii=False), sid))
    cur.executemany("UPDATE sessions SET result = %s::jsonb WHERE id = %s", values)
    conn.commit()
    return {"итогов записано": len(values), "с данными продаж": sum(1 for sid in need if pools[sid]), "снятых вернулось в продажу": reopened}


def main() -> None:
    conn = connect.connect()
    try:
        print(json.dumps(fix(conn), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
