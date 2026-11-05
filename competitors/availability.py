"""Общие ответы площадок, прозвон и наши резервы. config/venue_availability.json — вне git, в копиях config/."""
from __future__ import annotations

import calendar
import re
import secrets
import threading
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from competitors import venuebook
from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "venue_availability.json"
KINDS = ("reports", "bookings", "requests")
_lock = threading.RLock()
bp = Blueprint("availability", __name__)


class AvailabilityError(ValueError):
    pass


def load():
    data = load_json(FILE, {})
    return {k: data.get(k, {}) for k in KINDS}


def read():
    data = load()
    data["venues"] = [{k: r.get(k, "") for k in ("id", "city", "name", "contact", "phone", "email")}
                      for r in venuebook.load().get("rows", [])]
    return data


def text(v, size=2000):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > size:
        raise AvailabilityError("Слишком длинный или неверный текст")
    return v.strip()


def day(v, optional=False):
    v = text(v, 10)
    if not v and optional:
        return ""
    try:
        if date.fromisoformat(v).isoformat() != v:
            raise ValueError()
    except ValueError:
        raise AvailabilityError("Укажите дату в формате ГГГГ-ММ-ДД")
    return v


def month(v):
    v = text(v, 7)
    day(v + "-01")
    return v


def enum(v, choices):
    if v not in choices:
        raise AvailabilityError("Недопустимый статус")
    return v


def days(values, ym):
    end = calendar.monthrange(int(ym[:4]), int(ym[5:]))[1]
    if not isinstance(values, list) or len(values) > 31 or any(type(v) is not int or not 1 <= v <= end for v in values):
        raise AvailabilityError("В списке есть день, которого нет в выбранном месяце")
    return sorted(set(values))


def venue(vid):
    vid = text(vid, 40)
    r = next((r for r in venuebook.load().get("rows", []) if r.get("id") == vid), None)
    if not r:
        raise AvailabilityError("Выберите площадку из справочника")
    return {"venue": vid, "venue_name": r["name"], "city": r["city"]}


def clean(kind, d):
    if not isinstance(d, dict):
        raise AvailabilityError("Неверная запись")
    r = venue(d.get("venue"))
    for field in ("contact", "author", "note", "artist", "project"):
        r[field] = text(d.get(field), 2000 if field == "note" else 300)
    if kind == "reports":
        r.update(month=month(d.get("month")), mode=enum(d.get("mode"), ("full", "partial")),
                 asof=day(d.get("asof")), void=False)
        if r["asof"] > date.today().isoformat():
            raise AvailabilityError("Дата ответа не может быть в будущем")
        r["free"], r["busy"] = days(d.get("free", []), r["month"]), days(d.get("busy", []), r["month"])
        if set(r["free"]) & set(r["busy"]):
            raise AvailabilityError("Дата не может быть одновременно свободной и занятой")
        if r["mode"] == "partial" and not r["free"] and not r["busy"]:
            raise AvailabilityError("Для частичного ответа укажите хотя бы одну проверенную дату")
    elif kind == "bookings":
        r.update(date=day(d.get("date")), status=enum(d.get("status"), ("hold", "confirmed", "cancelled")),
                 until=day(d.get("until"), True))
        if not r["artist"]:
            raise AvailabilityError("Укажите артиста или название проекта")
        if r["until"] and r["until"] > r["date"]:
            raise AvailabilityError("Срок подтверждения не может быть позже мероприятия")
    else:
        r.update(month=month(d.get("month")), status=enum(d.get("status", "call"), ("call", "waiting", "answered")),
                 next=day(d.get("next"), True))
    return r


def validate_state(data):
    occupied = set()
    for r in data.get("bookings", {}).values():
        if r.get("status") not in ("hold", "confirmed"):
            continue
        slot = (r["venue"], r["date"])
        if slot in occupied:
            raise AvailabilityError("На эту дату уже есть наш резерв или бронь. Сначала снимите прежнюю договорённость.")
        occupied.add(slot)


