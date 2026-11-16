"""Разбор афиши. Постоянные исключения, 4 секунды отмены, очистка рабочей истории.

Пользовательские решения приватные. Ни один вызов чтения правил не запускает сбор.
Очередь удаления хранится на диске и переживает закрытие страницы/перезапуск сайта.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
import uuid
from functools import wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path

from competitors import curation
from competitors.storage import BASE_DIR, CONFIG_DIR, JsonLock, load_json, save_json

FILE = CONFIG_DIR / "event_review.json"
ROOT = BASE_DIR
LOCK = JsonLock(lambda: FILE.with_name(FILE.name + ".purge"))
STATE_LOCK = JsonLock(lambda: FILE)
UNDO_SECONDS = 4
_worker = None
_worker_lock = threading.Lock()
_cache = {}
_cur_cache = {}
_rules_cache = {}


class ReviewError(ValueError):
    pass


def stamp():
    return datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")


def load():
    return {"version": 1, "rev": 0, "operations": {}, "kept": {}, "deleted": [], **load_json(FILE, {})}


def save(data):
    data["rev"] += 1
    save_json(FILE, data)


def guard():
    return LOCK


def synchronized(fn):
    """Не допустить запись старого снимка поверх завершённого удаления."""
    @wraps(fn)
    def run(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return run


class RuleSet(list):
    """Индексы: разбор тысяч строк не перебирает весь накопленный список запретов."""
    def __init__(self, values):
        super().__init__(values)
        self.index = {}
        for r in self:
            tokens = [("key", k) for k in r.get("keys", [])]
            tokens += [("name", k) for k in r.get("names", [])]
            if r.get("pid") is not None:
                tokens.append(("pid", r["pid"]))
            if r["kind"] == "artist":
                tokens += [("artist", r["artist_key"]), ("aid", r.get("aid"))]
            for token in tokens:
                self.index.setdefault(token, []).append(r)

    def candidates(self, e):
        pk = key(e["title"])
        tokens = [("key", k) for k in e["keys"]]
        tokens += [("pid", e["pid"]), ("aid", e["aid"]), ("name", pk),
                   ("name", curation.canonical(current_curation(), pk)),
                   ("artist", pk), ("artist", key(curation.artist_part(e["title"])))]
        seen = set()
        for token in tokens:
            for r in self.index.get(token, []):
                if id(r) not in seen:
                    seen.add(id(r))
                    yield r


def _cached_rules():
    sig = (str(FILE), FILE.stat().st_mtime_ns, FILE.stat().st_size) if FILE.exists() else (str(FILE), 0, 0)
    if _rules_cache.get("sig") != sig:
        data = load()
        _rules_cache.update(sig=sig, active=RuleSet(r for op in data["operations"].values() if op["status"] != "cancelled" for r in op["rules"]),
                            permanent=RuleSet(r for op in data["operations"].values() if op["status"] in ("applying", "done", "error") for r in op["rules"]))
    return _rules_cache


def rules(data=None):
    if data is None:
        return _cached_rules()["active"]
    return RuleSet(r for op in data["operations"].values() if op["status"] != "cancelled" for r in op["rules"])


def permanent_rules():
    return _cached_rules()["permanent"]


def key(title):
    return curation.project_key(str(title or ""))


def qualifier(title):
    """Сохранить различие программ «А/Б» и «1/2», потерянное общим project_key."""
    title = re.sub(r"\([^)]*\)", " ", str(title or "").lower().replace("ё", "е"))
    return sorted({w for w in re.split(r"[^a-zа-я0-9]+", title) if len(w) == 1 and w not in {"и", "в", "с", "к", "у", "о", "г"}})


def norm(s):
    return re.sub(r"\s+", " ", str(s or "").lower().replace("ё", "е")).strip()


def current_curation():
    sig = curation.FILE.stat().st_mtime_ns if curation.FILE.exists() else 0
    if _cur_cache.get("sig") != sig:
        _cur_cache.update(sig=sig, value=curation.load())
    return _cur_cache["value"]


def event(row):
    return {"title": str(row.get("title", row.get("t", ""))),
            "city": str(row.get("city", row.get("c", ""))),
            "venue": str(row.get("venue", row.get("v", ""))),
            "date": str(row.get("date", row.get("d", "")))[:10],
            "time": str(row.get("time", "")), "org": str(row.get("org") or ""),
            "format": row.get("format", row.get("f", "")), "genre": row.get("genre", ""),
            "tour": row.get("tour"), "tour_why": row.get("tour_why", ""),
            "keys": list(row.get("keys") or ([row["uid"]] if row.get("uid") else [])),
            "pid": row.get("pid"), "aid": row.get("aid")}


def matches(row, rule):
    e = event(row)
    if rule["kind"] == "project" and set(e["keys"]) & set(rule.get("protected_keys", [])):
        return False
    if set(e["keys"]) & set(rule.get("keys", [])):
        return True
    if rule["kind"] == "project":
        if "qualifier" in rule and qualifier(e["title"]) != rule["qualifier"]:
            return False
        if e.get("pid") is not None and rule.get("pid") is not None:
            return e["pid"] == rule["pid"]
    ctx = rule.get("context") or {}
    if any(norm(e.get(k)) != norm(v) for k, v in ctx.items()):
        return False
    if rule["kind"] == "artist":
        if e.get("aid") is not None and rule.get("aid") is not None:
            return e["aid"] == rule["aid"]
        return key(e["title"]) == rule["artist_key"] or key(curation.artist_part(e["title"]) or "") == rule["artist_key"]
    cur = current_curation()
    return curation.canonical(cur, key(e["title"])) in rule["names"] or key(e["title"]) in rule["names"]


def blocked(row, active=None):
    active = rules() if active is None else active
    if not active:
        return False
    return any(matches(row, r) for r in (active.candidates(event(row)) if isinstance(active, RuleSet) else active))


def filter_rows(rows, permanent=False):
    active = permanent_rules() if permanent else rules()
    return [r for r in rows if not blocked(r, active)] if active else rows


def blocked_key(listing_key):
    return bool(rules().index.get(("key", listing_key)))


def db_connection():
    from db import connect
    return connect.connect()


def registry():
    """Привязки только читаются. Без базы используется осторожная текстовая группировка."""
    from competitors.storage import ON_SERVER
    if not ON_SERVER:
        return {}, {}, {}
    conn = db_connection()
    try:
        conn.set_session(readonly=True)
        cur = conn.cursor()
        cur.execute("SELECT l.ext_key,s.project_id,p.scope,p.artist_id FROM listings l JOIN sessions s ON s.id=l.session_id JOIN projects p ON p.id=s.project_id")
        lookup = {k: (pid, scope, aid) for k, pid, scope, aid in cur.fetchall()}
        cur.execute("SELECT project_id,key FROM project_names")
        names = {}
        for pid, k in cur.fetchall():
            names.setdefault(pid, set()).add(k)
        cur.execute("SELECT id,name FROM artists")
        return lookup, names, dict(cur.fetchall())
    finally:
        conn.close()


def catalogue():
    files = [ROOT / "data/competitors/market/events.json", ROOT / "data/competitors/events.json", curation.FILE,
             ROOT / "data/competitors/official_sites.json"]
    sig = (datetime.now().date().isoformat(),) + tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in files)
    if _cache.get("sig") == sig:
        return _cache["groups"]
    cur = curation.load()
    raw = load_json(files[0], [])
    direct = load_json(files[1], {})
    raw += [dict(v, uid=k) for k, v in direct.items()]
    for entry in load_json(ROOT / "data/competitors/official_sites.json", {}).values():
        raw += [dict(r, title=entry.get("title", "")) for r in entry.get("rows", [])]
    rows = [event(r) for r in raw if str(r.get("date") or "")[:10] >= datetime.now().strftime("%Y-%m-%d")]
    # Ничего не пишем в исходные файлы, даже при ручной классификации.
    curation.classify(rows, cur)
    lookup, db_names, artists = registry()
    groups = {}
    for e in rows:
        known = [lookup[k] for k in e["keys"] if k in lookup]
        pid, scope, aid = known[0] if known else (None, "", None)
        context = {}
        # Репертуарная постановка определяется вместе с её сценой, не словом «Гамлет».
        if scope.startswith("venue:") or (e["tour"] == "local" and e["format"] in curation.THEATRE_FORMATS):
            context = {"city": e["city"], "venue": e["venue"]}
        elif scope.startswith("org:"):
            context = {"org": scope[4:]}
        pk = curation.canonical(cur, key(e["title"]))
        identity = json.dumps([pid if pid is not None else pk, context, qualifier(e["title"])], ensure_ascii=False, sort_keys=True)
        gid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        e.update(pid=pid, aid=aid)
        if gid not in groups:
            groups[gid] = {"id": gid, "title": e["title"], "tour": e["tour"], "why": e["tour_why"],
                           "format": e["format"], "genre": e["genre"], "pid": pid, "aid": aid,
                           "artist": artists.get(aid, ""), "context": context, "qualifier": qualifier(e["title"]),
                           "names": set(db_names.get(pid, set())) | {pk}, "keys": set(), "events": []}
        g = groups[gid]
        g["names"].add(pk)
        g["keys"].update(e["keys"])
        if not any((x["city"], x["venue"], x["date"], x["time"]) == (e["city"], e["venue"], e["date"], e["time"]) for x in g["events"]):
            g["events"].append(e)
    result = []
    for g in groups.values():
        g["names"], g["keys"] = sorted(g["names"]), sorted(g["keys"])
        g["events"].sort(key=lambda e: (e["date"], e["city"]))
        orgs = {norm(e["org"]) for e in g["events"]}
        if g["context"].get("venue") and len(orgs) == 1 and "" not in orgs:
            g["context"]["org"] = g["events"][0]["org"]
        result.append(g)
    result.sort(key=lambda g: (g["tour"] != "local", norm(g["title"]), g["id"]))
    _cache.update(sig=sig, groups=result)
    return result


def version():
    files = [FILE, curation.FILE, ROOT / "data/competitors/market/events.json",
             ROOT / "data/competitors/events.json", ROOT / "data/competitors/official_sites.json"]
    signature = [datetime.now().date().isoformat()] + [str((p.stat().st_mtime_ns, p.stat().st_size)) if p.exists() else "0" for p in files]
    return hashlib.sha256("|".join(signature).encode()).hexdigest()


def view():
    data = load()
    active = rules(data)
    all_groups = catalogue()
    groups = []
    for g in all_groups:
        if any(blocked(e, active) for e in g["events"]):
            continue
        groups.append({k: v for k, v in g.items() if k not in ("names", "keys", "pid", "aid", "context", "events", "qualifier")} |
                      {"kept": g["id"] in data["kept"], "events": [{k: e[k] for k in ("city", "venue", "date", "time", "org", "keys")} for e in g["events"]]})
    pending = [{"id": oid, "count": len(op["rules"]), "until": op["until"], "status": op["status"], "error": op.get("error", "")}
               for oid, op in data["operations"].items() if op["status"] in ("pending", "applying", "error")]
    return {"rev": data["rev"], "groups": groups, "deleted": data["deleted"], "pending": pending, "rules": active,
            "server_time": time.time(), "kept": sum(g["kept"] for g in groups), "rule_count": len(active)}


def apply(op):
    action = op.get("op")
    with STATE_LOCK:
        data = load()
        if action == "cancel":
            item = data["operations"].get(op.get("id"))
            if not item or item["status"] != "pending" or time.time() >= item["until"]:
                raise ReviewError("Четыре секунды истекли — отмена уже недоступна")
            item["status"] = "cancelled"
            save(data)
            return {"ok": True}
        if action not in ("keep", "exclude"):
            raise ReviewError("Неизвестное действие")
        ids = op.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(i, str) for i in ids):
            raise ReviewError("Выберите от 1 до 500 проектов")
        index = {g["id"]: g for g in catalogue()}
        if any(i not in index for i in ids):
            raise ReviewError("Афиша изменилась. Обновите список")
        selected = [index[i] for i in dict.fromkeys(ids)]
        if any(blocked(e, rules(data)) for g in selected for e in g["events"]):
            raise ReviewError("Проект уже исключён. Обновите список")
        if action == "keep":
            for g in selected:
                data["kept"][g["id"]] = {"title": g["title"], "at": stamp()}
            save(data)
            return {"ok": True}
        if op.get("reason") not in ("local", "uninteresting"):
            raise ReviewError("Выберите причину удаления")
        kind = op.get("scope", "project")
        if kind not in ("project", "artist"):
            raise ReviewError("Неизвестная область исключения")
        new_rules = []
        for g in selected:
            if kind == "artist" and not g["artist"]:
                raise ReviewError("Для этого проекта исполнитель не определён. Используйте область «Проект»")
            new_rules.append({k: g[k] for k in ("title", "pid", "aid", "context", "names", "keys", "qualifier")} |
                             {"kind": kind, "artist_key": key(g["artist"]), "reason": op["reason"], "group": g["id"]})
            if kind == "artist":
                new_rules[-1]["context"] = {}
            else:
                new_rules[-1]["protected_keys"] = sorted({k for other in index.values()
                    if other["id"] != g["id"] and other["pid"] != g["pid"] and set(other["names"]) & set(g["names"])
                    for k in other["keys"]})
        oid = uuid.uuid4().hex
        until = time.time() + UNDO_SECONDS
        entries = [{k: e[k] for k in ("title", "city", "venue", "date")} for g in selected for e in g["events"]]
        data["operations"][oid] = {"status": "pending", "at": stamp(), "until": until, "rules": new_rules, "entries": entries}
        save(data)
    start_worker()
    return {"ok": True, "id": oid, "until": until, "server_time": time.time()}


def _session_rows(conn):
    cur = conn.cursor()
    cur.execute("""SELECT s.id,s.project_id,p.artist_id,s.title,c.name,v.name,s.local_date,
                   coalesce(array_agg(DISTINCT l.ext_key) FILTER(WHERE l.ext_key IS NOT NULL),'{}'),
                   max(l.organizer) FROM sessions s JOIN venues v ON v.id=s.venue_id JOIN cities c ON c.id=v.city_id
                   LEFT JOIN projects p ON p.id=s.project_id LEFT JOIN listings l ON l.session_id=s.id
                   GROUP BY s.id,p.artist_id,c.name,v.name""")
    return [{"sid": sid, "pid": pid, "aid": aid, "title": title or "", "city": city, "venue": venue,
             "date": str(d), "keys": keys, "org": org or ""} for sid, pid, aid, title, city, venue, d, keys, org in cur.fetchall()]


def enforce_db(conn, active=None):
    """Удалить запрещённые сеансы в текущей транзакции. Коммит выполняет вызывающий."""
    active = rules() if active is None else active
    active = active if isinstance(active, RuleSet) else RuleSet(active)
    if not active:
        return [], []
    targets = [r for r in _session_rows(conn) if blocked(r, active)]
    ids = [r["sid"] for r in targets]
    keys = list({k for e in targets for k in e["keys"]} | {k for r in active for k in r["keys"]})
    cur = conn.cursor()
    cur.execute("SELECT o.raw_ref FROM observations o JOIN pools p ON p.id=o.pool_id WHERE (p.session_id=ANY(%s) OR p.listing_key=ANY(%s)) AND o.raw_ref IS NOT NULL", (ids, keys))
    raw = [r[0] for r in cur.fetchall()]
    # pools после миграции 04.10 не имеют FK к sessions; удалить явно.
    # Дочерние наблюдения, продажи по местам и ценам удаляются каскадом.
    cur.execute("DELETE FROM pools WHERE session_id=ANY(%s) OR listing_key=ANY(%s)", (ids, keys))
    cur.execute("DELETE FROM listings WHERE session_id=ANY(%s) OR ext_key=ANY(%s)", (ids, keys))
    cur.execute("DELETE FROM sessions WHERE id=ANY(%s)", (ids,))
    cur.execute("DELETE FROM listing_seen WHERE ext_key=ANY(%s)", (keys,))
    cur.execute("DELETE FROM session_edits WHERE ext_key=ANY(%s)", (keys,))
    return targets, raw


def _delete_raw(ref):
    if ref.startswith("s3://"):
        import os
        import boto3
        bucket, path = ref[5:].split("/", 1)
        client = boto3.session.Session().client("s3", endpoint_url="https://storage.yandexcloud.net",
                    aws_access_key_id=os.environ["S3_KEY_ID"], aws_secret_access_key=os.environ["S3_SECRET"])
        client.delete_object(Bucket=bucket, Key=path)
        return
    path = (ROOT / ref).resolve()
    if path.is_relative_to(ROOT.resolve() / "data"):
        path.unlink(missing_ok=True)


def purge(active, remember=None):
    """Идемпотентная очистка рабочих файлов/БД. Внешние резервные копии не переписывает."""
    from competitors.storage import ON_SERVER
    targets, raw_refs = [], []
    conn = db_connection() if ON_SERVER else None
    try:
        if conn:
            targets, raw_refs = enforce_db(conn, active)
            # Ссылки сохраняем до удаления БД: сбой сырья допускает повтор операции.
            for rule in active:
                rule["keys"] = sorted(set(rule["keys"]) | {k for e in targets if matches(e, rule) for k in e["keys"]})
        active = RuleSet(active)
        source_keys = {k for r in active for k in r["keys"]} | {k for e in targets for k in e["keys"]}
        folder = ROOT / "data/competitors"
        current = folder / "market/events.json"
        direct = folder / "events.json"
        # До разрушительных действий сохраняем минимальный журнал и все известные
        # ключи. Повтор после аварии не потеряет названия уже удалённых сеансов.
        for path in (current, folder / "market/archive.json", direct):
            value = load_json(path, [] if path == current else {})
            candidates = value if isinstance(value, list) else [dict(v, keys=v.get("keys") or [k]) for k, v in value.items()]
            targets.extend(event(e) for e in candidates if blocked(e, active))
        if remember:
            remember(targets, raw_refs)
        source_keys |= {k for e in targets for k in e.get("keys", [])}
        for path in [current, folder / "market/archive.json", direct]:
            value = load_json(path, [] if path == current else {})
            if isinstance(value, list):
                removed = [e for e in value if blocked(e, active)]
                kept = [e for e in value if not blocked(e, active)]
            else:
                removed = [dict(e, keys=e.get("keys") or [k]) for k, e in value.items() if blocked(dict(e, keys=e.get("keys") or [k]), active)]
                kept = {k: e for k, e in value.items() if not blocked(dict(e, keys=e.get("keys") or [k]), active)}
            targets.extend(event(e) for e in removed)
            for e in removed:
                source_keys.update(e.get("keys") or ([e["uid"]] if e.get("uid") else []))
            if path.exists() and kept != value:
                save_json(path, kept)
        for path in (folder / "market/days").glob("*.json"):
            value = load_json(path, {})
            for field in ("new", "gone"):
                value[field] = [e for e in value.get(field, []) if not blocked(e, active) and not set(e.get("keys", [])) & source_keys]
            save_json(path, value)
        for sub in ("history", "seats"):
            for k in source_keys:
                if not k.startswith(("k:", "y:", "q:")):
                    (folder / sub / (k.replace(":", "_").replace("/", "_") + ".json")).unlink(missing_ok=True)
        seen_path = folder / "market/seen.json"
        if seen_path.exists():
            seen = load_json(seen_path, {})
            save_json(seen_path, {k: v for k, v in seen.items() if k not in source_keys})
        # Схемы Кассира сохранялись отдельно от raw_ref. Удаляем файлы именно этих карточек.
        for path in (ROOT / "data/raw_sales").rglob("*.gz"):
            if any(path.name.startswith(k.replace("/", "_") + "_") for k in source_keys):
                raw_refs.append(str(path.relative_to(ROOT)))
        for ref in set(raw_refs):
            _delete_raw(ref)
        site_file = folder / "official_sites.json"
        if site_file.exists():
            save_json(site_file, clean_sites(load_json(site_file, {}), active))
        # Снимки дат в «Моей базе» — производные от афиши. Профиль, контакты,
        # файлы и собственные рабочие записи пользователя не удаляем.
        from competitors import myprojects
        with myprojects._lock:
            path = ROOT / "config/my_projects.json"
            projects = load_json(path, {})
            changed = False
            for project in projects.get("projects", {}).values():
                snap = project.get("snap") or {}
                before = snap.get("dates") or []
                after = [d for d in before if not blocked({"title": project.get("title", ""),
                         "date": d[0], "city": d[1], "venue": d[2]}, active)]
                if after != before:
                    snap["dates"] = after
                    changed = True
            if changed:
                save_json(path, projects)
        # Старый ручной мониторинг (пять карточек, отдельный от афиши):
        # убрать совпавшие карточки и их собственные файлы истории.
        legacy_path = ROOT / "config/events.json"
        legacy = load_json(legacy_path, [])
        kept_legacy = []
        for e in legacy:
            if not blocked(e, active):
                kept_legacy.append(e)
                continue
            ident = str(e.get("id") or "")
            if ident and re.fullmatch(r"[\w.\-]+", ident):
                for sub in ("state", "processed", "geometry"):
                    (ROOT / "data" / sub / (ident + ".json")).unlink(missing_ok=True)
                import shutil
                raw_dir = ROOT / "data/raw" / ident
                if raw_dir.exists():
                    shutil.rmtree(raw_dir)
        if legacy_path.exists() and kept_legacy != legacy:
            save_json(legacy_path, kept_legacy)
        snapshot = ROOT / "data/sales_snapshot.json.gz"
        if snapshot.exists():
            if conn:
                from sales import export as sales_export
                value = sales_export.build(conn)
            else:
                value = json.loads(gzip.decompress(snapshot.read_bytes()))
            value["rows"] = {k: v for k, v in value.get("rows", {}).items() if k not in source_keys}
            gone = {(e["city"], e["date"]) for e in targets}
            for k, entries in list(value.get("finals", {}).items()):
                if any(k in r["names"] for r in active):
                    value["finals"][k] = [x for x in entries if (x[0], x[3]) not in gone]
            # Тот же атомарный формат, что в sales.export.
            import tempfile, os
            fd, tmp = tempfile.mkstemp(dir=snapshot.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(gzip.compress(json.dumps(value, ensure_ascii=False).encode()))
                    f.flush(); os.fsync(f.fileno())
                Path(tmp).replace(snapshot)
            finally:
                Path(tmp).unlink(missing_ok=True)
        if conn:
            conn.commit()
        _cache.clear()
        return targets, source_keys
    except BaseException:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def clean_sites(data, active=None):
    active = rules() if active is None else active
    out = {}
    for k, entry in data.items():
        e = dict(entry)
        for part in ("rows", "gone", "past"):
            e[part] = [r for r in e.get(part, []) if not blocked(dict(r, title=e.get("title") or k), active)]
        out[k] = e
    return out


def finalize_due():
    # Очистка может занять дольше окна отмены другого нажатия. Замок очереди
    # освобождаем на время очистки: отмена соседней операции остаётся доступной.
    with STATE_LOCK:
        due = [oid for oid, op in load()["operations"].items()
               if op["status"] in ("pending", "error", "applying") and op["until"] <= time.time()
               and op.get("retry_at", 0) <= time.time()]
    for oid in due:
        # Единственный исполнитель очистки, включая несколько web-процессов.
        with LOCK:
            with STATE_LOCK:
                data = load()
                op = data["operations"][oid]
                if op["status"] not in ("pending", "error", "applying") or op.get("retry_at", 0) > time.time():
                    continue
                op["status"] = "applying"
                save(data)
                active = op["rules"]
            try:
                def remember(targets, raw_refs):
                    with STATE_LOCK:
                        data = load()
                        op = data["operations"][oid]
                        have = {(e["title"], e["city"], e["venue"], e["date"]) for e in op.get("entries", [])}
                        for e in targets:
                            identity = (e["title"], e["city"], e["venue"], e["date"])
                            if identity not in have:
                                op.setdefault("entries", []).append({k: e[k] for k in ("title", "city", "venue", "date")})
                                have.add(identity)
                        for r in op["rules"]:
                            r["keys"] = sorted(set(r["keys"]) | {k for e in targets if matches(e, r) for k in e.get("keys", [])})
                        op["raw_refs"] = sorted(set(op.get("raw_refs", [])) | set(raw_refs))
                        save(data)
                targets, _ = purge(active, remember)
                with STATE_LOCK:
                    data = load()
                    op = data["operations"][oid]
                    for ref in op.get("raw_refs", []):
                        _delete_raw(ref)
                    have = {(r["title"], r["city"], r["venue"], r["date"]) for r in data["deleted"]}
                    for e in targets + op.get("entries", []):
                        identity = (e["title"], e["city"], e["venue"], e["date"])
                        if identity in have:
                            continue
                        have.add(identity)
                        r = next((r for r in op["rules"] if matches(e, r)), op["rules"][0])
                        data["deleted"].append({k: e[k] for k in ("title", "city", "venue", "date")} |
                                               {"reason": r["reason"], "at": stamp()})
                    op["status"] = "done"
                    for k in ("entries", "error", "raw_refs", "retry_at"):
                        op.pop(k, None)
                    save(data)
            except Exception as exc:
                with STATE_LOCK:
                    data = load()
                    data["operations"][oid].update(status="error", error="Очистка не завершена: " + type(exc).__name__, retry_at=time.time() + 30)
                    save(data)


def start_worker():
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        def run():
            while True:
                try:
                    finalize_due()
                except Exception:
                    pass  # Состояние операции сохранено; следующий проход повторит.
                time.sleep(.25)
        _worker = threading.Thread(target=run, name="event-review", daemon=True)
        _worker.start()


def reapply():
    """После восстановления копии: повторно очистить по АКТУАЛЬНОМУ файлу решений."""
    with STATE_LOCK:
        data = load()
        for op in data["operations"].values():
            if op["status"] in ("done", "error", "applying"):
                op.update(status="applying", until=0)
                op.pop("retry_at", None)
        save(data)
    finalize_due()
    failed = [op for op in load()["operations"].values() if op["status"] == "error"]
    if failed:
        raise RuntimeError("Повторная очистка не завершена. Не открывайте восстановленный сайт до устранения ошибок")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["reapply"]:
        raise SystemExit("Usage: TM_ON_SERVER=1 python3 -m competitors.review reapply")
    reapply()
    print("Актуальные исключения повторно применены")
