"""
Перенос накопленного из JSON-файлов в базу и сверка (шаг 4 плана, DATA_MODEL.md, раздел 7).

    python3 -m db.migrate          пересобрать базу из data/competitors и config/ и сверить
    python3 -m db.migrate verify   только сверка
    python3 -m db.migrate stop     остановить локальный Postgres (ноутбук)

Пока база не главная (сбор пишет в JSON), перенос каждый раз пересобирает её с нуля — повторяемо
и безопасно. Ваша разметка берётся из config/market_curation.json и не меняется.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg2.extras import Json, execute_values

from competitors import collector, curation, market, protodata, seatmap, vladimirkoncert
from competitors.storage import CONFIG_DIR, load_json
from db import connect
from db.projects import Registry, homonym_keys, title_key

DATA = collector.DATA_DIR
MARKET = DATA / "market"
TABLES = ["migrations_log", "collection_runs", "settings", "ai_cache", "niche_overrides", "session_edits", "price_maps",
          "seat_sales", "observations", "pools", "listing_seen", "listings", "sessions", "project_suggestions",
          "project_names", "projects", "artists", "hall_reserve", "layouts", "hall_seats", "halls", "venue_names",
          "venues", "cities", "operators"]

OPERATORS = [
    ("kassir", "Кассир", "federal", "kassir", ["kassir.ru"], {"scheme": "иногда", "remaining_by_price": True, "organizer": True}),
    ("yandex", "Яндекс Афиша", "aggregator", "yandex", ["afisha.yandex.ru"], {"scheme": "только свободные + геометрия", "sale_opening": True}),
    ("vladimirkoncert", "Движок vladimirkoncert", "regional", "vladimirkoncert", sorted(vladimirkoncert.SITES), {"scheme": "все места"}),
    ("odk33", "ОДКиИ (odk33.ru)", "venue_site", "odk33", ["odk33.ru"], {"scheme": "через vladimirkoncert"}),
    ("custom", "Свои мероприятия", "custom", None, [], {}),
]


# Площадки прямого сбора: как они пишутся в афише рынка (Кассир / Яндекс) — одна площадка в базе
DIRECT_VENUE_ALIASES = {
    ("Владимир", "ОДКиИ"): ["Областной Дворец культуры и искусства", "Дворец культуры и искусства"],
    ("Иваново", "Центр культуры и отдыха"): ["ЦКиО"],
    ("Иваново", "Ивановский музыкальный театр"): ["Музыкальный театр"],
}


def _op(key: str) -> str:
    return "kassir" if key.startswith("k:") else "yandex" if key.startswith("y:") else "odk33" if key.startswith("odk33:") else "vladimirkoncert"


def _starts(date: str, time: str | None, tz: str):
    if not date:
        return None
    try:
        return datetime.fromisoformat(date + "T" + (time or "12:00")).replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        return None


class Migration:
    def __init__(self, conn):
        self.conn, self.cur = conn, conn.cursor()
        self.report: dict = {}
        self.city_id: dict[str, int] = {}
        self.city_tz: dict[str, str] = {}
        self.venue_id: dict[tuple, int] = {}
        self.venue_kind: dict[tuple, str] = {}
        self.alias_to = {(city, curation.venue_key(city, a)): name for (city, name), al in DIRECT_VENUE_ALIASES.items() for a in al}

    # ------------------------------------------------------------ справочники
    def operators(self):
        execute_values(self.cur, "INSERT INTO operators (id, name, kind, engine, sites, caps) VALUES %s",
                       [(i, n, k, e, s, Json(c)) for i, n, k, e, s, c in OPERATORS])

    def cities(self, names: set):
        cfg = load_json(CONFIG_DIR / "market.json", {})
        fo = cfg.get("fo", {})
        regions = load_json(CONFIG_DIR / "market_kassir_regions.json", [])
        tz, kassir = {}, {}
        for reg in regions:
            tz.setdefault(market.norm_city(reg["name"]), reg.get("timezone"))
            kassir.setdefault(market.norm_city(reg["name"]), {"domain": reg["domain"]})
            for sub in reg.get("suburbs", []):
                n = market.norm_city(sub["name"].replace("г. ", ""))
                tz.setdefault(n, reg.get("timezone"))
                kassir.setdefault(n, {"domain": reg["domain"], "suburbId": sub["id"]})
        ya = {market.norm_city(c["name"]): c["id"] for c in load_json(MARKET / "yandex_cities.json", [])}
        for name in sorted(set(cfg.get("cities", [])) | names):
            n = market.norm_city(name)
            t = tz.get(n) or "Europe/Moscow"
            ext = {"kassir": kassir.get(n), "yandex": ya.get(n)}
            self.cur.execute("INSERT INTO cities (name, fo, tz, ext) VALUES (%s, %s, %s, %s) RETURNING id",
                             (name, fo.get(name), t, Json(ext)))
            self.city_id[name], self.city_tz[name] = self.cur.fetchone()[0], t

    def venue(self, city: str, name: str) -> int:
        alias = name
        name = self.alias_to.get((city, curation.venue_key(city, name)), name)
        vk = curation.venue_key(city, name)
        key = (city, vk)
        if key in self.venue_id and alias != name:
            self._alias_name(self.venue_id[key], city, alias)
        if key in self.venue_id:
            return self.venue_id[key]
        mark = self.cur_marks["venues"].get(vk)
        kind, src = (mark["type"], "user") if mark else (curation.auto_venue_type(name), "auto")
        self.cur.execute("INSERT INTO venues (city_id, name, name_key, kind, kind_src, kind_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                         (self.city_id[city], name, vk.split("|", 1)[1], kind, src, mark.get("at") if mark else None))
        vid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO venue_names (venue_id, city_id, name_key, name, source) VALUES (%s,%s,%s,%s,%s)",
                         (vid, self.city_id[city], vk.split("|", 1)[1], name, "user" if mark else "auto"))
        self.venue_id[key], self.venue_kind[key] = vid, kind if src == "user" else None
        if alias != name:
            self._alias_name(vid, city, alias)
        return vid

    def _alias_name(self, vid: int, city: str, alias: str) -> None:
        self.cur.execute("INSERT INTO venue_names (venue_id, city_id, name_key, name, source) VALUES (%s,%s,%s,%s,'alias') ON CONFLICT DO NOTHING",
                         (vid, self.city_id[city], curation.venue_key(city, alias).split("|", 1)[1], alias))

    # ------------------------------------------------------------ проекты
    def build_projects(self, rows: list[dict]) -> Registry:
        reg = Registry()
        legacy_marks = self.cur_marks["projects"]
        conflicts = []
        # Ваши пометки — первыми: ключ по новому правилу + старый ключ как ещё одно написание
        for old_pk, m in sorted(legacy_marks.items(), key=lambda kv: kv[1].get("at") or ""):
            key = title_key(m.get("title") or old_pk) or old_pk
            pid = reg.find(key)
            if pid is None:
                pid = reg.add_project(m.get("title") or old_pk, key, source="migrated")
            elif reg.projects[pid]["mark"] and reg.projects[pid]["mark"] != m["type"]:
                conflicts.append((reg.projects[pid]["title"], m.get("title")))
            reg.add_name(pid, old_pk, "", m.get("title") or old_pk, "legacy_key")
            reg.projects[pid]["mark"], reg.projects[pid]["mark_at"] = m["type"], m.get("at")  # позднейшая пометка
        homonyms = homonym_keys(rows, lambda r: self.venue_kind.get((r["city"], curation.venue_key(r["city"], r["venue"]))))
        for r in rows:
            key = r["_key"]
            scope = "venue:%d" % self.venue(r["city"], r["venue"]) if key in homonyms else ""
            pid = reg.find(key, scope) or (reg.find("", "", legacy=r["_legacy"]) if not scope else None)
            if pid is None and scope:  # одноимённая постановка: пометка «Щелкунчика» — на каждую сцену отдельно
                base = reg.find(key) or reg.find("", "", legacy=r["_legacy"])
                pid = reg.add_project(r["_title"], key, scope, format=r.get("format"), sphere=r.get("sphere"))
                if base is not None and reg.projects[base]["mark"]:
                    reg.projects[pid]["mark"], reg.projects[pid]["mark_at"] = reg.projects[base]["mark"], reg.projects[base]["mark_at"]
            elif pid is None:
                pid = reg.add_project(r["_title"], key or r["_legacy"] or r["_title"].lower(), "", format=r.get("format"),
                                      sphere=r.get("sphere"), genre=r.get("genre"))
            reg.projects[pid].setdefault("format", r.get("format"))
            r["_pid"] = pid
        self.report["projects"] = {"проектов": len(reg.projects), "одноимённых ключей (по площадке)": len(homonyms),
                                   "конфликтов пометок": conflicts[:10]}
        self.report["projects"]["артистов"] = reg.link_artists()
        return reg

    def save_projects(self, reg: Registry) -> dict[int, int]:
        artist_db = {}
        for ak, a in reg.artists.items():
            self.cur.execute("INSERT INTO artists (name, key, mark, mark_at) VALUES (%s,%s,%s,%s) RETURNING id", (a["name"], ak, a["mark"], a["mark_at"]))
            artist_db[ak] = self.cur.fetchone()[0]
        pid_db = {}
        for pid, p in reg.projects.items():
            self.cur.execute("INSERT INTO projects (title, artist_id, format, sphere, genre, mark, mark_at, scope) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                             (p["title"], artist_db.get(p["artist"]), p.get("format"), p.get("sphere"), p.get("genre"), p["mark"], p["mark_at"], p["scope"]))
            pid_db[pid] = self.cur.fetchone()[0]
        execute_values(self.cur, "INSERT INTO project_names (key, scope, project_id, example, source) VALUES %s",
                       [(k, s, pid_db[pid], reg.projects[pid]["names"][(k, s)][0], reg.projects[pid]["names"][(k, s)][1])
                        for (k, s), pid in reg.names.items()])
        sugg = reg.suggestions()
        if sugg:
            execute_values(self.cur, "INSERT INTO project_suggestions (key, title, project_id, reason, score) VALUES %s ON CONFLICT DO NOTHING",
                           [(s["key"], s["title"], pid_db[s["project_id"]], s["reason"], s["score"]) for s in sugg])
        self.report["projects"]["подсказок"] = len(sugg)
        self.report["projects"]["примеры подсказок"] = [f"{s['title']} → {reg.projects[s['project_id']]['title']} ({s['reason']}, {s['score']})" for s in sugg[:8]]
        return pid_db

    def classify(self, rows: list[dict], reg: Registry) -> None:
        """Гастроль / местное: пометка проекта → артиста → площадки (ваша) → авто (curation._auto по новому ключу)."""
        groups: dict = defaultdict(lambda: defaultdict(list))
        for r in rows:
            r["pk"] = "%s#%s" % (r["_pid"], "")  # группы авто-правила — по проекту, а не по тексту названия
            groups[r["pk"]][r["city"]].append(r)
        for r in rows:
            mark, src = reg.mark_of(r["_pid"])
            if mark:
                r["_tour"], r["_tour_src"], r["_tour_why"] = mark, src, "отмечено вручную" + (" (артист)" if src == "artist" else "")
                continue
            vmark = self.cur_marks["venues"].get(curation.venue_key(r["city"], r["venue"]))
            if vmark and vmark["type"] in ("rental", "repertory"):
                r["_tour"] = "tour" if vmark["type"] == "rental" else "local"
                r["_tour_src"], r["_tour_why"] = "venue", ("прокатная площадка" if vmark["type"] == "rental" else "репертуарный театр") + " (вручную)"
                continue
            r["_tour_src"] = "auto"
            r["_tour"], r["_tour_why"] = curation._auto(r, groups)

    # ------------------------------------------------------------ сеансы рынка
    def market_sessions(self, rows: list[dict], pid_db: dict) -> None:
        orgs = load_json(MARKET / "organizers.json", {})
        n_list = 0
        for r in rows:
            city = r["city"]
            vid = self.venue(city, r["venue"])
            self.cur.execute(
                "INSERT INTO sessions (project_id, venue_id, starts_at, local_date, local_time, status, track_sales, track_since, tour, tour_src, tour_why, "
                "sphere, format, genre, age, pushkin, title, first_seen, last_seen) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (pid_db[r["_pid"]], vid, _starts(r["date"], r.get("time"), self.city_tz[city]), r["date"], r.get("time") or None,
                 r.get("_status", "on_sale"), r["_tour"] == "tour" and r.get("_status", "on_sale") == "on_sale", None,
                 r["_tour"], r["_tour_src"], r["_tour_why"], r.get("sphere"), r.get("format"), r.get("genre"), r.get("age"),
                 bool(r.get("pushkin")), r["title"], r.get("first_seen"), r.get("last_seen")))
            sid = self.cur.fetchone()[0]
            r["_sid"] = sid
            vals = []
            for k in r["keys"]:
                op = _op(k)
                org = (orgs.get(k) or [None])[0] if op == "kassir" else None
                vals.append((sid, op, k, r.get("url_k") if op == "kassir" else r.get("url_y"), (r.get("orig") or {}).get("title") or r["title"],
                             r.get("title_api"), r.get("pmin"), r.get("pmax"), org or r.get("org") or None, r.get("first_seen"), r.get("last_seen")))
            execute_values(self.cur, "INSERT INTO listings (session_id, operator_id, ext_key, url, title, title_api, price_min, price_max, organizer, first_seen, last_seen) "
                                     "VALUES %s ON CONFLICT (operator_id, ext_key) DO NOTHING", vals)
            n_list += len(vals)
        self.report["рынок"] = {"сеансов": len(rows), "карточек": n_list}

    # ------------------------------------------------------------ площадки прямого сбора
    def direct(self, reg: Registry, pid_db: dict, market_rows: list[dict]) -> None:
        events = collector.load_events()
        states = collector.load_seat_states()
        halls = load_json(collector.HALLS_FILE, {})
        hall_of_layout = {l: hid for hid, h in halls.items() for l in h.get("layouts", [])}
        aliases = market.Aliases(load_json(MARKET / "venue_aliases.json", {}))
        slot: dict[tuple, list[dict]] = defaultdict(list)
        for r in market_rows:
            slot[(r["city"], r["date"], r.get("time") or "")].append(r)
        hall_db: dict[str, int] = {}
        known = protodata._venues(list(events.values()))  # источник → (код, название, город): «Арт Холл» — Владимир, а не «Владимирская обл.»
        rep = Counter()
        sold_check = []
        for uid, e in events.items():
            _code, vname, vcity = known.get(e.get("source_id") or e.get("source"), ("", e.get("venue") or "", e.get("city") or ""))
            e = {**e, "venue": vname or e.get("venue") or "", "city": vcity or e.get("city") or ""}
            city = e["city"]
            if city not in self.city_id:
                self.cities_extra(city)
            st0 = states.get(collector.seat_state_path(uid).stem) or {}
            date, time = (e.get("date") or st0.get("date") or "")[:10], e.get("time") or ""  # дата потерялась в строке — из схемы зала
            if not date:
                rep["без даты"] += 1
                continue
            # Тот же сеанс уже есть в афише рынка (Кассир / Яндекс) — одна строка, ещё одна карточка
            # Та же площадка и время + похожее название (DATA_MODEL.md, правило 1): закрытый «Стинг» и новый «Хор русского
            # рока» CAGMO в один вечер в Арт Холле — разные сеансы
            twin = next((m for m in slot.get((city, date, time), [])
                         if (market.same_venue(m["venue"], e["venue"], city, aliases)
                             or self.alias_to.get((city, curation.venue_key(city, m["venue"]))) == e["venue"])
                         and market.similar_title(m["title"], e["title"])), None)
            if twin:
                sid = twin["_sid"]
                rep["склеено с рынком"] += 1
                self.cur.execute("UPDATE sessions SET track_sales = true WHERE id = %s", (sid,))
            else:
                vid = self.venue(city, e.get("venue") or "")
                key = title_key(e["title"])
                pid = reg.find(key) or reg.find("", "", legacy=curation.project_key(e["title"]))
                if pid is None:
                    pid = reg.add_project(e["title"], key or e["title"].lower(), "", format=e.get("format"), sphere=e.get("sphere"))
                    self.cur.execute("INSERT INTO projects (title, format, sphere, genre) VALUES (%s,%s,%s,%s) RETURNING id", (e["title"], e.get("format"), e.get("sphere"), e.get("genre")))
                    pid_db[pid] = self.cur.fetchone()[0]
                    if key:
                        self.cur.execute("INSERT INTO project_names (key, scope, project_id, example) VALUES (%s,'',%s,%s) ON CONFLICT DO NOTHING", (key, pid_db[pid], e["title"]))
                status = "done" if date < datetime.now().date().isoformat() else "on_sale"
                self.cur.execute(
                    "INSERT INTO sessions (project_id, venue_id, starts_at, local_date, local_time, status, track_sales, sphere, format, genre, age, pushkin, title, first_seen, last_seen) "
                    "VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (pid_db[pid], vid, _starts(date, time, self.city_tz.get(city, "Europe/Moscow")), date, time or None, status,
                     e.get("sphere"), e.get("format"), e.get("genre"), e.get("age"), bool(e.get("pushkin")), e["title"],
                     (e.get("first_seen") or "")[:10] or None, (e.get("last_seen") or "")[:10] or None))
                sid = self.cur.fetchone()[0]
                rep["новых сеансов"] += 1
            op = _op(uid)
            self.cur.execute("INSERT INTO listings (session_id, operator_id, ext_key, url, title, price_min, price_max, first_seen, last_seen, ext) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (operator_id, ext_key) DO NOTHING RETURNING id",
                             (sid, op, uid, e.get("url"), e["title"], e.get("price_min"), e.get("price_max"),
                              (e.get("first_seen") or "")[:10] or None, (e.get("last_seen") or "")[:10] or None, Json({"site": e.get("site"), "hall": e.get("hall")})))
            lid = (self.cur.fetchone() or [None])[0]
            st = states.get(collector.seat_state_path(uid).stem)
            sale_op = "vladimirkoncert" if (e.get("vk_event_id") or op == "vladimirkoncert") else op
            self.cur.execute("INSERT INTO pools (session_id, operator_id, service, listing_id, has_scheme) VALUES (%s,%s,%s,%s,%s) "
                             "ON CONFLICT (session_id, operator_id, service) DO UPDATE SET has_scheme = EXCLUDED.has_scheme RETURNING id",
                             (sid, sale_op, e.get("site") or "", lid, bool(st)))
            pool = self.cur.fetchone()[0]
            # Наблюдения — история сборов (точки «весь зал занят» уже помечены anomaly)
            hist = load_json(collector.history_path(uid), [])
            if hist:
                execute_values(self.cur, "INSERT INTO observations (pool_id, ts, free, total, taken, gross, anomaly) VALUES %s",
                               [(pool, p["ts"], p.get("seats_free"), p.get("seats_total"), p.get("seats_taken"), p.get("gross"), bool(p.get("anomaly"))) for p in hist])
                rep["наблюдений"] += len(hist)
            if not st:
                continue
            seats = collector._expand_seats(st["seats"])
            by_id = {s["id"]: seatmap.seat_key(s) for s in seats}
            layout = st.get("layout") or seatmap.layout_signature(seats)  # старые схемы без отпечатка рассадки
            hall_key = hall_of_layout.get(layout) or layout
            if hall_key not in hall_db:
                h = halls.get(hall_key, {})
                vid = self.venue(city, e.get("venue") or "")
                self.cur.execute("INSERT INTO halls (venue_id, name, capacity, ext) VALUES (%s,%s,%s,%s) RETURNING id",
                                 (vid, e.get("hall") or h.get("name"), len(seats), Json({"vladimirkoncert_hall": hall_key})))
                hall_db[hall_key] = self.cur.fetchone()[0]
            hid = hall_db[hall_key]
            execute_values(self.cur, "INSERT INTO hall_seats (hall_id, seat_key, zone, row_name, place, x, y) VALUES %s ON CONFLICT DO NOTHING",
                           [(hid, by_id[s["id"]], str(s["zone"]), s["row"], s.get("place"), s["x"], s["y"]) for s in seats])
            self.cur.execute("INSERT INTO layouts (id, hall_id, seats, seat_keys) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                             (layout, hid, len(seats), sorted(by_id.values())))
            self.cur.execute("UPDATE sessions SET hall_id = %s WHERE id = %s AND hall_id IS NULL", (hid, sid))
            # Продажи по местам и распоясовка (цены мест, когда-либо виденных свободными)
            sales = [(pool, by_id.get(s, "?|?|" + s), sale["ts"], sale.get("price")) for s, sale in st.get("sold", {}).items()]
            if sales:
                execute_values(self.cur, "INSERT INTO seat_sales (pool_id, seat_key, ts, price) VALUES %s ON CONFLICT DO NOTHING", sales)
            prices = [(sid, by_id[s], p, st.get("tracking_since")) for s, p in st.get("registry", {}).items() if s in by_id and p]
            if prices:
                execute_values(self.cur, "INSERT INTO price_maps (session_id, seat_key, price, valid_from) VALUES %s ON CONFLICT DO NOTHING", prices)
            if hist:
                free_keys = sorted(by_id[s] for s in st.get("last_free", []) if s in by_id)
                self.cur.execute("UPDATE observations SET free_seats = %s WHERE id = (SELECT max(id) FROM observations WHERE pool_id = %s)", (free_keys, pool))
            sold_check.append((uid, len(st.get("sold", {})), sum(x.get("price") or 0 for x in st.get("sold", {}).values()), len(sales)))
        manual = load_json(collector.HALL_RESERVE_FILE, {})
        for hall_key, m in manual.items():
            if hall_key in hall_db:
                for row in m.get("rows", []):
                    # ручная бронь рядов — на зал целиком, не на одну рассадку
                    self.cur.execute("INSERT INTO hall_reserve (hall_id, seat_key, kind) VALUES (%s,%s,'manual_row') ON CONFLICT DO NOTHING", (hall_db[hall_key], row))
        self.report["площадки прямого сбора"] = {**rep, "залов": len(hall_db), "мероприятий": len(events)}
        self._sold_check = sold_check

    def cities_extra(self, name: str):
        self.cur.execute("INSERT INTO cities (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id, tz", (name,))
        self.city_id[name], self.city_tz[name] = self.cur.fetchone()

    # ------------------------------------------------------------ ваша разметка, служебное
    def user_data(self):
        execute_values(self.cur, "INSERT INTO session_edits (ext_key, fields, at) VALUES %s",
                       [(k, Json(v["fields"]), v.get("at")) for k, v in self.cur_marks["edits"].items()] or [("—", Json({}), None)])
        self.cur.execute("DELETE FROM session_edits WHERE ext_key = '—'")
        ov = load_json(collector.OVERRIDES_FILE, {})
        if ov:
            execute_values(self.cur, "INSERT INTO niche_overrides (title_key, sphere, format, genre) VALUES %s",
                           [(k, v.get("sphere"), v.get("format"), v.get("genre")) for k, v in ov.items()])
        ai = load_json(collector.AI_CACHE_FILE, {})
        if ai:
            execute_values(self.cur, "INSERT INTO ai_cache (title_key, sphere, format, genre) VALUES %s ON CONFLICT DO NOTHING",
                           [(k, v.get("sphere"), v.get("format"), v.get("genre")) for k, v in ai.items()])
        self.cur.execute("INSERT INTO settings (key, value) VALUES ('market_filters', %s)", (Json(self.cur_marks["filters"]),))
        self.cur.execute("INSERT INTO settings (key, value) VALUES ('venue_aliases', %s)", (Json(load_json(MARKET / "venue_aliases.json", {})),))
        seen = load_json(MARKET / "seen.json", {})
        execute_values(self.cur, "INSERT INTO listing_seen (operator_id, ext_key, first_seen) VALUES %s",
                       [(_op(k), k, d) for k, d in seen.items()], page_size=5000)
        self.report["разметка"] = {"пометок проектов": len(self.cur_marks["projects"]), "пометок площадок": len(self.cur_marks["venues"]),
                                   "правок": len(self.cur_marks["edits"]), "ниш по названию": len(ov), "кэш нейросети": len(ai),
                                   "номеров с датой появления": len(seen)}

    # ------------------------------------------------------------ всё вместе
    def run(self):
        # Пересборка с нуля — только пока база не главная. Когда сбор начнёт писать в базу, ставится
        # settings.db_authoritative = true, и перенос откажется стирать данные.
        self.cur.execute("SELECT value FROM settings WHERE key = 'db_authoritative'")
        flag = self.cur.fetchone()
        if flag and flag[0] is True:
            raise SystemExit("База уже главная (settings.db_authoritative) — пересборка из JSON запрещена")
        self.cur.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
        self.cur_marks = curation.load()
        rows = load_json(MARKET / "events.json", [])
        curation.apply_edits(rows, self.cur_marks)
        archive = load_json(MARKET / "archive.json", {})
        live_keys = {k for r in rows for k in r["keys"]}
        arch_rows = []
        for k, a in archive.items():  # архив гастролей: прошедшие и снятые — сеансы со статусом
            if a.get("status") in ("past", "gone") and k not in live_keys:
                arch_rows.append({**a, "keys": [k], "_status": "done" if a["status"] == "past" else "removed",
                                  "pushkin": False, "age": None})
        all_rows = rows + arch_rows
        cities = {r["city"] for r in all_rows} | {e.get("city") for e in collector.load_events().values() if e.get("city")}
        self.operators()
        self.cities(cities)
        for r in all_rows:
            r["_title"] = (r.get("orig") or {}).get("title") or r["title"]
            r["_key"], r["_legacy"] = title_key(r["_title"]), curation.project_key(r["_title"])
            self.venue(r["city"], r["venue"])
        reg = self.build_projects(all_rows)
        self.classify(all_rows, reg)
        pid_db = self.save_projects(reg)
        self.market_sessions(all_rows, pid_db)
        self.report["архив гастролей"] = {"перенесено (прошло / снято)": len(arch_rows)}
        self.direct(reg, pid_db, rows)
        self.user_data()
        self.report["гастроль / местное"] = self.compare_tour(rows)
        self.cur.execute("INSERT INTO migrations_log (step, report) VALUES ('json_import', %s)", (Json(self.report),))
        self.conn.commit()

    def compare_tour(self, rows: list[dict]) -> dict:
        """Сверка разметки: как было в афише (JSON) → как стало по проектам (база)."""
        moves = Counter((r.get("tour"), r["_tour"]) for r in rows)
        ex = [f"{r['title']} ({r['city']}): {r.get('tour')} → {r['_tour']} — {r['_tour_why']}" for r in rows if r.get("tour") != r["_tour"]][:12]
        lost_marks = [r["title"] for r in rows if r.get("tour_src") == "project" and r["_tour_src"] not in ("project", "artist")]
        return {"было → стало": {f"{a} → {b}": n for (a, b), n in moves.items()}, "примеры изменений": ex,
                "потеряно ваших пометок": len(lost_marks), "гастролей было": sum(1 for r in rows if r.get("tour") == "tour"),
                "гастролей стало": sum(1 for r in rows if r["_tour"] == "tour")}


def verify(conn) -> dict:
    """Сверка базы с JSON-файлами: числа должны совпасть."""
    cur = conn.cursor()
    out = {}
    rows = load_json(MARKET / "events.json", [])
    cur.execute("SELECT count(*) FROM listings WHERE operator_id IN ('kassir', 'yandex') AND session_id IN (SELECT id FROM sessions WHERE status = 'on_sale')")
    out["карточки рынка в продаже (база / JSON)"] = (cur.fetchone()[0], sum(len(r["keys"]) for r in rows))
    events = collector.load_events()
    states = collector.load_seat_states()
    bad = []
    for uid in events:
        st = states.get(collector.seat_state_path(uid).stem) or {}
        cur.execute("SELECT count(*), coalesce(sum(price), 0) FROM seat_sales WHERE pool_id IN (SELECT p.id FROM pools p JOIN listings l ON l.id = p.listing_id WHERE l.ext_key = %s)", (uid,))
        n, s = cur.fetchone()
        want = (len(st.get("sold", {})), sum(x.get("price") or 0 for x in st.get("sold", {}).values()))
        if (n, int(s)) != (want[0], int(want[1])):
            bad.append((uid, (n, int(s)), want))
    out["продажи по местам: расхождений с JSON"] = len(bad)
    out["примеры расхождений"] = bad[:5]
    cur.execute("SELECT count(*) FROM observations")
    out["наблюдений (база / история JSON)"] = (cur.fetchone()[0], sum(len(load_json(collector.history_path(u), [])) for u in events))
    cur.execute("SELECT count(*) FROM projects WHERE mark IS NOT NULL")
    out["проектов с вашей пометкой"] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM project_suggestions WHERE status = 'open'")
    out["подсказок в очереди"] = cur.fetchone()[0]
    return out


def main(argv: list[str]) -> None:
    if argv[:1] == ["stop"]:
        import pgserver
        pgserver.get_server(str(connect.PGDATA), cleanup_mode="stop").cleanup()
        print("Локальный Postgres остановлен")
        return
    conn = connect.connect()
    connect.ensure_schema(conn)
    if argv[:1] != ["verify"]:
        m = Migration(conn)
        m.run()
        print(json.dumps(m.report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(verify(conn), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
