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
from functools import lru_cache, wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

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
_view_cache = {}


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
    def __init__(self, values, protected=None):
        super().__init__(values)
        if protected is None:
            protected = getattr(values, "protected", ())
        self.protected = RuleSet(protected, ()) if protected else ()
        self.curation = current_curation()
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
                   ("name", curation.canonical(self.curation, pk)),
                   ("artist", pk), ("artist", key(curation.artist_part(e["title"])))]
        seen = set()
        for token in tokens:
            for r in self.index.get(token, []):
                if id(r) not in seen:
                    seen.add(id(r))
                    yield r


def _cached_rules():
    sig = (str(FILE), FILE.stat().st_mtime_ns, FILE.stat().st_size) if FILE.exists() else (str(FILE), 0, 0)
    sig += (str(curation.FILE), curation.FILE.stat().st_mtime_ns if curation.FILE.exists() else 0)
    if _rules_cache.get("sig") != sig:
        data = load()
        protected = kept_rules(data)
        _rules_cache.update(sig=sig, active=RuleSet((r for op in data["operations"].values() if op["status"] != "cancelled" for r in op["rules"]), protected),
                            permanent=RuleSet((r for op in data["operations"].values() if op["status"] in ("applying", "done", "error") for r in op["rules"]), protected))
    return _rules_cache


def rules(data=None):
    if data is None:
        return _cached_rules()["active"]
    return RuleSet((r for op in data["operations"].values() if op["status"] != "cancelled" for r in op["rules"]), kept_rules(data))


def kept_rules(data):
    return [v["rule"] for v in data["kept"].values() if v.get("rule")]


def group_rule(g):
    return {k: g[k] for k in ("title", "pid", "aid", "context", "names", "keys", "qualifier")} | {"kind": "project", "group": g["id"]}


def hydrate_kept(data, groups):
    for g in groups:
        if g["id"] in data["kept"] and not data["kept"][g["id"]].get("rule"):
            data["kept"][g["id"]]["rule"] = group_rule(g)


def permanent_rules():
    return _cached_rules()["permanent"]


@lru_cache(maxsize=65536)
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


def matches(row, rule, cur=None):
    e = event(row)
    # Контекст постановки обязателен даже при общем ошибочном project_id.
    ctx = rule.get("context") or {}
    if any(norm(e.get(k)) != norm(v) for k, v in ctx.items()):
        return False
    if rule["kind"] == "project" and set(e["keys"]) & set(rule.get("protected_keys", [])):
        return False
    if rule["kind"] == "project":
        if "qualifier" in rule and qualifier(e["title"]) != rule["qualifier"]:
            return False
        if e.get("pid") is not None and rule.get("pid") is not None:
            return e["pid"] == rule["pid"]
    if set(e["keys"]) & set(rule.get("keys", [])):
        return True
    if rule["kind"] == "artist":
        if e.get("aid") is not None and rule.get("aid") is not None:
            return e["aid"] == rule["aid"]
        return key(e["title"]) == rule["artist_key"] or key(curation.artist_part(e["title"]) or "") == rule["artist_key"]
    cur = current_curation() if cur is None else cur
    return curation.canonical(cur, key(e["title"])) in rule["names"] or key(e["title"]) in rule["names"]


def blocked(row, active=None):
    active = rules() if active is None else active
    if not active:
        return False
    if isinstance(active, RuleSet):
        if active.protected and any(matches(row, r, active.curation) for r in active.protected.candidates(event(row))):
            return False
        return any(matches(row, r, active.curation) for r in active.candidates(event(row)))
    return any(matches(row, r) for r in active)


def filter_rows(rows, permanent=False):
    active = permanent_rules() if permanent else rules()
    return [r for r in rows if not blocked(r, active)] if active else rows


def blocked_key(listing_key):
    active = rules()
    return bool(active.index.get(("key", listing_key))) and not (active.protected and active.protected.index.get(("key", listing_key)))


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


