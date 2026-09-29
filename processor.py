"""
Обработчик снимков.

На входе: сырой JSON hallplan/async (сегодняшний) + сохранённое состояние
с прошлого запуска (какие места были свободны и почём).

На выходе: дневная запись со всеми метриками, которые обсуждали:
  - продано сегодня / вал за сегодня
  - накопленный вал с начала слежения
  - сколько мест всего было в продаже (с поправкой на резерв площадки)
  - обнаружение новых скидок (price != originalPrice)
  - карта цен по рядам (диапазоны)
  - % распроданности по ряду (покупательский паттерн)

Плюс обновлённое состояние seats_state для следующего запуска.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from gross_potential import (
    update_registry,
    compute_gross_and_revenue_with_geometry,
    compute_gross_and_revenue_without_geometry,
    infer_price_for_seat,
)


def _price_rub(price_info: dict | None) -> float | None:
    if not price_info:
        return None
    value = price_info.get("price", {}).get("value")
    return value / 100 if value is not None else None


def _original_price_rub(seat_wrapper: dict) -> float | None:
    return _price_rub(seat_wrapper.get("originalPrice"))


def extract_current_free_seats(raw: dict) -> dict[str, dict]:
    """
    Разворачивает сырой JSON в плоский словарь:
    seat_id -> {row, place, level, price, original_price, admission}

    Места с admission=True (входные пропуска без своего кресла, например
    Meet & Greet) исключаются — это не полноценное место в зале.
    """
    hallplan = raw.get("result", {}).get("hallplan", {})
    flat: dict[str, dict] = {}

    for level in hallplan.get("levels", []):
        level_name = level.get("name")
        for seat_wrapper in level.get("seats", []):
            seat = seat_wrapper.get("seat", {})
            if seat_wrapper.get("admission"):
                continue  # не место в зале, а входной пропуск

            seat_id = seat_wrapper.get("sourceSeatId") or f'{level_name}-{seat.get("row")}-{seat.get("place")}'
            flat[seat_id] = {
                "row": seat.get("row"),
                "place": seat.get("place"),
                "level": level_name,
                "price": _price_rub(seat_wrapper.get("priceInfo")),
                "original_price": _original_price_rub(seat_wrapper),
            }

    return flat


def apply_exclusions(free_seats: dict[str, dict], exclusions: dict) -> dict[str, dict]:
    """
    Убирает из списка места, которые площадка сознательно не продаёт онлайн:
    - по конкретным id мест (excluded_seat_ids)
    - по целым рядам, например "административный ряд" (excluded_rows —
      список {"level": ..., "row": ...})
    """
    excluded_ids = set(exclusions.get("excluded_seat_ids", []))
    excluded_rows = {
        (r.get("level"), str(r.get("row")))
        for r in exclusions.get("excluded_rows", [])
    }

    if not excluded_ids and not excluded_rows:
        return free_seats

    result = {}
    for sid, info in free_seats.items():
        if sid in excluded_ids:
            continue
        if (info.get("level"), str(info.get("row"))) in excluded_rows:
            continue
        result[sid] = info
    return result


def total_seats_from_levels(hallplan: dict) -> int:
    """
    Считает вместимость только тех секций, которые реально участвуют
    в онлайн-продаже через этот виджет (были в hallplan.levels[]).

    Это НЕ то же самое, что hallplan.totalSeatCount — то поле отражает
    вместимость всего физического зала, включая секции вроде балкона
    или боковых мест, которые иногда вообще не продаются через
    конкретный онлайн-канал (тогда их не будет и в levels[] — ни
    свободными, ни проданными, их просто нет в структуре ответа).
    """
    total = 0
    for level in hallplan.get("levels", []):
        for row in level.get("rows", []):
            total += row.get("seatCount", 0)
    return total


def rows_capacity_from_levels(hallplan: dict) -> dict[str, dict[str, int]]:
    """То же самое, но по каждому ряду отдельно: {level: {row: вместимость}}."""
    result: dict[str, dict[str, int]] = {}
    for level in hallplan.get("levels", []):
        level_name = level.get("name")
        rows = {}
        for row in level.get("rows", []):
            rows[str(row.get("row"))] = row.get("seatCount", 0)
        result[level_name] = rows
    return result


def process_snapshot(
    raw: dict,
    previous_state: dict[str, Any] | None,
    exclusions: dict,
    tracking_start_date: str,
    geometry: dict | None = None,
) -> tuple[dict, dict]:
    """
    Возвращает (daily_record, new_state).

    geometry — распарсенная статическая геометрия зала (geometry.parse_geometry),
    нужна только для расчёта "вала". Если None — вал не считается, только выручка.
    """
    hallplan = raw.get("result", {}).get("hallplan", {})
    now = datetime.now()
    today = date.today().isoformat()

    free_seats = extract_current_free_seats(raw)
    free_seats = apply_exclusions(free_seats, exclusions)
    free_ids_today = set(free_seats.keys())

    total_seat_count = hallplan.get("totalSeatCount", 0)  # весь физический зал (диагностика, не используем для вала)
    total_syndicated = total_seats_from_levels(hallplan)   # только секции, реально участвующие в онлайн-продаже
    reserved = exclusions.get("reserved_seats_count", 0)
    sellable_total = max(total_syndicated - reserved, 0)
    sellable_available = len(free_ids_today)
    sellable_sold_cumulative = max(sellable_total - sellable_available, 0)

    # --- Сравнение с прошлым снимком (это "продажи/динамика" — со вчера/с последней проверки) ---
    prev_free_map = (previous_state or {}).get("free_seats", {})
    prev_free_ids = set(prev_free_map.keys())

    sold_today_ids = prev_free_ids - free_ids_today
    revenue_today = 0.0
    sold_today_details = []
    for sid in sold_today_ids:
        info = prev_free_map[sid]
        price = info.get("price") or 0
        revenue_today += price
        sold_today_details.append({
            "seat_id": sid, "row": info.get("row"), "place": info.get("place"),
            "level": info.get("level"), "price": price,
        })

    # --- Обнаружение скидок (цена ушла ниже original) ---
    discounts_detected = []
    for sid, info in free_seats.items():
        price = info.get("price")
        original = info.get("original_price")
        if price is not None and original is not None and price < original:
            discounts_detected.append({
                "seat_id": sid, "row": info.get("row"), "place": info.get("place"),
                "level": info.get("level"), "price": price, "original_price": original,
            })

    # --- Реестр цен: пополняем постоянную память о ценах ДО расчёта вала/выручки ---
    seat_price_registry = (previous_state or {}).get("seat_price_registry", {})
    seat_price_registry = update_registry(dict(seat_price_registry), free_seats)

    # --- Карта цен по рядам (диапазоны ценообразования) ---
    # Если есть геометрия — используем полный список мест ряда (включая
    # уже проданные, цена которых выведена по соседям), иначе — только
    # то, что видно свободным сейчас (более бедный, но всё же рабочий вариант).
    price_map_by_row: dict[str, list[float]] = {}
    if geometry:
        for level_name, rows in geometry.items():
            for row, places_list in rows.items():
                key = f'{level_name} / ряд {row}'
                prices = set()
                for place in places_list:
                    price, _ = infer_price_for_seat(
                        level_name, row, place, places_list, seat_price_registry, rows
                    )
                    if price is not None:
                        prices.add(price)
                if prices:
                    price_map_by_row[key] = sorted(prices)
    else:
        tmp: dict[str, set] = defaultdict(set)
        for info in free_seats.values():
            key = f'{info.get("level")} / ряд {info.get("row")}'
            if info.get("price") is not None:
                tmp[key].add(info["price"])
        price_map_by_row = {k: sorted(v) for k, v in tmp.items()}

    # --- Паттерн распроданности по ряду (относительно первого снимка) ---
    baseline_by_row = (previous_state or {}).get("baseline_by_row")
    if baseline_by_row is None:
        # первый запуск — сегодняшний снимок и есть точка отсчёта
        baseline_by_row = defaultdict(int)
        for info in free_seats.values():
            key = f'{info.get("level")} / ряд {info.get("row")}'
            baseline_by_row[key] += 1
        baseline_by_row = dict(baseline_by_row)

    current_free_by_row_str: dict[str, int] = defaultdict(int)     # "Уровень / ряд X" -> кол-во свободно (для паттерна)
    current_free_by_row_tuple: dict[tuple, int] = defaultdict(int)  # (Уровень, ряд) -> кол-во свободно (для резервного расчёта)
    for info in free_seats.values():
        level, row = info.get("level"), str(info.get("row"))
        current_free_by_row_str[f'{level} / ряд {row}'] += 1
        current_free_by_row_tuple[(level, row)] += 1

    sold_share_by_row = {}
    for key, baseline in baseline_by_row.items():
        if baseline <= 0:
            continue
        still_free = current_free_by_row_str.get(key, 0)
        sold_share_by_row[key] = round(1 - (still_free / baseline), 3)

    # --- Операторы, продающие событие (в рамках этого виджета) ---
    operators = [s.get("serviceName") for s in hallplan.get("sessionServices", [])]

    # --- Вал и выручка: точный расчёт по местам (если есть геометрия),
    # иначе резервный расчёт по ряду целиком ---
    if geometry:
        money = compute_gross_and_revenue_with_geometry(
            geometry, seat_price_registry, free_seats, exclusions
        )
    else:
        rows_capacity = rows_capacity_from_levels(hallplan)
        money = compute_gross_and_revenue_without_geometry(
            rows_capacity, current_free_by_row_tuple, seat_price_registry, exclusions
        )

    revenue_actual = money["revenue_actual"]

    daily_record = {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": today,
        "tracking_start_date": tracking_start_date,
        "sale_status": raw.get("result", {}).get("saleStatus"),
        "total_seat_count_venue": total_seat_count,
        "total_seat_count_syndicated": total_syndicated,
        "sellable_total": sellable_total,
        "sellable_available": sellable_available,
        "sellable_sold_cumulative": sellable_sold_cumulative,
        "sold_today_count": len(sold_today_ids),
        "revenue_today": round(revenue_today, 2),
        "revenue_actual": revenue_actual,
        "revenue_confidence_ratio": money["revenue_confidence_ratio"],
        "gross_total": money["gross_total"],
        "gross_confidence_ratio": money["gross_confidence_ratio"],
        "gross_by_row": money["gross_by_row"],
        "gross_method": "geometry" if geometry else "row_fallback",
        "sold_today_details": sold_today_details,
        "discounts_detected": discounts_detected,
        "price_map_by_row": price_map_by_row,
        "sold_share_by_row": sold_share_by_row,
        "operators": operators,
    }

    new_state = {
        "free_seats": free_seats,
        "baseline_by_row": baseline_by_row,
        "seat_price_registry": seat_price_registry,
    }

    return daily_record, new_state
