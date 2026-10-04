"""
Один прогон сбора продаж гастролей: сеансы, которым пора (DATA_MODEL.md, 3.4а), — ближние даты первыми,
Яндекс и Кассир параллельно, каждый в своём темпе, в пределах бюджета времени.

    python3 -m sales.run [--cities "Ульяновск,Ярославль"] [--budget 40] [--limit 0]

Кассир — только где без него нельзя: сеанс только на Кассире, или запас Кассира не совпал с Яндексом
(поделён). Совпал (общий запас) — Кассир не опрашивается неделю, хватает Яндекса.
"""

from __future__ import annotations

import argparse
import threading
import time
from collections import Counter
from datetime import datetime

from psycopg2.extras import Json

from db import connect
from sales import archive, kassir, metrics, store, yandex
from sales.net import Net, Stopped

WORK_SQL = """
SELECT s.id, s.local_date, to_char(s.local_time, 'HH24:MI'), c.name, v.name, l.operator_id, l.ext_key, l.url,
       EXISTS (SELECT 1 FROM listings y WHERE y.session_id = s.id AND y.operator_id = 'yandex') AS has_yandex,
       p.ext
  FROM sessions s
  JOIN venues v ON v.id = s.venue_id
  JOIN cities c ON c.id = v.city_id
  JOIN listings l ON l.session_id = s.id AND l.operator_id IN ('kassir', 'yandex')
  LEFT JOIN pools p ON p.source = 'live' AND p.operator_id = l.operator_id AND p.listing_key = l.ext_key AND p.service = ''
 WHERE s.track_sales AND s.status = 'on_sale'
   AND (s.starts_at > now() OR (s.starts_at IS NULL AND s.local_date >= current_date))   -- уже начавшиеся — не снимаем
   AND (p.next_check IS NULL OR p.next_check <= now())
   AND (%(cities)s::text[] IS NULL OR c.name = ANY(%(cities)s::text[]))
 ORDER BY s.local_date, p.next_check NULLS FIRST
"""
TOLERANCE = 3   # мест: запас Кассира и Яндекса «общий», если отличается не больше чем на max(3, 2%) — продажи за минуты между запросами


def _yandex_job(conn, net: Net, items: list, stats: Counter) -> None:
    cur = conn.cursor()
    pages, wcookie = {}, [False]
    for (sid, d, t, city, venue, _op, key, url, _hy, _ext) in items:
        if net.time_left() < 30:
            break
        now = datetime.now().astimezone()
        p = store.pool(cur, "yandex", key, sid)
        try:
            skey = p["ext"].get("key")
            if skey:
                s, sbody = yandex.summary(net, skey)
            else:
                skey, s, sbody = yandex.find_session(net, url, d.isoformat(), t, pages)
            if not s:
                if not skey and not pages.get(url):  # Яндекс сам не продаёт (ссылка на чужую кассу) — запас смотрим у Кассира
                    stats["яндекс: продажи не на Яндексе"] += 1
                    p["ext"].update(no_tickets=True, checked=now.isoformat(timespec="seconds"))
                    store.save_ext(cur, p)
                    cur.execute("UPDATE pools SET next_check = %s WHERE id = %s", (now + store.FAR, p["id"]))
                else:
                    stats["яндекс: сеанс не найден"] += 1
                    store.schedule(cur, p["id"], d, now, retry=True)
                conn.commit()
                continue
            parts = yandex.key_parts(skey)
            hall_key = "yandex:%s:%s" % (parts[0], parts[2]) if len(parts) >= 3 else None
            capacity = store.hall_capacity(cur, hall_key) if hall_key else None
            if hall_key and capacity is None and s.get("hallplanSchemeUrl"):
                seats_all, hbody = yandex.hall(net, s["hallplanSchemeUrl"])
                if seats_all:
                    store.save_hall(cur, hall_key, city, venue, seats_all)
                    archive.save("yandex", "hall", hall_key, hbody)
                    capacity = len(seats_all)
            avail, sale = s.get("availableSeatCount"), s.get("saleStatus")
            info = {"avail": avail, "total": s.get("totalSeatCount"), "services": [x.get("serviceDescription") or x.get("serviceName") for x in s.get("sessionServices") or []],
                    "protocols": [x.get("protocolName") for x in s.get("sessionServices") or []], "admission": s.get("admission"),
                    "sale_opening": s.get("saleOpening")}
            unchanged = p["ext"].get("avail") == avail and p["ext"].get("sale") == sale and p["ext"].get("seen")
            if unchanged:
                store.record(cur, p["id"], now, free=p["ext"].get("free"), by_price=p["ext"].get("by_price"), total=capacity,
                             seats=None, sale_status=sale)  # без изменений — только «проверено»
                stats["яндекс: без изменений"] += 1
            else:
                seats, hp_body = (None, b"") if s.get("admission") else yandex.free_seats(net, skey, wcookie)
                ref = archive.save("yandex", "hallplan" if seats is not None else "summary", key, hp_body if seats is not None else sbody)
                g = metrics.gross(store.hall_keys(cur, hall_key), seats) if seats and hall_key else None  # вал по залу — оценка
                res = store.record(cur, p["id"], now, free=len(seats) if seats is not None else avail, by_price=None, total=capacity,
                                   seats=seats, sale_status=sale, summary=info, raw_ref=ref, gross=g)
                obs_by_price = None
                if seats is not None:
                    obs_by_price = {str(k): v for k, v in Counter(seats.values()).items()}
                p["ext"].update(free=len(seats) if seats is not None else avail, by_price=obs_by_price, seen=True,
                                scheme=seats is not None)
                stats["яндекс: снято"] += 1
                stats["яндекс: продано мест"] += res.get("sold", 0)
                stats["яндекс: вернулось мест"] += res.get("returned", 0)
                stats["яндекс: «весь зал занят»"] += int(bool(res.get("anomaly")))
            p["ext"].update(key=skey, avail=avail, sale=sale, services=info["services"], hall=hall_key, sale_opening=info["sale_opening"])
            store.save_ext(cur, p)
            store.schedule(cur, p["id"], d, now)
            conn.commit()
        except Stopped:
            conn.rollback()
            break
        except Exception as e:  # одна карточка не должна останавливать прогон
            conn.rollback()
            stats["яндекс: ошибка " + type(e).__name__] += 1


