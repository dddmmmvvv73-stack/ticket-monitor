"""
Простой детектор аномалий по дневной записи.

Пока просто печатает в консоль — при желании легко заменить print()
на отправку в Telegram (через requests к Bot API) или на email.
"""

from __future__ import annotations

SPIKE_THRESHOLD = 15  # если продано за раз больше этого числа мест — алерт


def check_alerts(event_id: str, daily_record: dict) -> list[str]:
    alerts = []

    if daily_record["sold_today_count"] >= SPIKE_THRESHOLD:
        alerts.append(
            f'[{event_id}] Всплеск продаж: {daily_record["sold_today_count"]} мест '
            f'за один снимок (выручка {daily_record["revenue_today"]:.0f} ₽). '
            f'Похоже на групповую/корпоративную бронь.'
        )

    if daily_record["discounts_detected"]:
        rows = sorted({d["row"] for d in daily_record["discounts_detected"]})
        alerts.append(
            f'[{event_id}] Обнаружена скидка на {len(daily_record["discounts_detected"])} '
            f'мест(а) в рядах: {", ".join(rows)}.'
        )

    for alert in alerts:
        print(f'ALERT: {alert}')

    return alerts
