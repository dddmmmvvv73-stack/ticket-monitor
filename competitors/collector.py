"""
Сбор афиш конкурентов: запуск источников, склейка дублей, классификация,
история изменений, журнал и фоновое расписание.

Разовый запуск из терминала (без интерфейса):
    python3 -m competitors.collector

Обычно же сбор запускается из веб-интерфейса (app.py → вкладка «Конкуренты»):
кнопкой «Собрать сейчас» или автоматически по расписанию, интервал задаётся там же.

Что где лежит:
    config/competitors.json               список площадок-источников
    config/settings.json                  расписание, ИИ, Google Таблица
    config/classification_overrides.json  ручные правки сферы/формата/жанра
    data/competitors/events.json          текущая таблица мероприятий
    data/competitors/history/{uid}.json   изменения цен и заполняемости во времени
    data/competitors/ai_cache.json        ответы ИИ (чтобы не спрашивать повторно)
    data/competitors/collector.log        журнал сбора
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
import urllib.request
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path

from competitors import edits
from competitors import odk33
from competitors import seatmap
from competitors import vladimirkoncert as vk
from competitors.classifier import FIELDS, classify_rows, title_key
from competitors.storage import BASE_DIR, CONFIG_DIR, DATA_DIR, load_json, save_json


SOURCES_FILE = CONFIG_DIR / "competitors.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
OVERRIDES_FILE = CONFIG_DIR / "classification_overrides.json"
EVENTS_FILE = DATA_DIR / "events.json"
STATUS_FILE = DATA_DIR / "status.json"
HISTORY_DIR = DATA_DIR / "history"
AI_CACHE_FILE = DATA_DIR / "ai_cache.json"
LOG_FILE = DATA_DIR / "collector.log"
SEATS_DIR = DATA_DIR / "seats"                  # схема зала и подтверждённые продажи по событию
HALLS_FILE = DATA_DIR / "halls.json"            # найденные залы: ряды, авто-бронь
HALL_RESERVE_FILE = CONFIG_DIR / "hall_reserve.json"  # ручная бронь: {зал: {auto, rows}}

DEFAULT_SOURCES = [
    {"id": "odk33", "type": "odk33", "name": "ОДКиИ (odk33.ru)", "city": "Владимир", "enabled": True},
]
DEFAULT_SETTINGS = {
    "auto_enabled": False,
    "interval_minutes": 360,
    "ai_provider": "gigachat",  # gigachat | claude | off
    "gigachat_auth_key": "",
    "gigachat_scope": "GIGACHAT_API_PERS",
    "gigachat_model": "GigaChat-2-Max",
    "anthropic_api_key": "",
    "sheets_webhook_url": "",
    "sheets_auto_export": False,
}
MIN_INTERVAL_MINUTES = 5
HISTORY_FIELDS = (
    "price_min", "price_max", "seats_free", "seats_taken", "seats_total",
    "gross", "revenue_est", "sold_confirmed", "revenue_confirmed",
)
MONEY_FIELDS = (
    "seats_sellable", "seats_taken_sellable", "reserve_seats", "gross", "revenue_est",
    "avg_price_taken", "gross_confidence", "sold_confirmed", "revenue_confirmed", "tracking_since",
)


# ---------------------------------------------------------------- хранение

def load_sources() -> list[dict]:
    return load_json(SOURCES_FILE, DEFAULT_SOURCES)


def save_sources(sources: list[dict]) -> None:
    save_json(SOURCES_FILE, sources)


def load_settings() -> dict:
    stored = load_json(SETTINGS_FILE, {}).get("competitors", {})
    if "ai_provider" not in stored and stored.get("ai_enabled") is False:
        stored = {**stored, "ai_provider": "off"}  # старая настройка «ИИ выключен»
    return {**DEFAULT_SETTINGS, **stored}


def ai_settings(settings: dict) -> dict:
    """Настройки для classifier.classify_rows — только то, что нужно выбранному провайдеру."""
    keys = ("gigachat_auth_key", "gigachat_scope", "gigachat_model", "anthropic_api_key")
    return {"provider": settings["ai_provider"], **{k: settings[k] for k in keys}}


def save_settings(changes: dict) -> dict:
    all_settings = load_json(SETTINGS_FILE, {})
    current = load_settings()
    current.pop("ai_enabled", None)  # заменено на ai_provider
    for key in DEFAULT_SETTINGS:
        if key in changes:
            current[key] = changes[key]
    current["interval_minutes"] = max(int(current["interval_minutes"]), MIN_INTERVAL_MINUTES)
    all_settings["competitors"] = current
    save_json(SETTINGS_FILE, all_settings)
    return current


def load_events() -> dict[str, dict]:
    return load_json(EVENTS_FILE, {})


def load_status() -> dict:
    return load_json(STATUS_FILE, {})


def history_path(uid: str) -> Path:
    return HISTORY_DIR / (uid.replace(":", "_").replace("/", "_") + ".json")


# ---------------------------------------------------------------- журнал

_log_lines: deque = deque(maxlen=400)
_log_lock = threading.Lock()


def log(message: str) -> None:
    line = f"{datetime.now().strftime('%d.%m %H:%M:%S')}  {message}"
    print(line, flush=True)
    with _log_lock:
        _log_lines.append(line)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def recent_log(limit: int = 150) -> list[str]:
    with _log_lock:
        if not _log_lines and LOG_FILE.exists():
            # После перезапуска приложения подтягиваем хвост журнала с диска
            tail = LOG_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
            _log_lines.extend(tail)
        return list(_log_lines)[-limit:]


# ---------------------------------------------------------------- сбор

_run_lock = threading.Lock()
_progress = {"running": False, "started_at": None, "trigger": None}


def _collect_source(source: dict) -> list[dict]:
    if source["type"] == "odk33":
        return odk33.collect(log)
    if source["type"] == "vladimirkoncert":
        return vk.collect_venue(source["venue_id"], source["name"], log, source.get("city", vk.CITY_BY_DEFAULT),
                                source.get("site", vk.DEFAULT_SITE))
    raise ValueError(f"неизвестный тип источника: {source['type']}")


def _merge_duplicates(rows: list[dict]) -> list[dict]:
    """
    Одно и то же мероприятие может прийти дважды: из афиши odk33.ru и из
    списка площадки на vladimirkoncert.ru. Склеиваем по id сеанса: карточку
    площадки оставляем (там зал и «Пушкинская карта»), а типы с билетного
    сайта, возраст и описание добавляем к ней.
    """
    by_vk_id = {r["vk_event_id"]: r for r in rows if r["source"] == "odk33" and r.get("vk_event_id")}
    merged = []
    for row in rows:
        twin = by_vk_id.get(row.get("vk_event_id")) if row["source"] == "vladimirkoncert" else None
        if twin is None:
            merged.append(row)
            continue
        twin["site_types"] = row["site_types"]
        twin["age"] = twin.get("age") or row.get("age")
        if len(row.get("description") or "") > len(twin.get("description") or ""):
            twin["description"] = row["description"]
    return merged


# ---------------------------------------------------------------- вал и выручка

def seat_state_path(uid: str) -> Path:
    return SEATS_DIR / (uid.replace(":", "_").replace("/", "_") + ".json")


def _compact_seats(seats: list[dict]) -> list[list]:
    return [[s["id"], s["x"], s["y"], s["zone"], s["row"], s["price"] or 0, int(s["taken"]), s.get("place")]
            for s in seats]


def _expand_seats(compact: list[list]) -> list[dict]:
    keys = ("id", "x", "y", "zone", "row", "price", "taken", "place")
    seats = [dict(zip(keys, item)) for item in compact]
    for seat in seats:
        seat["price"] = seat["price"] or None
        seat["taken"] = bool(seat["taken"])
    if seats and seats[0].get("place") is None:
        # Схемы, сохранённые до появления номеров мест: номер = порядок в ряду слева направо
        rows: dict[tuple, list[dict]] = defaultdict(list)
        for seat in seats:
            rows[(seat["zone"], seat["row"])].append(seat)
        for row in rows.values():
            for n, seat in enumerate(sorted(row, key=lambda s: s["x"]), 1):
                seat["place"] = str(n)
    seatmap.normalize(seats)  # схемы, сохранённые до нормировки координат
    return seats


def _repair_flips_once() -> None:
    """Разовая починка «весь зал занят», записанного до правила seatmap.is_flip (у каждого события — один раз)."""
    total = {"anomalies": 0, "removed": 0, "moved": 0, "returned_fixed": 0}
    for path in SEATS_DIR.glob("*.json") if SEATS_DIR.exists() else []:
        state = load_json(path, {})
        if not state or state.get("flips_repaired"):
            continue
        hpath = HISTORY_DIR / path.name
        history = load_json(hpath, [])
        report = seatmap.repair_flips(state, history)
        save_json(path, state)
        if report["anomalies"]:
            save_json(hpath, history)
            log(f"Починка «весь зал занят»: {state.get('title', path.stem)} — сбоев {report['anomalies']}, "
                f"ложных продаж убрано {report['removed']}, перенесено {report['moved']}, возвратов вычтено {report['returned_fixed']}")
        for k in total:
            total[k] += report[k]
    if total["anomalies"]:
        log(f"Починка «весь зал занят» завершена: сбоев {total['anomalies']}, ложных продаж убрано {total['removed']}")


def _update_seat_states(rows: list[dict], now_iso: str) -> None:
    """Сохраняет схему зала каждого события и отмечает подтверждённые продажи."""
    new_sales = new_sales_rub = 0
    for row in rows:
        seats = row.pop("_seats", None)
        if not seats:
            continue
        path = seat_state_path(row["uid"])
        previous = load_json(path, {})
        state = seatmap.update_state(previous, seats, now_iso)
        suspect = state.get("suspect")
        if suspect and suspect.get("last") == now_iso:  # «весь зал занят» — продажами не считаем
            row["seats_suspect"] = suspect["since"]
            if suspect["since"] == now_iso:
                log(f"⚠ {row['title']} ({row.get('date')}): разом недоступны {suspect['free_before'] - suspect['free_now']} "
                    f"из {suspect['free_before']} свободных мест — не считаю продажами (сбой сайта или сеанс снят с продажи)")
        fresh = set(state["sold"]) - set(previous.get("sold", {}))
        new_sales += len(fresh)
        new_sales_rub += sum(state["sold"][s]["price"] or 0 for s in fresh)
        state.update(
            layout=seatmap.layout_signature(seats), seats=_compact_seats(seats),
            date=row.get("date"), title=row["title"], venue=row.get("venue"), hall=row.get("hall"),
        )
        save_json(path, state)
    if new_sales:
        log(f"Подтверждённые продажи с прошлого сбора: {new_sales} мест на {new_sales_rub:,} ₽".replace(",", " "))


def load_seat_states() -> dict[str, dict]:
    states = {}
    if SEATS_DIR.exists():
        for path in SEATS_DIR.glob("*.json"):
            state = load_json(path, {})
            if state.get("seats"):
                states[path.stem] = state
    return states


def recompute_money() -> None:
    """
    Пересчитывает вал / выручку всех событий по сохранённым схемам залов:
    авто-бронь по каждому залу + ручная бронь из интерфейса. Сайты не опрашиваются.
    """
    states = load_seat_states()
    manual_all = load_json(HALL_RESERVE_FILE, {})

    # Зал = группа похожих рассадок одной площадки (см. seatmap.group_layouts)
    layout_seats: dict[str, dict[str, set]] = defaultdict(dict)  # площадка -> рассадка -> места
    by_layout: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for key, state in states.items():
        seats = _expand_seats(state["seats"])
        state["seats"] = _compact_seats(seats)  # дальше работаем с нормированными координатами
        state["layout"] = seatmap.layout_signature(seats)
        by_layout[state["layout"]].append((key, state))
        layout_seats[state.get("venue") or ""][state["layout"]] = {seatmap.seat_key(s) for s in seats}

    halls: dict[str, dict] = {}
    money_by_file_key: dict[str, dict] = {}
    for venue, layouts in layout_seats.items():
        for group in seatmap.group_layouts(layouts):
            members = [m for layout in group for m in by_layout[layout]]
            # Идентификатор зала — самая частая рассадка группы (ручная бронь хранится по всем)
            hall_id = max(group, key=lambda layout: (len(by_layout[layout]), layout))
            manual = next((manual_all[l] for l in [hall_id, *group] if l in manual_all), {})
            seat_sets: dict[str, tuple[set, set]] = {}
            for file_key, st in members:
                seats = _expand_seats(st["seats"])
                seat_sets[file_key] = (
                    {seatmap.seat_key(s) for s in seats},
                    {seatmap.seat_key(s) for s in seats if s["taken"]},
                )
            # Бронь двух уровней: зала целиком (служебные места) и одинаковой рассадки —
            # у серии спектаклей одного продюсера бывает своя закрытая квота мест
            found = seatmap.auto_reserve(list(seat_sets.values()))
            series_found = {
                layout: seatmap.auto_reserve([seat_sets[k] for k, _st in by_layout[layout]])
                for layout in group
            }
            auto_enabled = manual.get("auto", True)
            manual_rows = set(manual.get("rows", []))

            latest = max(members, key=lambda m: m[1].get("date") or "")[1]
            sample = _expand_seats(latest["seats"])
            halls[hall_id] = {
                "name": " · ".join(filter(None, [venue, latest.get("hall")])),
                "seats": len(sample),
                "events": len(members),
                "layouts": group,
                "auto_enabled": auto_enabled,
                "auto_reserve": len(found),
                "series_reserve": {l: len(s) for l, s in series_found.items() if s - found},
                "auto_possible": len(members) >= seatmap.MIN_EVENTS_FOR_AUTO_RESERVE,
                "manual_rows": sorted(manual_rows),
                "rows": seatmap.describe_rows(sample),
            }
            for file_key, state in members:
                seats = _expand_seats(state["seats"])
                seatmap.price_seats(seats, state.get("registry", {}))
                auto = (found | series_found[state["layout"]]) if auto_enabled else set()
                money_by_file_key[file_key] = seatmap.compute_money(seats, auto, manual_rows, state)

    save_json(HALLS_FILE, halls)

    events = load_events()
    for uid, row in events.items():
        money = money_by_file_key.get(seat_state_path(uid).stem)
        for field in MONEY_FIELDS:
            row[field] = money.get(field) if money else None
    save_json(EVENTS_FILE, events)


def load_halls() -> dict:
    return load_json(HALLS_FILE, {})


def save_hall_reserve(hall_id: str, auto: bool, rows: list[str]) -> None:
    """Ручная бронь зала — сохраняется для всех вариантов его рассадки."""
    manual_all = load_json(HALL_RESERVE_FILE, {})
    layouts = load_halls().get(hall_id, {}).get("layouts", [hall_id])
    for layout in layouts:
        manual_all[layout] = {"auto": bool(auto), "rows": sorted(set(rows))}
    save_json(HALL_RESERVE_FILE, manual_all)
    recompute_money()


def sales_by_day() -> dict[str, dict[str, list]]:
    """Подтверждённые продажи по дням: {uid-файл: {дата: [мест, ₽]}} — для аналитики."""
    result: dict[str, dict[str, list]] = {}
    for key, state in load_seat_states().items():
        days: dict[str, list] = {}
        for sale in state.get("sold", {}).values():
            day = sale["ts"][:10]
            bucket = days.setdefault(day, [0, 0])
            bucket[0] += 1
            bucket[1] += sale["price"] or 0
        if days:
            result[key] = days
    return result


def _append_history(uid: str, row: dict, now_iso: str) -> None:
    path = history_path(uid)
    history = load_json(path, [])
    point = {f: row.get(f) for f in HISTORY_FIELDS}
    if history and all(history[-1].get(f) == point[f] for f in HISTORY_FIELDS):
        return  # ничего не поменялось — не раздуваем историю
    if row.get("seats_suspect"):
        point["anomaly"] = True  # «весь зал занят» — графики и «что изменилось» эту точку пропускают
    history.append({"ts": now_iso, **point})
    save_json(path, history)


def run_collection(trigger: str = "manual") -> bool:
    """Полный цикл сбора. Возвращает False, если сбор уже идёт."""
    if not _run_lock.acquire(blocking=False):
        return False
    started = time.time()
    _progress.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"), trigger=trigger)
    status = load_status()
    try:
        settings = load_settings()
        sources = [s for s in load_sources() if s.get("enabled", True)]
        log(f"=== Сбор начат ({'по расписанию' if trigger == 'auto' else 'вручную'}), "
            f"площадок: {len(sources)} ===")

        rows: list[dict] = []
        failed: list[str] = []
        for source in sources:
            try:
                found = _collect_source(source)
                for row in found:
                    row["source_id"] = source["id"]
                rows.extend(found)
            except Exception as e:
                failed.append(source["name"])
                log(f"✖ {source['name']}: ошибка сбора — {e}")

        rows = _merge_duplicates(rows)
        classify_rows(
            rows,
            overrides=load_json(OVERRIDES_FILE, {}),
            ai_cache_path=AI_CACHE_FILE,
            ai=ai_settings(settings),
            log=log,
        )

        now_iso = datetime.now().isoformat(timespec="seconds")
        for row in rows:
            row["date"] = row["date"].isoformat() if isinstance(row.get("date"), date) else row.get("date")
        _repair_flips_once()
        _update_seat_states(rows, now_iso)

        events = load_events()
        new_count = 0
        for row in rows:
            previous = events.get(row["uid"])
            if previous is None:
                new_count += 1
            row["first_seen"] = previous["first_seen"] if previous else now_iso
            row["last_seen"] = now_iso
            events[row["uid"]] = row
        save_json(EVENTS_FILE, events)

        recompute_money()  # вал, выручка, бронь — по схемам залов
        events = load_events()
        for row in rows:
            _append_history(row["uid"], events[row["uid"]], now_iso)

        took = time.time() - started
        summary = f"найдено {len(rows)} мероприятий, новых {new_count}, за {took:.0f} с"
        if failed:
            summary += f"; не удалось: {', '.join(failed)}"
        status.update(last_run_at=now_iso, last_ok=not failed, last_summary=summary, last_error=None)
        log(f"=== Сбор завершён: {summary} ===")

        if settings["sheets_auto_export"] and settings["sheets_webhook_url"]:
            try:
                export_to_sheets(settings["sheets_webhook_url"])
            except Exception as e:
                log(f"✖ Автовыгрузка в Google Таблицу не удалась: {e}")
        return True
    except Exception as e:
        status.update(last_run_at=datetime.now().isoformat(timespec="seconds"),
                      last_ok=False, last_error=str(e), last_summary=None)
        log(f"✖ Сбор прерван ошибкой: {e}")
        return True
    finally:
        save_json(STATUS_FILE, status)
        _progress.update(running=False)
        _run_lock.release()


def run_in_background(trigger: str = "manual") -> bool:
    if _progress["running"]:
        return False
    threading.Thread(target=run_collection, args=(trigger,), daemon=True).start()
    return True


# ---------------------------------------------------------------- расписание

def next_run_at() -> datetime | None:
    settings = load_settings()
    if not settings["auto_enabled"]:
        return None
    last = load_status().get("last_run_at")
    if not last:
        return datetime.now()
    return datetime.fromisoformat(last) + timedelta(minutes=settings["interval_minutes"])


def _scheduler_loop() -> None:
    while True:
        try:
            due = next_run_at()
            if due is not None and datetime.now() >= due and not _progress["running"]:
                run_collection("auto")
        except Exception as e:
            log(f"✖ Планировщик: {e}")
        time.sleep(20)


_scheduler_started = False


def start_scheduler() -> None:
    """Фоновый поток: раз в 20 секунд проверяет, не пора ли запускать сбор."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_scheduler_loop, daemon=True, name="competitors-scheduler").start()


