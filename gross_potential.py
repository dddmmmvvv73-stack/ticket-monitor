"""
Расчёт "вала" (максимум при полной распродаже) и "выручки" (уже полученные
деньги) — двумя способами в зависимости от того, что доступно:

1. С геометрией (точный, по каждому месту). Уровни уверенности цены:
     exact        — место видели свободным хотя бы раз, цена известна напрямую
     neighbors    — не видели, но соседние места слева/справа в этом же
                    ряду известны и совпадают по цене
     vertical     — соседи по ряду не помогли, но то же место в соседнем
                    ряду сверху/снизу известно
     estimate     — настоящая граница ценовой зоны — пропорция по ряду,
                    а если и там пусто — по всему уровню

2. Без геометрии (резервный, по ряду целиком, без номеров мест):
     если в ряду видели только одну цену — считаем весь ряд по ней;
     если несколько разных — средневзвешенная по частоте (estimate);
     если ни одной — среднее по всему уровню (estimate).

И вал, и выручка считаются одной и той же функцией — разница только
в том, какие места входят в подсчёт (все места / только проданные).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from geometry import sorted_row_labels


def registry_key(level: str, row: str, place: int) -> str:
    return f"{level}|{row}|{place}"


def update_registry(registry: dict[str, float], free_seats: dict[str, dict]) -> dict[str, float]:
    """
    Пополняет постоянный реестр цен новыми наблюдениями из текущего снимка.
    Реестр никогда не уменьшается — однажды увиденная цена места запоминается
    навсегда, даже после того как место будет продано и исчезнет из free_seats.
    """
    for info in free_seats.values():
        if info.get("price") is None:
            continue
        try:
            place = int(info.get("place"))
        except (TypeError, ValueError):
            continue
        key = registry_key(info.get("level"), str(info.get("row")), place)
        registry[key] = info["price"]
    return registry


def _is_excluded(level: str, row: str, exclusions: dict) -> bool:
    excluded_rows = {
        (r.get("level"), str(r.get("row")))
        for r in exclusions.get("excluded_rows", [])
    }
    return (level, str(row)) in excluded_rows


# ---------------------------------------------------------------------------
# Способ 1: с геометрией — точный расчёт по каждому месту
# ---------------------------------------------------------------------------

def _nearest_known(places: list[int], place: int, known: dict[int, float], direction: str) -> float | None:
    idx = places.index(place) if place in places else None
    if idx is None:
        return None
    step = -1 if direction == "left" else 1
    i = idx + step
    while 0 <= i < len(places):
        if places[i] in known:
            return known[places[i]]
        i += step
    return None


def infer_price_for_seat(
    level: str, row: str, place: int,
    row_places: list[int],
    registry: dict[str, float],
    geometry_level: dict[str, list[int]],
) -> tuple[float | None, str]:
    """Возвращает (цена, метка_уверенности) для одного места."""

    exact_key = registry_key(level, row, place)
    if exact_key in registry:
        return registry[exact_key], "exact"

    known_in_row = {
        p: registry[registry_key(level, row, p)]
        for p in row_places if registry_key(level, row, p) in registry
    }

    left = _nearest_known(row_places, place, known_in_row, "left")
    right = _nearest_known(row_places, place, known_in_row, "right")
    if left is not None and right is not None and left == right:
        return left, "neighbors"

    row_labels = sorted_row_labels(geometry_level)
    if row in row_labels:
        idx = row_labels.index(row)
        vertical_prices = []
        for step in (-1, 1):
            j = idx + step
            while 0 <= j < len(row_labels):
                other_row = row_labels[j]
                if place in geometry_level.get(other_row, []):
                    k = registry_key(level, other_row, place)
                    if k in registry:
                        vertical_prices.append(registry[k])
                    break
                j += step
        if len(vertical_prices) == 2 and vertical_prices[0] == vertical_prices[1]:
            return vertical_prices[0], "vertical"
        if len(vertical_prices) == 1:
            return vertical_prices[0], "vertical"

    if known_in_row:
        counts = Counter(known_in_row.values())
        most_common_price = counts.most_common(1)[0][0]
        return most_common_price, "estimate"

    return None, "estimate"


def _compute_seat_level_summary(
    geometry: dict[str, dict[str, list[int]]],
    registry: dict[str, float],
    exclusions: dict,
    include_seat,  # функция (level, row, place) -> bool: включать ли место в сумму
) -> dict:
    total = 0.0
    total_seats = 0
    known_seats = 0
    per_row: dict[str, dict] = {}
    level_known_prices: dict[str, list[float]] = defaultdict(list)

    for level, rows in geometry.items():
        for row, places in rows.items():
            if _is_excluded(level, row, exclusions):
                continue
            for place in places:
                key = registry_key(level, row, place)
                if key in registry:
                    level_known_prices[level].append(registry[key])

    for level, rows in geometry.items():
        for row, places in rows.items():
            if _is_excluded(level, row, exclusions):
                continue
            row_key = f"{level} / ряд {row}"
            row_total = 0.0
            row_seat_count = 0
            row_confidences = []

            for place in places:
                if not include_seat(level, row, place):
                    continue

                price, confidence = infer_price_for_seat(level, row, place, places, registry, rows)

                if price is None:
                    if level_known_prices[level]:
                        price = sum(level_known_prices[level]) / len(level_known_prices[level])
                        confidence = "estimate"
                    else:
                        continue

                total_seats += 1
                row_seat_count += 1
                total += price
                row_total += price
                row_confidences.append(confidence)
                if confidence != "estimate":
                    known_seats += 1

            if row_seat_count:
                reliable_share = round(
                    sum(1 for c in row_confidences if c != "estimate") / len(row_confidences), 3
                )
                per_row[row_key] = {
                    "total": round(row_total, 2),
                    "seat_count": row_seat_count,
                    "reliable_share": reliable_share,
                }

    confidence_ratio = round(known_seats / total_seats, 3) if total_seats else 0.0
    return {
        "total": round(total, 2),
        "total_seats": total_seats,
        "confidence_ratio": confidence_ratio,
        "by_row": per_row,
    }


def _free_seat_keys(free_seats: dict[str, dict]) -> set[tuple[str, str, int]]:
    keys = set()
    for info in free_seats.values():
        try:
            place = int(info.get("place"))
        except (TypeError, ValueError):
            continue
        keys.add((info.get("level"), str(info.get("row")), place))
    return keys


def compute_gross_and_revenue_with_geometry(
    geometry: dict[str, dict[str, list[int]]],
    registry: dict[str, float],
    free_seats: dict[str, dict],
    exclusions: dict,
) -> dict:
    """Вал = все места. Выручка = только те места, которых сейчас нет среди свободных (то есть проданные)."""
    free_keys = _free_seat_keys(free_seats)

    gross = _compute_seat_level_summary(geometry, registry, exclusions, include_seat=lambda l, r, p: True)
    revenue = _compute_seat_level_summary(
        geometry, registry, exclusions,
        include_seat=lambda l, r, p: (l, str(r), p) not in free_keys,
    )

    return {
        "gross_total": gross["total"],
        "gross_confidence_ratio": gross["confidence_ratio"],
        "gross_by_row": gross["by_row"],
        "revenue_actual": revenue["total"],
        "revenue_confidence_ratio": revenue["confidence_ratio"],
    }


# ---------------------------------------------------------------------------
# Способ 2: без геометрии — резервный расчёт по ряду целиком
# ---------------------------------------------------------------------------

def _prices_by_row_from_registry(registry: dict[str, float]) -> dict[tuple[str, str], Counter]:
    result: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for key, price in registry.items():
        level, row, _place = key.split("|", 2)
        result[(level, row)][price] += 1
    return result


def compute_gross_and_revenue_without_geometry(
    rows_capacity: dict[str, dict[str, int]],   # {level: {row: физическая вместимость}}
    current_free_by_row: dict[tuple[str, str], int],  # {(level, row): сейчас свободно}
    registry: dict[str, float],
    exclusions: dict,
) -> dict:
    prices_by_row = _prices_by_row_from_registry(registry)
    level_known_prices: dict[str, list[float]] = defaultdict(list)
    for (level, _row), counter in prices_by_row.items():
        for price, count in counter.items():
            level_known_prices[level].extend([price] * count)

    gross_total = 0.0
    gross_seats = 0
    gross_known_seats = 0
    revenue_total = 0.0
    revenue_seats = 0
    revenue_known_seats = 0
    gross_by_row: dict[str, dict] = {}

    for level, rows in rows_capacity.items():
        for row, capacity in rows.items():
            if capacity <= 0 or _is_excluded(level, row, exclusions):
                continue

            counter = prices_by_row.get((level, row), Counter())
            free_count = current_free_by_row.get((level, row), 0)
            sold_count = max(capacity - free_count, 0)

            if len(counter) == 1:
                price = next(iter(counter))
                confident = True
            elif len(counter) > 1:
                total_occurrences = sum(counter.values())
                price = sum(p * c for p, c in counter.items()) / total_occurrences
                confident = False
            elif level_known_prices[level]:
                price = sum(level_known_prices[level]) / len(level_known_prices[level])
                confident = False
            else:
                continue  # вообще никаких данных по этому уровню — пропускаем ряд

            row_gross = capacity * price
            row_revenue = sold_count * price

            gross_total += row_gross
            revenue_total += row_revenue
            gross_seats += capacity
            revenue_seats += sold_count
            if confident:
                gross_known_seats += capacity
                revenue_known_seats += sold_count

            gross_by_row[f"{level} / ряд {row}"] = {
                "total": round(row_gross, 2),
                "seat_count": capacity,
                "reliable_share": 1.0 if confident else 0.0,
            }

    return {
        "gross_total": round(gross_total, 2),
        "gross_confidence_ratio": round(gross_known_seats / gross_seats, 3) if gross_seats else 0.0,
        "gross_by_row": gross_by_row,
        "revenue_actual": round(revenue_total, 2),
        "revenue_confidence_ratio": round(revenue_known_seats / revenue_seats, 3) if revenue_seats else 0.0,
    }
