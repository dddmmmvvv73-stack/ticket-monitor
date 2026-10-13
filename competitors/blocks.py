"""
Блокировки билетных сайтов (TICKET_PLATFORMS.md, 7.3 и 8.8): сайт отказал нашему адресу (403, страница капчи) —
этот канал не опрашивается до срока, потом — один пробный запрос; снова отказ — срок вдвое дольше (сутки → 2 → 4 → 7).
Обходить отказ (другие адреса, прокси, капча) нельзя — только ждать и снижать нагрузку.

Канал — оператор и вид сбора: у Кассира 06.10 закрылись запросы мест и остатков, а афиша и страницы работали.
    yandex/sales, kassir/sales    — сбор продаж (sales/run.py)
    yandex/afisha, kassir/afisha  — афиша рынка (competitors/market.py)

Файл data/operator_blocks.json (только на сервере, не в git): его читают оба сбора и экран «Билетные операторы»
(через sales/export.py). Запись: {канал: {since, until, strikes, status, note, lifted}}.

Журнал data/operator_blocks_log.jsonl — каждое событие строкой, навсегда: отказ сайта (trip) с нагрузкой в этот момент
(запросов за прогон и за сутки, пауза, лимит), снятие блокировки (lift), предупреждение (warn — например, усложнилась
проверка Qtickets). По нему видно, при какой частоте сайт закрывает доступ; сводная таблица — OPERATOR_BLOCKS.md.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

from competitors.storage import BASE_DIR, load_json, save_json

FILE = BASE_DIR / "data" / "operator_blocks.json"
LOG_FILE = BASE_DIR / "data" / "operator_blocks_log.jsonl"
FIRST = timedelta(hours=24)
LONGEST = timedelta(days=7)
# Операторы, которых на этом компьютере не опрашиваем совсем (TM_DISABLED_OPERATORS через запятую; ноутбук-сервер
# 12–13.10 — yandex, с 13.10 — пусто: Яндекс собирается с лимитом SALES_BUDGET_YANDEX)
DISABLED = {x.strip() for x in os.environ.get("TM_DISABLED_OPERATORS", "").split(",") if x.strip()}
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
    if channel.split("/")[0] in DISABLED:
        return "blocked"
    b = load().get(channel)
    if not b or b.get("lifted"):
        return "ok"
    return "blocked" if datetime.fromisoformat(b["until"]) > _now() else "probe"


def until(channel: str) -> str | None:
    if channel.split("/")[0] in DISABLED:
        return "отключён здесь"
    b = load().get(channel)
    return b.get("until") if b and not b.get("lifted") else None


def log_event(channel: str, kind: str, note: str = "", ctx: dict | None = None, **extra) -> None:
    """Строка в журнал событий (trip / lift / warn). Сбой записи журнала сбор не останавливает."""
    rec = {"at": _now().isoformat(timespec="seconds"), "channel": channel, "kind": kind, "note": note, "load": ctx or {}, **extra}
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def history(prefix: str = "", since: str = "") -> list[dict]:
    """События журнала по каналам, начинающимся с prefix («qtickets/»), не раньше since (ISO)."""
    out = []
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("channel", "").startswith(prefix) and e.get("at", "") >= since:
                    out.append(e)
    except OSError:
        pass
    return out


def trip(channel: str, status, note: str = "", ctx: dict | None = None) -> dict:
    """Сайт отказал: закрыть канал на срок (у повторного отказа — вдвое дольше прошлого). ctx — нагрузка в этот момент."""
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
    log_event(channel, "trip", note, ctx, status=status, strikes=strikes, until=rec["until"])
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
    log_event(channel, "lift", "доступ снова открыт", since=old.get("since"), strikes=old.get("strikes"))
    return True


def is_denied(status, url: str = "", body: bytes = b"") -> bool:
    """Отказ сайта: 403 или страница капчи (Яндекс уводит на /showcaptcha, отвечает заголовком x-yandex-captcha)."""
    if status == 403:
        return True
    return "showcaptcha" in (url or "") or b"showcaptcha" in (body or b"")[:4000]
