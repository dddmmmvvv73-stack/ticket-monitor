"""
Qtickets для сбора продаж (TICKET_PLATFORMS.md, 9.3 и 9.5): страница покупки `qtickets.ru/event/<номер>` открывается
браузером, как у покупателя, и из того, что загрузило окно зала, берутся:
    - схема зала — `window.schemeConfig.screens.*.seats`: у каждого места зона, ряд, место, **цена** и «недоступно»;
    - занятые места — ответ окна `/widget/seats` (`ordered_seats`; проверку 428 проходит код самой страницы);
    - танцпол и входные — остаток по зоне (`appends.zones[зона].free_quantity`): мест у них нет, вместимости тоже.
Цены известны у всех мест, поэтому вал точный (как у vladimirkoncert), а продажи — по местам.
Несколько сеансов у мероприятия — окно сначала показывает выбор даты и времени: нажимается время нашего сеанса (PICK_JS).

Нагрузка (TICKET_PLATFORMS 9.5): одна страница — 5 запросов к серверу Qtickets (страница, загрузчик окна, окно зала,
проверка 428, места) и ~6 к его CDN (скрипты, стили, схема — из кэша браузера); лимит и паузы — в страницах (`Browser`), по
одной странице, пауза 20–40 с; картинки, шрифты и чужие счётчики не грузятся. Суточный лимит поднимается ступенями
(`daily_budget`: 60 → 150 → 300 → 500 → 800, ступень — после суток без отказов, отказ — шаг назад и двое суток ниже).
Отказ (403, 429) — канал qtickets/sales закрывается (competitors/blocks.py); проверка 428 стала заметно сложнее — медленнее,
сильно сложнее — стоп на прогон (в журнал отказов — предупреждение). Частота: до 7 дней — 2 раза в сутки, до 30 — раз
в сутки; без изменений 2 снимка подряд — вдвое реже; «всё продано» — не чаще раза в 3 дня (итог — по последнему снимку).

Браузер — Playwright (Chromium) с постоянным профилем в data/browser/qtickets: кэш схем и файлов окна.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import Counter, deque
from datetime import date, datetime, timedelta

from competitors import blocks
from competitors.storage import BASE_DIR, load_json, save_json
from sales.net import Stopped

PROFILE = BASE_DIR / "data" / "browser" / "qtickets"
RAMP_FILE = BASE_DIR / "data" / "qtickets_ramp.json"   # ступень суточного лимита, с какого момента, исходная сложность 428
RAMP = [60, 150, 300, 500, 800]   # страниц в сутки; потолок — SALES_BUDGET_QTICKETS (по умолчанию — последняя ступень)
RAMP_HOLD = timedelta(hours=24)   # на ступени — сутки без отказов, потом выше
RAMP_BACK = timedelta(hours=48)   # после отказа — шаг назад и двое суток без подъёма
PAUSE = (20.0, 40.0)  # секунд между страницами — случайно в этих пределах
PAUSE_MAX = 240.0
POW_SLOW, POW_STOP = 3, 7          # проверка 428 сложнее исходной на столько бит — медленнее / стоп на прогон
TIERS = [(7, timedelta(hours=12)), (30, timedelta(hours=24)), (90, timedelta(hours=72))]   # 2 раза в сутки — до 7 дней
SOLD_OUT_EVERY = timedelta(days=3)
PAGE_TIMEOUT = 45     # секунд на загрузку страницы и окна зала
RECYCLE = 50          # страниц — и браузер перезапускается (память не копится за прогон; после аварии 11.10)
# Chromium на машине 4 ГБ: без /dev/shm (там мало места), без GPU, кэш — небольшой, память JS — ограничена
CHROME_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--disable-background-networking",
               "--disk-cache-size=52428800", "--js-flags=--max-old-space-size=256", "--renderer-process-limit=2"]
WINDOW, BAD_SHARE, STOP_AFTER = 20, 0.3, 8   # окно ответов; доля сбоев для замедления; подряд сбоев — стоп на прогон
# Что не нужно для данных: картинки афиши, шрифты, счётчики и чаты (схема зала — svg Qtickets — нужна окну)
BLOCK = re.compile(r"\.(png|jpe?g|webp|gif|ico|woff2?|ttf|otf)(\?|$)|/thumbs/|/payment-icons/|mc\.yandex|yandex\.ru/(metrika|watch)|vk\.com|"
                   r"top-fwz|mail\.ru|google|facebook|me-talk|verbox|tiktok|pixel", re.I)
ADDON = re.compile(r"meet|встреч\w* с артист|фото с артист|не является входным", re.I)   # дополнительная услуга, не билет в зал
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# Из памяти окна зала — то, что окно уже показывает покупателю
SCHEME_JS = """() => {
  const c = window.schemeConfig; if (!c || !c.screens) return null;
  const seats = {}, zones = {};
  for (const s of Object.values(c.screens)) {
    for (const [k, z] of Object.entries(s.zones || {}))
      zones[k] = {name: z.name || k, admission: z.admission ? 1 : 0, disabled: z.disabled ? 1 : 0, price: z.price || 0,
                  label: (z.label || '') + ' ' + (z.description || '')};
    for (const [k, v] of Object.entries(s.seats || {}))
      seats[k] = [v.zone_id, v.row, v.place, v.price || 0, v.disabled ? 1 : 0, v.x, v.y];
  }
  const sh = c.show || {};
  return {seats, zones, show: sh.id || null, date: sh.date_text || '', event: (c.event || {}).id || null};
}"""
# Выбор сеанса: у мероприятия с несколькими сеансами окно сначала показывает даты и время (как покупателю), схема зала —
# после нажатия на время (окно переходит на `<организатор>.qtickets.ru/show/<номер>`). [{day, time, show}]
PICK_JS = """() => {
  const box = document.querySelector('.event-dates'); if (!box) return null;
  const out = [];
  for (const row of box.querySelectorAll('.row')) {
    const day = ((row.querySelector('.day') || {}).textContent || '').trim().replace(/\\s+/g, ' ');
    for (const a of row.querySelectorAll('a.times__item')) {
      const m = (a.getAttribute('onclick') || '').match(/loadShow'?,\\s*(\\d+)/);
      if (m) out.push({day, time: a.textContent.trim().replace(/\\s+/g, ' '), show: m[1]});
    }
  }
  return out;
}"""
WIDGET = re.compile(r"\.qtickets\.ru/(event|show)/")


class Browser:
    """Как sales.net.Net, но единица — страница: лимит `cap` страниц за прогон, паузы, сторож отказов, предохранитель."""

    def __init__(self, deadline: float, cap: int | None = None):
        self.site, self.deadline, self.cap = "qtickets", deadline, cap
        self.channel = "qtickets/sales"
        self.probe = blocks.state(self.channel) == "probe"
        self.base = self.pause = 1.0   # множитель паузы PAUSE: предохранитель и сторож проверки его увеличивают
        self.recent: deque = deque(maxlen=WINDOW)
        self.denied: deque = deque(maxlen=WINDOW)
        self.in_row = 0
        self.sent = 0
        self.stats: Counter = Counter()
        self.stopped = False
        self.why = ""
        self._last = 0.0
        self._pw = self._ctx = self._page = None
        self.context: dict = {}            # нагрузка за сутки и лимит (sales/run.py) — в журнал отказов
        self.pow_seen: Counter = Counter()   # сложность проверки 428 → сколько раз (в отчёт прогона)
        self.pow_base = load_json(RAMP_FILE, {}).get("pow")   # исходная сложность (10.10 — 13 бит)
        self._pow_warned = False

    # ------------------------------------------------------------ браузер
    def start(self) -> None:
        from playwright.sync_api import sync_playwright   # здесь: без Playwright остальные кассы работают
        PROFILE.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(str(PROFILE), headless=True, viewport={"width": 1280, "height": 800},
                                                                locale="ru-RU", timezone_id="Europe/Moscow", args=CHROME_ARGS)
        self._ctx.route("**/*", lambda r: r.abort() if BLOCK.search(r.request.url) else r.continue_())
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def recycle(self) -> None:
        """Закрыть и снова открыть браузер — каждые RECYCLE страниц."""
        self.close()
        self._pw = self._ctx = self._page = None
        self.start()

    def close(self) -> None:
        for x in (self._ctx, self._pw):
            try:
                if x is self._pw and x:
                    x.stop()
                elif x:
                    x.close()
            except Exception:
                pass

    def time_left(self) -> float:
        return self.deadline - time.time()

    # ------------------------------------------------------------ страница
    def snapshot(self, event_id: str, d: date | None = None, t: str | None = None) -> dict | None:
        """{seats, zones, show, date, ordered, appends, all_sold, raw} — окно зала загрузилось; {"gone": True} — мероприятия
        нет (404); {"no_show": True, "date": …} — в выборе сеансов нет даты d и времени t; None — не загрузилось (сбой,
        повтор позже). Stopped — лимит, отказ сайта или предохранитель. Несколько сеансов — нажимается время сеанса (d, t)."""
        if self.stopped:
            raise Stopped(self.site)
        if self.cap is not None and self.sent >= self.cap:
            self._stop("лимит", "лимит страниц")
            raise Stopped(self.site)
        if self.sent and self.sent % RECYCLE == 0:
            self.recycle()
        wait = self._last + self.pause * random.uniform(*PAUSE) - time.time()
        if wait > 0:
            time.sleep(wait)
        page, got, bad, pow_ = self._page, {}, [], []

        def on_resp(r):
            host = r.url.split("/")[2] if r.url.count("/") >= 2 else ""
            if not host.endswith(("qtickets.ru", "qtickets.events", "qtickets.tech")):
                return
            if r.status in (403, 429) or "captcha" in r.url:
                bad.append(r.status)
            if "/widget/seats" in r.url and r.status == 200:
                try:
                    got["seats"] = r.body()
                except Exception:
                    pass
            elif "/widget/seats" in r.url and r.status == 428:
                try:
                    pow_.append(int(r.json().get("difficulty") or 0))
                except Exception:
                    pass

        page.on("response", on_resp)
        status, out, err = None, None, None
        try:
            resp = page.goto("https://qtickets.ru/event/%s" % event_id, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT * 1000)
            status = resp.status if resp else None
            if status == 404:
                out = {"gone": True}
            elif status and status < 400:
                end = time.time() + PAGE_TIMEOUT
                scheme, picked = None, False
                while time.time() < end and not bad:
                    frame = next((f for f in page.frames if WIDGET.search(f.url)), None)
                    if frame and "seats" in got:
                        try:
                            scheme = frame.evaluate(SCHEME_JS)
                        except Exception:
                            scheme = None
                        if scheme and scheme["seats"] is not None:
                            break
                    elif frame and not picked:
                        try:
                            picks = frame.evaluate(PICK_JS)
                        except Exception:
                            picks = None
                        for x in picks or []:   # у дня две подписи (широкий и узкий экран): «13 октября вторник 13 октября вторник»
                            x["day"] = re.sub(r"^(.+) \1$", r"\1", x["day"])
                        if picks:   # выбор сеансов: нажать время нужного сеанса, как покупатель
                            pick = pick_show(picks, d, t)
                            if not pick:
                                out = {"no_show": True, "date": "; ".join(sorted({"%s %s" % (x["day"], x["time"]) for x in picks}))[:300]}
                                break
                            picked = True
                            got.pop("seats", None)
                            frame.locator("a.times__item[onclick*='%s']" % pick["show"]).first.click(timeout=10000)
                            end = max(end, time.time() + PAGE_TIMEOUT * 2 / 3)
                    page.wait_for_timeout(400)
                if out:
                    status = 200
                elif scheme and "seats" in got:
                    s = json.loads(got["seats"])
                    out = {**scheme, "ordered": s.get("ordered_seats") or {}, "appends": s.get("appends") or {},
                           "all_sold": bool(s.get("all_sold")), "raw": got["seats"]}
                    status = 200
                else:
                    status = None   # окно зала не загрузилось
        except Exception as e:
            err, status = "ошибка " + type(e).__name__, None
        finally:
            page.remove_listener("response", on_resp)
            self._last = time.time()
            self.sent += 1
        if bad:
            status = bad[0]
        self.stats[("страница", err or status)] += 1   # одна страница — одна запись: по ним считается суточный лимит
        if self._deny(status):
            raise Stopped(self.site)
        if pow_ and self._pow(max(pow_)):
            raise Stopped(self.site)
        self._breaker(status, out)
        return out

    def _pow(self, diff: int) -> bool:
        """Сторож проверки 428: сложность выросла — медленнее (раз за прогон), сильно выросла — стоп. True — остановлен."""
        self.pow_seen[diff] += 1
        if not diff:
            return False
        if self.pow_base is None:   # первая проверка — исходная сложность
            self.pow_base = diff
            ramp = load_json(RAMP_FILE, {})
            save_json(RAMP_FILE, {**ramp, "pow": diff})
            return False
        if diff >= self.pow_base + POW_STOP:
            blocks.log_event(self.channel, "warn", "проверка 428 сильно усложнилась: %d бит (было %d) — стоп на прогон" % (diff, self.pow_base), self._load())
            self._stop("предохранитель", "проверка сложнее на %d бит" % (diff - self.pow_base))
            return True
        if diff >= self.pow_base + POW_SLOW and not self._pow_warned:
            self._pow_warned = True
            self.pause = min(PAUSE_MAX / PAUSE[1], self.pause * 2)
            self.stats[("предохранитель", "проверка сложнее — медленнее")] += 1
            blocks.log_event(self.channel, "warn", "проверка 428 усложнилась: %d бит (было %d) — вдвое медленнее" % (diff, self.pow_base), self._load())
        return False

    def _load(self) -> dict:
        return {"страниц за прогон": self.sent, "пауза, с": round(self.pause * sum(PAUSE) / 2), "лимит прогона": self.cap, **self.context}

    # ------------------------------------------------------------ сторож и предохранитель (как sales.net.Net)
    def _stop(self, why: str, stat: str) -> None:
        self.stopped, self.why = True, why
        self.stats[("предохранитель", stat)] += 1

    def _deny(self, status) -> bool:
        bad = status in (403, 429)
        self.denied.append(bad)
        if not bad:
            if self.probe and status == 200:
                self.probe = False
                if blocks.clear(self.channel):
                    self.stats[("блокировка", "снялась")] += 1
            return False
        if self.probe or sum(self.denied) >= blocks.DENY_IN_WINDOW:
            rec = blocks.trip(self.channel, status, "%s: отказ сайта (%s)" % (self.channel, status), self._load())
            self._stop("отказ", "отказ сайта — закрыт до " + rec["until"][:16])
            return True
        return False

    def _breaker(self, status, out) -> None:
        bad = out is None
        self.recent.append(bad)
        self.in_row = self.in_row + 1 if bad else 0
        if self.in_row >= STOP_AFTER:
            self._stop("предохранитель", "стоп")
            return
        if len(self.recent) >= 10 and sum(self.recent) / len(self.recent) >= BAD_SHARE:
            self.pause = min(PAUSE_MAX / PAUSE[1], self.pause * 2)
            self.recent.clear()
            self.stats[("предохранитель", "медленнее")] += 1
        elif not bad and self.pause > self.base:
            self.pause = max(self.base, self.pause * 0.9)


# ---------------------------------------------------------------- разбор снимка

def pick_show(picks: list, d: date | None, t: str | None) -> dict | None:
    """Сеанс из выбора дат: день «13 октября» и время «20:00» (без времени — единственный в этот день)."""
    if d is None:
        return picks[0] if len(picks) == 1 else None
    day = re.compile(r"(?<!\d)%d %s" % (d.day, MONTHS[d.month - 1]), re.I)
    same_day = [x for x in picks if day.search(x["day"])]
    hm = lambda v: re.sub(r"^0(?=\d:)", "", (re.search(r"\d{1,2}:\d{2}", v or "") or [""])[0])   # «09:00» = «9:00»
    hit = [x for x in same_day if t and hm(x["time"]) == hm(t)]
    if hit:
        return hit[0]
    return same_day[0] if len(same_day) == 1 else None


def same_date(snap: dict, d: date, t: str | None) -> bool:
    """Окно открыло тот же сеанс: «18 октября, 18:00» — день, месяц и (если известно) время совпадают."""
    text = (snap.get("date") or "").lower()
    if not text:
        return True
    if not re.search(r"(?<!\d)%d %s" % (d.day, MONTHS[d.month - 1]), text):
        return False
    return not t or t in text or not re.search(r"\d{1,2}:\d{2}", text)


def hall(snap: dict) -> dict:
    """
    Места с креслами: all {«зона|ряд|место»: цена} — выставленные (без «недоступно» и дополнительных услуг), free — свободные,
    geo — [[место, зона, ряд, номер, x, y]] для «Зала по рядам»; входные (танцпол): [[зона, цена, свободно]];
    outside — занятых, которых нет в схеме (старая раскладка зала — в продажи не идут).
    """
    zones = snap.get("zones") or {}
    names = Counter(z["name"] for z in zones.values())
    zname = lambda zid: (zones.get(zid) or {}).get("name") or zid
    label = lambda zid: zname(zid) if names[zname(zid)] == 1 else "%s (%s)" % (zname(zid), zid)
    addon = {zid for zid, z in zones.items() if ADDON.search(z["name"] + " " + z.get("label", ""))}
    admission = {zid for zid, z in zones.items() if z["admission"]}
    occ = set(snap.get("ordered") or {})
    all_, free, geo = {}, {}, []
    for sid, (zid, row, place, price, disabled, x, y) in (snap.get("seats") or {}).items():
        if zid in admission or zid in addon or disabled or (zones.get(zid) or {}).get("disabled"):
            continue
        k = "%s|%s|%s" % (label(zid), row, place)
        all_[k] = price
        geo.append([k, label(zid), str(row), str(place), x, y])
        if sid not in occ:
            free[k] = price
    adm = []
    for zid, a in ((snap.get("appends") or {}).get("zones") or {}).items():
        z = zones.get(zid)
        if not z or zid in addon or zid not in admission:   # «disabled» у входной зоны — не выбирается на схеме, но продаётся
            continue
        adm.append([z["name"], z["price"], int(a.get("free_quantity") or 0)])
    outside = len(occ - set(snap.get("seats") or {}))
    return {"all": all_, "free": free, "geo": geo, "admission": adm, "outside": outside}


def gross(all_: dict) -> dict | None:
    """Вал выставленных мест — точный: цена известна у каждого места."""
    total = sum(p for p in all_.values() if p)
    if not total:
        return None
    return {"gross": round(total), "gross_lo": round(total), "gross_hi": round(total), "exact_share": 1.0, "exposed": len(all_)}


# ---------------------------------------------------------------- суточный лимит ступенями и частота опроса

def daily_budget(now: datetime | None = None) -> tuple[int, str]:
    """Суточный лимит страниц по ступеням RAMP: сутки на ступени без отказов Qtickets (любой канал qtickets/…) — выше;
    отказ после начала ступени — ниже и двое суток без подъёма. Возвращает (лимит, что изменилось — для журнала)."""
    now = now or datetime.now().astimezone()
    cap = int(os.environ.get("SALES_BUDGET_QTICKETS") or RAMP[-1])
    st = load_json(RAMP_FILE, {})
    step = min(int(st.get("step", 0)), len(RAMP) - 1)
    since = st.get("since") or now.isoformat(timespec="seconds")
    hold = st.get("hold") or since
    note = ""
    denied = [e for e in blocks.history("qtickets/", since) if e.get("kind") == "trip"]
    if denied:
        step, since, note = max(0, step - 1), now.isoformat(timespec="seconds"), "отказ сайта — ступень ниже"
        hold = (now + RAMP_BACK).isoformat(timespec="seconds")
    elif (now - datetime.fromisoformat(since) >= RAMP_HOLD and now >= datetime.fromisoformat(hold)
          and blocks.state("qtickets/sales") == "ok" and RAMP[step] < cap and step < len(RAMP) - 1):
        step, since, note = step + 1, now.isoformat(timespec="seconds"), "сутки без отказов — ступень выше"
    if note or "since" not in st:   # в файле может быть только «pow» (сложность 428) — ступень всё равно записать
        save_json(RAMP_FILE, {**st, "step": step, "since": since, "hold": hold, "budget": min(cap, RAMP[step])})
        if note:
            blocks.log_event("qtickets/sales", "warn" if "ниже" in note else "ramp", "%s: %d страниц в сутки" % (note, min(cap, RAMP[step])))
    return min(cap, RAMP[step]), note


def next_check(local_date: date, now: datetime, same: int, sold_out: bool) -> datetime:
    """Следующий снимок: до 7 дней — через 12 ч, до 30 — через сутки; 2 снимка подряд без изменений — вдвое реже;
    «всё продано» — через 3 дня (если сеанс раньше — итог по этому снимку)."""
    days = (local_date - now.date()).days
    iv = next((v for limit, v in TIERS if days <= limit), timedelta(days=7))
    if sold_out:
        iv = max(iv, SOLD_OUT_EVERY)
    elif same >= 2:
        iv *= 2
    return now + iv
