"""
Локальный веб-интерфейс для мониторинга билетов.

Запуск:
    python3 app.py

Откроется страница в браузере на http://127.0.0.1:5050
Останавливается через Ctrl+C в терминале.
"""

from __future__ import annotations

import csv
import io
import re
import webbrowser
from datetime import date, datetime
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, request, send_file, Response

from alerts import check_alerts
from competitors import collector, edits, sync
from competitors.api import bp as app_api
from competitors.market_api import bp as market_api
from competitors import vladimirkoncert
from competitors.classifier import FORMATS, GENRES, SPHERES
from processor import process_snapshot
from scraper import fetch_hallplan
from main import (
    BASE_DIR, CONFIG_DIR, DATA_DIR,
    load_json, save_json,
    state_path, processed_path, raw_snapshot_path, geometry_path,
    is_event_finished, get_or_fetch_geometry, rotate_raw,
)

app = Flask(__name__, static_folder=str(BASE_DIR / "static"))
app.register_blueprint(app_api)
app.register_blueprint(market_api)  # прототип на /proto/ и ручная разметка рынка

EVENTS_FILE = CONFIG_DIR / "events.json"
EXCLUSIONS_FILE = CONFIG_DIR / "exclusions.json"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9а-яё]+", "-", text)
    return text.strip("-") or "venue"


def event_id_from_url(url: str) -> str:
    path = url.split("?")[0].rstrip("/")
    return slugify(path.split("/")[-1])


def upsert_event(url: str, venue_hint: str | None) -> dict:
    events = load_json(EVENTS_FILE, [])
    for e in events:
        if e["url"] == url:
            return e

    ev_id = event_id_from_url(url)
    venue = slugify(venue_hint) if venue_hint else ev_id
    title = event_id_from_url(url).replace("-", " ").capitalize()

    new_event = {
        "id": ev_id, "url": url, "venue": venue,
        "title": title, "active": True,
    }
    events.append(new_event)
    save_json(EVENTS_FILE, events)
    return new_event


def get_since_yesterday(event_id: str, current_record: dict) -> dict | None:
    history = load_json(processed_path(event_id), [])
    today = current_record["date"]
    previous_days = [r for r in history if r["date"] != today]
    if not previous_days:
        return None
    prev = previous_days[-1]
    return {
        "sold": current_record["sellable_sold_cumulative"] - prev["sellable_sold_cumulative"],
        "revenue": round(current_record["revenue_actual"] - prev["revenue_actual"], 2),
        "since_date": prev["date"],
    }


@app.route("/")
def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.route("/api/parse_one", methods=["POST"])
def parse_one():
    body = request.get_json(force=True)
    url = (body.get("url") or "").strip()
    venue_hint = (body.get("venue") or "").strip() or None

    if not url:
        return jsonify({"error": "Пустая ссылка"}), 400

    event = upsert_event(url, venue_hint)
    event_id = event["id"]
    venue = event["venue"]

    exclusions_all = load_json(EXCLUSIONS_FILE, {})
    exclusions = exclusions_all.get(venue, {})

    raw, fail_reason = fetch_hallplan(url)
    if raw is None:
        return jsonify({
            "error": f"Не удалось получить данные с этой страницы. Причина: {fail_reason}",
            "event_id": event_id, "url": url,
        }), 502

    now = datetime.now()
    save_json(raw_snapshot_path(event_id, now), raw)

    state_wrapper = load_json(state_path(event_id), {})
    previous_state = state_wrapper.get("processing_state")
    tracking_start_date = state_wrapper.get("tracking_start_date") or now.date().isoformat()

    geometry = get_or_fetch_geometry(event_id, url)

    daily_record, new_processing_state = process_snapshot(
        raw, previous_state, exclusions, tracking_start_date, geometry=geometry
    )

    history = load_json(processed_path(event_id), [])
    history.append(daily_record)
    save_json(processed_path(event_id), history)

    alerts = check_alerts(event_id, daily_record)

    state_wrapper["processing_state"] = new_processing_state
    state_wrapper["tracking_start_date"] = tracking_start_date
    state_wrapper["last_checked_at"] = now.isoformat(timespec="seconds")
    state_wrapper["active"] = not is_event_finished(daily_record)
    save_json(state_path(event_id), state_wrapper)

    since_yesterday = get_since_yesterday(event_id, daily_record)

    return jsonify({
        "event_id": event_id,
        "title": event.get("title", event_id),
        "url": url,
        "venue": venue,
        "record": daily_record,
        "since_yesterday": since_yesterday,
        "alerts": alerts,
    })


@app.route("/api/venues")
def venues():
    events = load_json(EVENTS_FILE, [])
    seen = {}
    for e in events:
        seen.setdefault(e["venue"], []).append(e.get("title", e["id"]))
    return jsonify([{"venue": v, "events": titles} for v, titles in seen.items()])


