"""
Qtickets для сбора продаж (TICKET_PLATFORMS.md, 9.3 и 9.5): страница покупки `qtickets.ru/event/<номер>` открывается
браузером, как у покупателя, и из того, что загрузило окно зала, берутся:
    - схема зала — `window.schemeConfig.screens.*.seats`: у каждого места зона, ряд, место, **цена** и «недоступно»;
    - занятые места — ответ окна `/widget/seats` (`ordered_seats`; проверку 428 проходит код самой страницы);
    - танцпол и входные — остаток по зоне (`appends.zones[зона].free_quantity`): мест у них нет, вместимости тоже.
Цены известны у всех мест, поэтому вал точный (как у vladimirkoncert), а продажи — по местам.

Нагрузка: одна страница — ~10 запросов к Qtickets; лимит и паузы — в страницах (`Browser`), по одной странице подряд,
пауза PAUSE с разбросом; картинки, шрифты и чужие счётчики не грузятся. Отказ (403, 429, капча) — канал qtickets/sales
закрывается (competitors/blocks.py), как у Кассира и Яндекса.

Браузер — Playwright (Chromium) с постоянным профилем в data/browser/qtickets: кэш схем и файлов окна.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, deque
from datetime import date

from competitors import blocks
from competitors.storage import BASE_DIR
from sales.net import Stopped

PROFILE = BASE_DIR / "data" / "browser" / "qtickets"
PAUSE = 15.0          # секунд между страницами (с разбросом 0,85–1,25)
PAUSE_MAX = 240.0
PAGE_TIMEOUT = 45     # секунд на загрузку страницы и окна зала
WINDOW, BAD_SHARE, STOP_AFTER = 20, 0.3, 8   # окно ответов; доля сбоев для замедления; подряд сбоев — стоп на прогон
# Что не нужно для данных: картинки афиши, шрифты, счётчики и чаты (схема зала — svg Qtickets — нужна окну)
BLOCK = re.compile(r"\.(png|jpe?g|webp|gif|ico|woff2?|ttf|otf)(\?|$)|/thumbs/|mc\.yandex|yandex\.ru/(metrika|watch)|vk\.com|"
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


class Browser:
    """Как sales.net.Net, но единица — страница: лимит `cap` страниц за прогон, паузы, сторож отказов, предохранитель."""

    def __init__(self, deadline: float, cap: int | None = None):
        self.site, self.deadline, self.cap = "qtickets", deadline, cap
        self.channel = "qtickets/sales"
        self.probe = blocks.state(self.channel) == "probe"
        self.base = self.pause = PAUSE
        self.recent: deque = deque(maxlen=WINDOW)
        self.denied: deque = deque(maxlen=WINDOW)
        self.in_row = 0
        self.sent = 0
        self.stats: Counter = Counter()
        self.stopped = False
        self.why = ""
        self._last = 0.0
        self._pw = self._ctx = self._page = None

    # ------------------------------------------------------------ браузер
    def start(self) -> None:
        from playwright.sync_api import sync_playwright   # здесь: без Playwright остальные кассы работают
        PROFILE.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(str(PROFILE), headless=True, viewport={"width": 1280, "height": 800},
                                                                locale="ru-RU", timezone_id="Europe/Moscow")
        self._ctx.route("**/*", lambda r: r.abort() if BLOCK.search(r.request.url) else r.continue_())
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

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
    def snapshot(self, event_id: str) -> dict | None:
        """{seats, zones, show, date, ordered, appends, all_sold, raw} — окно зала загрузилось; {"gone": True} — мероприятия
        нет (404); None — не загрузилось (сбой, повтор позже). Stopped — лимит, отказ сайта или предохранитель."""
        if self.stopped:
            raise Stopped(self.site)
        if self.cap is not None and self.sent >= self.cap:
            self._stop("лимит", "лимит страниц")
            raise Stopped(self.site)
        wait = self._last + self.pause * random.uniform(0.85, 1.25) - time.time()
        if wait > 0:
            time.sleep(wait)
        page, got, bad = self._page, {}, []

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

        page.on("response", on_resp)
        status, out, err = None, None, None
        try:
            resp = page.goto("https://qtickets.ru/event/%s" % event_id, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT * 1000)
            status = resp.status if resp else None
            if status == 404:
                out = {"gone": True}
            elif status and status < 400:
                end = time.time() + PAGE_TIMEOUT
                scheme = None
                while time.time() < end and not bad:
                    frame = next((f for f in page.frames if re.search(r"\.qtickets\.ru/event/", f.url)), None)
                    if frame and "seats" in got:
                        try:
                            scheme = frame.evaluate(SCHEME_JS)
                        except Exception:
                            scheme = None
                        if scheme and scheme["seats"] is not None:
                            break
                    page.wait_for_timeout(400)
                if scheme and "seats" in got:
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
        self._breaker(status, out)
        return out

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
            rec = blocks.trip(self.channel, status, "%s: отказ сайта (%s)" % (self.channel, status))
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
            self.pause = min(PAUSE_MAX, self.pause * 2)
            self.recent.clear()
            self.stats[("предохранитель", "медленнее")] += 1
        elif not bad and self.pause > self.base:
            self.pause = max(self.base, self.pause * 0.9)


# ---------------------------------------------------------------- разбор снимка

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
