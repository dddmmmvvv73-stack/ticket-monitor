"""Сырые ответы Кассира и Яндекс Афиши (raw/) -> строки «Афиши рынка» (market.json).

Строка = одно мероприятие в одну дату в одном городе списка.
Шум (кино, музеи, экскурсии, квесты, спорт, программы сельских филиалов и библиотек
по Пушкинской карте) отбрасывается; остаются события с форматом из справочника.
"""
import glob, json, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))  # корень проекта — для competitors.classifier
from competitors.classifier import classify_by_rules, GENRES  # noqa: E402

TODAY = "2026-09-30"
CITIES = [l.strip() for l in open("cities.txt", encoding="utf-8") if l.strip()]
REGIONS = json.load(open("kassir_regions.json"))

def norm_city(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е").replace("г.", "").replace("-", " ")).strip()
CITY_BY_NORM = {norm_city(c): c for c in CITIES}

drop = Counter()          # почему отброшено — для блока «Как собрано»
def dropped(src, why):
    drop[(src, why)] += 1

# ---------------------------------------------------------------- общие правила
NOISE_VENUE = re.compile(r"филиал|библиотек|сельск|(?<![а-яё])(сдк|црб|рдк|мбук|мкук|мбу|мау)(?![а-яё])", re.I)
NOISE_TITLE = re.compile(r"познавательн\w* программ|молодежн\w* программ|игров\w* программ|мастер-класс|квест|экскурси|аудиогид|выставк|экспозици", re.I)

# категория сайта -> «тип на сайте» для classify_by_rules (как у vladimirkoncert.ru)
SITE_TYPE = {"koncert": "Концерт", "teatr": "Спектакль", "standup": "Стендапы", "detyam": "Для детей",
             "concert": "Концерт", "theatre": "Спектакль", "kids": "Для детей"}
# категории, которые целиком не рынок мероприятий
DROP_CAT = {"film", "kino", "muzey", "muzei", "ekskursii", "excursion", "excursions", "sport", "kvesty", "quest",
            "cinema", "art", "turizm", "sertifikaty", "certificates"}
EXTRA_FORMAT = {"shou": ("Шоу", "Шоу"), "show": ("Шоу", "Шоу"), "festival": (None, "Фестиваль"), "festivali": (None, "Фестиваль")}

GENRE_BY_NAME = {g.lower(): g for g in GENRES}
YA_GENRE = {"хип-хоп и рэп": "Рэп / хип-хоп", "рэп": "Рэп / хип-хоп", "поп": "Поп", "поп-музыка": "Поп", "рок": "Рок",
            "джаз": "Джаз", "блюз": "Блюз", "классическая музыка": "Классическая музыка", "классика": "Классическая музыка",
            "шансон": "Шансон", "электронная музыка": "Электронная музыка", "электроника": "Электронная музыка",
            "инди": "Инди", "метал": "Метал", "панк": "Панк", "фолк": "Фолк / этника", "этно": "Фолк / этника",
            "альтернатива": "Альтернатива", "r&b": "R&B", "соул": "Соул", "фанк": "Фанк", "эстрада": "Эстрада",
            "комедия": "Комедия", "драма": "Драма", "мелодрама": "Мелодрама", "трагедия": "Трагедия",
            "трагикомедия": "Трагикомедия", "неоклассика": "Неоклассика", "стендап": "Стендап"}
YA_FORMAT_TAG = {"мюзикл": ("Театр", "Мюзикл"), "балет": ("Танец", "Балет"), "опера": ("Музыка", "Опера"),
                 "стендап": ("Комедия и юмор", "Стендап"), "фестиваль": (None, "Фестиваль"), "шоу": ("Шоу", "Шоу"),
                 "спектакль": ("Театр", "Спектакль"), "концерт": ("Музыка", "Концерт"), "лекция": ("Разговорный жанр", "Лекция"),
                 "танцевальное шоу": ("Танец", "Танцевальное шоу"), "иммерсивный спектакль": ("Театр", "Иммерсивный спектакль")}

def niche(title, site_types, extra=None, genre_hint=None):
    res, _ = classify_by_rules(title, site_types)
    for sphere, fmt in (extra or []):
        if not res.get("format") and fmt: res["format"] = fmt
        if not res.get("sphere") and sphere: res["sphere"] = sphere
    if genre_hint and not res.get("genre"): res["genre"] = genre_hint
    if res.get("format") and not res.get("sphere"):
        res["sphere"] = {"Концерт": "Музыка", "Фестиваль": "Музыка", "Спектакль": "Театр", "Шоу": "Шоу", "Стендап": "Комедия и юмор",
                         "Лекция": "Разговорный жанр"}.get(res["format"], "")
    return res

def ntitle(t):
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\b(концерт|спектакль|шоу|группа|гр\.|stand ?up|стендап|tour|тур|балет|мюзикл|опера)\b", " ", t)
    return re.sub(r"[^a-zа-я0-9]", "", t)

def clean_venue(v, city):
    v = re.sub(r"\s*\((%s)\)\s*$" % re.escape(city), "", v or "").strip()
    return v or "—"

rows = []

# ---------------------------------------------------------------- Кассир
suburb_of = defaultdict(set)   # (type, id) -> города пригородов, где Кассир его показывает
files = []
for f in sorted(glob.glob("raw/kassir/*.json")):
    d = json.load(open(f, encoding="utf-8")); files.append(d)
    m = re.search(r"suburbId=(\d+)", d["query"])
    if m:
        reg = next(r for r in REGIONS if r["domain"] == d["domain"])
        sub = next(s for s in reg["suburbs"] if str(s["id"]) == m.group(1))
        for it in d["items"]: suburb_of[(it["type"], it["object"]["id"])].add(sub["name"])

seen = set()
for d in files:
    reg = next(r for r in REGIONS if r["domain"] == d["domain"])
    in_suburb_query = "suburbId" in d["query"]
    for it in d["items"]:
        o, typ = it["object"], it["type"]
        key = (typ, o["id"])
        if key in seen: continue
        seen.add(key)
        cat = (o.get("urlSlug") or "").split("/")[0]
        if cat in DROP_CAT: dropped("Кассир", "кино, музеи, экскурсии, спорт"); continue
        venues = o.get("venues") or []
        vname = venues[0]["name"] if venues else (o.get("venueName") or "")
        if NOISE_VENUE.search(vname) or NOISE_TITLE.search(o["title"]):
            dropped("Кассир", "сельские филиалы, библиотеки, программы"); continue
        # город: «г. X» в адресе → пригород, где Кассир это показывает → поле города → столица региона
        city = None
        addr = (venues[0].get("address") or {}) if venues else {}
        m = re.search(r"(?:^|[\s,])г\.\s*([А-ЯЁ][а-яё]+(?:[\s\-][А-ЯЁа-яё][а-яё]+)?)", addr.get("addressString") or "")
        if m: city = m.group(1)
        elif suburb_of.get(key): city = sorted(suburb_of[key])[0]
        elif addr.get("city"): city = addr["city"]
        elif not in_suburb_query and reg["domain"] not in ("msk.kassir.ru", "spb.kassir.ru"): city = reg["name"]
        city = CITY_BY_NORM.get(norm_city(city))
        if not city: dropped("Кассир", "город не из списка"); continue
        dr = o.get("dateRange") or {}
        begins = (o.get("beginsAt") or dr.get("beginsAt") or "")
        date, time_ = begins[:10], begins[11:16]
        if not date or (dr.get("endsAt") or begins)[:10] < TODAY: dropped("Кассир", "прошло"); continue
        if date < TODAY: date, time_ = TODAY, ""
        extra = [EXTRA_FORMAT[cat]] if cat in EXTRA_FORMAT else []
        nc = niche(o["title"], [SITE_TYPE[cat]] if cat in SITE_TYPE else [], extra)
        if not nc.get("format"): dropped("Кассир", "формат не из справочника"); continue
        pr = o.get("priceRange") or {}
        rows.append({"src": "k", "city": city, "venue": clean_venue(vname, city), "title": o["title"].strip(), "date": date, "time": time_,
                     "sphere": nc.get("sphere", ""), "format": nc["format"], "genre": nc.get("genre", ""),
                     "pmin": int(pr["min"]) if pr.get("min") else None, "pmax": int(pr["max"]) if pr.get("max") else None,
                     "pushkin": bool(o.get("isPushkin")), "age": (o.get("ageGroup") or (o.get("ageGroups") or [{}])[0] or {}).get("name", ""),
                     "urlK": o.get("url"), "urlY": None, "more": max(0, (o.get("activeEventsCount") or 1) - 1),
                     "until": (dr.get("endsAt") or "")[:10] if (o.get("activeEventsCount") or 1) > 1 else ""})

# ---------------------------------------------------------------- Яндекс
ya_types = Counter()
for f in sorted(glob.glob("raw/yandex/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    for it in d["items"]:
        ev, sc = it["event"], it["scheduleInfo"] or {}
        code = (ev.get("type") or {}).get("code", "")
        ya_types[code] += 1
        if code in DROP_CAT: dropped("Яндекс", "кино, музеи, экскурсии, спорт"); continue
        place = sc.get("onlyPlace") or {}
        vname = place.get("title") or sc.get("placePreview") or ""
        if NOISE_VENUE.search(vname) or NOISE_TITLE.search(ev["title"]):
            dropped("Яндекс", "сельские филиалы, библиотеки, программы"); continue
        city = CITY_BY_NORM.get(norm_city((place.get("city") or {}).get("name") or d["city"]))
        if not city: dropped("Яндекс", "город не из списка"); continue
        tags = [t["name"].lower() for t in ev.get("tags") or []]
        genre = next((YA_GENRE.get(t) or GENRE_BY_NAME.get(t) for t in tags if YA_GENRE.get(t) or GENRE_BY_NAME.get(t)), None)
        extra = [YA_FORMAT_TAG[t] for t in tags if t in YA_FORMAT_TAG]
        nc = niche(ev["title"], [SITE_TYPE[code]] if code in SITE_TYPE else [], extra, genre)
        if not nc.get("format"): dropped("Яндекс", "формат не из справочника"); continue
        dates = sorted(x for x in (sc.get("dates") or []) if x >= TODAY)
        if not dates: dropped("Яндекс", "прошло"); continue
        prices = [p["value"] / 100 for p in sc.get("prices") or [] if p.get("value")]
        one = (sc.get("regularity") or {}).get("singleShowtime") or ""
        base = {"src": "y", "city": city, "venue": clean_venue(vname if (sc.get("placesTotal") or 1) == 1 else sc.get("placePreview") or vname, city),
                "title": ev["title"].strip(), "sphere": nc.get("sphere", ""), "format": nc["format"], "genre": nc.get("genre", ""),
                "pmin": int(min(prices)) if prices else None, "pmax": int(max(prices)) if prices else None, "pushkin": False,
                "age": ev.get("contentRating") or "", "urlK": None, "urlY": "https://afisha.yandex.ru" + ev["url"], "more": 0, "until": ""}
        if len(dates) > 12:     # идёт почти каждый день — одна строка с периодом
            rows.append({**base, "date": dates[0], "time": "", "more": len(dates) - 1, "until": dates[-1]})
        else:
            for x in dates:
                rows.append({**base, "date": x, "time": one[11:16] if one[:10] == x else ""})

# ---------------------------------------------------------------- склейка Кассир + Яндекс
by_key = defaultdict(list)
for r in rows:
    if r["src"] == "y": by_key[(r["city"], r["date"])].append(r)
out, merged = [], 0
for r in rows:
    if r["src"] != "k": continue
    nt = ntitle(r["title"]); hit = None
    for y in by_key.get((r["city"], r["date"]), []):
        ny = ntitle(y["title"])
        if nt and ny and (nt == ny or (min(len(nt), len(ny)) >= 5 and (nt in ny or ny in nt))):
            hit = y; break
    if hit:
        merged += 1
        hit["src"] = "ky"; hit["urlK"] = r["urlK"]; hit["pushkin"] = hit["pushkin"] or r["pushkin"]
        if not hit["time"]: hit["time"] = r["time"]
        if hit["pmin"] is None: hit["pmin"], hit["pmax"] = r["pmin"], r["pmax"]
        if not hit["genre"]: hit["genre"] = r["genre"]
    else:
        out.append(r)
out += [r for r in rows if r["src"] != "k"]
out.sort(key=lambda r: (r["date"], r["time"] or "99", r["city"], r["title"]))

stats = {"rows": len(out), "merged": merged, "by_src": Counter(r["src"] for r in out), "cities": len({r["city"] for r in out}),
         "dropped": {f"{s}: {w}": n for (s, w), n in sorted(drop.items())}, "ya_types": ya_types.most_common()}
json.dump({"rows": out, "stats": stats}, open("market.json", "w"), ensure_ascii=False)
print(json.dumps(stats, ensure_ascii=False, indent=1, default=dict))
print("по городам:", Counter(r["city"] for r in out).most_common())
print("нет в данных:", [c for c in CITIES if c not in {r["city"] for r in out}])
