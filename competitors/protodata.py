"""
Живые данные конкурентов для прототипа (Design/prototype/competitors-data.js).

Прототип показывает «Мероприятия», «Историю продаж», «Динамику», «Площадки и залы», «Архив» и журнал сбора
по этому снимку. Через приложение (/proto/competitors-data.js) он собирается заново после каждого
./pull_data.sh; открытый файлом прототип берёт последний сохранённый снимок.

    python3 -m competitors.protodata export     пересобрать Design/prototype/competitors-data.js

Источники — data/competitors: events.json (+ ручные правки config/event_edits.json), seats/ (схемы залов и
подтверждённые продажи), halls.json, history/, collector.log, status.json.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from competitors import collector, edits, seatmap
from competitors.storage import BASE_DIR, load_json

PROTOTYPE_DATA = BASE_DIR / "Design" / "prototype" / "competitors-data.js"

# Площадки, которые уже были в прототипе: короткий код строки, название и город, как их показывает интерфейс.
# Новая площадка из config/competitors.json получает код S1, S2… и название из настроек.
KNOWN_VENUES = {
    "odk33": ("О", "ОДКиИ", "Владимир"),
    "vk-1": ("А", "Арт Холл", "Владимир"),
    "ivanovokoncert-2": ("Ц", "Центр культуры и отдыха", "Иваново"),
    "ivanovokoncert-1": ("М", "Ивановский музыкальный театр", "Иваново"),
}
# Названия залов, которые дал пользователь (номер зала = самая частая рассадка группы)
KNOWN_HALLS = {
    "83ed02b4ac14": "Большой зал",
    "ed5f9a8a0e5a": "Основная рассадка",
    "555588a017c5": "Рассадка без рядов 1–13",
    "156a8c059790": "Рассадка с рядом 13А",
    "98216eba9f75": "Зрительный зал",
    "0cf0fe300fd5": "Зрительный зал",
}
GONE_AFTER = timedelta(hours=3)   # не видно на сайте дольше, чем другие события той же площадки, — снято с продажи
RUN_MATCH = timedelta(minutes=15)  # отметка сбора в истории и строка «Сбор завершён» в журнале — один сбор
LOG_LINES = 80
# Поля прототипа ↔ поля API /api/events (competitors/edits.py)
PROTO_FIELDS = {"title": "title", "date": "date", "time": "time", "city": "city", "venue": "venue", "sphere": "sphere",
                "format": "format", "genre": "genre", "pmin": "price_min", "pmax": "price_max", "sellable": "seats_sellable",
                "taken": "seats_taken_sellable", "gross": "gross", "revenue": "revenue_est", "pushkin": "pushkin",
                "priceText": "price_text", "link": "url"}

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_DOT = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."]

LOG_RE = re.compile(r"^(\d\d)\.(\d\d) (\d\d:\d\d:\d\d)\s+(.*)$")
START_RE = re.compile(r"=== Сбор начат \((.+?)\)")
END_RE = re.compile(r"=== Сбор завершён: найдено (\d+) мероприятий, новых (\d+), за (\d+) с")
SOLD_RE = re.compile(r"Подтверждённые продажи с прошлого сбора: (\d+) мест на ([\d\s\u00a0]+) ₽")


# ---------------------------------------------------------------- мелочи

def _hm(t: datetime) -> str:
    return f"{t:%H:%M}"


def _day_long(t: datetime) -> str:
    return f"{t.day} {MONTHS_GEN[t.month - 1]}"


def _day_short(iso: str) -> str:
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{d} {MONTHS_SHORT[m - 1]}"


def _stamp(iso: str | None) -> str:
    """«1 окт. 16:45» — как подпись правки в прототипе."""
    if not iso:
        return ""
    t = datetime.fromisoformat(iso)
    return f"{t.day} {MONTHS_DOT[t.month - 1]} {t:%H:%M}"


def _pretty_title(e: dict) -> str:
    title = e.get("alt_title") or e["title"]
    return re.sub(r'"([^"]*)"', r"«\1»", title).strip()


def _price_text(text: str | None) -> str:
    # «Вход по пригласительным билетам» → «по пригласительным»: в таблице вместо цены
    t = re.sub(r"^вход\s+", "", (text or "").strip(), flags=re.I)
    t = re.sub(r"\s+билетам$", "", t)
    return t[:1].lower() + t[1:] if t else ""


def _natural(s: str):
    m = re.match(r"(\d+)(.*)", str(s))
    return (0, int(m.group(1)), m.group(2)) if m else (1, 0, str(s))


def _ref(e: dict):
    """Ссылка строки в прототипе: номер сеанса vladimirkoncert.ru, полный адрес другого сайта или адрес odk33.ru."""
    if e.get("vk_event_id") and e.get("source") in ("odk33", "vladimirkoncert"):
        return int(e["vk_event_id"])
    if e.get("source") == "odk33":
        return e["uid"].split(":", 1)[1]
    return e.get("url") or e["uid"]


def _key(e: dict):
    """Ключ события в ROWS / HALLS / SALES: номер сеанса vladimirkoncert.ru или «сайт:номер»."""
    ref = _ref(e)
    return ref if isinstance(ref, int) else e["uid"]


def _venues(events: list[dict]) -> dict[str, tuple[str, str, str]]:
    """source_id → (код, название, город)."""
    result, n = {}, 0
    for s in collector.load_sources():
        if s["id"] in KNOWN_VENUES:
            result[s["id"]] = KNOWN_VENUES[s["id"]]
        else:
            n += 1
            result[s["id"]] = (f"S{n}", re.sub(r"\s*\(.*?\)\s*", " ", s["name"]).strip(), s.get("city") or "")
    for e in events:  # площадка отключена в настройках, а её события ещё в данных
        sid = e.get("source_id") or e.get("source")
        if sid not in result:
            n += 1
            result[sid] = (f"S{n}", re.sub(r"\s*\(.*?\)\s*", " ", e.get("venue") or sid).strip(), e.get("city") or "")
    return result


# ---------------------------------------------------------------- сборы: журнал + история

def _parse_log(lines: list[str], year: int, last_month: int) -> list[tuple[datetime, str]]:
    out = []
    for line in lines:
        m = LOG_RE.match(line)
        if not m:
            continue
        d, mo, t, text = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        y = year - 1 if mo > last_month else year
        try:
            out.append((datetime.fromisoformat(f"{y:04d}-{mo:02d}-{d:02d}T{t}"), text))
        except ValueError:
            continue
    return out


def _runs(stamps: set[str], log: list[tuple[datetime, str]]) -> list[dict]:
    """Все сборы по порядку: отметки в history/ и seats/ (точное время сбора) + строки журнала."""
    times = sorted({datetime.fromisoformat(s) for s in stamps})
    ends = [(t, m) for t, text in log for m in [END_RE.search(text)] if m]
    for t, _m in ends:  # сбор без единого изменения в истории не оставил следа — берём время из журнала
        if not any(timedelta(0) <= t - x <= RUN_MATCH for x in times):
            times.append(t)
    times.sort()
    starts = [(t, m.group(1)) for t, text in log for m in [START_RE.search(text)] if m]
    sold = [(t, m) for t, text in log for m in [SOLD_RE.search(text)] if m]
    runs = []
    for t in times:
        run = {"ts": t, "trigger": "по расписанию"}
        end = next(((et, m) for et, m in ends if timedelta(0) <= et - t <= RUN_MATCH), None)
        start = next(((st, trig) for st, trig in reversed(starts) if st <= t and t - st <= timedelta(hours=2)), None)
        if start:
            run.update(start=start[0], trigger=start[1])
        if end:
            run.update(end=end[0], found=int(end[1].group(1)), fresh=int(end[1].group(2)), took=int(end[1].group(3)))
        s = next((m for st, m in sold if timedelta(0) <= st - t <= RUN_MATCH), None)
        if s:
            run.update(sold=int(s.group(1)), soldRub=int(re.sub(r"\D", "", s.group(2))))
        runs.append(run)
    return runs


# ---------------------------------------------------------------- снимок

def build() -> dict:
    parsed = collector.load_events()
    if not parsed:
        raise RuntimeError("Нет данных конкурентов — сначала ./pull_data.sh")
    # Строки — данные парсера; ручные правки и свои события прототип накладывает сам (CD.edits, CD.custom)
    events = list(parsed.values())
    venues = _venues(events)
    by_stem = {collector.seat_state_path(e["uid"]).stem: e for e in events}
    states = collector.load_seat_states()
    histories = {e["uid"]: load_json(collector.history_path(e["uid"]), []) for e in events}

    def vinfo(e):
        return venues.get(e.get("source_id") or e.get("source"), ("?", e.get("venue") or "", e.get("city") or ""))

    # Снято с продажи: давно не видно на сайте, хотя другие события той же площадки видны
    latest_seen = defaultdict(str)
    for e in events:
        sid = e.get("source_id") or e.get("source")
        latest_seen[sid] = max(latest_seen[sid], e.get("last_seen") or "")
    today = datetime.now().date().isoformat()

    def status(e):
        if (e.get("date") or "9999") < today:
            return "past"
        last, top = e.get("last_seen"), latest_seen[e.get("source_id") or e.get("source")]
        if last and top and datetime.fromisoformat(top) - datetime.fromisoformat(last) > GONE_AFTER:
            return "gone"
        return ""

    ev_rows = []
    for e in sorted(events, key=lambda r: (r.get("date") or "9999", r.get("time") or "", r["title"])):
        code, _name, _city = vinfo(e)
        ev_rows.append([
            _pretty_title(e), code, e.get("date") or "", e.get("time") or "", e.get("sphere") or "", e.get("format") or "",
            e.get("genre") or "", e.get("price_min"), e.get("price_max"), e.get("seats_taken_sellable"), e.get("seats_sellable"),
            e.get("gross"), e.get("revenue_est"), 1 if e.get("pushkin") else 0, _price_text(e.get("price_text")), _ref(e),
            e["uid"], e.get("sold_confirmed"), e.get("revenue_confirmed"), (e.get("first_seen") or "")[:16],
            (e.get("last_seen") or "")[:16], status(e),
        ])

    # Зал по рядам у каждого события со схемой
    rows, track_from = {}, {}
    for stem, st in states.items():
        e = by_stem.get(stem)
        if not e:
            continue
        seats = collector._expand_seats(st["seats"])
        seatmap.price_seats(seats, st.get("registry", {}))
        zones = defaultdict(lambda: defaultdict(list))
        for s in seats:
            zones[s["zone"]][s["row"]].append(s)
        rows[str(_key(e))] = [
            [z, [[r, len(ss), sum(1 for s in ss if s["taken"]),
                  (Counter(s["price"] or s.get("est_price") for s in ss if s["price"] or s.get("est_price")).most_common(1) or [(0, 0)])[0][0]]
                 for r, ss in sorted(zones[z].items(), key=lambda kv: _natural(kv[0]))]]
            for z in sorted(zones, key=_natural)
        ]
        if st.get("tracking_since"):
            name = vinfo(e)[1]
            track_from[name] = min(track_from.get(name, st["tracking_since"]), st["tracking_since"])

    halls = _halls(states, by_stem, vinfo)

    # Сборы и подтверждённые продажи
    status_file = collector.load_status()
    last_at = datetime.fromisoformat(status_file["last_run_at"]) if status_file.get("last_run_at") else datetime.now()
    log_lines = collector.LOG_FILE.read_text(encoding="utf-8").splitlines() if collector.LOG_FILE.exists() else []
    log = _parse_log(log_lines, last_at.year, last_at.month)
    stamps = {p["ts"] for h in histories.values() for p in h if p.get("ts")}
    sold_by_ts = defaultdict(lambda: defaultdict(list))  # время сбора → событие → места
    for stem, st in states.items():
        e = by_stem.get(stem)
        if not e or not st.get("sold"):
            continue
        seat_by_id = {s[0]: s for s in st["seats"]}
        for seat_id, sale in st["sold"].items():
            stamps.add(sale["ts"])
            sold_by_ts[sale["ts"]][_key(e)].append((seat_by_id.get(seat_id), sale.get("price") or 0))
    runs = _runs(stamps, log)
    run_index = {r["ts"]: i for i, r in enumerate(runs)}

    sales = []
    for ts in sorted(sold_by_ts, reverse=True):
        t = datetime.fromisoformat(ts)
        i = run_index.get(t, 0)
        prev = runs[i - 1]["ts"] if i > 0 else None
        items = []
        for key, sold in sold_by_ts[ts].items():
            groups = defaultdict(list)
            for seat, price in sold:
                if seat:
                    groups[(seat[3], seat[4], price)].append(str(seat[7] or "?"))
            items.append({"id": key, "seats": [[z, r, sorted(p, key=_natural), price]
                                                for (z, r, price), p in sorted(groups.items(), key=lambda kv: (_natural(kv[0][0]), _natural(kv[0][1])))]})
        sales.append({"day": _day_long(t), "at": _hm(t), "prev": _hm(prev) if prev else "",
                      "trigger": runs[i]["trigger"] if runs else "по расписанию",
                      "mins": int((t - prev).total_seconds() // 60) if prev else 0, "items": items})

    # Изменения по истории: освободившиеся места и цены; «Что изменилось» — последний сбор против прошлого
    freed, prices, changes = [], [], []
    last_run = runs[-1]["ts"] if runs else last_at
    prev_run = runs[-2]["ts"] if len(runs) > 1 else None
    by_uid = {e["uid"]: e for e in events}
    for uid, hist in histories.items():
        e = by_uid[uid]
        for a, b in zip(hist, hist[1:]):
            ta, tb = datetime.fromisoformat(a["ts"]), datetime.fromisoformat(b["ts"])
            base = {"id": _key(e), "at": _hm(tb), "day": _day_short(b["ts"]) + ".", "prev": _hm(ta)}
            if a.get("seats_taken") is not None and b.get("seats_taken") is not None:
                if b["seats_taken"] < a["seats_taken"]:
                    freed.append({**base, "from": a["seats_taken"], "to": b["seats_taken"], "_t": b["ts"]})
                if tb == last_run and b["seats_taken"] != a["seats_taken"] and (e.get("date") or "") >= today:
                    _code, name, city = vinfo(e)
                    changes.append({"title": _pretty_title(e), "city": city, "venue": name, "date": _day_short(e["date"]),
                                    "from": a["seats_taken"], "to": b["seats_taken"]})
            pa, pb = (a.get("price_min"), a.get("price_max")), (b.get("price_min"), b.get("price_max"))
            if all(v is not None for v in pa + pb) and pa != pb:
                prices.append({**base, "from": list(pa), "to": list(pb), "_t": b["ts"]})
    freed.sort(key=lambda x: x.pop("_t"), reverse=True)
    prices.sort(key=lambda x: x.pop("_t"), reverse=True)

    # Кто определил нишу у предстоящих событий
    upcoming = [e for e in events if (e.get("date") or "9999") >= today]
    class_src = {f: dict(Counter((e.get("class_source") or {}).get(f) or "none" for e in upcoming)) for f in ("sphere", "format", "genre")}

    # Источники в настройках: событий и сколько со схемой зала
    src_counts = defaultdict(lambda: [0, 0])
    for e in upcoming:
        name = vinfo(e)[1]
        src_counts[name][0] += 1
        src_counts[name][1] += 1 if collector.seat_state_path(e["uid"]).stem in states else 0

    lr = runs[-1] if runs else {"ts": last_at}
    last = {"day": f"{lr['ts'].day} {MONTHS_DOT[lr['ts'].month - 1]}", "trigger": lr.get("trigger", "по расписанию"),
            "from": _hm(lr.get("start", lr["ts"])), "to": _hm(lr.get("end", lr["ts"])), "took": lr.get("took", 0),
            "found": lr.get("found", len(upcoming)), "fresh": lr.get("fresh", 0), "sold": lr.get("sold", 0),
            "soldRub": lr.get("soldRub", 0), "ok": status_file.get("last_ok", True), "error": status_file.get("last_error")}

    by_api = {v: k for k, v in PROTO_FIELDS.items()}
    saved = edits._load()
    edit_map = {uid: {"fields": {by_api[f]: v for f, v in rec["fields"].items() if f in by_api}, "at": _stamp(rec["at"])}
                for uid, rec in saved["by_uid"].items() if uid in parsed}
    custom = [{"uid": c["uid"], "created": _stamp(c.get("created")), **{k: c.get(f) for k, f in PROTO_FIELDS.items()}}
              for c in saved["custom"]]

    return {
        "at": last_at.isoformat(timespec="minutes"),
        "edits": edit_map, "custom": custom,
        "venue": {v[0]: v[1] for v in venues.values()},
        "venueCity": {v[0]: v[2] for v in venues.values()},
        "ev": ev_rows, "rows": rows, "halls": halls, "sales": sales,
        "trackFrom": {k: v[:16] for k, v in sorted(track_from.items(), key=lambda kv: kv[1])},
        "runs": [r["ts"].isoformat(timespec="minutes") for r in runs],
        "prevRun": prev_run.isoformat(timespec="minutes") if prev_run else None,
        "freed": freed[:300], "prices": prices[:300], "changes": changes,
        "classSrc": class_src, "srcCounts": dict(src_counts), "last": last,
        "log": log_lines[-LOG_LINES:],
    }


def _halls(states: dict, by_stem: dict, vinfo) -> list[dict]:
    """Залы для «Площадки и залы»: схема последнего события, частота занятости каждого места и бронь."""
    out = []
    by_layout = defaultdict(list)
    for stem, st in states.items():
        by_layout[st.get("layout")].append(stem)
    for hall_id, h in collector.load_halls().items():
        members = [stem for layout in h.get("layouts", [hall_id]) for stem in by_layout.get(layout, []) if stem in by_stem]
        if not members:
            continue
        expanded = {stem: collector._expand_seats(states[stem]["seats"]) for stem in members}
        sets = {stem: ({seatmap.seat_key(s) for s in ss}, {seatmap.seat_key(s) for s in ss if s["taken"]})
                for stem, ss in expanded.items()}
        found = seatmap.auto_reserve(list(sets.values()))
        latest = max(members, key=lambda stem: (states[stem].get("date") or "", stem))
        # Квота серии — места, закрытые во всех событиях одной рассадки (как в collector.recompute_money)
        series = set()
        for layout in {states[stem].get("layout") for stem in members}:
            series |= seatmap.auto_reserve([sets[s] for s in members if states[s].get("layout") == layout])
        series -= found
        present, taken = Counter(), Counter()
        for all_keys, taken_keys in sets.values():
            present.update(all_keys)
            taken.update(taken_keys)
        sample = expanded[latest]
        seatmap.price_seats(sample, states[latest].get("registry", {}))
        seat = []
        for s in sample:
            k = seatmap.seat_key(s)
            seat.append([s["x"], s["y"], s["zone"], s["row"], s.get("place") or "?", s["price"] or 0,
                         round(taken[k] / present[k] * 100) if present[k] else 0, 2 if k in found else 3 if k in series else 0])
        e = by_stem[latest]
        out.append({
            "id": hall_id, "venue": vinfo(e)[1], "name": KNOWN_HALLS.get(hall_id) or states[latest].get("hall") or "Зал",
            "seats": len(sample), "events": len(members), "layouts": len(h.get("layouts", [])), "auto": h.get("auto_enabled", True),
            "autoN": h.get("auto_reserve", len(found)), "seriesN": sum(1 for x in seat if x[7] == 3),
            "w": max((x[0] for x in seat), default=0), "h": max((x[1] for x in seat), default=0),
            "sample": [_pretty_title(e), e.get("date") or ""],
            "members": sorted((_key(by_stem[stem]) for stem in members), key=str), "seat": seat,
        })
    out.sort(key=lambda x: (-x["events"], x["venue"]))
    return out


def export_js() -> str:
    data = build()
    return ("// Живые данные конкурентов для прототипа: сбор " + data["at"].replace("T", " ") + ".\n"
            "// Пересобрать: ./pull_data.sh && python3 -m competitors.protodata export (через app.py — собирается сам)\n"
            "// ev: [название, код площадки, дата, время, сфера, формат, жанр, цена от, цена до, занято, мест в продаже, вал, выручка,\n"
            "//  Пушкинская, текст вместо цены, ссылка, uid, подтв. продано мест, подтв. выручка, впервые, в последний раз, past|gone|\"\"]\n"
            "var CD = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")


def export_prototype() -> None:
    try:
        js = export_js()
    except RuntimeError as e:
        sys.exit(str(e))
    PROTOTYPE_DATA.write_text(js, encoding="utf-8")
    print(f"{PROTOTYPE_DATA.relative_to(BASE_DIR)}: {len(js) // 1024} КБ")


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        export_prototype()
    else:
        sys.exit(__doc__)