def apply_op(op):
    if not isinstance(op, dict):
        raise AvailabilityError("Неверная операция")
    kind, action = op.get("kind"), op.get("op")
    if kind not in KINDS:
        raise AvailabilityError("Неизвестный вид записи")
    from competitors import journal
    with _lock:
        before = journal.snapshot("availability")
        data = load()
        now = datetime.now().isoformat(timespec="microseconds")
        oid = text(op.get("id"), 40)
        if oid and not re.fullmatch(r"[a-z0-9]{1,40}", oid):
            raise AvailabilityError("Неверный номер записи")
        old = data[kind].get(oid)
        if oid and not old:
            raise AvailabilityError("Запись удалена. Обновите раздел.")
        if old and ("expected" not in op or op["expected"] != old):
            raise AvailabilityError("Запись уже изменена в другой вкладке. Обновите раздел перед правкой.")
        if action == "request_batch" and kind == "requests":
            vids, months = op.get("venues"), op.get("months")
            if not isinstance(vids, list) or not isinstance(months, list) or not vids or not months or len(vids) * len(months) > 1000:
                raise AvailabilityError("Выберите площадки и месяцы (до 1000 запросов)")
            if any(not isinstance(v, str) for v in vids + months) or not isinstance(op.get("data", {}), dict):
                raise AvailabilityError("Неверный список площадок или месяцев")
            for vid in set(vids):
                for ym in set(months):
                    rec = clean(kind, dict(op.get("data") or {}, venue=vid, month=ym))
                    if any(r["venue"] == rec["venue"] and r["month"] == rec["month"] and r["artist"] == rec["artist"]
                           and r.get("project", "") == rec["project"] and r["status"] != "answered" for r in data[kind].values()):
                        continue
                    data[kind]["q" + secrets.token_hex(8)] = dict(rec, created=now, upd=now)
        elif action == "void" and kind == "reports" and old:
            data[kind][oid] = dict(old, void=True, upd=now)
            for key, q in list(data["requests"].items()):
                if q.get("response") == oid:
                    alternatives = [(rid, r) for rid, r in data["reports"].items()
                                    if not r.get("void") and r["mode"] == "full" and r["venue"] == q["venue"]
                                    and r["month"] == q["month"] and r["asof"] >= q["created"][:10]]
                    if alternatives:
                        rid, _ = max(alternatives, key=lambda item: (item[1]["asof"], item[1]["created"]))
                        data["requests"][key] = dict(q, response=rid, upd=now)
                        continue
                    q = dict(q, status=q.get("response_prev", "waiting"), upd=now)
                    q.pop("response", None)
                    q.pop("response_prev", None)
                    data["requests"][key] = q
        elif action == "put":
            if kind == "reports" and oid:
                raise AvailabilityError("Ответы сохраняются в истории. Добавьте новый ответ или отмените ошибочный.")
            rec = clean(kind, op.get("data"))
            if kind == "bookings":
                rec["status_at"] = now if not old or old["status"] != rec["status"] else old["status_at"]
                rec["confirmation"] = "В разговоре" if rec["status"] == "confirmed" else ""
            oid = oid or kind[0] + secrets.token_hex(8)
            data[kind][oid] = dict(rec, created=old["created"] if old else now, upd=now)
            if kind == "reports" and rec["mode"] == "full":
                # Один общий ответ закрывает ожидающие запросы разных артистов за этот месяц.
                for key, q in list(data["requests"].items()):
                    if (q["venue"] == rec["venue"] and q["month"] == rec["month"] and q["status"] != "answered"
                            and rec["asof"] >= q["created"][:10]):
                        data["requests"][key] = dict(q, status="answered", response=oid, response_prev=q["status"], upd=now)
        else:
            raise AvailabilityError("Неизвестная операция")
        validate_state(data)
        save_json(FILE, data)
        journal.record("availability", before)
        return read()


@bp.get("/api/availability")
def availability_get():
    response = jsonify(read())
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/api/availability")
def availability_post():
    try:
        return jsonify(apply_op(request.get_json(silent=True)))
    except AvailabilityError as e:
        return jsonify(error=str(e)), 400
