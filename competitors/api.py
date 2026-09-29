"""
API нового интерфейса (static/app/): мероприятия с ручными правками и свои события.

    GET    /api/events?past=1          мероприятия (парсер + правки + свои), справочник, статус сбора
    POST   /api/events                 добавить своё событие
    PATCH  /api/events/<uid>           исправить мероприятие (своё или спарсенное)
    DELETE /api/events/<uid>           удалить своё событие
    POST   /api/events/<uid>/revert    вернуть данные парсера

Поля — как в data/competitors/events.json (price_min, seats_sellable, revenue_est…).
Ошибки проверки: 400 {"errors": {поле: текст}}.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from competitors import collector, edits
from competitors.classifier import FORMATS, GENRES, SPHERES

bp = Blueprint("app_api", __name__, url_prefix="/api")


def _event(uid: str) -> dict | None:
    return next((e for e in edits.apply(collector.load_events().values()) if e["uid"] == uid), None)


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _save_niche(parsed: dict, values: dict) -> None:
    """Ниша спарсенного мероприятия правится по названию — сразу для всех его дат."""
    niche = {f: values.get(f, parsed.get(f) or "") for f in edits.NICHE_FIELDS}
    if any(not edits.same(niche[f], parsed.get(f)) for f in edits.NICHE_FIELDS):
        collector.set_override(parsed["title"], niche)


@bp.errorhandler(edits.EditError)
def _edit_error(e: edits.EditError):
    return jsonify({"errors": e.errors}), 400


@bp.get("/events")
def events_list():
    return jsonify({
        "events": collector.visible_events(request.args.get("past") == "1"),
        "taxonomy": {"sphere": SPHERES, "format": FORMATS, "genre": GENRES},
        "today": date.today().isoformat(),
        "status": collector.status_snapshot(),
    })


@bp.post("/events")
def events_create():
    uid = edits.create_custom(edits.clean(_body()))
    return jsonify(_event(uid)), 201


@bp.patch("/events/<path:uid>")
def events_update(uid):
    values = edits.clean(_body())
    if edits.is_custom(uid):
        try:
            edits.update_custom(uid, values)
        except KeyError:
            return jsonify({"error": "Событие не найдено"}), 404
        return jsonify(_event(uid))

    parsed = collector.load_events().get(uid)
    if parsed is None:
        return jsonify({"error": "Мероприятие не найдено"}), 404
    edits.save_parsed(uid, parsed, values)  # сначала проверки и поля, потом ниша
    _save_niche(parsed, values)
    return jsonify(_event(uid))


@bp.delete("/events/<path:uid>")
def events_delete(uid):
    if not edits.is_custom(uid):
        return jsonify({"error": "Удалить можно только своё событие"}), 400
    try:
        edits.delete_custom(uid)
    except KeyError:
        return jsonify({"error": "Событие не найдено"}), 404
    return jsonify({"ok": True})


@bp.post("/events/<path:uid>/revert")
def events_revert(uid):
    parsed = collector.load_events().get(uid)
    if parsed is None:
        return jsonify({"error": "Мероприятие не найдено"}), 404
    edits.revert(uid)
    if "manual" in (parsed.get("class_source") or {}).values():
        collector.set_override(parsed["title"], {})  # ниша снова по правилам и нейросети
    return jsonify(_event(uid))