def status_snapshot() -> dict:
    status = load_status()
    due = next_run_at()
    return {
        **status,
        "running": _progress["running"],
        "trigger": _progress["trigger"] if _progress["running"] else None,
        "started_at": _progress["started_at"] if _progress["running"] else None,
        "next_run_at": due.isoformat(timespec="seconds") if due else None,
    }


# ---------------------------------------------------------------- ручные правки

def set_override(title: str, values: dict) -> None:
    """Сохраняет ручную классификацию для названия и сразу применяет её к таблице."""
    overrides = load_json(OVERRIDES_FILE, {})
    key = title_key(title)
    entry = {f: (values.get(f) or "").strip() for f in FIELDS}
    entry = {f: v for f, v in entry.items() if v}
    if entry:
        overrides[key] = entry
    else:
        overrides.pop(key, None)
    save_json(OVERRIDES_FILE, overrides)

    # Пересчёт классификации по уже собранным данным — без запросов к сайтам и ИИ
    rows = list(load_events().values())
    classify_rows(rows, overrides, AI_CACHE_FILE, ai=None, log=lambda _m: None)
    save_json(EVENTS_FILE, {r["uid"]: r for r in rows})


def _reclassify() -> None:
    """ИИ-классификация уже собранной таблицы — без повторного обхода сайтов."""
    if not _run_lock.acquire(blocking=False):
        return
    _progress.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"), trigger="ai")
    try:
        log("=== Доклассификация через ИИ ===")
        rows = list(load_events().values())
        classify_rows(rows, load_json(OVERRIDES_FILE, {}), AI_CACHE_FILE,
                      ai=ai_settings(load_settings()), log=log)
        save_json(EVENTS_FILE, {r["uid"]: r for r in rows})
        empty = sum(1 for r in rows if not all(r.get(f) for f in FIELDS))
        log(f"=== Доклассификация завершена, без полной классификации осталось: {empty} ===")
    except Exception as e:
        log(f"✖ Доклассификация прервана ошибкой: {e}")
    finally:
        _progress.update(running=False)
        _run_lock.release()