@app.route("/api/admin_rows", methods=["GET"])
def get_admin_rows():
    venue = request.args.get("venue", "")
    exclusions_all = load_json(EXCLUSIONS_FILE, {})
    data = exclusions_all.get(venue, {
        "reserved_seats_count": 0, "excluded_seat_ids": [], "excluded_rows": [],
    })
    return jsonify(data)


@app.route("/api/admin_rows", methods=["POST"])
def save_admin_rows():
    body = request.get_json(force=True)
    venue = body.get("venue")
    if not venue:
        return jsonify({"error": "Не указана площадка"}), 400

    exclusions_all = load_json(EXCLUSIONS_FILE, {})
    exclusions_all[venue] = {
        "reserved_seats_count": int(body.get("reserved_seats_count") or 0),
        "excluded_seat_ids": body.get("excluded_seat_ids", []),
        "excluded_rows": body.get("excluded_rows", []),
    }
    save_json(EXCLUSIONS_FILE, exclusions_all)
    return jsonify({"ok": True})


@app.route("/api/history/<event_id>")
def history(event_id):
    return jsonify(load_json(processed_path(event_id), []))


@app.route("/api/export.csv")
def export_csv():
    events = load_json(EVENTS_FILE, [])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Событие", "Ссылка", "Дата", "Всего мест", "Свободно",
        "Продано всего", "Выручка, ₽", "Точность выручки, %",
        "Вал, ₽", "Точность вала, %", "Способ расчёта",
        "Скидок обнаружено", "Операторы",
    ])
    for e in events:
        history = load_json(processed_path(e["id"]), [])
        if not history:
            continue
        r = history[-1]
        writer.writerow([
            e.get("title", e["id"]), e["url"], r.get("date"),
            r.get("sellable_total"), r.get("sellable_available"),
            r.get("sellable_sold_cumulative"), r.get("revenue_actual"),
            round(r.get("revenue_confidence_ratio", 0) * 100, 1),
            r.get("gross_total"),
            round(r.get("gross_confidence_ratio", 0) * 100, 1),
            r.get("gross_method"),
            len(r.get("discounts_detected", [])), ", ".join(r.get("operators", [])),
        ])

    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # utf-8-sig — чтобы Excel не ломал кириллицу
    return send_file(
        mem, mimetype="text/csv", as_attachment=True,
        download_name=f"tickets_{date.today().isoformat()}.csv",
    )


# ---------------------------------------------------------------- Конкуренты

SECRET_SETTINGS = ("anthropic_api_key", "gigachat_auth_key")


def _public_settings(settings: dict) -> dict:
    """Ключи наружу не отдаём — только признак, что ключ задан."""
    public = {k: v for k, v in settings.items() if k not in SECRET_SETTINGS}
    for key in SECRET_SETTINGS:
        public[f"{key}_set"] = bool(settings.get(key))
    return public


@app.route("/competitors")
def competitors_page():
    return (BASE_DIR / "static" / "competitors.html").read_text(encoding="utf-8")


@app.route("/api/competitors/events")
def competitors_events():
    include_past = request.args.get("past") == "1"
    return jsonify({
        "events": collector.visible_events(include_past),
        "taxonomy": {"sphere": SPHERES, "format": FORMATS, "genre": GENRES},
    })


@app.route("/api/competitors/history/<path:uid>")
def competitors_history(uid):
    return jsonify(collector.load_json(collector.history_path(uid), []))


@app.route("/api/competitors/run", methods=["POST"])
def competitors_run():
    started = collector.run_in_background("manual")
    return jsonify({"started": started, "message": None if started else "Сбор уже идёт"})


@app.route("/api/competitors/reclassify", methods=["POST"])
def competitors_reclassify():
    started = collector.reclassify_in_background()
    return jsonify({"started": started, "message": None if started else "Уже идёт сбор или классификация"})


@app.route("/api/competitors/ai_test", methods=["POST"])
def competitors_ai_test():
    return jsonify(collector.test_ai_connection())


@app.route("/api/competitors/status")
def competitors_status():
    return jsonify({**collector.status_snapshot(), "log": collector.recent_log()})


@app.route("/api/competitors/settings", methods=["GET", "POST"])
def competitors_settings():
    if request.method == "GET":
        return jsonify(_public_settings(collector.load_settings()))
    body = request.get_json(force=True)
    for key in SECRET_SETTINGS:
        if key in body and not body[key]:
            body.pop(key)  # пустое поле = «не менять сохранённый ключ»
        if body.get(f"clear_{key}"):
            body[key] = ""
    try:
        saved = collector.save_settings(body)
    except (TypeError, ValueError):
        return jsonify({"error": "Интервал должен быть числом минут"}), 400
    return jsonify(_public_settings(saved))


