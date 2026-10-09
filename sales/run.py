"""
Один прогон сбора продаж гастролей: сеансы, которым пора (DATA_MODEL.md, 3.4а), — ближние даты первыми,
Яндекс и Кассир параллельно, каждый в своём темпе, в пределах бюджета времени.

    python3 -m sales.run [--cities "Ульяновск,Ярославль"] [--budget 40] [--limit 0]

Кассир — только где без него нельзя: сеанс только на Кассире, или запас Кассира не совпал с Яндексом
(поделён). Совпал (общий запас) — Кассир не опрашивается неделю, хватает Яндекса.

Нагрузка (после блокировки 06.10, TICKET_PLATFORMS.md, 8.8): суточный лимит запросов на оператора (BUDGET),
делится поровну на оставшиеся прогоны дня; сеансы — не дальше HORIZON_DAYS дней, ближние первыми. Сайт закрыл
доступ (403, капча) — оператор пропускается до срока блокировки (competitors/blocks.py).
"""

from __future__ import annotations

import argparse
import math
import os
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from psycopg2.extras import Json

from competitors import blocks
from db import connect
from sales import archive, kassir, metrics, store, yandex
from sales.net import Net, Stopped

WORK_SQL = """
SELECT s.id, s.local_date, to_char(s.local_time, 'HH24:MI'), c.name, v.name, l.operator_id, l.ext_key, l.url,
       EXISTS (SELECT 1 FROM listings y WHERE y.session_id = s.id AND y.operator_id = 'yandex') AS has_yandex,
       p.ext, y.nt, y.measured
  FROM sessions s
  JOIN venues v ON v.id = s.venue_id
  JOIN cities c ON c.id = v.city_id
  JOIN listings l ON l.session_id = s.id AND l.operator_id IN ('kassir', 'yandex')
  LEFT JOIN pools p ON p.source = 'live' AND p.operator_id = l.operator_id AND p.listing_key = l.ext_key AND p.service = ''
  -- для Кассира: снят ли уже Яндекс этого сеанса и продаёт ли он сам
  LEFT JOIN LATERAL (
    SELECT bool_or(coalesce((yp.ext->>'no_tickets')::boolean, false)) AS nt,
           bool_or(EXISTS (SELECT 1 FROM observations o WHERE o.pool_id = yp.id)) AS measured
      FROM listings yl JOIN pools yp ON yp.source = 'live' AND yp.operator_id = 'yandex' AND yp.listing_key = yl.ext_key AND yp.service = ''
     WHERE yl.session_id = s.id AND yl.operator_id = 'yandex') y ON l.operator_id = 'kassir'
 WHERE s.track_sales AND s.status = 'on_sale'
   AND (s.starts_at > now() OR (s.starts_at IS NULL AND s.local_date >= current_date))   -- уже начавшиеся — не снимаем
   AND s.local_date <= current_date + %(horizon)s
   AND (p.next_check IS NULL OR p.next_check <= now())
   AND (%(cities)s::text[] IS NULL OR c.name = ANY(%(cities)s::text[]))
 ORDER BY s.local_date, p.next_check NULLS FIRST
"""
MARKET_RUNNING = Path(__file__).resolve().parent.parent / "data" / ".market_running"   # ставит tm-market.service
# Запросов в сутки на оператора (06.10 было: Яндекс ~47 тыс., Кассир ~13 тыс. — оба закрыли доступ серверу)
BUDGET = {"yandex": int(os.environ.get("SALES_BUDGET_YANDEX", 4000)), "kassir": int(os.environ.get("SALES_BUDGET_KASSIR", 2000))}
HORIZON_DAYS = int(os.environ.get("SALES_HORIZON_DAYS", 30))   # дальние сеансы — когда подойдёт их дата
USED_SQL = """SELECT operator_id, sum(value::int) FROM collection_runs, jsonb_each_text(report->'запросы')
               WHERE kind = 'sales' AND started >= date_trunc('day', now()) AND key !~ '^(предохранитель|блокировка) '
               GROUP BY 1"""
TOLERANCE = 3   # мест: запас Кассира и Яндекса «общий», если отличается не больше чем на max(3, 2%) — продажи за минуты между запросами