def reclassify_in_background() -> bool:
    if _progress["running"]:
        return False
    threading.Thread(target=_reclassify, daemon=True).start()
    return True


def test_ai_connection() -> dict:
    """Кнопка «Проверить подключение»: для GigaChat — ключ, сертификат и список моделей."""
    settings = load_settings()
    if settings["ai_provider"] != "gigachat":
        return {"ok": True, "message": "Проверка доступна для GigaChat; Claude проверится при сборе."}
    from competitors import gigachat_ai
    try:
        models = gigachat_ai.list_models(settings["gigachat_auth_key"], settings["gigachat_scope"], log)
    except gigachat_ai.GigaChatSetupError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"не удалось подключиться к GigaChat: {e}"}
    chat_models = [m for m in models if "embed" not in m.lower()]
    log(f"GigaChat: подключение работает, доступные модели: {', '.join(chat_models)}")
    return {"ok": True, "message": "Подключение работает", "models": chat_models}


# ---------------------------------------------------------------- выгрузка

EXPORT_HEADER = [
    "Площадка", "Город", "Зал", "Название", "Дата", "Время", "Длительность",
    "Сфера", "Формат", "Жанр",
    "Цена от, ₽", "Цена до, ₽", "Цена (текст)", "Мест всего", "Свободно",
    "Занято (вкл. бронь)", "Заполняемость, %",
    "Вал, ₽", "Выручка (оценка), ₽", "% вала", "Подтв. продажи, мест", "Подтв. выручка, ₽",
    "Средняя цена занятого, ₽", "Бронь площадки, мест", "Точность вала, %", "Слежение с",
    "Возраст", "Пушкинская карта", "Ссылка", "Купить", "Впервые замечено", "Обновлено",
]


