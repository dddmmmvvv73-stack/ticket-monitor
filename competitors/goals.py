"""Validation for the approved Goals UI. Records live in work.json and its journal/backups."""
from __future__ import annotations

import math
import re
from datetime import date


def validate(kind, value):
    from competitors.work import WorkError

    def fail(message):
        raise WorkError("Цели: " + message)

    def text(v, limit=300, required=False):
        if not isinstance(v, str) or len(v) > limit or (required and not v.strip()):
            fail("неверный или слишком длинный текст")
        return v.strip()

    def num(v):
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v) > 1e15:
            fail("нужно конечное число")
        return v

    def day(v, optional=False):
        if optional and not v:
            return ""
        try:
            if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError()
            date.fromisoformat(v)
        except (ValueError, TypeError):
            fail("неверная дата")
        return v

    def ident(v):
        if not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", v):
            fail("неверный номер записи")
        return v

    def choice(v, options):
        if v not in options:
            fail("неизвестное значение")
        return v

    def flag(v):
        if not isinstance(v, bool):
            fail("нужно логическое значение")
        return v

    def rows(v, limit):
        if not isinstance(v, list) or len(v) > limit or any(not isinstance(x, dict) for x in v):
            fail("неверный или слишком большой список")
        return v

    def unique(items):
        ids = [x["id"] for x in items]
        if len(ids) != len(set(ids)):
            fail("номера записей не должны повторяться")
        return items

    if kind == "goalvision":
        horizon = text(value.get("horizon", ""), 4, True)
        if not re.fullmatch(r"[1-9]\d{3}", horizon):
            fail("укажите год четырьмя цифрами")
        return {"text": text(value.get("text", ""), 10000), "horizon": horizon}

    out = {"title": text(value.get("title", ""), required=True), "why": text(value.get("why", ""), 10000),
           "sphere": choice(value.get("sphere"), ["biz", "money", "art", "team", "life"]),
           "status": choice(value.get("status"), ["active", "done", "drop"]),
           "start": day(value.get("start")), "deadline": day(value.get("deadline"))}
    if out["deadline"] < out["start"]:
        fail("срок раньше начала")
    if value.get("doneAt"):
        out["doneAt"] = day(value["doneAt"])
    projects = value.get("projects", [])
    if not isinstance(projects, list) or len(projects) > 200:
        fail("неверный список проектов")
    out["projects"] = list(dict.fromkeys(ident(x) for x in projects))
    out["krs"] = unique([{
        "id": ident(k.get("id")), "title": text(k.get("title"), required=True),
        "unit": choice(k.get("unit"), ["шт.", "₽", "%", "да/нет", "раз", "часов", "дней", "человек"]),
        "start": num(k.get("start")), "target": num(k.get("target")), "cur": num(k.get("cur")),
        "auto": choice(k.get("auto") or "", ["", "shows", "docs", "projects"]),
    } for k in rows(value.get("krs"), 50)])
    if not out["krs"]:
        fail("нужен измеримый результат")
    for k in out["krs"]:
        if k["target"] == k["start"]:
            fail("начало и цель результата должны различаться")
        if k["auto"] and k["unit"] != "шт.":
            fail("автоматический результат измеряется в штуках")
    out["stages"] = []
    for s in rows(value.get("stages", []), 200):
        steps = []
        for x in rows(s.get("steps", []), 500):
            r = {"id": ident(x.get("id")), "t": text(x.get("t"), 1000, True), "done": flag(x.get("done", False)), "due": day(x.get("due"), True)}
            if x.get("doneAt"):
                r["doneAt"] = day(x["doneAt"])
            if x.get("task"):
                r["task"] = ident(x["task"])
            steps.append(r)
        out["stages"].append({"id": ident(s.get("id")), "title": text(s.get("title"), required=True), "due": day(s.get("due")), "steps": unique(steps)})
    unique(out["stages"])
    out["habits"] = []
    for h in rows(value.get("habits", []), 100):
        per = num(h.get("per"))
        if not 1 <= per <= 99 or per != int(per):
            fail("частота — целое число от 1 до 99")
        log = h.get("log", {})
        if not isinstance(log, dict) or len(log) > 5200:
            fail("неверный журнал регулярных действий")
        for at, n in log.items():
            day(at)
            if not 0 <= num(n) <= 99 or n != int(n):
                fail("неверное число действий")
        out["habits"].append({"id": ident(h.get("id")), "title": text(h.get("title"), required=True), "per": per, "log": log})
    unique(out["habits"])
    out["checkins"] = []
    for c in rows(value.get("checkins", []), 10000):
        vals = c.get("vals", {})
        if not isinstance(vals, dict) or len(vals) > 500:
            fail("неверная отметка прогресса")
        out["checkins"].append({"at": day(c.get("at")), "vals": {ident(k): num(v) for k, v in vals.items()},
                                "conf": choice(c.get("conf"), ["ok", "risk", "bad"]),
                                "note": text(c.get("note", ""), 10000), "next": text(c.get("next", ""), 1000)})
    return out
