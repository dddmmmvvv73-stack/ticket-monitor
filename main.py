"""
Точка входа. Запускать так:

    python3 main.py

Это разовая проверка: скрипт проверяет активные события и завершается.
Для непрерывной работы — два варианта:

1) cron (фоново, без открытого терминала):
    * * * * * cd /path/to/ticket_monitor && /usr/bin/python3 main.py >> run.log 2>&1

   Скрипт сам решает, кого из событий пора проверять (через
   MIN_SECONDS_BETWEEN_CHECKS), поэтому cron можно дёргать хоть каждую
   минуту — лишних запросов он не сделает.

2) режим --loop (держать терминал открытым и смотреть живые логи):
    python3 main.py --loop

   Работает вечно (до Ctrl+C), сам засыпает между проверками и печатает
   в терминал, что происходит на каждом шаге — удобно, когда хочется
   визуально убедиться, что скрипт не завис, а реально работает.

Сырые снимки старше 14 дней сжимаются в gzip автоматически (после каждой
проверки и при старте app.py). Вручную: python3 main.py --rotate
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from alerts import check_alerts
from processor import process_snapshot
from scraper import fetch_hallplan
from geometry import fetch_venue_geometry, parse_geometry

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"

MIN_SECONDS_BETWEEN_CHECKS = 60  # минимальный интервал проверки одного события


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def state_path(event_id: str) -> Path:
    return DATA_DIR / "state" / f"{event_id}.json"


def processed_path(event_id: str) -> Path:
    return DATA_DIR / "processed" / f"{event_id}.json"


def geometry_path(event_id: str) -> Path:
    return DATA_DIR / "geometry" / f"{event_id}.json"


def raw_snapshot_path(event_id: str, ts: datetime) -> Path:
    stamp = ts.strftime("%Y-%m-%d_%H%M%S")
    return DATA_DIR / "raw" / event_id / f"{stamp}.json"


RAW_KEEP_DAYS = 14  # сколько дней сырые снимки лежат несжатыми


def rotate_raw(keep_days: int = RAW_KEEP_DAYS) -> tuple[int, int]:
    """
    Сжимает в gzip сырые снимки старше keep_days (снимок ~2,3 МБ → ~30 КБ).
    Ничего не удаляет: любой снимок можно распаковать (gunzip) для пересчёта.
    Возвращает (сколько файлов сжато, сколько байт освобождено).
    """
    import gzip
    import os

    cutoff = time.time() - keep_days * 86400
    compressed = freed = 0
    for path in sorted((DATA_DIR / "raw").glob("*/*.json")):
        stat = path.stat()
        if stat.st_mtime >= cutoff:
            continue
        gz_path = path.with_suffix(".json.gz")
        data = path.read_bytes()
        with gzip.open(gz_path, "wb") as dst:
            dst.write(data)
        with gzip.open(gz_path, "rb") as check:  # оригинал удаляем, только если копия читается байт в байт
            if check.read() != data:
                gz_path.unlink()
                continue
        os.utime(gz_path, (stat.st_atime, stat.st_mtime))  # дата снимка сохраняется
        freed += stat.st_size - gz_path.stat().st_size
        path.unlink()
        compressed += 1
    return compressed, freed


def should_check_now(state: dict) -> bool:
    last_checked = state.get("last_checked_at")
    if not last_checked:
        return True
    elapsed = (datetime.now() - datetime.fromisoformat(last_checked)).total_seconds()
    return elapsed >= MIN_SECONDS_BETWEEN_CHECKS


def is_event_finished(daily_record: dict) -> bool:
    # Останавливаем слежение, когда продажи закрыты или зал распродан полностью
    if daily_record.get("sale_status") not in ("available", None):
        return True
    if daily_record["sellable_available"] == 0 and daily_record["sellable_total"] > 0:
        return True
    return False


def get_or_fetch_geometry(event_id: str, event_url: str) -> dict | None:
    """
    Геометрия зала не меняется день ото дня — забираем один раз на событие
    и кэшируем. Возвращает уже распарсенную геометрию (parse_geometry),
    либо None, если забрать не удалось (вал тогда просто не считается).
    """
    cache_path = geometry_path(event_id)
    if cache_path.exists():
        return load_json(cache_path, None)

    raw_geometry = fetch_venue_geometry(event_url)
    if raw_geometry is None:
        print(f'[{event_id}] Не удалось получить геометрию зала — вал считаться не будет, только выручка.')
        return None

    parsed = parse_geometry(raw_geometry)
    save_json(cache_path, parsed)
    return parsed


def run_event(event: dict, exclusions_all: dict) -> None:
    event_id = event["id"]
    venue = event.get("venue", "")
    exclusions = exclusions_all.get(venue, {})

    state_wrapper = load_json(state_path(event_id), {})
    if not should_check_now(state_wrapper):
        return  # ещё не время проверять это событие снова

    print(f'[{event_id}] Проверяю...')
    raw, fail_reason = fetch_hallplan(event["url"])

    now = datetime.now()

    if raw is None:
        print(f'[{event_id}] Не удалось получить данные: {fail_reason}')
        state_wrapper["last_checked_at"] = now.isoformat(timespec="seconds")
        state_wrapper["last_check_failed"] = True
        save_json(state_path(event_id), state_wrapper)
        return

    # Сырой архив — сохраняем как есть, для полной пересчитываемости в будущем
    save_json(raw_snapshot_path(event_id, now), raw)

    previous_state = state_wrapper.get("processing_state")
    tracking_start_date = state_wrapper.get("tracking_start_date") or now.date().isoformat()

    geometry = get_or_fetch_geometry(event_id, event["url"])

    daily_record, new_processing_state = process_snapshot(
        raw, previous_state, exclusions, tracking_start_date, geometry=geometry
    )

    history = load_json(processed_path(event_id), [])
    history.append(daily_record)
    save_json(processed_path(event_id), history)

    check_alerts(event_id, daily_record)

    state_wrapper["processing_state"] = new_processing_state
    state_wrapper["tracking_start_date"] = tracking_start_date
    state_wrapper["last_checked_at"] = now.isoformat(timespec="seconds")
    state_wrapper["last_check_failed"] = False
    state_wrapper["active"] = not is_event_finished(daily_record)
    save_json(state_path(event_id), state_wrapper)

    status = "ЗАВЕРШЕНО" if not state_wrapper["active"] else "активно"
    gross_note = f', вал ~{daily_record["gross_total"]:.0f} ₽ (точность {daily_record["gross_confidence_ratio"]*100:.0f}%)' if daily_record.get("gross_total") is not None else ''
    print(
        f'[{event_id}] Продано за проверку: {daily_record["sold_today_count"]} '
        f'(+{daily_record["revenue_today"]:.0f} ₽ выручки){gross_note}. '
        f'Свободно: {daily_record["sellable_available"]}/{daily_record["sellable_total"]}. '
        f'Статус: {status}.'
    )


def run_once() -> None:
    events = load_json(CONFIG_DIR / "events.json", [])
    exclusions_all = load_json(CONFIG_DIR / "exclusions.json", {})

    active_events = [e for e in events if e.get("active", True)]
    if not active_events:
        print('Нет активных событий в config/events.json — нечего проверять.')
        return

    for event in active_events:
        # Пропускаем события, которые сами себя закрыли по факту распродажи
        state_wrapper = load_json(state_path(event["id"]), {})
        if state_wrapper.get("active") is False:
            print(f'[{event["id"]}] Пропускаю — уже завершено ранее.')
            continue
        try:
            run_event(event, exclusions_all)
        except Exception as e:
            print(f'[{event["id"]}] Ошибка: {e}')

    rotate_raw()  # старые сырые снимки — в gzip, чтобы папка data не разрасталась


def main_loop() -> None:
    print(
        f'Режим непрерывного слежения запущен (проверка не чаще раза в '
        f'{MIN_SECONDS_BETWEEN_CHECKS} секунд на событие). Останови через Ctrl+C.\n'
    )
    try:
        cycle = 1
        while True:
            print(f'--- Цикл {cycle}, {datetime.now().strftime("%H:%M:%S")} ---')
            run_once()
            print(f'--- Цикл {cycle} завершён, сплю {MIN_SECONDS_BETWEEN_CHECKS} секунд ---\n')
            cycle += 1
            time.sleep(MIN_SECONDS_BETWEEN_CHECKS)
    except KeyboardInterrupt:
        print('\nОстановлено пользователем (Ctrl+C).')


if __name__ == "__main__":
    if "--rotate" in sys.argv:
        n, freed = rotate_raw()
        print(f"Сжато снимков: {n}, освобождено {freed / 1024 / 1024:.0f} МБ.")
    elif "--loop" in sys.argv:
        main_loop()
    else:
        run_once()