def ticket_link(row):
    """Сохранённая ссылка на продажу; никаких запросов к оператору при разборе."""
    for field, fallback in (("url_k", "Кассир"), ("url_y", "Яндекс Афиша"),
                            ("url_q", "Qtickets"), ("buy_url", "Билеты"),
                            ("buy", "Билеты"), ("url", "Сайт мероприятия")):
        url = str(row.get(field) or "").strip()
        if not url or any(c in url for c in "\r\n\t"):
            continue
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
        except ValueError:
            continue
        if parsed.scheme.lower() not in ("https", "http") or not host:
            continue
        label = fallback
        for domain, name in (("kassir.ru", "Кассир"), ("yandex.ru", "Яндекс Афиша"), ("qtickets.ru", "Qtickets")):
            if host == domain or host.endswith("." + domain):
                label = name
                break
        return {"url": url, "label": label}
    return None


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
    rows = [dict(event(r), ticket=ticket_link(r)) for r in raw
            if str(r.get("date") or "")[:10] >= datetime.now().strftime("%Y-%m-%d")]
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
        same = next((x for x in g["events"] if (x["city"], x["venue"], x["date"], x["time"]) ==
                     (e["city"], e["venue"], e["date"], e["time"])), None)
        if same is None:
            g["events"].append(e)
        elif not same["ticket"]:
            same["ticket"] = e["ticket"]
    result = []
    for g in groups.values():
        g["names"], g["keys"] = sorted(g["names"]), sorted(g["keys"])
        g["events"].sort(key=lambda e: (e["date"], e["city"]))
        g["ticket"] = next((e["ticket"] for e in g["events"] if e["ticket"]), None)
        orgs = {norm(e["org"]) for e in g["events"]}
        if g["context"].get("venue") and len(orgs) == 1 and "" not in orgs:
            g["context"]["org"] = g["events"][0]["org"]
        result.append(g)
    result.sort(key=lambda g: (g["tour"] != "local", norm(g["title"]), g["id"]))
    _cache.update(sig=sig, groups=result, index={g["id"]: g for g in result})
    return result


def version(include_state=True):
    files = ([FILE] if include_state else []) + [curation.FILE, ROOT / "data/competitors/market/events.json",
             ROOT / "data/competitors/events.json", ROOT / "data/competitors/official_sites.json"]
    signature = [datetime.now().date().isoformat()] + [str((p.stat().st_mtime_ns, p.stat().st_size)) if p.exists() else "0" for p in files]
    return hashlib.sha256("|".join(signature).encode()).hexdigest()


def view(known_catalogue=None, deleted_count=None):
    data = load()
    rule_data = [(oid, op["rules"]) for oid, op in data["operations"].items() if op["status"] != "cancelled"]
    catalogue_version = hashlib.sha256(json.dumps([version(include_state=False), rule_data], sort_keys=True).encode()).hexdigest()
    content_version = hashlib.sha256(json.dumps([catalogue_version, sorted(data["kept"]), len(data["deleted"])]).encode()).hexdigest()
    pending = [{"id": oid, "count": len(op["rules"]), "until": op["until"], "status": op["status"], "error": op.get("error", "")}
               for oid, op in data["operations"].items() if op["status"] in ("pending", "applying", "error")]
    result = {"rev": data["rev"], "content_version": content_version, "catalogue_version": catalogue_version,
              "protections": kept_rules(data),
              "pending": pending, "server_time": time.time(), "rule_count": sum(len(r) for _, r in rule_data)}
    if deleted_count != len(data["deleted"]):
        result["deleted"] = data["deleted"]
    # После «Оставить» меняются только решения. Не строить и не передавать
    # заново десятки тысяч мероприятий; старые клиенты получают полный ответ.
    if known_catalogue == catalogue_version:
        return result | {"kept_ids": list(data["kept"])}
    sig = (str(FILE), catalogue_version)
    cached = _view_cache.get(sig)
    if cached is None:
        active = rules(data)
        groups = []
        for g in catalogue():
            if any(blocked(e, active) for e in g["events"]):
                continue
            groups.append({k: v for k, v in g.items() if k not in ("names", "keys", "pid", "aid", "context", "events", "qualifier")} |
                          {"events": [{k: e[k] for k in ("city", "venue", "date", "time", "org", "keys")} for e in g["events"]]})
        _view_cache.clear()
        _view_cache[sig] = (groups, active)
    else:
        groups, active = cached
    visible = [g | {"kept": g["id"] in data["kept"]} for g in groups]
    return result | {"groups": visible, "rules": active, "kept": sum(g["kept"] for g in visible), "deleted": data["deleted"]}