def visible_events(include_past: bool = False) -> list[dict]:
    """Мероприятия для интерфейса и выгрузки: данные парсера + ручные правки и свои события."""
    today = date.today().isoformat()
    rows = [r for r in edits.apply(load_events().values())
            if include_past or not r.get("date") or r["date"] >= today]
    return sorted(rows, key=lambda r: (r.get("date") or "9999", r.get("time") or "", r["title"]))


def _blank(value):
    return "" if value is None else value


def _money_cells(r: dict) -> list:
    gross, revenue = r.get("gross"), r.get("revenue_est")
    share = round(revenue / gross * 100, 1) if gross and revenue is not None else ""
    confidence = round(r["gross_confidence"] * 100) if r.get("gross_confidence") is not None and gross else ""
    return [
        _blank(gross), _blank(revenue), share, _blank(r.get("sold_confirmed")),
        _blank(r.get("revenue_confirmed")), _blank(r.get("avg_price_taken")),
        _blank(r.get("reserve_seats")), confidence, (r.get("tracking_since") or "")[:10],
    ]


def export_rows(rows: list[dict]) -> list[list]:
    table = []
    for r in rows:
        total, taken = r.get("seats_total"), r.get("seats_taken")
        fill = round(taken / total * 100, 1) if total else ""
        table.append([
            r.get("venue"), r.get("city"), r.get("hall") or "", r["title"],
            r.get("date") or "", r.get("time") or "", r.get("duration") or "",
            r.get("sphere", ""), r.get("format", ""), r.get("genre", ""),
            r.get("price_min") if r.get("price_min") is not None else "",
            r.get("price_max") if r.get("price_max") is not None else "",
            r.get("price_text") or "",
            total if total is not None else "", r.get("seats_free") if r.get("seats_free") is not None else "",
            taken if taken is not None else "", fill,
            *_money_cells(r),
            r.get("age") or "", "да" if r.get("pushkin") else "",
            r.get("url") or "", r.get("buy_url") or "",
            r.get("first_seen", ""), r.get("last_seen", ""),
        ])
    return table


