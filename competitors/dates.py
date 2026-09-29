"""
Разбор дат вида «18 ОКТЯБРЯ» / «30 Сентября» без указания года.

Обе площадки не пишут год в афише, поэтому он вычисляется: берём ближайший
год, при котором дата не оказывается давно в прошлом. Декабрьская афиша
с январскими событиями получит следующий год автоматически.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

# Насколько далеко в прошлом может быть дата, чтобы считать её «этим годом»
# (афиша иногда ещё показывает события, прошедшие несколько дней назад)
PAST_TOLERANCE = timedelta(days=60)


def month_number(word: str) -> int | None:
    word = word.strip().lower()
    # "ма" должно проверяться последним, иначе "март" совпадёт с ним
    for prefix, number in sorted(MONTHS.items(), key=lambda kv: -len(kv[0])):
        if word.startswith(prefix):
            return number
    return None


def infer_date(day: int, month: int, today: date | None = None) -> date | None:
    today = today or date.today()
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today - PAST_TOLERANCE:
            return candidate
    return None


def parse_day_month(text: str) -> date | None:
    """«18 ОКТЯБРЯ», «02 октября 18:00», «18 ОКТЯБРЯ / 18:00» -> date."""
    m = re.search(r"(\d{1,2})\s+([А-Яа-яЁё]+)", text or "")
    if not m:
        return None
    month = month_number(m.group(2))
    if month is None:
        return None
    return infer_date(int(m.group(1)), month)


def parse_time(text: str) -> str | None:
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
