"""market.json -> Design/prototype/market-data.js (компактный снимок для прототипа)."""
import json, sys

AT = sys.argv[1]   # время снимка, например «30 сент., 13:40»
d = json.load(open("market.json", encoding="utf-8"))
rows, st = d["rows"], d["stats"]

FO_LISTS = {
    "Центральный": ["Брянск", "Владимир", "Ковров", "Муром", "Иваново", "Калуга", "Кострома", "Орел", "Рязань", "Смоленск", "Тверь",
                    "Ярославль", "Рыбинск", "Белгород", "Старый Оскол", "Воронеж", "Курск", "Липецк", "Реутов", "Щелково", "Королев",
                    "Дубна", "Чехов", "Подольск", "Электросталь", "Серпухов", "Жуковский", "Воскресенск", "Коломна", "Зеленоград",
                    "Раменское", "Химки", "Мытищи", "Орехово-Зуево"],
    "Северо-Западный": ["Архангельск", "Северодвинск", "Вологда", "Череповец", "Мурманск", "Выборг", "Великий Новгород", "Псков",
                        "Петрозаводск", "Калининград"],
    "Южный": ["Ростов-На-Дону", "Краснодар", "Новороссийск", "Астрахань", "Волгоград", "Волжский", "Камышин"],
    "Северо-Кавказский": ["Ставрополь", "Пятигорск"],
    "Приволжский": ["Казань", "Набережные Челны", "Пенза", "Самара", "Тольятти", "Сызрань", "Саратов", "Энгельс", "Балаково", "Ульяновск",
                    "Димитровград", "Уфа", "Ижевск", "Пермь", "Оренбург", "Йошкар-Ола", "Саранск", "Чебоксары", "Нижний Новгород"],
    "Уральский": ["Курган", "Екатеринбург", "Нижний Тагил", "Первоуральск", "Челябинск", "Магнитогорск", "Златоуст", "Миасс", "Тюмень",
                  "Тобольск", "Сургут", "Нижневартовск", "Ханты-Мансийск", "Новый Уренгой", "Ноябрьск", "Салехард", "Надым"],
    "Сибирский": ["Красноярск", "Иркутск", "Братск", "Барнаул", "Кемерово", "Новосибирск", "Омск", "Томск"],
    "Дальневосточный": ["Чита"],
}
FO = {c: fo for fo, cs in FO_LISTS.items() for c in cs}
ALL = [l.strip() for l in open("cities.txt", encoding="utf-8") if l.strip()]
miss = [c for c in ALL if c not in FO]
assert not miss, miss

def idx(lst, v):
    if v not in lst: lst.append(v)
    return lst.index(v)

cities, venues, spheres, formats, genres = list(ALL), [], [], [], []
packed = []
for r in rows:
    packed.append([idx(cities, r["city"]), idx(venues, r["venue"]), r["title"], r["date"], r["time"] or "",
                   idx(spheres, r["sphere"] or ""), idx(formats, r["format"]), idx(genres, r["genre"] or ""),
                   r["pmin"] or 0, r["pmax"] or 0, 1 if r["pushkin"] else 0, r["src"], r["urlK"] or "", r["urlY"] or "",
                   r["more"] or 0, r["until"] or "", "2026-09-30", r["age"] or ""])
out = {"at": AT, "first": "2026-09-30", "cities": cities, "fo": FO, "venues": venues, "spheres": spheres, "formats": formats,
       "genres": genres, "rows": packed,
       "stats": {"merged": st["merged"], "dropped": st["dropped"], "bySrc": st["by_src"]}}
js = ("// Снимок «Афиши рынка»: Кассир + Яндекс Афиша по 98 городам, " + AT + ".\n"
      "// Собран разово для прототипа; строка: [город, площадка, название, дата, время, сфера, формат, жанр,\n"
      "//  цена от, цена до, Пушкинская, источник k/y/ky, ссылка Кассир, ссылка Яндекс, ещё дат, до, впервые замечено, возраст]\n"
      "var MK = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
open(__import__("pathlib").Path(__file__).resolve().parents[1] / "market-data.js", "w", encoding="utf-8").write(js)
print("rows", len(packed), "cities with data", len({r[0] for r in packed}), "venues", len(venues), "size", len(js.encode()) // 1024, "KB")