def apply(op):
    action = op.get("op")
    # Построение каталога/привязок БД не должно занимать окно отмены соседнего
    # нажатия. Под замком решений остаются проверки состояния и атомарная запись.
    groups = catalogue() if action in ("keep", "exclude") else []
    index = _cache["index"] if groups is _cache.get("groups") else {g["id"]: g for g in groups}
    by_name = {}
    if action == "exclude":
        for g in index.values():
            for name in g["names"]:
                by_name.setdefault(name, []).append(g)
    with STATE_LOCK:
        data = load()
        if action == "cancel":
            item = data["operations"].get(op.get("id"))
            if not item or item["status"] != "pending" or time.time() >= item["until"]:
                raise ReviewError("Четыре секунды истекли — отмена уже недоступна")
            item["status"] = "cancelled"
            for gid, value in item.get("previous_kept", {}).items():
                data["kept"].setdefault(gid, value)
            save(data)
            return {"ok": True}
        if action not in ("keep", "exclude"):
            raise ReviewError("Неизвестное действие")
        ids = op.get("ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
            raise ReviewError("Выберите проекты из списка")
        if any(i not in index for i in ids):
            raise ReviewError("Афиша изменилась. Обновите список")
        selected = [index[i] for i in dict.fromkeys(ids)]
        hydrate_kept(data, groups)
        active = rules(data)
        if any(blocked(e, active) for g in selected for e in g["events"]):
            raise ReviewError("Проект уже исключён. Обновите список")
        if action == "keep":
            for g in selected:
                data["kept"][g["id"]] = {"title": g["title"], "at": stamp(), "rule": group_rule(g)}
            save(data)
            return {"ok": True, "ids": [g["id"] for g in selected]}
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
                new_rules[-1]["protected_keys"] = sorted({k for name in g["names"] for other in by_name.get(name, [])
                    if other["id"] != g["id"] and other["pid"] != g["pid"] and set(other["names"]) & set(g["names"])
                    for k in other["keys"]})
        oid = uuid.uuid4().hex
        previous_kept = {g["id"]: data["kept"].pop(g["id"]) for g in selected if g["id"] in data["kept"]}
        until = time.time() + UNDO_SECONDS
        entries = [{k: e[k] for k in ("title", "city", "venue", "date")} for g in selected for e in g["events"]]
        data["operations"][oid] = {"status": "pending", "at": stamp(), "until": until, "rules": new_rules, "entries": entries,
                                  "previous_kept": previous_kept}
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


def enforce_db(conn, active=None, rows=None):
    """Удалить запрещённые сеансы в текущей транзакции. Коммит выполняет вызывающий."""
    active = rules() if active is None else active
    active = active if isinstance(active, RuleSet) else RuleSet(active)
    if not active:
        return [], []
    rows = _session_rows(conn) if rows is None else rows
    targets = [r for r in rows if blocked(r, active)]
    ids = [r["sid"] for r in targets]
    wanted = set(ids)
    active.spared_keys = {k for e in rows if e["sid"] not in wanted for k in e["keys"]}
    active.spared_keys |= {k for r in active.protected for k in r["keys"]}
    keys = list(({k for e in targets for k in e["keys"]} | {k for r in active for k in r["keys"]}) - active.spared_keys)
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
        _delete_raw_many([ref])
        return
    path = (ROOT / ref).resolve()
    if path.is_relative_to(ROOT.resolve() / "data"):
        path.unlink(missing_ok=True)


def _delete_raw_many(refs):
    """Один клиент и до 1000 объектов на S3-запрос вместо соединения на каждый файл."""
    buckets = {}
    for ref in set(refs):
        if ref.startswith("s3://"):
            bucket, path = ref[5:].split("/", 1)
            buckets.setdefault(bucket, []).append({"Key": path})
        else:
            _delete_raw(ref)
    if not buckets:
        return
    import os
    import boto3
    from botocore.config import Config
    client = boto3.session.Session().client("s3", endpoint_url="https://storage.yandexcloud.net",
                aws_access_key_id=os.environ["S3_KEY_ID"], aws_secret_access_key=os.environ["S3_SECRET"],
                config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2}))
    try:
        for bucket, objects in buckets.items():
            for i in range(0, len(objects), 1000):
                result = client.delete_objects(Bucket=bucket, Delete={"Objects": objects[i:i + 1000], "Quiet": True})
                if result.get("Errors"):
                    raise RuntimeError("Не удалось удалить часть облачного архива")
    finally:
        client.close()


