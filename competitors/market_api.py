"""
Прототип нового интерфейса через приложение и ручная разметка «Афиши рынка».

    GET  /proto/                  прототип (Design/prototype/index.html); открытый так, он сохраняет правки
    GET  /proto/market-data.js    снимок рынка — собирается из data/competitors/market при каждом открытии
    GET  /proto/competitors-data.js  мероприятия, залы и продажи конкурентов — из data/competitors (competitors/protodata.py)
    GET  /api/market/curation     разметка: проекты, площадки, правки мероприятий, фильтры
    POST /api/market/curation     одна правка {"op": "project"|"venue"|"edit"|"revert"|"filters"|"niche", …}

Каждая правка сразу записывается в config/ и в фоне отправляется на GitHub (competitors/sync.py),
поэтому сбор на сервере применяет её с ближайшего запуска. Ошибки проверки — 400 {"error": текст}.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, redirect, request, send_from_directory

from competitors import collector, curation, edits, market, protodata, sync
from competitors.classifier import FORMATS, GENRES, SPHERES
from competitors.storage import BASE_DIR, load_json

bp = Blueprint("market_api", __name__)
PROTOTYPE_DIR = BASE_DIR / "Design" / "prototype"
_cache = {"key": None, "js": ""}
_cd_cache = {"key": None, "js": ""}


@bp.get("/proto")
def proto_root():
    return redirect("/proto/")


@bp.get("/proto/")
def proto_index():
    return send_from_directory(PROTOTYPE_DIR, "index.html", max_age=0)


@bp.get("/proto/market-data.js")
def proto_market_data():
    # Свежие данные после ./pull_data.sh без отдельной команды экспорта; пересобираем, только если данные изменились
    files = [market.EVENTS_FILE, market.STATUS_FILE, market.ARCHIVE_FILE]
    key = tuple(f.stat().st_mtime if f.exists() else 0 for f in files)
    if _cache["key"] != key:
        try:
            _cache.update(key=key, js=market.export_js())
        except RuntimeError:
            return send_from_directory(PROTOTYPE_DIR, "market-data.js", max_age=0)  # данных нет — последний снимок
    return Response(_cache["js"], mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.get("/proto/competitors-data.js")
def proto_competitors_data():
    # Как и рынок: после ./pull_data.sh страница показывает свежий сбор, пересобираем только при изменениях
    files = [collector.EVENTS_FILE, collector.STATUS_FILE, collector.HALLS_FILE, collector.LOG_FILE, edits.EDITS_FILE]
    key = tuple(f.stat().st_mtime if f.exists() else 0 for f in files)
    if _cd_cache["key"] != key:
        try:
            _cd_cache.update(key=key, js=protodata.export_js())
        except RuntimeError:
            return send_from_directory(PROTOTYPE_DIR, "competitors-data.js", max_age=0)  # данных нет — последний снимок
    return Response(_cd_cache["js"], mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.get("/proto/<path:name>")
def proto_file(name: str):
    return send_from_directory(PROTOTYPE_DIR, name, max_age=0)


@bp.get("/api/market/curation")
def curation_get():
    return jsonify({"curation": curation.load(), "niche": load_json(collector.OVERRIDES_FILE, {}),
                    "taxonomy": {"sphere": SPHERES, "format": FORMATS, "genre": GENRES}})


@bp.post("/api/market/curation")
def curation_post():
    op = request.get_json(silent=True) or {}
    try:
        if op.get("op") == "niche":
            # Ниша правится по названию — сразу для всех дат, общий файл со сбором конкурентов
            values = {f: str(op.get(f) or "") for f in ("sphere", "format", "genre")}
            if not str(op.get("title") or "").strip():
                raise curation.CurationError("нет названия")
            collector.set_override(op["title"], values)
            sync.publish_files(["config/classification_overrides.json"], f"Ниша: «{op['title']}»", collector.log)
            return jsonify({"curation": curation.load(), "niche": load_json(collector.OVERRIDES_FILE, {})})
        cur, note = curation.apply_op(op)
    except curation.CurationError as e:
        return jsonify({"error": str(e)}), 400
    sync.publish_files([str(curation.FILE.relative_to(BASE_DIR))], f"Рынок: {note}", collector.log)
    return jsonify({"curation": cur})
