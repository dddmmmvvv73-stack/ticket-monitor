"""
Вал и выручка по схеме зала vladimirkoncert.ru.

Схема зала на странице сеанса содержит ВСЕ места:
  свободное — <a data-id="…" style="left:Xpx; top:Ypx" value="цена"> + «Ряд: N Место: M»
  занятое   — <span data-id="…" class="nonfree-place" style="left:Xpx; top:Ypx">M</span>
У занятых нет ни ряда, ни цены. Их восстанавливаем так:
  ряд   — по координате Y (все места одного ряда стоят на одной высоте);
  зона  — ряды, разделённые большим промежутком по Y (партер / амфитеатр / балкон);
  цена  — уровни точности, от лучшего к худшему:
            exact    место видели свободным в прошлых сборах — цена известна точно
            row      в этом ряду есть свободные места — цена ряда (цены идут по рядам)
            neighbor ближайший по высоте ряд той же зоны с известной ценой
            zone     средняя цена зоны

Три цифры по событию:
  вал                    — все продаваемые места × цена (бронь площадки не входит)
  выручка (оценка)       — занятые продаваемые места × цена; оценка сверху:
                           «занято» включает пригласительные и квоты других касс
  подтверждённые продажи — место было свободно в прошлом сборе и стало занятым;
                           точная цифра, но только с начала слежения

Бронь площадки:
  авто   — места (зона|ряд|место), занятые во ВСЕХ событиях одного зала, где они
           встречаются (минимум 3 события): так себя ведут служебные места и
           закрытые квоты, а не продажи. Зал = группа похожих рассадок площадки.
  ручная — ряды, отмеченные в интерфейсе (config/hall_reserve.json).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from statistics import median

MIN_EVENTS_FOR_AUTO_RESERVE = 3
EXACT_LEVELS = ("exact", "row")  # уровни, которые считаем «точными» для процента точности


# ---------------------------------------------------------------- разбор схемы

def parse_seats(page: str) -> list[dict]:
    """Все места схемы: id, x, y, номер места, ряд (если виден), цена (у свободных), taken."""
    seats = []
    row_labels: dict[int, str] = {}
    for _tag, attrs, seat_id, inner in re.findall(
            r'<(a|span)\s([^>]*data-id="(-?\d+)"[^>]*)>(.*?)</\1>', page, re.S):
        x = re.search(r"left:\s*(\d+)", attrs)
        y = re.search(r"top:\s*(\d+)", attrs)
        if not (x and y):
            continue
        number = re.sub(r"<.*", "", inner, flags=re.S).strip()
        if "place-row-label" in attrs:
            row_labels.setdefault(int(y.group(1)), number)
            continue
        if 'data-content="seat"' not in attrs:
            continue
        taken = "nonfree-place" in attrs
        value = re.search(r'value="(\d+)"', attrs)
        price = int(value.group(1)) if value and not taken else None
        price = price or None  # value="0" — цены нет
        popup_row = re.search(r"Ряд:\s*([^<]+)</p>", inner)
        seats.append({
            "id": seat_id, "x": int(x.group(1)), "y": int(y.group(1)),
            "place": number, "row": popup_row.group(1).strip() if popup_row else None,
            "price": price, "taken": taken,
        })
    for seat in seats:
        if not seat["row"]:
            seat["row"] = row_labels.get(seat["y"], "?")
    _assign_zones(seats)
    normalize(seats)
    return seats


def normalize(seats: list[dict]) -> None:
    """
    Координаты отсчитываем от левого верхнего места. На концертах над креслами
    рисуется танцпол разного размера, и та же рассадка «съезжает» вниз — без
    нормировки один зал выглядел бы как несколько разных.
    """
    if not seats:
        return
    min_x = min(s["x"] for s in seats)
    min_y = min(s["y"] for s in seats)
    for seat in seats:
        seat["x"] -= min_x
        seat["y"] -= min_y


def _assign_zones(seats: list[dict]) -> None:
    """Зона = группа рядов без большого разрыва по высоте (партер / амфитеатр / балкон)."""
    ys = sorted({s["y"] for s in seats})
    if not ys:
        return
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    typical = median(gaps) if gaps else 0
    zone, zone_of = 1, {ys[0]: 1}
    for prev, cur in zip(ys, ys[1:]):
        if typical and cur - prev > typical * 2:
            zone += 1
        zone_of[cur] = zone
    for seat in seats:
        seat["zone"] = zone_of[seat["y"]]


def seat_key(seat: dict) -> str:
    """
    Место в зале так, как его назвал бы зритель: зона | ряд | место. В отличие от
    пиксельных координат (они «плавают» на 1px между схемами и сдвигаются из-за
    танцпола), это одинаково во всех мероприятиях зала.
    """
    return f"{seat['zone']}|{seat['row']}|{seat.get('place') or '?'}"


def layout_signature(seats: list[dict]) -> str:
    """Отпечаток рассадки: одинаковый набор мест (зона|ряд|место) = та же рассадка."""
    keys = ",".join(sorted(seat_key(s) for s in seats))
    return hashlib.sha1(keys.encode()).hexdigest()[:12]


def row_key(seat: dict) -> str:
    return f"{seat['zone']}|{seat['row']}"


def describe_rows(seats: list[dict]) -> list[dict]:
    """Ряды зала для интерфейса ручной брони: ключ, подпись, число мест."""
    by_row: dict[str, list[dict]] = defaultdict(list)
    for seat in seats:
        by_row[row_key(seat)].append(seat)
    zone_rows: dict[int, list[str]] = defaultdict(list)
    for seat in sorted(seats, key=lambda s: s["y"]):
        if seat["row"] not in zone_rows[seat["zone"]]:
            zone_rows[seat["zone"]].append(seat["row"])
    result = []
    for key, row_seats in sorted(by_row.items(), key=lambda kv: kv[1][0]["y"]):
        zone = row_seats[0]["zone"]
        rows = zone_rows[zone]
        result.append({
            "key": key, "seats": len(row_seats),
            "label": f"Зона {zone} (ряды {rows[0]}–{rows[-1]}) · ряд {row_seats[0]['row']}",
        })
    return result


# ---------------------------------------------------------------- цены мест

def price_seats(seats: list[dict], registry: dict[str, int]) -> None:
    """Проставляет каждому месту seat['est_price'] и seat['level'] (на месте)."""
    row_price: dict[int, int] = {}
    by_y: dict[int, list[int]] = defaultdict(list)
    for seat in seats:
        if seat["price"]:
            by_y[seat["y"]].append(seat["price"])
    for y, prices in by_y.items():
        row_price[y] = Counter(prices).most_common(1)[0][0]

    zone_prices: dict[int, list[int]] = defaultdict(list)
    for seat in seats:
        if seat["y"] in row_price:
            zone_prices[seat["zone"]].append(row_price[seat["y"]])

    known_rows_by_zone: dict[int, list[int]] = defaultdict(list)
    for y in row_price:
        zone = next(s["zone"] for s in seats if s["y"] == y)
        known_rows_by_zone[zone].append(y)

    for seat in seats:
        if seat["price"]:
            seat["est_price"], seat["level"] = seat["price"], "exact"
        elif seat["id"] in registry:
            seat["est_price"], seat["level"] = registry[seat["id"]], "exact"
        elif seat["y"] in row_price:
            seat["est_price"], seat["level"] = row_price[seat["y"]], "row"
        elif known_rows_by_zone.get(seat["zone"]):
            nearest = min(known_rows_by_zone[seat["zone"]], key=lambda y: abs(y - seat["y"]))
            seat["est_price"], seat["level"] = row_price[nearest], "neighbor"
        elif zone_prices.get(seat["zone"]) or row_price:
            pool = zone_prices.get(seat["zone"]) or list(row_price.values())
            seat["est_price"], seat["level"] = round(sum(pool) / len(pool)), "zone"
        else:
            seat["est_price"], seat["level"] = None, "none"


# ---------------------------------------------------------------- состояние между сборами

# «Весь зал разом занят» — не продажи: сбой сайта, ночное закрытие продаж или снятый сеанс (CAGMO в Арт Холле
# заменил программы 26.12 и 06.02 — старые сеансы закрылись целиком). Признак: за один сбор недоступны стали
# ≥ 90% мест, свободных в прошлый раз, и таких мест не меньше 20.
FLIP_SHARE = 0.9
FLIP_MIN_SEATS = 20


def is_flip(free_before: int, became_taken: int) -> bool:
    return free_before >= FLIP_MIN_SEATS and became_taken >= FLIP_SHARE * free_before


def update_state(state: dict, seats: list[dict], now_iso: str) -> dict:
    """
    state (на событие): {
      registry:  {seat_id: цена}      — цены всех мест, когда-либо виденных свободными
      last_free: [seat_id]            — свободные места прошлого нормального сбора
      sold:      {seat_id: {price, ts}} — подтверждённые продажи
      returned:  число возвратов (место снова стало свободным)
      suspect:   {since, last, free_before, free_now} — сейчас «весь зал занят» (см. is_flip)
    }
    Возвращает обновлённый state; подтверждённые продажи — переход свободно → занято.
    «Весь зал занят» продажами не считается: state остаётся как после прошлого нормального
    сбора (следующий сбор сравнивается с ним), отмечается только suspect.
    """
    registry = dict(state.get("registry", {}))
    last_free = set(state.get("last_free", []))
    sold = dict(state.get("sold", {}))
    returned = state.get("returned", 0)
    first_snapshot = "last_free" not in state

    if not first_snapshot:
        free_ids = {seat["id"] for seat in seats if not seat["taken"]}
        became_taken = len(last_free - free_ids - set(sold))
        if is_flip(len(last_free - set(sold)), became_taken):
            suspect = dict(state.get("suspect") or {"since": now_iso, "free_before": len(last_free)})
            suspect.update(last=now_iso, free_now=len(free_ids))
            return {**{k: v for k, v in state.items() if k not in ("seats", "layout")}, "suspect": suspect}

    free_now = set()
    for seat in seats:
        if seat["taken"]:
            if not first_snapshot and seat["id"] in last_free and seat["id"] not in sold:
                sold[seat["id"]] = {"price": registry.get(seat["id"]), "ts": now_iso}
        else:
            free_now.add(seat["id"])
            registry[seat["id"]] = seat["price"]
            if seat["id"] in sold:  # возврат или снятие брони
                sold.pop(seat["id"])
                returned += 1

    return {
        "registry": registry,
        "last_free": sorted(free_now),
        "sold": sold,
        "returned": returned,
        "tracking_since": state.get("tracking_since", now_iso),
        **({"flips_repaired": state["flips_repaired"]} if "flips_repaired" in state else {}),
    }


def repair_flips(state: dict, history: list[dict]) -> dict:
    """
    Разовая починка состояний, записанных до правила is_flip (меняет state и history на месте):
    точки истории «весь зал занят» помечаются anomaly (продажи в них — как в прошлой нормальной точке);
    ложные продажи такого сбора убираются, если зал так и остался закрыт (места снова считаются
    свободными прошлого нормального сбора), или переносятся на время возврата зала — это настоящие
    продажи за тот промежуток; «возвраты» после возврата зала вычитаются. Возвращает отчёт.
    """
    report = {"anomalies": 0, "removed": 0, "moved": 0, "returned_fixed": 0}
    sold = state.get("sold", {})
    normal = None  # последняя нормальная точка
    for i, p in enumerate(history):
        if normal is None or p.get("seats_free") is None:
            normal = p if p.get("seats_free") is not None else normal
            continue
        free_before = normal.get("seats_free") or 0
        if not (free_before >= FLIP_MIN_SEATS and p["seats_free"] <= (1 - FLIP_SHARE) * free_before):
            normal = p
            continue
        report["anomalies"] += 1
        raw_sold = p.get("sold_confirmed")
        p["anomaly"] = True
        p["sold_confirmed"], p["revenue_confirmed"] = normal.get("sold_confirmed"), normal.get("revenue_confirmed")
        back = next((q for q in history[i + 1:] if q.get("seats_free") is not None
                     and q["seats_free"] > (1 - FLIP_SHARE) * free_before), None)
        fake = [s for s, sale in sold.items() if sale.get("ts") == p["ts"]]
        if back is None:  # зал так и остался закрыт — продаж не было
            for s in fake:
                sold.pop(s)
            state["last_free"] = sorted(set(state.get("last_free", [])) | set(fake))
            state["suspect"] = {"since": p["ts"], "last": history[-1]["ts"], "free_before": free_before,
                                "free_now": p["seats_free"]}
            report["removed"] += len(fake)
        else:  # зал вернулся: оставшиеся занятыми — продажи за промежуток, по времени возврата
            for s in fake:
                sold[s]["ts"] = back["ts"]
            report["moved"] += len(fake)
            if raw_sold is not None and back.get("sold_confirmed") is not None:
                fixed = min(state.get("returned", 0), max(0, raw_sold - back["sold_confirmed"]))
                state["returned"] = state.get("returned", 0) - fixed
                report["returned_fixed"] += fixed
    state["sold"] = sold
    state["flips_repaired"] = 1
    return report


# ---------------------------------------------------------------- бронь зала

SAME_HALL_SIMILARITY = 0.8  # доля общих мест, при которой две рассадки считаются одним залом


def group_layouts(layouts: dict[str, set]) -> list[list[str]]:
    """
    Рассадка одного зала слегка меняется от события к событию (787 / 807 / 809 мест:
    добавили приставные, убрали ряд под пульт). Объединяем рассадки, совпадающие
    по координатам мест хотя бы на 80%. Разные залы площадки (большой и малый)
    почти не пересекаются и остаются отдельными.
    """
    parent = {k: k for k in layouts}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    keys = sorted(layouts)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            union = len(layouts[a] | layouts[b])
            if union and len(layouts[a] & layouts[b]) / union >= SAME_HALL_SIMILARITY:
                parent[find(a)] = find(b)

    groups: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    return list(groups.values())


def auto_reserve(events_seats: list[tuple[set, set]]) -> set:
    """
    events_seats: [(все места события, занятые места события)] — ключи seat_key.
    Бронь — место, которое встречается минимум в 3 событиях зала и занято во всех
    из них. Одинаковые места, занятые во всех датах, — это служебные места или
    закрытая квота, а не продажи.
    """
    present, taken = Counter(), Counter()
    for all_seats, taken_seats in events_seats:
        present.update(all_seats)
        taken.update(taken_seats)
    return {xy for xy, n in present.items() if n >= MIN_EVENTS_FOR_AUTO_RESERVE and taken[xy] == n}


# ---------------------------------------------------------------- итог по событию

def compute_money(seats: list[dict], reserve: set, manual_rows: set, state: dict) -> dict:
    sellable = [s for s in seats if seat_key(s) not in reserve and row_key(s) not in manual_rows]
    taken = [s for s in sellable if s["taken"]]
    priced = [s for s in sellable if s["est_price"]]
    priced_taken = [s for s in taken if s["est_price"]]

    gross = sum(s["est_price"] for s in priced)
    revenue = sum(s["est_price"] for s in priced_taken)
    exact_share = (sum(1 for s in sellable if s["level"] in EXACT_LEVELS) / len(sellable)) if sellable else 0

    confirmed = [v for v in state.get("sold", {}).values()]
    return {
        "seats_sellable": len(sellable),
        "seats_taken_sellable": len(taken),
        "reserve_seats": len(seats) - len(sellable),
        "gross": gross if priced else None,
        "revenue_est": revenue if priced else None,
        "avg_price_taken": round(revenue / len(priced_taken)) if priced_taken else None,
        "gross_confidence": round(exact_share, 3),
        "sold_confirmed": len(confirmed),
        "revenue_confirmed": sum(v["price"] or 0 for v in confirmed),
        "tracking_since": state.get("tracking_since"),
    }
