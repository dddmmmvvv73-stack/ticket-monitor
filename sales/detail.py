"""
Подробности продаж одного сеанса — для карточки мероприятия в прототипе (ноутбук спрашивает по SSH, /api/sales/detail).

    python3 -m sales.detail <номер карточки> [<номер карточки> …]    # k:event:…, k:activity:…, y:…@город

По каждому запасу кассы: цифры последнего снимка, история «свободно» по снимкам, «Зал по рядам» (зона, ряд, мест,
свободно, цены), продажи с начала слежения и последние продажи / возвраты. JSON — в stdout.
"""

from __future__ import annotations

import json
import re
import sys

from db import connect

HISTORY = 120   # снимков в графике (последние)
RECENT = 25     # последних продаж / возвратов


def _rows(hall_seats: list, free: dict) -> list:
    """«Зал по рядам»: [[зона, [[ряд, мест, свободно, цена от, цена до], …]], …] — в порядке схемы."""
    zones: dict = {}
    for s in hall_seats:
        key, zone, row = s[0], s[1], s[2]
        z = zones.setdefault(zone, {})
        r = z.setdefault(row, [0, 0, []])
        r[0] += 1
        if key in free:
            r[1] += 1
            if free[key]:
                r[2].append(free[key])
    def order(row):  # ряды по номеру: в схеме Яндекса они идут с конца зала
        m = re.match(r"\d+", str(row or ""))
        return (0, int(m.group()), str(row)) if m else (1, 0, str(row))
    return [[zone, [[row, z[row][0], z[row][1], min(z[row][2]) if z[row][2] else None, max(z[row][2]) if z[row][2] else None]
                    for row in sorted(z, key=order)]] for zone, z in zones.items()]


def detail(conn, keys: list[str]) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT id, operator_id, listing_key, ext FROM pools WHERE source = 'live' AND listing_key = ANY(%s)", (keys,))
    out = []
    for pid, op, key, ext in cur.fetchall():
        ext = ext or {}
        cur.execute("SELECT ts, free, total, anomaly, gross, summary, seat_prices IS NOT NULL, checked_at FROM observations "
                    "WHERE pool_id = %s ORDER BY ts", (pid,))
        obs = cur.fetchall()
        if not obs:
            out.append({"op": op, "key": key, "nt": bool(ext.get("no_tickets")), "snapshots": 0})
            continue
        normal = [o for o in obs if not o[3]]
        last = normal[-1] if normal else obs[-1]
        g = next((o[5].get("gross") for o in reversed(normal) if o[5] and o[5].get("gross")), None)
        cur.execute("SELECT seat_prices FROM observations WHERE pool_id = %s AND NOT anomaly AND seat_prices IS NOT NULL ORDER BY ts DESC LIMIT 1", (pid,))
        r = cur.fetchone()
        free_seats = r[0] if r else None
        rows = None
        if free_seats is not None and ext.get("hall"):
            cur.execute("SELECT seats FROM live_halls WHERE key = %s", (ext["hall"],))
            h = cur.fetchone()
            if h:
                rows = _rows(h[0], free_seats)
        cur.execute("SELECT kind, count(*), coalesce(sum(price), 0) FROM seat_sales WHERE pool_id = %s GROUP BY kind", (pid,))
        seat_tot = {k: (n, float(s)) for k, n, s in cur.fetchall()}
        cur.execute("SELECT ts, seat_key, price, kind FROM seat_sales WHERE pool_id = %s ORDER BY ts DESC LIMIT %s", (pid, RECENT))
        recent = [[t.isoformat(timespec="minutes"), k, float(p) if p is not None else None, kind] for t, k, p, kind in cur.fetchall()]
        if not seat_tot:  # схемы нет — продажи по ценам
            cur.execute("SELECT coalesce(sum(qty) FILTER (WHERE qty > 0), 0), coalesce(sum(qty * price) FILTER (WHERE qty > 0), 0), "
                        "coalesce(-sum(qty) FILTER (WHERE qty < 0), 0), coalesce(-sum(qty * price) FILTER (WHERE qty < 0), 0) "
                        "FROM price_sales WHERE pool_id = %s AND NOT anomaly", (pid,))
            a, b, c, d = cur.fetchone()
            seat_tot = {"sale": (int(a), float(b)), "return": (int(c), float(d))}
            cur.execute("SELECT ts_to, price, qty FROM price_sales WHERE pool_id = %s ORDER BY ts_to DESC LIMIT %s", (pid, RECENT))
            recent = [[t.isoformat(timespec="minutes"), None, float(p), "sale" if q > 0 else "return", abs(q)] for t, p, q in cur.fetchall()]
        sold, sold_rub = seat_tot.get("sale", (0, 0))
        ret, ret_rub = seat_tot.get("return", (0, 0))
        summary = last[5] or {}
        out.append({
            "op": op, "key": key, "shared": ext.get("shared"), "services": ext.get("services"), "sale_opening": ext.get("sale_opening"),
            "since": obs[0][0].isoformat(timespec="minutes"), "at": (last[7] or last[0]).isoformat(timespec="minutes"),
            "snapshots": len(obs), "anomalies": sum(1 for o in obs if o[3]),
            "free": last[1], "exp": (g or {}).get("exposed") if op == "kassir" else None, "hall": last[2] if op == "yandex" else None,
            "gross": g, "scheme": free_seats is not None,
            "history": [[o[0].isoformat(timespec="minutes"), o[1], bool(o[3])] for o in obs[-HISTORY:]],
            "rows": rows, "sold": sold - ret, "rev": round(sold_rub - ret_rub), "sold_gross": sold, "returned": ret,
            "recent": recent, "sectors": summary.get("sectors"),
        })
    return {"pools": out}


if __name__ == "__main__":
    print(json.dumps(detail(connect.connect(), sys.argv[1:]), ensure_ascii=False, default=str))
