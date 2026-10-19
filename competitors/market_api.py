"""
Прототип нового интерфейса через приложение и ручная разметка «Афиши рынка».

    GET  /proto/                  прототип (Design/prototype/index.html); открытый так, он сохраняет правки
    GET  /proto/market-data.js    снимок рынка — собирается из data/competitors/market при каждом открытии
    GET  /proto/competitors-data.js  мероприятия, залы и продажи конкурентов — из data/competitors (competitors/protodata.py)
    GET  /api/market/curation     разметка: проекты, площадки, правки мероприятий, фильтры
    POST /api/market/curation     одна правка {"op": "project"|"venue"|"edit"|"revert"|"filters"|"niche", …}
    GET  /api/market/myprojects   избранные проекты и ваши записи о них (competitors/myprojects.py)
    POST /api/market/myprojects   одна правка {"op": "fav"|"notes"|"profile"|"media"|"seen"|"link"|"skip", …}
    GET  /api/market/myprojects/media/<файл>   фото проекта (аватар, фон) из config/project_media/
    GET  /api/sales/detail?keys=… продажи сеанса для карточки — с сервера в Яндекс Облаке по SSH (sales/detail.py)
    GET  /proto/site-data.js      даты с официальных сайтов проектов (competitors/officialsite.py)
    POST /api/market/site/check   {"key"} — разобрать сайт проекта сейчас (кнопка «Проверить», ~10–40 с)
    GET  /proto/venue-cap.js      вместимость площадок по схемам касс (competitors/venuecap.py)
    GET  /proto/venue-book.js     справочник площадок: контакты и условия (competitors/venuebook.py; config/venue_book.json вне git)
    GET  /api/work                раздел «Проекты»: задачи, проекты, документы (competitors/work.py); POST — правка записи
    GET  /api/journal             журнал изменений (competitors/journal.py); POST /api/journal/restore {"id"} — вернуть правку
    POST /api/venuebook           правка площадки: поля, фото, технический райдер; GET /api/venuebook/file/<файл> — фото и райдер
    GET  /api/sales/feed?days=14  продажи по кассам для «Истории» и «Динамики продаж» (sales/feed.py) — из базы
    GET  /api/planning            «Планирование»: справочники и туры (competitors/planning.py; config/planning.json вне git)
    POST /api/planning            {"op": "put" | "del", "kind", "id", "data"}

Каждая правка сразу записывается в config/ и в фоне отправляется на GitHub (competitors/sync.py),
поэтому сбор на сервере применяет её с ближайшего запуска. Избранное и записи о проектах — только на этом
компьютере (config/my_projects.json вне git: там контакты). Ошибки проверки — 400 {"error": текст}.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime

from flask import Blueprint, Response, jsonify, redirect, request, send_file, send_from_directory

from competitors import collector, curation, edits, journal, market, myprojects, officialsite, planning, protodata, sync, venuebook, venuecap, work
from competitors.classifier import FORMATS, GENRES, SPHERES
from competitors.storage import BASE_DIR, ON_SERVER, load_json

bp = Blueprint("market_api", __name__)
SERVER_FILE = BASE_DIR / "config" / "server.json"   # {"ssh": "tm@<адрес>", "key": "~/.ssh/…"} — только на этом компьютере
_KEY = re.compile(r"^[kyd]:[\w:.@\-]{1,120}$")
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
    files = [market.EVENTS_FILE, market.STATUS_FILE, market.ARCHIVE_FILE, market.SALES_SNAPSHOT, collector.EVENTS_FILE]
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
    stamp = lambda: tuple(f.stat().st_mtime if f.exists() else 0 for f in files)
    key = stamp()
    if _cd_cache["key"] != key:
        try:
            js = protodata.export_js()
        except RuntimeError:
            return send_from_directory(PROTOTYPE_DIR, "competitors-data.js", max_age=0)  # данных нет — последний снимок
        # Файлы поменялись, пока собирали (пересчёт брони, правка) — отдаём, но не запоминаем: следующий запрос соберёт заново
        _cd_cache.update(key=key if stamp() == key else None, js=js)
    return Response(_cd_cache["js"], mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.get("/proto/site-data.js")
def proto_site_data():
    # Даты с официальных сайтов: файл разбора пишет сборщик (tm-sync каждый час, кнопка «Проверить») — отдаём свежим
    return Response(officialsite.export_js(), mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.get("/proto/venue-cap.js")
def proto_venue_cap():
    return Response(venuecap.export_js(), mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.get("/proto/venue-book.js")
def proto_venue_book():
    return Response(venuebook.export_js(), mimetype="application/javascript", headers={"Cache-Control": "no-store"})


@bp.post("/api/venuebook")
def venuebook_post():
    before = journal.snapshot("venues")
    try:
        row = venuebook.apply_op(request.get_json(silent=True) or {})   # не на GitHub: там контакты
    except venuebook.VenueBookError as e:
        return jsonify({"error": str(e)}), 400
    journal.record("venues", before)
    return jsonify({"row": row})


@bp.get("/api/work")
def work_get():
    return jsonify(work.load())


@bp.get("/api/work/file/<name>")
def work_file(name):
    path = work.media_file(name)
    if not path:
        return jsonify({"error": "нет такого файла"}), 404
    if request.args.get("dl"):   # «Скачать» — под именем, с которым загружали
        return send_file(path, as_attachment=True, download_name=work.doc_name(name), max_age=0)
    return send_file(path, max_age=0 if any(k in name for k in work.DOC_KINDS) else 86400)


@bp.post("/api/work")
def work_post():
    """Раздел «Проекты»: задачи, проекты, документы (competitors/work.py; config/work.json вне git)."""
    before = journal.snapshot("work")
    try:
        data = work.apply_op(request.get_json(silent=True) or {})
    except work.WorkError as e:
        return jsonify({"error": str(e)}), 400
    journal.record("work", before)
    return jsonify(data)


@bp.get("/api/journal")
def journal_get():
    """Журнал изменений (competitors/journal.py): последние правки, новые сверху; area / key — фильтр."""
    try:
        limit = max(1, min(1000, int(request.args.get("limit") or 200)))
    except ValueError:
        limit = 200
    return jsonify({"entries": journal.read(request.args.get("area") or "", request.args.get("key") or "", limit),
                    "areas": {k: a["label"] for k, a in journal.AREAS.items()}})


@bp.post("/api/journal/restore")
def journal_restore():
    try:
        return jsonify(journal.restore(str((request.get_json(silent=True) or {}).get("id") or "")))
    except journal.JournalError as e:
        return jsonify({"error": str(e)}), 400


@bp.get("/api/venuebook/file/<name>")
def venuebook_file(name):
    path = venuebook.media_file(name)
    if not path:
        return jsonify({"error": "нет такого файла"}), 404
    rider = name.split("-", 1)[1].startswith("rider")
    if rider:   # скачивается под тем именем, под которым вы его загружали
        rec = next((r for r in venuebook.load().get("rows", []) if (r.get("rider") or {}).get("file") == name), {})
        return send_file(path, as_attachment=True, download_name=(rec.get("rider") or {}).get("name") or name, max_age=0)
    return send_file(path, max_age=86400)


@bp.post("/api/market/site/check")
def site_check():
    """«Проверить»: разобрать страницу сайта проекта сейчас (страница → GigaChat → проверка). Ссылка уже сохранена (myprojects «site»)."""
    key = str((request.get_json(silent=True) or {}).get("key") or "")
    if key not in officialsite.configs():
        return jsonify({"error": "у проекта нет ссылки на сайт"}), 400
    data = officialsite.run(only=key, log=collector.log)
    return jsonify({"sites": officialsite.export(data), "error": (data.get(key) or {}).get("error", "")})


@bp.get("/api/planning")
def planning_get():
    return jsonify(planning.load())


@bp.post("/api/planning")
def planning_post():
    before = journal.snapshot("planning")
    try:
        data = planning.apply_op(request.get_json(silent=True) or {})
    except planning.PlanningError as e:
        return jsonify({"error": str(e)}), 400
    journal.record("planning", before)
    return jsonify(data)   # не отправляется на GitHub — репозиторий публичный, здесь гонорары и аренда


@bp.get("/api/sales/detail")
def sales_detail():
    """Продажи сеанса (кассы, снимки, зал по рядам, последние продажи) — спрашиваем сервер; данные в git не попадают."""
    keys = [k for k in (request.args.get("keys") or "").split(",") if _KEY.match(k)][:10]
    if not keys:
        return jsonify(error="нет номеров карточек"), 400
    cfg = load_json(SERVER_FILE, {})
    if ON_SERVER:  # на сервере — та же команда здесь (окружение с адресом базы — у tm-web из /etc/ticket-monitor.env)
        cmd = [sys.executable, "-m", "sales.detail", *keys]
    elif not cfg.get("ssh"):
        return jsonify(error="сервер не настроен на этом компьютере (config/server.json)"), 503
    else:
        remote = "set -a; . /etc/ticket-monitor.env; set +a; cd /opt/ticket-monitor && .venv/bin/python -m sales.detail " + " ".join(shlex.quote(k) for k in keys)
        cmd = ["ssh", "-i", os.path.expanduser(cfg.get("key", "")), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", cfg["ssh"], remote]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40, cwd=BASE_DIR)
    except subprocess.TimeoutExpired:
        return jsonify(error="сервер не ответил за 40 с"), 504
    if r.returncode != 0:
        return jsonify(error="сервер недоступен (адрес сменился или нет сети)"), 502
    try:
        return jsonify(json.loads(r.stdout))
    except ValueError:
        return jsonify(error="сервер вернул непонятный ответ"), 502


_arch_cache: dict = {}


_feed_cache: dict = {}


@bp.get("/api/sales/feed")
def sales_feed():
    """Продажи по кассам (sales.feed): на сервере — из базы, на ноутбуке разработки — с сервера по SSH. Кэш — 5 минут."""
    days = request.args.get("days", "14")
    days = int(days) if days.isdigit() and 1 <= int(days) <= 120 else 14
    key = (days, datetime.now().strftime("%Y-%m-%d %H:") + str(datetime.now().minute // 5))
    if key in _feed_cache:
        return Response(_feed_cache[key], mimetype="application/json")
    if ON_SERVER:
        from db import connect as dbc
        from sales import feed
        conn = dbc.connect()
        try:
            body = json.dumps(feed.build(conn, days), ensure_ascii=False, separators=(",", ":"))
        finally:
            conn.close()
    else:
        cfg = load_json(SERVER_FILE, {})
        if not cfg.get("ssh"):
            return jsonify(error="сервер не настроен на этом компьютере (config/server.json)"), 503
        remote = "set -a; . /etc/ticket-monitor.env; set +a; cd /opt/ticket-monitor && .venv/bin/python -m sales.feed %d" % days
        cmd = ["ssh", "-i", os.path.expanduser(cfg.get("key", "")), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", cfg["ssh"], remote]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return jsonify(error="сервер не ответил за 60 с"), 504
        if r.returncode != 0:
            return jsonify(error="сервер недоступен"), 502
        body = r.stdout.decode("utf-8")
    _feed_cache.clear()
    _feed_cache[key] = body
    return Response(body, mimetype="application/json")


@bp.get("/api/archive")
def archive_rows():
    """Архив для прототипа (sales.history): прошедшие и снятые сеансы за период — из базы на сервере. Данные в git не попадают."""
    frm, to, city = request.args.get("from", ""), request.args.get("to", ""), (request.args.get("city") or "").strip()
    if not (re.match(r"^\d{4}-\d{2}-\d{2}$", frm) and re.match(r"^\d{4}-\d{2}-\d{2}$", to)) or len(city) > 60 or re.search(r"[\x00-\x1f]", city):
        return jsonify(error="период — from/to ГГГГ-ММ-ДД, город — название"), 400
    key = (frm, to, city, datetime.now().strftime("%Y-%m-%d %H"))  # итоги фиксируются раз в час — кэш на час
    if key in _arch_cache:
        return Response(_arch_cache[key], mimetype="application/json")
    if ON_SERVER:
        from db import connect as dbc
        from sales import history
        conn = dbc.connect()
        try:
            body = json.dumps(history.rows(conn, frm, to, city), ensure_ascii=False, separators=(",", ":"))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        finally:
            conn.close()
    else:
        cfg = load_json(SERVER_FILE, {})
        if not cfg.get("ssh"):
            return jsonify(error="сервер не настроен на этом компьютере (config/server.json)"), 503
        remote = ("set -a; . /etc/ticket-monitor.env; set +a; cd /opt/ticket-monitor && .venv/bin/python -m sales.history "
                  + " ".join(shlex.quote(x) for x in [frm, to] + ([city] if city else [])))
        cmd = ["ssh", "-i", os.path.expanduser(cfg.get("key", "")), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", cfg["ssh"], remote]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired:
            return jsonify(error="сервер не ответил за 90 с"), 504
        if r.returncode != 0:
            return jsonify(error="сервер недоступен или период неверный"), 502
        body = r.stdout.decode("utf-8")
    if len(_arch_cache) > 40:
        _arch_cache.clear()
    _arch_cache[key] = body
    return Response(body, mimetype="application/json")


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


@bp.get("/api/market/myprojects")
def myprojects_get():
    return jsonify(myprojects.load())


@bp.get("/api/market/myprojects/media/<name>")
def myprojects_media(name):
    path = myprojects.media_file(name)
    if not path:
        return jsonify({"error": "нет такого фото"}), 404
    return send_file(path, max_age=86400)


@bp.post("/api/market/myprojects")
def myprojects_post():
    op = request.get_json(silent=True) or {}
    before = journal.snapshot("projects")
    try:
        data, _note = myprojects.apply_op(op)
    except myprojects.MyProjectsError as e:
        return jsonify({"error": str(e)}), 400
    journal.record("projects", before, note=_note)
    return jsonify(data)  # не отправляется на GitHub — репозиторий публичный