def _yandex_job(conn, net: Net, items: list, stats: Counter) -> None:
    cur = conn.cursor()
    pages, wcookie = {}, [False]
    for (sid, d, t, city, venue, _op, key, url, _hy, _ext, _ynt, _ym) in items:
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
    for (sid, d, t, city, venue, _op, key, url, has_yandex, ext, y_nt, y_measured), prio in items:
        if net.time_left() < 30:
            break
        if MARKET_RUNNING.exists():  # идёт афиша рынка — она тоже ходит к Кассиру с этого адреса; Кассир — в следующем прогоне
            stats["кассир: пропуск — идёт афиша рынка"] += 1
            break
        if prio == "wait":  # сеанс есть на Яндексе, но Яндекс ещё не снят — сначала он (хватит ли его, станет ясно)
            stats["кассир: ждём снимка Яндекса"] += 1
            continue
        now = datetime.now().astimezone()
        p = store.pool(cur, "kassir", key, sid)
        if prio == "shared":
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
                    p["ext"]["hall"] = "kassir:%s" % eid   # схема кассы этого сеанса — для «Зала по рядам»
                    store.save_hall(cur, p["ext"]["hall"], city, venue, sch["geo"])
            ref = archive.save("kassir", "kit", key, kbody) if changed else None
            # Остаток Кассира включает входные билеты (танцпол); «свободно» для заполняемости — кресла схемы, входные — отдельно
            free = len(seats) if seats is not None else rem["free"]
            summ = {"sectors": rem["sectors"], "scheme": rem["scheme"]} if changed else None
            if seats is not None and rem["free"] > len(seats):
                summ = {**(summ or {}), "admission_free": rem["free"] - len(seats)}
            res = store.record(cur, p["id"], now, free=free, by_price=rem["by_price"], total=total or p["ext"].get("total"),
                               seats=seats if seats is not None else None, hidden=rem["hidden"], summary=summ, raw_ref=ref, gross=g)
            p["ext"].update(sid=eid, domain=domain, by_price=rem["by_price"], free=free if seats is not None else p["ext"].get("free", free), seen=True,
                            total=total or p["ext"].get("total"))
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


def kassir_priority(r, yandex_closed: bool = False) -> str:
    """need — опросить; check — недельная проверка «общий ли запас с Яндексом»; shared — хватает Яндекса; wait — ждём Яндекс.
    Яндекс закрыл доступ — его снимков нет, Кассир опрашивает и общие запасы (в пределах своего лимита)."""
    has_yandex, ext, y_nt, y_measured = r[8], r[9] or {}, r[10], r[11]
    if not has_yandex or y_nt or yandex_closed:
        return "need"
    if not y_measured:
        return "wait"
    fresh = ext.get("shared_at", "") > (datetime.now() - store.SHARED_RECHECK).isoformat()
    if fresh:
        return "shared" if ext.get("shared") else "need"   # запас поделён — нужны обе кассы
    return "check"


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
    cur.execute(WORK_SQL, {"cities": cities, "horizon": HORIZON_DAYS})
    rows = cur.fetchall()
    cur.execute(USED_SQL)
    used = dict(cur.fetchall())
    conn.commit()  # не держать транзакцию весь прогон: иначе ALTER / TRUNCATE ждут, а за ними встаёт и сбор
    work = {"yandex": [r for r in rows if r[5] == "yandex"], "kassir": [(r, kassir_priority(r, blocks.state("yandex/sales") != "ok")) for r in rows if r[5] == "kassir"]}
    # Кассир: сначала то, где без него нельзя (только Кассир, Яндекс сам не продаёт, запас поделён), потом недельная проверка
    # «общий ли запас», последними — пропуски без запросов
    order = {"need": 0, "check": 1, "shared": 2, "wait": 3}
    work["kassir"].sort(key=lambda x: order[x[1]])
    if a.limit:
        work = {k: v[:a.limit] for k, v in work.items()}
    stats: Counter = Counter()
    runs_left = 24 - datetime.now().hour   # прогон раз в час: остаток суточного лимита — поровну на оставшиеся
    caps = {op: max(0, math.ceil((BUDGET[op] - int(used.get(op) or 0)) / runs_left)) for op in work}
    closed = {}
    for op in work:
        if blocks.state("%s/sales" % op) == "blocked":   # сайт закрыл доступ — ни одного запроса до срока
            closed[op] = blocks.until("%s/sales" % op)
            stats["%s: сайт закрыл доступ — пропуск до %s" % ("яндекс" if op == "yandex" else "кассир", closed[op][:16])] += 1
            work[op] = []
    nets = {op: Net(op, deadline, cap=caps[op]) for op in work}
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
                     int(op in closed or nets[op].why in ("отказ", "предохранитель")), _summary(op, work, nets, caps, closed, took),
                     Json({"сбор": mine, "запросы": net_stats, "лимит": caps[op], "закрыт до": closed.get(op) or blocks.until("%s/sales" % op)})))
    conn.commit()
    print("Сбор продаж: %d с, в очереди: Яндекс %d, Кассир %d; общий запас найден у %d" % (took, len(work["yandex"]), len(work["kassir"]), shared))
    for k, v in sorted(stats.items()):
        print("  %s: %s" % (k, v))
    for op in nets:
        print("  запросы %s (лимит прогона %d): %s%s" % (op, caps[op], dict(nets[op].stats), " — " + _summary(op, work, nets, caps, closed, took)))


def _summary(op: str, work: dict, nets: dict, caps: dict, closed: dict, took: int) -> str:
    """Строка прогона для журнала и экрана «Билетные операторы»."""
    if op in closed:
        return "сайт закрыл доступ серверу — не опрашивается до %s" % closed[op][:16].replace("T", " ")
    n = nets[op]
    tail = {"отказ": "сайт отказал (403 / капча) — закрыт до %s" % (blocks.until(n.channel) or "")[:16].replace("T", " "),
            "предохранитель": "остановлен «предохранителем» (ошибки сайта)",
            "лимит": "достигнут лимит прогона (%d запросов)" % caps[op]}.get(n.why, "")
    return "в очереди %d, запросов %d, за %d с%s" % (len(work[op]), n.sent, took, " · " + tail if tail else "")


if __name__ == "__main__":
    main()
