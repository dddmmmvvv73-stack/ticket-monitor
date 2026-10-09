"""
Архив для прототипа: прошедшие и снятые с продажи сеансы за период (все города или один) — из базы, с итогом сеанса.

    python3 -m sales.history 2026-10-01 2026-10-31 [Рязань]     # JSON в stdout (ноутбук спрашивает сервер по SSH)

Строка — те же поля, что у строки «Мероприятий» в прототипе (сокращённые имена — см. ROW), итог — sessions.result
(sales.results): «s» — строка самой полной кассы в том же виде, что сводка продаж, «st» — прошло / снято до даты.
Сеанс, у которого итог ещё не зафиксирован (дата прошла меньше часа назад), отдаётся без «s».
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

from db import connect

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_DAYS = 400   # не больше года с небольшим за раз — страница грузит выбранный период целиком

SQL = """
SELECT c.name, v.name, coalesce(s.title, p.title), s.local_date, s.local_time, s.sphere, s.format, s.genre, s.pushkin, s.age,
       s.tour, s.tour_why, s.status, s.first_seen, s.result,
       array_agg(l.operator_id ORDER BY l.operator_id), array_agg(l.ext_key ORDER BY l.operator_id), array_agg(l.url ORDER BY l.operator_id),
       min(l.price_min), max(l.price_max), max(l.organizer)
  FROM sessions s
  JOIN venues v ON v.id = s.venue_id
  JOIN cities c ON c.id = v.city_id
  LEFT JOIN projects p ON p.id = s.project_id
  LEFT JOIN listings l ON l.session_id = s.id
 WHERE s.local_date BETWEEN %(frm)s AND %(to)s
   AND (s.local_date < current_date OR s.status IN ('done', 'removed', 'cancelled'))
   AND (%(city)s = '' OR c.name = %(city)s)
 GROUP BY s.id, c.name, v.name, p.title
 ORDER BY s.local_date, s.local_time NULLS LAST, c.name
"""
NOT_DIRECT = {"kassir", "yandex", "qtickets", "custom"}   # остальные операторы — кассы и сайты площадок прямого сбора (ОрелКонцерт и др.)
MARKET_SRC = (("kassir", "k"), ("yandex", "y"), ("qtickets", "q"))   # сайты афиши рынка → буквы источника, как в market-data.js


def rows(conn, frm: str, to: str, city: str = "") -> list[dict]:
    if not (ISO.match(frm) and ISO.match(to)) or frm > to:
        raise ValueError("период — две даты ГГГГ-ММ-ДД, начало не позже конца")
    if (date.fromisoformat(to) - date.fromisoformat(frm)).days > MAX_DAYS:
        raise ValueError(f"период — не больше {MAX_DAYS} дней")
    cur = conn.cursor()
    cur.execute(SQL, {"frm": frm, "to": to, "city": city or ""})
    out = []
    for (city_, venue, title, d, t, sphere, fmt, genre, pushkin, age, tour, why, status, first, result,
         ops, keys, urls, pmin, pmax, org) in cur.fetchall():
        ops = [o for o in ops if o]
        has = set(ops)
        direct = [(o, u) for o, u in zip(ops, urls) if o not in NOT_DIRECT]
        src = "d" if direct else "".join(c for o, c in MARKET_SRC if o in has)
        r = {"c": city_, "v": venue, "t": title or "", "d": d.isoformat(), "tm": t.strftime("%H:%M") if t else "",
             "sp": sphere or "", "f": fmt or "", "g": genre or "", "pn": int(pmin) if pmin else 0, "px": int(pmax) if pmax else 0,
             "pu": 1 if pushkin else 0, "src": src, "seen": first.isoformat() if first else "", "age": age or "",
             "tour": tour or "", "why": why or "", "org": org or "",
             "keys": [k for k in keys if k], "st": (result or {}).get("st") or ("gone" if status in ("removed", "cancelled") else "past")}
        if direct:   # касса прямого сбора — для подписи в «Источнике» и фильтра (прототип, DIRECT_OPS)
            r["dop"] = direct[0][0]
            if direct[0][1]:
                r["ud"] = direct[0][1]
        for o, u in zip(ops, urls):
            if u and o == "kassir":
                r["uk"] = u
            elif u and o == "yandex":
                r["uy"] = u
            elif u and o == "qtickets":
                r["uq"] = u
        if result and result.get("best"):
            r["s"] = result["pools"][result["best"]]
            r["np"] = len(result["pools"])     # сколько касс видели
        out.append(r)
    return out


def main() -> None:
    args = sys.argv[1:]
    if len(args) not in (2, 3):
        sys.exit("python3 -m sales.history ГГГГ-ММ-ДД ГГГГ-ММ-ДД [город]")
    conn = connect.connect()
    try:
        json.dump(rows(conn, args[0], args[1], args[2] if len(args) == 3 else ""), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
