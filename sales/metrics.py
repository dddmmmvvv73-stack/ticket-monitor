"""
Цифры сеанса по схеме мест (DATA_MODEL.md, 3.9): вал — выставленные места × цена без сервисного сбора;
занятым местам — цена ближайшего свободного соседа по ряду; диапазон — от самой низкой до самой высокой цены
ряда (ряд целиком занят — по всему залу); доля точных — сколько вала по ценам свободных мест.
"""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median


def _num(place: str, fallback: int) -> float:
    m = re.match(r"\d+", str(place or ""))
    return float(m.group()) if m else float(fallback)


def gross(all_keys: list[str], free: dict) -> dict | None:
    """all_keys — все места («зона|ряд|место»), free — свободные {место: цена}. None — свободных с ценой нет."""
    prices_all = [p for p in free.values() if p]
    if not prices_all:
        return None
    rows: dict[str, list] = defaultdict(list)
    for i, k in enumerate(all_keys):
        row, _, place = k.rpartition("|")
        rows[row].append((_num(place, i), k))
    exact = lo = hi = est = 0.0
    g_med, g_lo, g_hi = median(prices_all), min(prices_all), max(prices_all)
    for row, seats in rows.items():
        known = [(n, free[k]) for n, k in seats if free.get(k)]
        rp = [p for _, p in known]
        for n, k in seats:
            p = free.get(k)
            if p:
                exact += p
                continue
            if known:
                e = min(known, key=lambda x: abs(x[0] - n))[1]
                est, lo, hi = est + e, lo + min(rp), hi + max(rp)
            else:
                est, lo, hi = est + g_med, lo + g_lo, hi + g_hi
    total = exact + est
    return {"gross": round(total), "gross_lo": round(exact + lo), "gross_hi": round(exact + hi),
            "exact_share": round(exact / total, 3) if total else None, "exposed": len(all_keys)}
