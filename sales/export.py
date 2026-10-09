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

from competitors import blocks
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
seat AS (SELECT pool_id, sum(CASE kind WHEN 'sale' THEN 1 WHEN 'return' THEN -1 ELSE 0 END) AS n,   -- «открыли места» — не возвраты
                sum(CASE kind WHEN 'sale' THEN price WHEN 'return' THEN -price ELSE 0 END) AS rub FROM seat_sales GROUP BY pool_id),
price AS (SELECT pool_id, sum(qty) AS n, sum(qty * price) AS rub FROM price_sales WHERE NOT anomaly AND NOT released GROUP BY pool_id)
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


OPS_SQL = {
    "registry": "SELECT id, name, kind, engine, sites, caps FROM operators ORDER BY id",
    # Сеансы в продаже по оператору и сколько из них видно только у него — польза оператора
    "coverage": """
        WITH s AS (SELECT s.id, array_agg(DISTINCT l.operator_id) AS ops, bool_or(s.track_sales) AS tour
                     FROM sessions s JOIN listings l ON l.session_id = s.id WHERE s.status = 'on_sale' GROUP BY s.id)
        SELECT op, count(*), count(*) FILTER (WHERE array_length(ops, 1) = 1), count(*) FILTER (WHERE tour)
          FROM s, unnest(ops) AS op GROUP BY op""",
    "tracked": """SELECT operator_id, count(*), count(*) FILTER (WHERE (ext->>'shared')::boolean), count(*) FILTER (WHERE (ext->>'no_tickets')::boolean)
                    FROM pools WHERE source = 'live' GROUP BY 1""",
    "runs": """SELECT operator_id, count(*), max(finished), sum(sessions), sum(errors), sum(blocked),
                      (array_agg(report ORDER BY started DESC))[1], (array_agg(summary ORDER BY started DESC))[1]
                 FROM collection_runs WHERE kind = 'sales' AND started > now() - interval '24 hours' GROUP BY 1""",
    "obs": """SELECT p.operator_id, count(*) FROM observations o JOIN pools p ON p.id = o.pool_id
               WHERE p.source = 'live' AND o.ts > now() - interval '24 hours' GROUP BY 1""",
}


def operators(conn) -> list:
    """Экран «Билетные операторы»: реестр + охват + слежение + сборы за сутки."""
    cur = conn.cursor()
    res = {}
    for name, sql in OPS_SQL.items():
        cur.execute(sql)
        res[name] = cur.fetchall()
    cov = {r[0]: r[1:] for r in res["coverage"]}
    trk = {r[0]: r[1:] for r in res["tracked"]}
    runs = {r[0]: r[1:] for r in res["runs"]}
    obs = {r[0]: r[1] for r in res["obs"]}
    blk = blocks.load()
    out = []
    for oid, name, kind, engine, sites, caps in res["registry"]:
        c, t, r = cov.get(oid, (0, 0, 0)), trk.get(oid, (0, 0, 0)), runs.get(oid)
        o = {"id": oid, "name": name, "kind": kind, "engine": engine, "sites": sites, "caps": caps,
             "sessions": c[0], "only": c[1], "tours": c[2], "tracked": t[0], "shared": t[1], "no_tickets": t[2],
             "snaps24": obs.get(oid, 0),
             # закрытые сайтом каналы (competitors/blocks.py): {"sales" | "afisha": {since, until, strikes}}
             "blocks": {ch.split("/", 1)[1]: {k: b.get(k) for k in ("since", "until", "strikes")}
                        for ch, b in blk.items() if ch.startswith(oid + "/") and not b.get("lifted")}}
        if r:
            rep = (r[5] or {}).get("сбор", {})
            o["runs24"] = {"runs": r[0], "last": r[1].isoformat(timespec="minutes") if r[1] else None, "queue": r[2], "errors": r[3],
                           "stopped": r[4], "summary": r[6],
                           "sold": sum(v for k, v in rep.items() if "продано" in k), "snapped": sum(v for k, v in rep.items() if k.endswith("снято"))}
        out.append(o)
    return out


def sales_row(op, ext, free, total, g, since, at, sold, rev, hall) -> dict:
    """Строка сводки по одной кассе — та же и в итоге сеанса (sales.results): прототип показывает их одинаково."""
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
    return r


def build(conn) -> dict:
    cur = conn.cursor()
    cur.execute(SQL)
    rows = {}
    for op, key, ext, free, total, g, gtotal, since, at, sold, rev, hall in cur.fetchall():
        rows[key] = sales_row(op, ext, free, total, g, since, at, sold, rev, hall)
    return {"at": datetime.now().astimezone().isoformat(timespec="minutes"), "rows": rows, "operators": operators(conn),
            "suggest": suggestions(conn)}


def suggestions(conn) -> list:
    """Подсказки «похоже на размеченный проект» (db.sync) — для страницы «Репертуар → Подсказки» в прототипе.
    Ключи — как в разметке (curation.project_key): по ним прототип и сохраняет «да, это он» / «нет, другой»."""
    from competitors.curation import project_key
    cur = conn.cursor()
    cur.execute("SELECT g.title, p.title, p.mark, g.reason, g.score FROM project_suggestions g JOIN projects p ON p.id = g.project_id "
                "WHERE g.status = 'open' ORDER BY g.score DESC, g.title")
    return [{"title": t, "pk": project_key(t), "target": tt, "tpk": project_key(tt), "mark": m, "reason": r, "score": round(sc, 2)}
            for t, tt, m, r, sc in cur.fetchall()]


def main() -> None:
    data = build(connect.connect())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()))
    tmp.replace(OUT)
    print("Сводка продаж: %d карточек → %s" % (len(data["rows"]), OUT))


if __name__ == "__main__":
    main()
