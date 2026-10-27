"""
Ссылки для руководителя: снимок предложения по городам и комментарии к нему (CITY_PICK_PLAN.md, п. 2.8; решение
пользователя 26.10.2026 — «и ссылка с комментариями, и PDF»).

Организатор во вкладке «Предложение» создаёт снимок (браузер собирает те же строки и цифры, что идут в PDF —
offer-doc.js); снимок сохраняется версией, правки подбора её не меняют. Руководитель открывает ссылку на отдельном
маленьком сервере share_app.py (только /s/<token>) и оставляет решение по городу и комментарии.

Хранится в config/shares/<token>.json — вне git (гонорары; репозиторий публичный), в часовой закрытой копии (db.offsite):
    {"token", "list", "title", "created", "closed", "prev", "next", "snapshot": {…},
     "comments": [{"city" — "" для общего, "name", "text", "decision": ok | ask | no | "", "at"}]}
config/shares/_settings.json — {"base": адрес, с которого руководитель открывает ссылки}.

Основной сайт (только этот компьютер):
    POST /api/shares                 {"list", "snapshot"} → новая версия; у прошлой версии этого списка — "next"
    GET  /api/shares?list=…          версии списка с комментариями и адрес для ссылок
    GET  /api/shares/summary         по всем спискам сразу — для таблицы артистов «Подбора городов»
    POST /api/shares/<token>/close   закрыть ссылку
    POST /api/shares/base            {"base"} — адрес для ссылок (после настройки внешнего доступа)
"""

from __future__ import annotations

import fcntl
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime

from flask import Blueprint, jsonify, request

from competitors.storage import CONFIG_DIR

DIR = CONFIG_DIR / "shares"
SETTINGS = DIR / "_settings.json"
DEFAULT_BASE = "http://127.0.0.1:5070"   # share_app.py; снаружи — после Tailscale Funnel (CITY_PICK_PLAN.md, этап 8)
SNAP_MAX = 1_000_000                     # байт снимка
TEXT_MAX, NAME_MAX, COMMENTS_MAX = 2000, 80, 2000
DECISIONS = ("", "ok", "ask", "no")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,40}$")

bp = Blueprint("shares", __name__)


