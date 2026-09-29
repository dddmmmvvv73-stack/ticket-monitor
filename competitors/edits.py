"""
Ручные правки мероприятий и свои события — отдельно от данных парсера.

Таблица парсера (data/competitors/events.json) перезаписывается при каждом сборе,
поэтому правки лежат в config/event_edits.json и накладываются сверху при чтении:
в интерфейсе, аналитике и выгрузке. Для спарсенного мероприятия хранятся только
отличия от парсера — остальные поля продолжают обновляться сборами.

Ниша (сфера / формат / жанр) здесь не хранится: её правка идёт в
classification_overrides.json — по названию, сразу для всех дат (см. api.py).

Формат файла:
    {"by_uid": {uid: {"fields": {поле: значение}, "at": iso}},
     "custom": [{"uid": "custom:1", "created": iso, поле: значение, …}],
     "next_id": 2}
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime
from typing import Iterable

from competitors.classifier import FORMATS, GENRES, SPHERES
from competitors.storage import CONFIG_DIR, load_json, save_json

EDITS_FILE = CONFIG_DIR / "event_edits.json"
CUSTOM_PREFIX = "custom:"

NICHE_FIELDS = ("sphere", "format", "genre")
INT_FIELDS = ("price_min", "price_max", "seats_sellable", "seats_taken_sellable", "gross", "revenue_est")
TEXT_FIELDS = ("title", "date", "time", "city", "venue", "price_text", "url")
EDITABLE = (*TEXT_FIELDS, *NICHE_FIELDS, *INT_FIELDS, "pushkin")
REQUIRED = ("title", "date", "venue")
TAXONOMY = {"sphere": SPHERES, "format": FORMATS, "genre": GENRES}

_lock = threading.Lock()


class EditError(ValueError):
    """Ошибки формы: {поле: текст для пользователя}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def is_custom(uid: str) -> bool:
    return uid.startswith(CUSTOM_PREFIX)


def _load() -> dict:
    data = load_json(EDITS_FILE, {})
    return {"by_uid": data.get("by_uid", {}), "custom": data.get("custom", []), "next_id": data.get("next_id", 1)}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- проверка

def clean(body: dict) -> dict:
    """Приводит пришедшие поля к типам. Неизвестные поля отбрасываются."""
    values, errors = {}, {}
    for field in EDITABLE:
        if field not in body:
            continue
        raw = body[field]
        if field in INT_FIELDS:
            if raw is None or raw == "":
                values[field] = None
                continue
            try:
                number = round(float(raw))
            except (TypeError, ValueError):
                errors[field] = "Нужно число"
                continue
            if number < 0:
                errors[field] = "Не может быть меньше нуля"
            values[field] = number
        elif field == "pushkin":
            values[field] = bool(raw)
        else:
            values[field] = str(raw if raw is not None else "").strip()

    if values.get("date"):
        try:
            date.fromisoformat(values["date"])
        except ValueError:
            errors["date"] = "Дата в формате ГГГГ-ММ-ДД"
    if values.get("time") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", values["time"]):
        errors["time"] = "Время в формате ЧЧ:ММ"
    if values.get("url") and not re.match(r"https?://", values["url"]):
        errors["url"] = "Ссылка должна начинаться с http:// или https://"
    for field in NICHE_FIELDS:
        if values.get(field) and values[field] not in TAXONOMY[field]:
            errors[field] = "Нет в справочнике"
    if errors:
        raise EditError(errors)
    return values


def check(event: dict) -> None:
    """Проверки итогового мероприятия — те же, что в форме интерфейса."""
    errors = {}
    for field, text in (("title", "Впишите название"), ("date", "Укажите дату"), ("venue", "Укажите площадку")):
        if not event.get(field):
            errors[field] = text
    taken, sellable = event.get("seats_taken_sellable"), event.get("seats_sellable")
    if taken is not None and sellable is None:
        errors["seats_sellable"] = "Укажите, сколько мест в продаже"
    elif taken is not None and taken > sellable:
        errors["seats_taken_sellable"] = "Занято больше, чем мест в продаже"
    pmin, pmax = event.get("price_min"), event.get("price_max")
    if pmin is not None and pmax is not None and pmin > pmax:
        errors["price_max"] = "«До» меньше, чем «от»"
    if errors:
        raise EditError(errors)


def same(a, b) -> bool:
    """None и пустая строка — одно и то же «не указано»."""
    return ("" if a is None else a) == ("" if b is None else b)


# ---------------------------------------------------------------- наложение

def _custom_row(record: dict) -> dict:
    row = {field: None for field in EDITABLE}
    row.update(record)
    for field in NICHE_FIELDS:
        row[field] = row[field] or ""  # как у парсера: «не указано» — пустая строка
    row.update(
        source="custom", source_id="custom", custom=True, edited_at=None, edited_fields=[],
        niche_manual=True, class_source={f: "manual" for f in NICHE_FIELDS if record.get(f)},
        first_seen=record.get("created"), last_seen=record.get("updated") or record.get("created"),
    )
    return row


def apply(events: Iterable[dict]) -> list[dict]:
    """Данные парсера + правки + свои события. Исходные словари не меняются."""
    data = _load()
    result = []
    for event in events:
        row = dict(event)
        edit = data["by_uid"].get(row["uid"])
        row.update(
            custom=False,
            edited_at=edit["at"] if edit else None,
            edited_fields=sorted(edit["fields"]) if edit else [],
            niche_manual="manual" in (row.get("class_source") or {}).values(),
        )
        if edit:
            row.update(edit["fields"])
        result.append(row)
    result.extend(_custom_row(record) for record in data["custom"])
    return result


# ---------------------------------------------------------------- изменение

def save_parsed(uid: str, parsed: dict, values: dict) -> None:
    """
    Правка спарсенного мероприятия: хранятся только отличия от парсера.
    Поля ниши сюда не попадают — их сохраняет api.py через ручную классификацию.
    """
    values = {k: v for k, v in values.items() if k not in NICHE_FIELDS}
    with _lock:
        data = _load()
        previous = data["by_uid"].get(uid, {}).get("fields", {})
        fields = {**previous, **values}
        fields = {k: v for k, v in fields.items() if not same(v, parsed.get(k))}
        check({**parsed, **fields})
        if fields:
            data["by_uid"][uid] = {"fields": fields, "at": _now()}
        else:
            data["by_uid"].pop(uid, None)
        save_json(EDITS_FILE, data)


def revert(uid: str) -> None:
    with _lock:
        data = _load()
        if data["by_uid"].pop(uid, None) is not None:
            save_json(EDITS_FILE, data)


def create_custom(values: dict) -> str:
    record = {field: None for field in EDITABLE}
    record["pushkin"] = False
    record.update(values)
    check(record)
    with _lock:
        data = _load()
        uid = f"{CUSTOM_PREFIX}{data['next_id']}"
        data["next_id"] += 1
        data["custom"].append({"uid": uid, "created": _now(), **record})
        save_json(EDITS_FILE, data)
    return uid


def update_custom(uid: str, values: dict) -> None:
    with _lock:
        data = _load()
        for record in data["custom"]:
            if record["uid"] == uid:
                merged = {**record, **values}
                check(merged)
                record.update(values, updated=_now())
                save_json(EDITS_FILE, data)
                return
    raise KeyError(uid)


def delete_custom(uid: str) -> None:
    with _lock:
        data = _load()
        kept = [r for r in data["custom"] if r["uid"] != uid]
        if len(kept) == len(data["custom"]):
            raise KeyError(uid)
        data["custom"] = kept
        save_json(EDITS_FILE, data)
