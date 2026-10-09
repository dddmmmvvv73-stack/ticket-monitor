"""
Пополнение базы из собранных файлов — база главная, ничего не стирается (шаг плана «база становится главной», 05.10.2026).

    python3 -m db.sync          пополнить базу из data/competitors и config/ (так работает tm-sync на сервере каждый час)
    python3 -m db.sync verify   сверка с файлами

В отличие от db.migrate (пересборка с нуля — до 05.10) номера записей постоянные:
  - площадки, проекты, сеансы, карточки — находятся по постоянным ключам и обновляются;
  - сеанс, пропавший из афиши, остаётся: «прошёл» (дата прошла) или «снят» (дата впереди, сбор источника прошёл
    нормально); перенос даты — в истории сеанса (status_log);
  - наблюдения площадок прямого сбора дописываются, продажи по местам и распоясовка — по последнему состоянию сбора;
  - ваша разметка (config/market_curation.json) — источник пометок «гастроль / местное», применяется каждый раз.
Сборы пока пишут в файлы (их рабочий формат); база — долгое хранение, архив за годы и аналитика.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from psycopg2.extras import Json, execute_values

from competitors import collector, curation, direct_match, market, protodata, seatmap
from competitors.storage import load_json
from db import connect
from db.migrate import MARKET, OPERATORS, Migration, _op, _starts, listing_url, verify
from db.projects import Registry, homonym_keys, title_key

FRESH = timedelta(hours=30)   # сбор источника свежее этого — его «пропало» значит «снято», иначе — сбой сбора, не трогаем


class Sync(Migration):
    """Те же шаги, что у переноса, но поверх уже накопленной базы: найти → обновить, нет — добавить."""

    def __init__(self, conn):
        super().__init__(conn)
        self.today = date.today().isoformat()
        self.rep = Counter()

    # ------------------------------------------------------------ справочники
    def operators(self):
        execute_values(self.cur, "INSERT INTO operators (id, name, kind, engine, sites, caps) VALUES %s ON CONFLICT (id) DO UPDATE "
                                 "SET name = EXCLUDED.name, kind = EXCLUDED.kind, engine = EXCLUDED.engine, sites = EXCLUDED.sites, caps = EXCLUDED.caps",
                       [(i, n, k, e, s, Json(c)) for i, n, k, e, s, c in OPERATORS])

    def load_cities(self, names: set):
        self.cur.execute("SELECT name, id, tz FROM cities")
        for name, cid, tz in self.cur.fetchall():
            self.city_id[name], self.city_tz[name] = cid, tz
        missing = {n for n in names if n and n not in self.city_id}
        if missing:
            self.cities(missing)  # как в переносе: пояс и номера у операторов — из справочников

    def load_venues(self):
        self.cur.execute("SELECT c.name, v.name_key, v.id, v.kind, v.kind_src FROM venues v JOIN cities c ON c.id = v.city_id")
        for city, nk, vid, kind, src in self.cur.fetchall():
            self.venue_id[(city, city + "|" + nk)] = vid
            self.venue_kind[(city, city + "|" + nk)] = kind if src == "user" else None
        self.cur.execute("SELECT c.name, n.name_key, n.venue_id FROM venue_names n JOIN cities c ON c.id = n.city_id")
        for city, nk, vid in self.cur.fetchall():  # написания площадки у операторов — тоже ведут на неё
            self.venue_id.setdefault((city, city + "|" + nk), vid)
        # Ваши пометки площадок — применяем к уже известным (могли поменяться с прошлого раза)
        for vk, m in self.cur_marks["venues"].items():
            city = vk.split("|", 1)[0]
            vid = self.venue_id.get((city, vk))
            if vid:
                self.cur.execute("UPDATE venues SET kind = %s, kind_src = 'user', kind_at = %s WHERE id = %s AND "
                                 "(kind IS DISTINCT FROM %s OR kind_src IS DISTINCT FROM 'user')", (m["type"], m.get("at"), vid, m["type"]))
                self.venue_kind[(city, vk)] = m["type"]

    # ------------------------------------------------------------ проекты
    def build_projects(self, rows: list[dict]) -> Registry:
        """Проекты из базы (постоянные номера) + новые; пометки — из вашей разметки; артисты и подсказки — заново."""
        reg = Registry()
        self.cur.execute("SELECT p.id, p.title, a.key, p.format, p.sphere, p.genre, p.scope FROM projects p LEFT JOIN artists a ON a.id = p.artist_id")
        for pid, title, akey, fmt, sph, gen, scope in self.cur.fetchall():
            reg.projects[pid] = {"title": title, "artist": None, "mark": None, "mark_at": None, "scope": scope, "names": {},
                                 "format": fmt, "sphere": sph, "genre": gen}
            reg._next = max(reg._next, pid + 1)
        self.cur.execute("SELECT key, scope, project_id, example, source FROM project_names")
        for k, s, pid, ex, src in self.cur.fetchall():
            if pid in reg.projects:
                reg.names[(k, s)] = pid
                reg.projects[pid]["names"][(k, s)] = (ex, src)
        self._known_names = set(reg.names)
        self._known_projects = set(reg.projects)
        new_projects = 0

        def add(title, key, scope="", source="auto", **extra):
            nonlocal new_projects
            self.cur.execute("INSERT INTO projects (title, format, sphere, genre, scope) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                             (title, extra.get("format"), extra.get("sphere"), extra.get("genre"), scope))
            new_projects += 1
            return reg.add_project(title, key, scope, source, pid=self.cur.fetchone()[0], **extra)

        # Ваши пометки — как в переносе: ключ по новому правилу + старый ключ как ещё одно написание
        for old_pk, m in sorted(self.cur_marks["projects"].items(), key=lambda kv: kv[1].get("at") or ""):
            key = title_key(m.get("title") or old_pk) or old_pk
            pid = reg.find(key) or reg.find("", "", legacy=old_pk)
            if pid is None:
                pid = add(m.get("title") or old_pk, key, source="migrated")
            reg.add_name(pid, old_pk, "", m.get("title") or old_pk, "legacy_key")
            reg.projects[pid]["mark"], reg.projects[pid]["mark_at"] = m["type"], m.get("at")
        self.apply_aliases(reg)
        homonyms = homonym_keys(rows, lambda r: self.venue_kind.get((r["city"], curation.venue_key(r["city"], r["venue"]))))
        for r in rows:
            # пустой ключ (в названии одни служебные слова) — ищем и храним проект под тем же запасным ключом, иначе
            # каждое пополнение заводило бы его заново
            key = r["_key"] or r["_legacy"] or r["_title"].lower()
            scope = "venue:%d" % self.venue(r["city"], r["venue"]) if key in homonyms else ""
            pid = reg.find(key, scope) or (reg.find("", "", legacy=r["_legacy"]) if not scope else None)
            if pid is None and scope:
                base = reg.find(key) or reg.find("", "", legacy=r["_legacy"])
                pid = add(r["_title"], key, scope, format=r.get("format"), sphere=r.get("sphere"))
                if base is not None and reg.projects[base]["mark"]:
                    reg.projects[pid]["mark"], reg.projects[pid]["mark_at"] = reg.projects[base]["mark"], reg.projects[base]["mark_at"]
            elif pid is None:
                pid = add(r["_title"], key, "", format=r.get("format"), sphere=r.get("sphere"), genre=r.get("genre"))
            r["_pid"] = pid
        artists = reg.link_artists()
        self.rep["проектов новых"] = new_projects
        self.rep["артистов"] = artists
        return reg

    def apply_aliases(self, reg: Registry) -> None:
        """Ваше «это тот же проект» (подсказки): новое название — написание проекта; если по нему уже был отдельный
        проект — его сеансы и написания переходят к проекту, а сам он удаляется."""
        for pk_new, a in self.cur_marks.get("aliases", {}).items():
            tgt = reg.find(title_key(a.get("target") or "")) or reg.find("", "", legacy=a["to"])
            if tgt is None:
                continue
            new_keys = [k for k in {title_key(a.get("title") or ""), pk_new} if k]
            olds = {reg.names.get((k, "")) for k in new_keys} - {None, tgt}
            for k in new_keys:
                reg.names[(k, "")] = tgt
                reg.projects[tgt]["names"].setdefault((k, ""), (a.get("title"), "user"))
                if (k, "") in self._known_names:
                    self.cur.execute("UPDATE project_names SET project_id = %s, source = 'user' WHERE key = %s AND scope = ''", (tgt, k))
            for old in olds:
                self.cur.execute("UPDATE sessions SET project_id = %s WHERE project_id = %s", (tgt, old))
                self.cur.execute("UPDATE project_names SET project_id = %s WHERE project_id = %s", (tgt, old))
                self.cur.execute("DELETE FROM project_suggestions WHERE project_id = %s", (old,))
                self.cur.execute("DELETE FROM projects WHERE id = %s", (old,))
                for k, pid in list(reg.names.items()):
                    if pid == old:
                        reg.names[k] = tgt
                reg.projects.pop(old, None)
                self.rep["проектов склеено по вашим подсказкам"] += 1

    def classify(self, rows: list[dict], reg: Registry) -> None:
        """Как в переносе, плюс пометка артиста из вашей разметки (по началу названия или названию целиком)."""
        super().classify(rows, reg)
        for r in rows:
            if r["_tour_src"] in ("project", "artist"):
                continue
            am = curation.artist_mark(self.cur_marks, r["_title"])
            if am:
                r["_tour"], r["_tour_src"], r["_tour_why"] = am["type"], "artist", f"артист «{am['name']}» — отмечено вручную"

    def save_projects(self, reg: Registry) -> dict[int, int]:
        """Новые написания, артисты (по ключу), пометки — в базу; подсказки — заново (принятые / отклонённые остаются)."""
        new_names = [(k, s, pid, reg.projects[pid]["names"][(k, s)][0], reg.projects[pid]["names"][(k, s)][1])
                     for (k, s), pid in reg.names.items() if (k, s) not in self._known_names]
        if new_names:
            execute_values(self.cur, "INSERT INTO project_names (key, scope, project_id, example, source) VALUES %s ON CONFLICT DO NOTHING", new_names)
        self.rep["написаний новых"] = len(new_names)
        artist_db = {}
        marks = self.cur_marks.get("artists", {})
        for ak, a in reg.artists.items():
            m = marks.get(curation.project_key(a["name"])) or {}
            self.cur.execute("INSERT INTO artists (name, key, mark, mark_at) VALUES (%s,%s,%s,%s) ON CONFLICT (key) DO UPDATE "
                             "SET name = EXCLUDED.name, mark = EXCLUDED.mark, mark_at = EXCLUDED.mark_at RETURNING id",
                             (a["name"], ak, m.get("type"), m.get("at")))
            artist_db[ak] = self.cur.fetchone()[0]
        execute_values(self.cur, "UPDATE projects p SET artist_id = v.a::int, mark = v.m::text, mark_at = v.t::timestamptz FROM (VALUES %s) v(id, a, m, t) "
                                 "WHERE p.id = v.id AND (p.artist_id IS DISTINCT FROM v.a::int OR p.mark IS DISTINCT FROM v.m::text)",
                       [(pid, artist_db.get(p["artist"]), p["mark"], p["mark_at"]) for pid, p in reg.projects.items()], page_size=2000)
        self.rep["проектов с вашей пометкой"] = sum(1 for p in reg.projects.values() if p["mark"])
        self.cur.execute("DELETE FROM project_suggestions WHERE status = 'open'")
        rejected, aliases = self.cur_marks.get("rejected", {}), self.cur_marks.get("aliases", {})
        sugg = [s for s in reg.suggestions()  # отклонённые и уже привязанные вами — не предлагаем
                if curation.project_key(s["title"]) not in aliases
                and curation.project_key(s["title"]) + " → " + curation.project_key(reg.projects[s["project_id"]]["title"]) not in rejected]
        if sugg:
            execute_values(self.cur, "INSERT INTO project_suggestions (key, title, project_id, reason, score) VALUES %s ON CONFLICT DO NOTHING",
                           [(s["key"], s["title"], s["project_id"], s["reason"], s["score"]) for s in sugg])
        self.rep["подсказок"] = len(sugg)
        return {pid: pid for pid in reg.projects}   # номера проектов — уже номера в базе

    # ------------------------------------------------------------ сеансы рынка
    def load_listings(self):
        self.cur.execute("SELECT operator_id, ext_key, id, session_id FROM listings")
        self.listing = {(op, k): (lid, sid) for op, k, lid, sid in self.cur.fetchall()}

    def market_sessions(self, rows: list[dict], pid_db: dict) -> None:
        orgs = load_json(MARKET / "organizers.json", {})
        self.cur.execute("SELECT id, local_date, status FROM sessions")
        sess = {sid: (d.isoformat(), st) for sid, d, st in self.cur.fetchall()}
        updates, listings, merged = [], [], []
        for r in rows:
            city = r["city"]
            vid = self.venue(city, r["venue"])
            sids = sorted({self.listing[(_op(k), k)][1] for k in r["keys"] if (_op(k), k) in self.listing and self.listing[(_op(k), k)][1]})
            status = r.get("_status", "on_sale")
            track = r["_tour"] == "tour" and status == "on_sale"
            starts = _starts(r["date"], r.get("time"), self.city_tz[city])
            if sids:
                sid = sids[0]
                for other in sids[1:]:  # карточки склеились в один сеанс позже — остальные сеансы указывают на него
                    merged.append(other)
                old_date, _old_status = sess.get(sid, (None, None))
                moved = old_date and old_date != r["date"]
                updates.append((sid, pid_db[r["_pid"]], vid, starts, r["date"], r.get("time") or None, status, track, r["_tour"], r["_tour_src"],
                                r["_tour_why"], r.get("sphere"), r.get("format"), r.get("genre"), r.get("age"), bool(r.get("pushkin")), r["title"],
                                r.get("last_seen") or self.today, Json([{"at": self.today, "moved_from": old_date}]) if moved else None))
                self.rep["перенесено дат" if moved else "сеансов обновлено"] += 1
            else:
                self.cur.execute(
                    "INSERT INTO sessions (project_id, venue_id, starts_at, local_date, local_time, status, track_sales, track_since, tour, tour_src, tour_why, "
                    "sphere, format, genre, age, pushkin, title, first_seen, last_seen) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (pid_db[r["_pid"]], vid, starts, r["date"], r.get("time") or None, status, track, datetime.now() if track else None,
                     r["_tour"], r["_tour_src"], r["_tour_why"], r.get("sphere"), r.get("format"), r.get("genre"), r.get("age"),
                     bool(r.get("pushkin")), r["title"], r.get("first_seen") or self.today, r.get("last_seen") or self.today))
                sid = self.cur.fetchone()[0]
                self.rep["сеансов новых"] += 1
            r["_sid"] = sid
            for k in r["keys"]:
                op = _op(k)
                org = (orgs.get(k) or [None])[0] if op == "kassir" else None
                listings.append((sid, op, k, listing_url(r, op), (r.get("orig") or {}).get("title") or r["title"],
                                 r.get("title_api"), r.get("pmin"), r.get("pmax"), org or r.get("org") or None, r.get("first_seen") or self.today,
                                 r.get("last_seen") or self.today))
        if updates:
            execute_values(self.cur, """
                UPDATE sessions s SET project_id = v.pid, venue_id = v.vid, starts_at = v.st::timestamptz, local_date = v.d::date, local_time = v.t::time,
                       status = v.status, track_sales = s.track_sales OR v.track, track_since = CASE WHEN v.track AND s.track_since IS NULL THEN now() ELSE s.track_since END,
                       tour = v.tour, tour_src = v.tsrc, tour_why = v.twhy, sphere = v.sph::text, format = v.fmt::text, genre = v.gen::text,
                       age = v.age::text, pushkin = v.push, title = v.title, last_seen = v.last::date,
                       status_log = s.status_log || coalesce(v.log::jsonb, '[]'::jsonb)
                  FROM (VALUES %s) v(id, pid, vid, st, d, t, status, track, tour, tsrc, twhy, sph, fmt, gen, age, push, title, last, log)
                 WHERE s.id = v.id""", updates, page_size=1000)
        if merged:
            self.cur.execute("UPDATE sessions SET status = 'removed', status_log = status_log || %s WHERE id = ANY(%s) AND status <> 'removed'",
                             (Json([{"at": self.today, "merged": True}]), merged))
            self.rep["сеансов склеено"] += len(merged)
        uniq = {}
        for x in listings:  # одна карточка — один раз за запрос (иначе ON CONFLICT DO UPDATE падает)
            uniq.setdefault((x[1], x[2]), x)
        listings = list(uniq.values())
        execute_values(self.cur, """
            INSERT INTO listings (session_id, operator_id, ext_key, url, title, title_api, price_min, price_max, organizer, first_seen, last_seen) VALUES %s
            ON CONFLICT (operator_id, ext_key) DO UPDATE SET session_id = EXCLUDED.session_id, url = EXCLUDED.url, title = EXCLUDED.title,
                   title_api = EXCLUDED.title_api, price_min = EXCLUDED.price_min, price_max = EXCLUDED.price_max,
                   organizer = coalesce(EXCLUDED.organizer, listings.organizer), last_seen = EXCLUDED.last_seen""", listings, page_size=2000)
        self.seen_market = {(op, k) for _sid, op, k, *_ in listings}

    def close_missing(self) -> None:
        """Карточки рынка, которых нет в свежей афише: сеанс — «прошёл» или «снят» (только если сбор рынка свежий и прошёл)."""
        st = load_json(MARKET / "status.json", {})
        last = st.get("last_run_at")
        fresh = bool(last) and st.get("last_ok", True) and datetime.now() - datetime.fromisoformat(last[:19]) < FRESH
        if not fresh:
            self.rep["рынок: сбор не свежий — «снято» не ставим"] += 1
            return
        gone = [sid for (op, k), (_lid, sid) in self.listing.items() if op in ("kassir", "yandex") and sid and (op, k) not in self.seen_market]
        if not gone:
            return
        # Сеанс снят, только если ни одной его карточки нет в афише (у сеанса бывают карточки двух сайтов)
        live = {self.listing.get((op, k), (None, None))[1] for op, k in self.seen_market}
        gone = sorted(set(gone) - live)
        self.cur.execute("""UPDATE sessions SET status = CASE WHEN local_date < %s THEN 'done' ELSE 'removed' END,
                                                status_log = status_log || jsonb_build_array(jsonb_build_object('at', %s::text, 'left_afisha', true))
                             WHERE id = ANY(%s) AND status = 'on_sale' AND NOT EXISTS
                                   (SELECT 1 FROM listings l WHERE l.session_id = sessions.id AND l.operator_id NOT IN ('kassir', 'yandex'))""",
                         (self.today, self.today, gone))
        self.rep["сеансов ушло из афиши (прошли / сняты)"] += self.cur.rowcount
        self.cur.execute("UPDATE sessions SET status = 'done' WHERE status = 'on_sale' AND local_date < %s", (self.today,))
        self.rep["сеансов прошло"] += self.cur.rowcount

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
        self.cur.execute("SELECT ext->>'vladimirkoncert_hall', id FROM halls WHERE ext ? 'vladimirkoncert_hall'")
        hall_db = dict(self.cur.fetchall())
        self.cur.execute("SELECT listing_key, id FROM pools WHERE source = 'json'")
        pool_db = dict(self.cur.fetchall())
        known = protodata._venues(list(events.values()))
        for uid, e in events.items():
            _code, vname, vcity = known.get(e.get("source_id") or e.get("source"), ("", e.get("venue") or "", e.get("city") or ""))
            e = {**e, "venue": vname or e.get("venue") or "", "city": vcity or e.get("city") or ""}
            city = e["city"]
            if city not in self.city_id:
                self.cities_extra(city)
            st = states.get(collector.seat_state_path(uid).stem)
            date_, time_ = (e.get("date") or (st or {}).get("date") or "")[:10], e.get("time") or ""
            if not date_:
                self.rep["прямой сбор: без даты"] += 1
                continue
            op = _op(uid)
            known_sid = (self.listing.get((op, uid)) or (None, None))[1]
            twin = next((m for m in slot.get((city, date_, time_), []) if direct_match.same_session(m, e, aliases)), None)
            status = "done" if date_ < self.today else "on_sale"
            if twin:
                sid = twin["_sid"]
                if known_sid and known_sid != sid:  # раньше был отдельным сеансом — теперь склеен с рынком
                    self.cur.execute("UPDATE sessions SET status = 'removed', status_log = status_log || %s WHERE id = %s AND status <> 'removed'",
                                     (Json([{"at": self.today, "merged": True}]), known_sid))
                self.cur.execute("UPDATE sessions SET track_sales = true, track_since = coalesce(track_since, now()) WHERE id = %s", (sid,))
            elif known_sid:
                sid = known_sid
                self.cur.execute("UPDATE sessions SET local_date = %s, local_time = %s, status = %s, title = %s, last_seen = %s, "
                                 "sphere = %s, format = %s, genre = %s WHERE id = %s",
                                 (date_, time_ or None, status, e["title"], (e.get("last_seen") or "")[:10] or self.today,
                                  e.get("sphere"), e.get("format"), e.get("genre"), sid))
            else:
                vid = self.venue(city, e["venue"])
                key = title_key(e["title"])
                pid = reg.find(key) or reg.find("", "", legacy=curation.project_key(e["title"]))
                if pid is None:
                    self.cur.execute("INSERT INTO projects (title, format, sphere, genre) VALUES (%s,%s,%s,%s) RETURNING id",
                                     (e["title"], e.get("format"), e.get("sphere"), e.get("genre")))
                    pid = reg.add_project(e["title"], key or e["title"].lower(), "", pid=self.cur.fetchone()[0])
                    if key:
                        self.cur.execute("INSERT INTO project_names (key, scope, project_id, example) VALUES (%s,'',%s,%s) ON CONFLICT DO NOTHING", (key, pid, e["title"]))
                self.cur.execute(
                    "INSERT INTO sessions (project_id, venue_id, starts_at, local_date, local_time, status, track_sales, track_since, sphere, format, genre, age, pushkin, "
                    "title, first_seen, last_seen) VALUES (%s,%s,%s,%s,%s,%s,true,now(),%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (pid, vid, _starts(date_, time_, self.city_tz.get(city, "Europe/Moscow")), date_, time_ or None, status,
                     e.get("sphere"), e.get("format"), e.get("genre"), e.get("age"), bool(e.get("pushkin")), e["title"],
                     (e.get("first_seen") or "")[:10] or self.today, (e.get("last_seen") or "")[:10] or self.today))
                sid = self.cur.fetchone()[0]
                self.rep["прямой сбор: сеансов новых"] += 1
            self.cur.execute("INSERT INTO listings (session_id, operator_id, ext_key, url, title, price_min, price_max, first_seen, last_seen, ext) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (operator_id, ext_key) DO UPDATE SET session_id = EXCLUDED.session_id, "
                             "url = EXCLUDED.url, title = EXCLUDED.title, price_min = EXCLUDED.price_min, price_max = EXCLUDED.price_max, "
                             "last_seen = EXCLUDED.last_seen RETURNING id",
                             (sid, op, uid, e.get("url"), e["title"], e.get("price_min"), e.get("price_max"),
                              (e.get("first_seen") or "")[:10] or self.today, (e.get("last_seen") or "")[:10] or self.today,
                              Json({"site": e.get("site"), "hall": e.get("hall")})))
            lid = self.cur.fetchone()[0]
            sale_op = "vladimirkoncert" if (e.get("vk_event_id") or op == "vladimirkoncert") else op
            pool = pool_db.get(uid)
            if pool is None:
                self.cur.execute("INSERT INTO pools (session_id, operator_id, service, listing_id, listing_key, source, has_scheme) "
                                 "VALUES (%s,%s,%s,%s,%s,'json',%s) RETURNING id", (sid, sale_op, e.get("site") or "", lid, uid, bool(st)))
                pool = self.cur.fetchone()[0]
            else:
                self.cur.execute("UPDATE pools SET session_id = %s, listing_id = %s, has_scheme = %s WHERE id = %s", (sid, lid, bool(st), pool))
            # Наблюдения — только новые точки истории (база хранит всё, файл истории — тоже, но на всякий случай не дублируем)
            hist = load_json(collector.history_path(uid), [])
            if hist:  # только точки позже последней в базе — сравнивает сама база (тот же часовой пояс, что при записи)
                execute_values(self.cur, """
                    INSERT INTO observations (pool_id, ts, free, total, taken, gross, anomaly)
                    SELECT v.p, v.ts::timestamptz, v.f::int, v.tt::int, v.tk::int, v.g::numeric, v.a FROM (VALUES %s) v(p, ts, f, tt, tk, g, a)
                     WHERE v.ts::timestamptz > coalesce((SELECT max(ts) FROM observations WHERE pool_id = v.p), '-infinity'::timestamptz)""",
                               [(pool, p["ts"], p.get("seats_free"), p.get("seats_total"), p.get("seats_taken"), p.get("gross"), bool(p.get("anomaly"))) for p in hist])
                self.rep["прямой сбор: наблюдений новых"] += self.cur.rowcount
            if not st:
                continue
            seats = collector._expand_seats(st["seats"])
            by_id = {s["id"]: seatmap.seat_key(s) for s in seats}
            layout = st.get("layout") or seatmap.layout_signature(seats)
            hall_key = hall_of_layout.get(layout) or layout
            if hall_key not in hall_db:
                self.cur.execute("INSERT INTO halls (venue_id, name, capacity, ext) VALUES (%s,%s,%s,%s) RETURNING id",
                                 (self.venue(city, e["venue"]), e.get("hall") or halls.get(hall_key, {}).get("name"), len(seats),
                                  Json({"vladimirkoncert_hall": hall_key})))
                hall_db[hall_key] = self.cur.fetchone()[0]
            hid = hall_db[hall_key]
            execute_values(self.cur, "INSERT INTO hall_seats (hall_id, seat_key, zone, row_name, place, x, y) VALUES %s ON CONFLICT DO NOTHING",
                           [(hid, by_id[s["id"]], str(s["zone"]), s["row"], s.get("place"), s["x"], s["y"]) for s in seats])
            self.cur.execute("INSERT INTO layouts (id, hall_id, seats, seat_keys) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                             (layout, hid, len(seats), sorted(by_id.values())))
            self.cur.execute("UPDATE sessions SET hall_id = %s WHERE id = %s AND hall_id IS NULL", (hid, sid))
            # Продажи по местам и распоясовка — как в последнем состоянии сбора (возвраты и починки сбоев туда уже внесены)
            self.cur.execute("DELETE FROM seat_sales WHERE pool_id = %s", (pool,))
            sales = [(pool, by_id.get(s, "?|?|" + s), sale["ts"], sale.get("price")) for s, sale in st.get("sold", {}).items()]
            if sales:
                execute_values(self.cur, "INSERT INTO seat_sales (pool_id, seat_key, ts, price) VALUES %s ON CONFLICT DO NOTHING", sales)
            self.cur.execute("DELETE FROM price_maps WHERE session_id = %s AND NOT estimated", (sid,))
            prices = [(sid, by_id[s], p, st.get("tracking_since")) for s, p in st.get("registry", {}).items() if s in by_id and p]
            if prices:
                execute_values(self.cur, "INSERT INTO price_maps (session_id, seat_key, price, valid_from) VALUES %s ON CONFLICT DO NOTHING", prices)
        manual = load_json(collector.HALL_RESERVE_FILE, {})
        for hall_key, m in manual.items():
            if hall_key in hall_db:
                self.cur.execute("DELETE FROM hall_reserve WHERE hall_id = %s AND kind = 'manual_row'", (hall_db[hall_key],))
                for row in m.get("rows", []):
                    self.cur.execute("INSERT INTO hall_reserve (hall_id, seat_key, kind) VALUES (%s,%s,'manual_row') ON CONFLICT DO NOTHING", (hall_db[hall_key], row))

    # ------------------------------------------------------------ ваша разметка, служебное
    def user_data(self):
        self.cur.execute("DELETE FROM session_edits")
        if self.cur_marks["edits"]:
            execute_values(self.cur, "INSERT INTO session_edits (ext_key, fields, at) VALUES %s",
                           [(k, Json(v["fields"]), v.get("at")) for k, v in self.cur_marks["edits"].items()])
        ov = load_json(collector.OVERRIDES_FILE, {})
        self.cur.execute("DELETE FROM niche_overrides")
        if ov:
            execute_values(self.cur, "INSERT INTO niche_overrides (title_key, sphere, format, genre) VALUES %s",
                           [(k, v.get("sphere"), v.get("format"), v.get("genre")) for k, v in ov.items()])
        ai = load_json(collector.AI_CACHE_FILE, {})
        if ai:
            execute_values(self.cur, "INSERT INTO ai_cache (title_key, sphere, format, genre) VALUES %s ON CONFLICT (title_key) DO UPDATE "
                                     "SET sphere = EXCLUDED.sphere, format = EXCLUDED.format, genre = EXCLUDED.genre",
                           [(k, v.get("sphere"), v.get("format"), v.get("genre")) for k, v in ai.items()], page_size=2000)
        for key, value in (("market_filters", self.cur_marks["filters"]), ("venue_aliases", load_json(MARKET / "venue_aliases.json", {}))):
            self.cur.execute("INSERT INTO settings (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, Json(value)))
        seen = load_json(MARKET / "seen.json", {})
        execute_values(self.cur, "INSERT INTO listing_seen (operator_id, ext_key, first_seen) VALUES %s ON CONFLICT DO NOTHING",
                       [(_op(k), k, d) for k, d in seen.items()], page_size=5000)

    # ------------------------------------------------------------ всё вместе
    def run(self):
        self.cur.execute("SET lock_timeout = '30s'")
        self.cur_marks = curation.load()
        rows = load_json(MARKET / "events.json", [])
        curation.apply_edits(rows, self.cur_marks)
        archive = load_json(MARKET / "archive.json", {})
        live_keys = {k for r in rows for k in r["keys"]}
        arch_rows = [{**a, "keys": [k], "_status": "done" if a["status"] == "past" else "removed", "pushkin": False, "age": None}
                     for k, a in archive.items() if a.get("status") in ("past", "gone") and k not in live_keys]
        all_rows = rows + arch_rows
        self.operators()
        self.load_cities({r["city"] for r in all_rows} | {e.get("city") for e in collector.load_events().values() if e.get("city")})
        self.load_venues()
        for r in all_rows:
            r["_title"] = (r.get("orig") or {}).get("title") or r["title"]
            r["_key"], r["_legacy"] = title_key(r["_title"]), curation.project_key(r["_title"])
            self.venue(r["city"], r["venue"])
        reg = self.build_projects(all_rows)
        self.classify(all_rows, reg)
        pid_db = self.save_projects(reg)
        self.load_listings()
        self.market_sessions(all_rows, pid_db)
        self.close_missing()
        self.direct(reg, pid_db, rows)
        self.user_data()
        self.cur.execute("UPDATE pools p SET session_id = l.session_id, listing_id = l.id FROM listings l "
                         "WHERE p.source = 'live' AND l.operator_id = p.operator_id AND l.ext_key = p.listing_key "
                         "AND (p.session_id IS DISTINCT FROM l.session_id OR p.listing_id IS DISTINCT FROM l.id)")
        self.rep["живые запасы касс перепривязано"] = self.cur.rowcount
        # Проекты, оставшиеся без сеансов, написаний и вашей пометки, — мусор (например, заведённые по ошибке)
        self.cur.execute("""DELETE FROM projects p WHERE p.mark IS NULL
                              AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.project_id = p.id)
                              AND NOT EXISTS (SELECT 1 FROM project_names n WHERE n.project_id = p.id)
                              AND NOT EXISTS (SELECT 1 FROM project_suggestions g WHERE g.project_id = p.id)""")
        self.rep["пустых проектов удалено"] = self.cur.rowcount
        # С первого пополнения база главная: пересборка с нуля (db.migrate) больше невозможна
        self.cur.execute("INSERT INTO settings (key, value) VALUES ('db_authoritative', 'true') ON CONFLICT (key) DO UPDATE SET value = 'true'")
        self.report = dict(self.rep)
        self.cur.execute("INSERT INTO migrations_log (step, report) VALUES ('json_sync', %s)", (Json(self.report),))
        self.conn.commit()


def main(argv: list[str]) -> None:
    conn = connect.connect()
    connect.ensure_schema(conn)
    if argv[:1] != ["verify"]:
        s = Sync(conn)
        s.run()
        print(json.dumps(s.report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(verify(conn), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