def _kassir_job(conn, net: Net, items: list, stats: Counter) -> None:
    cur = conn.cursor()
    pages = {}
    for (sid, d, t, city, venue, _op, key, url, has_yandex, ext) in items:
        if net.time_left() < 30:
            break
        ext = ext or {}
        now = datetime.now().astimezone()
        p = store.pool(cur, "kassir", key, sid)
        if has_yandex and ext.get("shared") and ext.get("shared_at", "") > (datetime.now() - store.SHARED_RECHECK).isoformat():
            stats["кассир: общий запас с Яндексом — пропуск"] += 1   # хватает Яндекса; перепроверка — через неделю
            store.schedule(cur, p["id"], d, now)
            conn.commit()
            continue
        try:
            domain = (url or "").split("/")[2] if url and url.count("/") >= 2 else None
            eid = p["ext"].get("sid") or (kassir.event_id(net, key, url, d.isoformat(), pages) if domain else None)
            if not eid or not domain:
                stats["кассир: сеанс не найден"] += 1
                store.schedule(cur, p["id"], d, now, retry=True)
                conn.commit()
                continue
            rem, kbody = kassir.remaining(net, eid, domain)
            if rem is None:
                stats["кассир: ошибка ответа"] += 1
                store.schedule(cur, p["id"], d, now, retry=True)
                p["ext"].update(sid=eid, domain=domain)
                store.save_ext(cur, p)
                conn.commit()
                continue
            changed = p["ext"].get("by_price") != rem["by_price"] or not p["ext"].get("seen")
            seats = total = g = None
            if changed and rem["scheme"]:
                sch, sbody = kassir.seats(net, eid, domain, rem["prices"])
                if sch:
                    seats, total = sch["free"], len(sch["all"])
                    g = metrics.gross(sch["all"], sch["free"])  # вал выставленных мест кассы
                    archive.save("kassir", "scheme", key, sbody)
            ref = archive.save("kassir", "kit", key, kbody) if changed else None
            res = store.record(cur, p["id"], now, free=rem["free"], by_price=rem["by_price"], total=total or p["ext"].get("total"),
                               seats=seats if seats is not None else None, hidden=rem["hidden"],
                               summary={"sectors": rem["sectors"], "scheme": rem["scheme"]} if changed else None, raw_ref=ref, gross=g)
            p["ext"].update(sid=eid, domain=domain, by_price=rem["by_price"], free=rem["free"], seen=True, total=total or p["ext"].get("total"))
            store.save_ext(cur, p)
            store.schedule(cur, p["id"], d, now)
            conn.commit()
            stats["кассир: снято" if changed else "кассир: без изменений"] += 1
            stats["кассир: продано мест"] += res.get("sold", 0)
            stats["кассир: вернулось мест"] += res.get("returned", 0)
            stats["кассир: «весь зал занят»"] += int(bool(res.get("anomaly")))
        except Stopped:
            conn.rollback()
            break
        except Exception as e:
            conn.rollback()
            stats["кассир: ошибка " + type(e).__name__] += 1