class ShareError(ValueError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _path(token: str):
    if not _TOKEN.match(token or ""):
        raise ShareError("нет такой ссылки")
    return DIR / f"{token}.json"


@contextmanager
def _locked(token: str):
    """Запись одной ссылки под замком: сайт (закрыть, новая версия) и share_app (комментарии) — разные процессы."""
    p = _path(token)
    if not p.exists():
        raise ShareError("нет такой ссылки")
    with open(p, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        d = json.load(f)
        yield d
        f.seek(0)
        f.truncate()
        json.dump(d, f, ensure_ascii=False, indent=1)


def load(token: str) -> dict | None:
    try:
        p = _path(token)
    except ShareError:
        return None
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        return json.load(f)


def base() -> str:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8")).get("base") or DEFAULT_BASE
    except (OSError, ValueError):
        return DEFAULT_BASE


def set_base(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if url and not re.match(r"^https?://[^\s/]+(:\d+)?$", url):
        raise ShareError("адрес вида https://имя.сеть.ts.net")
    DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({"base": url}, ensure_ascii=False), encoding="utf-8")
    return url or DEFAULT_BASE


def versions(list_id: str) -> list[dict]:
    out = []
    for p in DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        d = load(p.stem)
        if d and d.get("list") == list_id:
            out.append(d)
    out.sort(key=lambda d: d.get("created", ""), reverse=True)
    return out


def create(list_id: str, snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("rows"), list) or not snapshot["rows"]:
        raise ShareError("в предложении нет городов")
    if len(json.dumps(snapshot, ensure_ascii=False).encode()) > SNAP_MAX:
        raise ShareError("снимок больше 1 МБ")
    list_id = str(list_id or "")[:40]
    DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    prev = next((v for v in versions(list_id) if not v.get("next")), None)
    d = {"token": token, "list": list_id, "title": str(snapshot.get("who") or snapshot.get("title") or "")[:200], "created": _now(),
         "closed": None, "prev": prev["token"] if prev else None, "next": None, "snapshot": snapshot, "comments": []}
    _path(token).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    if prev:
        with _locked(prev["token"]) as p:
            p["next"] = token
    return d


def close(token: str) -> dict:
    with _locked(token) as d:
        d["closed"] = d.get("closed") or _now()
    return d


def add_comment(token: str, city: str, name: str, text: str, decision: str) -> dict:
    """Комментарий или решение руководителя. Город — из снимка или "" (общий)."""
    name, text, city, decision = str(name or "").strip()[:NAME_MAX], str(text or "").strip(), str(city or ""), str(decision or "")
    if len(text) > TEXT_MAX:
        raise ShareError(f"комментарий длиннее {TEXT_MAX} знаков")
    if decision not in DECISIONS:
        raise ShareError("неизвестное решение")
    if not text and not decision:
        raise ShareError("пустой комментарий")
    if not name:
        raise ShareError("укажите имя")
    with _locked(token) as d:
        if d.get("closed"):
            raise ShareError("ссылка закрыта")
        if city and city not in {r.get("city") for r in d["snapshot"].get("rows", [])}:
            raise ShareError("нет такого города в предложении")
        if len(d["comments"]) >= COMMENTS_MAX:
            raise ShareError("слишком много комментариев")
        d["comments"].append({"city": city, "name": name, "text": text, "decision": decision, "at": _now()})
    return d


def summary() -> dict:
    """По каждому списку: версий, есть ли открытая, дата последней, последние решения руководителя по городам (ok / ask / no),
    комментариев, когда последний, и токены с датой последнего комментария — браузер считает новые."""
    out: dict = {}
    for p in DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        d = load(p.stem)
        if not d:
            continue
        o = out.setdefault(d.get("list") or "", {"versions": 0, "open": False, "created": "", "dec": {}, "comments": 0, "last_at": "", "tokens": []})
        o["versions"] += 1
        o["open"] = o["open"] or not d.get("closed")
        o["created"] = max(o["created"], d.get("created") or "")
        cs = d.get("comments") or []
        o["comments"] += len(cs)
        last = max((c.get("at") or "" for c in cs), default="")
        o["last_at"] = max(o["last_at"], last)
        o["tokens"].append({"token": d["token"], "last_at": last, "created": d.get("created") or ""})
        for c in cs:
            if c.get("city") and c.get("decision"):
                prev = o["dec"].get(c["city"])
                if not prev or c["at"] >= prev[1]:
                    o["dec"][c["city"]] = [c["decision"], c["at"]]
    for o in out.values():
        n = {"ok": 0, "ask": 0, "no": 0}
        for dec, _ in o.pop("dec").values():
            n[dec] = n.get(dec, 0) + 1
        o.update(n)
    return out


def _brief(d: dict) -> dict:
    return {k: d.get(k) for k in ("token", "list", "title", "created", "closed", "prev", "next", "comments")} | {"cities": len(d["snapshot"].get("rows", []))}


@bp.post("/api/shares")
def api_create():
    body = request.get_json(silent=True) or {}
    try:
        d = create(body.get("list"), body.get("snapshot"))
    except ShareError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "share": _brief(d), "base": base()})


@bp.get("/api/shares/summary")
def api_summary():
    return jsonify({"base": base(), "lists": summary()})


@bp.get("/api/shares")
def api_list():
    return jsonify({"base": base(), "shares": [_brief(d) for d in versions(request.args.get("list", ""))]})


@bp.post("/api/shares/<token>/close")
def api_close(token: str):
    try:
        d = close(token)
    except ShareError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "share": _brief(d)})


@bp.post("/api/shares/base")
def api_base():
    try:
        b = set_base((request.get_json(silent=True) or {}).get("base"))
    except ShareError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "base": b})