def export_csv_bytes(include_past: bool = False) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADER)
    writer.writerows(export_rows(visible_events(include_past)))
    return buf.getvalue().encode("utf-8-sig")  # utf-8-sig — чтобы Excel не ломал кириллицу


def export_to_sheets(webhook_url: str, include_past: bool = False) -> str:
    """
    Отправляет таблицу в Google Таблицу через веб-приложение Apps Script
    (скрипт и инструкция — в README.md, раздел «Google Таблица для конкурентов»).
    Такой способ не требует gspread/service account и сборки cryptography.
    """
    rows = export_rows(visible_events(include_past))
    payload = json.dumps({"sheet": "Конкуренты", "header": EXPORT_HEADER, "rows": rows},
                         ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        answer = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("Google ответил не JSON — проверь, что веб-приложение развёрнуто "
                           "с доступом «Все» и ссылка заканчивается на /exec")
    if not answer.get("ok"):
        raise RuntimeError(answer.get("error") or "неизвестная ошибка Apps Script")
    message = f"В Google Таблицу выгружено строк: {len(rows)}"
    log(message)
    return message


if __name__ == "__main__":
    # python3 -m competitors.collector        — сбор вручную
    # python3 -m competitors.collector auto   — сбор по расписанию (GitHub Actions)
    import sys
    run_collection(sys.argv[1] if len(sys.argv) > 1 else "manual")
