"""
Блокировки билетных сайтов (TICKET_PLATFORMS.md, 7.3 и 8.8): сайт отказал нашему адресу (403, страница капчи) —
этот канал не опрашивается до срока, потом — один пробный запрос; снова отказ — срок вдвое дольше (сутки → 2 → 4 → 7).
Обходить отказ (другие адреса, прокси, капча) нельзя — только ждать и снижать нагрузку.

Канал — оператор и вид сбора: у Кассира 06.10 закрылись запросы мест и остатков, а афиша и страницы работали.
    yandex/sales, kassir/sales    — сбор продаж (sales/run.py)
    yandex/afisha, kassir/afisha  — афиша рынка (competitors/market.py)

Файл data/operator_blocks.json (только на сервере, не в git): его читают оба сбора и экран «Билетные операторы»
(через sales/export.py). Запись: {канал: {since, until, strikes, status, note, lifted}}.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from competitors.storage import BASE_DIR, load_json, save_json

FILE = BASE_DIR / "data" / "operator_blocks.json"
FIRST = timedelta(hours=24)
LONGEST = timedelta(days=7)
DENY_IN_WINDOW = 5     # отказов среди последних 20 ответов — сайт закрыл доступ (до 06.10 не было ни одного 403)
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now().astimezone()


def load() -> dict:
    try:
        return load_json(FILE, {})
    except ValueError:
        return {}


def state(channel: str) -> str:
    """ok — опрашивать как обычно; probe — срок вышел, нужен пробный запрос (отказ на первом же); blocked — не опрашивать."""
    b = load().get(channel)
    if not b or b.get("lifted"):
        return "ok"
    return "blocked" if datetime.fromisoformat(b["until"]) > _now() else "probe"


def until(channel: str) -> str | None:
    b = load().get(channel)
    return b.get("until") if b and not b.get("lifted") else None


def trip(channel: str, status, note: str = "") -> dict:
    """Сайт отказал: закрыть канал на срок (у повторного отказа — вдвое дольше прошлого)."""
    with _lock:
        data = load()
        old = data.get(channel) or {}
        active = old and not old.get("lifted")
        strikes = old.get("strikes", 0) + 1 if active else 1
        now = _now()
        rec = {"since": old["since"] if active else now.isoformat(timespec="seconds"),
               "until": (now + min(FIRST * 2 ** (strikes - 1), LONGEST)).isoformat(timespec="seconds"),
               "strikes": strikes, "status": status, "note": note, "checked": now.isoformat(timespec="seconds")}
        data[channel] = rec
        save_json(FILE, data)
        return rec


def clear(channel: str) -> bool:
    """Ответ без отказа — блокировка снялась (в файле остаётся отметка, когда). True — если она была."""
    with _lock:
        data = load()
        old = data.get(channel)
        if not old or old.get("lifted"):
            return False
        data[channel] = {**old, "lifted": _now().isoformat(timespec="seconds")}
        save_json(FILE, data)
        return True


def is_denied(status, url: str = "", body: bytes = b"") -> bool:
    """Отказ сайта: 403 или страница капчи (Яндекс уводит на /showcaptcha, отвечает заголовком x-yandex-captcha)."""
    if status == 403:
        return True
    return "showcaptcha" in (url or "") or b"showcaptcha" in (body or b"")[:4000]
