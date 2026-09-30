"""Разовый сбор сырых данных «Афиши рынка»: Кассир + Яндекс Афиша по городам списка.
Сохраняет ответы как есть в raw/, разбор — отдельным скриптом (market_build.py)."""
import json, sys, time, threading, urllib.request, urllib.error, http.cookiejar
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
RAW = Path("raw"); (RAW / "kassir").mkdir(parents=True, exist_ok=True); (RAW / "yandex").mkdir(parents=True, exist_ok=True)
REGIONS = json.load(open("kassir_regions.json"))
KMAP = json.load(open("city_map.json"))          # город -> [(kind, domain, name, slug, active, region)]
YMAP = json.load(open("ya_city_map.json"))       # город -> yandex id
LOG = open("fetch.log", "a", encoding="utf-8")

def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

def get_json(url, headers=None, opener=None, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})},
                                         method="POST" if data else "GET")
            with (opener.open(req, timeout=40) if opener else urllib.request.urlopen(req, timeout=40)) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            log("retry", i + 1, url[:120], repr(e)[:120]); time.sleep(5 * (i + 1))
    return None

# ---------------------------------------------------------------- Кассир
def kassir_query(domain, extra, tag):
    items, page = [], 1
    while True:
        url = f"https://api.kassir.ru/api/search?domain={domain}&pageSize=100&currentPage={page}{extra}"
        d = get_json(url)
        if not d: log("kassir FAIL", tag, page); break
        items += d["items"]; pc = d["pagination"]["pagesCount"]
        time.sleep(0.8)
        if page >= pc: break
        page += 1
    json.dump({"domain": domain, "query": extra, "items": items}, open(RAW / "kassir" / f"{tag}.json", "w"), ensure_ascii=False)
    return len(items)

def kassir_all():
    domains = {}
    for city, hits in KMAP.items():
        domains.setdefault(hits[0][1], set()).add(city)
    for domain, cities in sorted(domains.items()):
        reg = next(r for r in REGIONS if r["domain"] == domain)
        big = domain in ("msk.kassir.ru", "spb.kassir.ru")        # Москву и Петербург не берём — только пригороды из списка
        if not big:
            n = kassir_query(domain, "", domain)
            log("kassir", domain, "всего", n)
        for s in reg["suburbs"]:
            if not s["isActive"]: continue
            if big and s["name"] not in cities: continue
            n = kassir_query(domain, f"&suburbId={s['id']}", f"{domain}__{s['id']}")
            log("kassir", domain, s["name"], n)

# ---------------------------------------------------------------- Яндекс
RUB = """query RubricEventsQuery($paging: PagingInput){ rubricEvents(paging:$paging){
 items{ event{ id url title contentRating type{ code name } tags{ code name type } }
   scheduleInfo{ dates dateStarted dateEnd placePreview placesTotal prices{ value } regularity{ singleShowtime }
     onlyPlace{ id title url address city{ id name } } } }
 paging{ total limit offset } } }"""

def yandex_all():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.open(urllib.request.Request("https://afisha.yandex.ru/vladimir", headers={"User-Agent": UA}), timeout=40).read()
    for city, cid in YMAP.items():
        items, off, total = [], 0, None
        while True:
            body = json.dumps({"operationName": "RubricEventsQuery", "query": RUB, "variables": {"paging": {"limit": 100, "offset": off}}}).encode()
            d = get_json(f"https://afisha.yandex.ru/api/graphql?city={cid}&version=601.0.0&query_name=RubricEventsQuery", opener=op, data=body,
                         headers={"Content-Type": "application/json", "Accept": "*/*", "Origin": "https://afisha.yandex.ru",
                                  "Referer": f"https://afisha.yandex.ru/{cid}", "x-csrf-token": "", "X-Parent-Request-Id": "1",
                                  "x-force-cors-preflight": "1"})
            if not d or not d.get("data"):
                log("yandex FAIL", city, off, str(d)[:200]); break
            r = d["data"]["rubricEvents"]; items += r["items"]; total = r["paging"]["total"]; off += 100
            time.sleep(1.2)
            if off >= total: break
        json.dump({"city": city, "id": cid, "total": total, "items": items}, open(RAW / "yandex" / f"{cid}.json", "w"), ensure_ascii=False)
        log("yandex", city, cid, total, len(items))

if __name__ == "__main__":
    what = sys.argv[1:] or ["kassir", "yandex"]
    th = [threading.Thread(target={"kassir": kassir_all, "yandex": yandex_all}[w]) for w in what]
    for t in th: t.start()
    for t in th: t.join()
    log("ГОТОВО")