def update_shared(conn) -> int:
    """Общий ли запас: последние снимки Кассира и Яндекса одного сеанса (не дальше 3 часов друг от друга) совпали."""
    cur = conn.cursor()
    cur.execute("""
        WITH last AS (
          SELECT DISTINCT ON (p.id) p.id, p.session_id, p.operator_id, o.ts, o.free, (p.ext->>'scheme')::boolean AS scheme
            FROM pools p JOIN observations o ON o.pool_id = p.id
           WHERE p.source = 'live' AND p.session_id IS NOT NULL AND NOT o.anomaly
           ORDER BY p.id, o.ts DESC)
        SELECT k.id, k.free, y.free FROM last k JOIN last y ON y.session_id = k.session_id AND y.operator_id = 'yandex'
         WHERE k.operator_id = 'kassir' AND y.scheme AND abs(extract(epoch FROM k.ts - y.ts)) < 3 * 3600""")
    n = 0
    for pid, kf, yf in cur.fetchall():
        shared = kf is not None and yf is not None and abs(kf - yf) <= max(TOLERANCE, 0.02 * max(kf, yf))
        cur.execute("UPDATE pools SET ext = ext || %s WHERE id = %s",
                    (Json({"shared": shared, "shared_at": datetime.now().isoformat(timespec="seconds")}), pid))
        n += shared
    conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default="")
    ap.add_argument("--budget", type=float, default=40, help="минут на прогон")
    ap.add_argument("--limit", type=int, default=0, help="не больше N карточек на оператора (проверка)")
    a = ap.parse_args()
    started = time.time()
    deadline = started + a.budget * 60
    conn = connect.connect()
    connect.ensure_schema(conn)
    cur = conn.cursor()
    cities = [c.strip() for c in a.cities.split(",") if c.strip()] or None
    cur.execute(WORK_SQL, {"cities": cities})
    rows = cur.fetchall()
    work = {"yandex": [r for r in rows if r[5] == "yandex"], "kassir": [r for r in rows if r[5] == "kassir"]}
    if a.limit:
        work = {k: v[:a.limit] for k, v in work.items()}
    stats: Counter = Counter()
    nets = {op: Net(op, deadline) for op in work}
    threads = [threading.Thread(target=job, args=(connect.connect(), nets[op], work[op], stats))
               for op, job in (("yandex", _yandex_job), ("kassir", _kassir_job))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    shared = update_shared(conn)
    took = int(time.time() - started)
    for op in work:
        net_stats = {"%s %s" % k: v for k, v in nets[op].stats.items()}
        mine = {k: v for k, v in stats.items() if k.startswith(("яндекс" if op == "yandex" else "кассир"))}
        cur.execute("INSERT INTO collection_runs (operator_id, kind, started, finished, sessions, errors, blocked, summary, report) "
                    "VALUES (%s,'sales',to_timestamp(%s),now(),%s,%s,%s,%s,%s)",
                    (op, started, len(work[op]), sum(v for k, v in nets[op].stats.items() if k[1] is None or (isinstance(k[1], int) and k[1] >= 500)),
                     int(nets[op].stopped), "в очереди %d, за %d с" % (len(work[op]), took), Json({"сбор": mine, "запросы": net_stats})))
    conn.commit()
    print("Сбор продаж: %d с, в очереди: Яндекс %d, Кассир %d; общий запас найден у %d" % (took, len(work["yandex"]), len(work["kassir"]), shared))
    for k, v in sorted(stats.items()):
        print("  %s: %s" % (k, v))
    for op in nets:
        print("  запросы %s: %s%s" % (op, dict(nets[op].stats), " — ОСТАНОВЛЕН предохранителем" if nets[op].stopped else ""))


if __name__ == "__main__":
    main()