def purge(active, remember=None):
    """Идемпотентная очистка рабочих файлов/БД. Внешние резервные копии не переписывает."""
    from competitors.storage import ON_SERVER
    targets, raw_refs = [], []
    active = RuleSet(active)
    conn = db_connection() if ON_SERVER else None
    try:
        db_rows = _session_rows(conn) if conn else []
        identities = {k: e for e in db_rows for k in e["keys"]}
        folder = ROOT / "data/competitors"
        current = folder / "market/events.json"
        direct = folder / "events.json"
        # Один проход чтения и сопоставления. Снимки держим до записи журнала:
        # повтор после аварии не потеряет названия уже удалённых сеансов.
        files = []
        for path in (current, folder / "market/archive.json", direct):
            value = load_json(path, [] if path == current else {})
            sequence = isinstance(value, list)
            kept, removed = ([] if sequence else {}), []
            for k, row in enumerate(value) if sequence else value.items():
                candidate = row if sequence else dict(row, keys=row.get("keys") or [k])
                known = next((identities[k] for k in candidate.get("keys", []) if k in identities), None)
                if known:
                    candidate = dict(candidate, pid=known["pid"], aid=known["aid"])
                if blocked(candidate, active):
                    removed.append(candidate)
                elif sequence:
                    kept.append(row)
                else:
                    kept[k] = row
            targets.extend(event(e) for e in removed)
            if removed:
                files.append((path, kept))
        # Сначала собрать полный набор ключей, затем применить к БД. Известные
        # разные pid и оставленные версии не превращаются в запрет через алиас.
        keys = {id(rule): set(rule["keys"]) for rule in active}
        for e in targets:
            for rule in active.candidates(event(e)):
                if matches(e, rule, active.curation):
                    keys[id(rule)].update(e.get("keys", []))
        for rule in active:
            rule["keys"] = sorted(keys[id(rule)])
        active = RuleSet(active)
        if conn:
            db_targets, raw_refs = enforce_db(conn, active, db_rows)
            targets.extend(db_targets)
            # Ключи новых сеансов того же проекта также сохраняются для retry.
            for e in db_targets:
                for rule in active.candidates(event(e)):
                    if matches(e, rule, active.curation):
                        keys[id(rule)].update(e["keys"])
            for rule in active:
                keys[id(rule)] -= active.spared_keys
                rule["keys"] = sorted(keys[id(rule)])
        source_keys = ({k for r in active for k in r["keys"]} | {k for e in targets for k in e.get("keys", [])}) - getattr(active, "spared_keys", set())
        source_keys -= {k for rule in active.protected for k in rule["keys"]}
        # Имя сырья = ключ + дата. Построить множество префиксов один раз,
        # вместо сравнения каждого из десятков тысяч файлов со всеми ключами.
        raw_prefixes = {k.replace("/", "_") for k in source_keys}
        for path in (ROOT / "data/raw_sales").rglob("*.gz"):
            if any(path.name[:i] in raw_prefixes for i, char in enumerate(path.name) if char == "_"):
                raw_refs.append(str(path.relative_to(ROOT)))
        if remember:
            remember(targets, raw_refs)
        for path, kept in files:
            save_json(path, kept)
        for path in (folder / "market/days").glob("*.json"):
            value = load_json(path, {})
            changed = False
            for field in ("new", "gone"):
                before = value.get(field, [])
                after = [e for e in before if not set(e.get("keys", [])) & source_keys and not blocked(e, active)]
                if len(after) != len(before):
                    value[field] = after
                    changed = True
            if changed:
                save_json(path, value)
        for sub in ("history", "seats"):
            for k in source_keys:
                if not k.startswith(("k:", "y:", "q:")):
                    (folder / sub / (k.replace(":", "_").replace("/", "_") + ".json")).unlink(missing_ok=True)
        seen_path = folder / "market/seen.json"
        if seen_path.exists():
            seen = load_json(seen_path, {})
            kept_seen = {k: v for k, v in seen.items() if k not in source_keys}
            if len(kept_seen) != len(seen):
                save_json(seen_path, kept_seen)
        _delete_raw_many(raw_refs)
        site_file = folder / "official_sites.json"
        if site_file.exists():
            sites = load_json(site_file, {})
            kept_sites = clean_sites(sites, active)
            if kept_sites != sites:
                save_json(site_file, kept_sites)
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
            # Удаление нескольких карточек не требует расчёта всех продаж в БД.
            # Остальные цифры остаются последним опубликованным снимком.
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
            # done означает отсутствие подходящих сеансов, а не только успешный
            # проход файлов. Не коммитить неполную очистку.
            if any(blocked(e, active) for e in _session_rows(conn)):
                raise RuntimeError("Очистка БД не завершена")
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
    def ready(op):
        return (op["status"] in ("pending", "error", "applying") and op["until"] <= time.time()
                and op.get("retry_at", 0) <= time.time())

    if not any(ready(op) for op in load()["operations"].values()):
        return
    # Все готовые удаления выполняются за один проход БД и файлов. Новые
    # нажатия и отмена своих четырёх секунд не ждут длительную очистку.
    with LOCK:
        with STATE_LOCK:
            data = load()
            batch = {oid: op for oid, op in data["operations"].items() if ready(op)}
            if not batch:
                return
            for op in batch.values():
                op["status"] = "applying"
            save(data)
        active = RuleSet((r for op in batch.values() for r in op["rules"]), kept_rules(data))
        owners = {id(rule): oid for oid, op in batch.items() for rule in op["rules"]}
        previous_raw = {ref for op in batch.values() for ref in op.get("raw_refs", [])}
        try:
            def remember(targets, raw_refs):
                entries = {oid: [] for oid in batch}
                keys = {id(r): set(r["keys"]) for r in active}
                for e in targets:
                    matched = set()
                    for rule in active.candidates(event(e)):
                        if matches(e, rule):
                            keys[id(rule)].update(e.get("keys", []))
                            matched.add(owners[id(rule)])
                    for oid in matched:
                        entries[oid].append(e)
                with STATE_LOCK:
                    data = load()
                    for oid in batch:
                        op = data["operations"][oid]
                        have = {(e["title"], e["city"], e["venue"], e["date"]) for e in op.get("entries", [])}
                        for e in entries[oid]:
                            identity = (e["title"], e["city"], e["venue"], e["date"])
                            if identity not in have:
                                op.setdefault("entries", []).append({k: e[k] for k in ("title", "city", "venue", "date")})
                                have.add(identity)
                        for saved, rule in zip(op["rules"], batch[oid]["rules"]):
                            saved["keys"] = sorted(keys[id(rule)])
                    # Общий журнал сырья нужен до коммита БД и переживает сбой.
                    first = data["operations"][next(iter(batch))]
                    first["raw_refs"] = sorted(previous_raw | set(raw_refs))
                    save(data)
            purge(active, remember)
            _delete_raw_many(previous_raw)
            with STATE_LOCK:
                data = load()
                have = {(r["title"], r["city"], r["venue"], r["date"]) for r in data["deleted"]}
                for oid in batch:
                    op = data["operations"][oid]
                    op_rules = RuleSet(op["rules"])
                    for e in op.get("entries", []):
                        identity = (e["title"], e["city"], e["venue"], e["date"])
                        if identity in have:
                            continue
                        have.add(identity)
                        rule = next((r for r in op_rules.candidates(event(e)) if matches(e, r)), op["rules"][0])
                        data["deleted"].append({k: e[k] for k in ("title", "city", "venue", "date")} |
                                               {"reason": rule["reason"], "at": stamp()})
                    op["status"] = "done"
                    for k in ("entries", "error", "raw_refs", "retry_at", "previous_kept"):
                        op.pop(k, None)
                save(data)
        except Exception as exc:
            with STATE_LOCK:
                data = load()
                for oid in batch:
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