@app.route("/api/competitors/sources", methods=["GET", "POST"])
def competitors_sources():
    if request.method == "GET":
        return jsonify(collector.load_sources())
    sources = request.get_json(force=True)
    if not isinstance(sources, list):
        return jsonify({"error": "Ожидается список площадок"}), 400
    for s in sources:
        if s.get("type") == "vladimirkoncert" and s.get("site", vladimirkoncert.DEFAULT_SITE) not in vladimirkoncert.SITES:
            return jsonify({"error": f"Неизвестный билетный сайт: {s.get('site')}"}), 400
    old = {s.get("id"): s for s in collector.load_sources()}
    collector.save_sources(sources)
    # Что поменялось — в сообщение коммита; затем список уходит на GitHub, где идёт сбор
    new = {s.get("id"): s for s in sources}
    on = lambda s: s.get("enabled", True)
    changes = ([f"+ {new[i]['name']}" for i in new if i not in old] +
               [f"− {old[i]['name']}" for i in old if i not in new] +
               [("включена " if on(new[i]) else "выключена ") + new[i]["name"] for i in new if i in old and on(new[i]) != on(old[i])])
    sync.publish_sources(", ".join(changes) or "список обновлён", collector.log)
    return jsonify(sources)


@app.route("/api/competitors/sites")
def competitors_sites():
    """Билетные сайты на движке vladimirkoncert: адрес, подпись, город по умолчанию."""
    return jsonify([{"site": k, "label": v[0], "city": v[1]} for k, v in vladimirkoncert.SITES.items()])


@app.route("/api/competitors/vk_venues")
def competitors_vk_venues():
    site = request.args.get("site", vladimirkoncert.DEFAULT_SITE)
    if site not in vladimirkoncert.SITES:
        return jsonify({"error": f"Неизвестный билетный сайт: {site}"}), 400
    try:
        return jsonify(vladimirkoncert.list_venues(site))
    except Exception as e:
        return jsonify({"error": f"Не удалось получить список площадок с {site}: {e}"}), 502


@app.route("/api/competitors/classify", methods=["POST"])
def competitors_classify():
    body = request.get_json(force=True)
    if not body.get("title"):
        return jsonify({"error": "Не указано название"}), 400
    collector.set_override(body["title"], body)
    return jsonify({"ok": True})


@app.route("/api/competitors/halls")
def competitors_halls():
    return jsonify(collector.load_halls())


@app.route("/api/competitors/halls/<layout>", methods=["POST"])
def competitors_hall_reserve(layout):
    body = request.get_json(force=True)
    if layout not in collector.load_halls():
        return jsonify({"error": "Зал не найден"}), 404
    collector.save_hall_reserve(layout, body.get("auto", True), body.get("rows", []))
    hall = collector.load_halls()[layout]
    # Сбор на GitHub пересчитывает вал по config/hall_reserve.json — отправляем туда же
    sync.publish_files(["config/hall_reserve.json"], f"Бронь зала: {hall['name']}", collector.log)
    return jsonify(hall)


@app.route("/analytics")
def analytics_page():
    return (BASE_DIR / "static" / "analytics.html").read_text(encoding="utf-8")


@app.route("/api/analytics")
def analytics_data():
    events = edits.apply(collector.load_events().values())  # с ручными правками и своими событиями
    sales = collector.sales_by_day()
    for e in events:
        e["sales_by_day"] = sales.get(collector.seat_state_path(e["uid"]).stem, {})
        e.pop("description", None)  # не нужно странице, экономим объём
    return jsonify({"events": events, "taxonomy": {"sphere": SPHERES}, "status": collector.load_status()})


@app.route("/api/competitors/export.csv")
def competitors_export_csv():
    mem = io.BytesIO(collector.export_csv_bytes(include_past=request.args.get("past") == "1"))
    return send_file(
        mem, mimetype="text/csv", as_attachment=True,
        download_name=f"competitors_{date.today().isoformat()}.csv",
    )


@app.route("/api/competitors/export_sheets", methods=["POST"])
def competitors_export_sheets():
    url = collector.load_settings().get("sheets_webhook_url")
    if not url:
        return jsonify({"error": "Не задана ссылка на веб-приложение Google Таблицы"}), 400
    try:
        message = collector.export_to_sheets(url, include_past=request.args.get("past") == "1")
    except Exception as e:
        return jsonify({"error": f"Выгрузка не удалась: {e}"}), 502
    return jsonify({"ok": True, "message": message})


if __name__ == "__main__":
    compressed, freed = rotate_raw()
    if compressed:
        print(f"Сжато старых сырых снимков: {compressed}, освобождено {freed / 1024 / 1024:.0f} МБ.")
    collector.start_scheduler()
    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5050")).start()
    app.run(port=5050, debug=False, threaded=True)
