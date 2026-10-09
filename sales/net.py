"""
HTTP для сбора продаж: у каждого оператора свой темп и «предохранитель».

Кассир после нескольких сотен запросов подряд часами отвечает адресу ошибкой 500 (пробный сбор 04.10,
TICKET_PLATFORMS.md, 8.6). Поэтому: ровный темп; если среди последних ответов много 500 — пауза растёт
(до PAUSE_MAX), подряд много ошибок — оператор на этот прогон останавливается.

Отказ сайта (403, капча — TICKET_PLATFORMS.md, 8.8): DENY_IN_WINDOW отказов среди последних ответов — канал
закрывается на сутки и дольше (competitors/blocks.py); после срока — пробный прогон, отказ на первом же запросе.
Лимит: не больше `cap` запросов за прогон (sales/run.py делит суточный лимит оператора на оставшиеся часы).
"""

from __future__ import annotations

import gzip
import http.cookiejar
import random
import time
import urllib.error
import urllib.request
from collections import Counter, deque

from competitors import blocks

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
PAUSE = {"kassir": 6.0, "yandex": 3.0}       # секунд между запросами (06.10 при 4 и 1 с оба сайта закрыли доступ серверу)
PAUSE_MAX = 120.0
# Какой ответ доказывает, что блокировка снялась: у Кассира 06.10 закрылись только места и остатки, страницы — нет
LIFT_KINDS = {"kassir": ("kit", "scheme"), "yandex": None}
WINDOW, BAD_SHARE, STOP_AFTER = 20, 0.3, 25   # окно ответов, доля 500 для замедления, подряд ошибок для остановки


class Stopped(Exception):
    """Оператор остановлен на этот прогон (предохранитель, отказ сайта или лимит запросов)."""


class Net:
    def __init__(self, site: str, deadline: float, cap: int | None = None, channel: str = "sales"):
        self.site, self.deadline, self.cap = site, deadline, cap
        self.channel = "%s/%s" % (site, channel)
        self.probe = blocks.state(self.channel) == "probe"   # срок блокировки вышел: первый же отказ — снова закрыть
        self.base = self.pause = PAUSE[site]
        self.recent: deque = deque(maxlen=WINDOW)
        self.denied: deque = deque(maxlen=WINDOW)
        self.in_row = 0
        self.sent = 0
        self.stats: Counter = Counter()
        self.stopped = False
        self.why = ""   # почему остановлен: предохранитель / отказ сайта / лимит
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._last = 0.0

    def time_left(self) -> float:
        return self.deadline - time.time()

    def req(self, url: str, data: bytes | None = None, headers: dict | None = None, kind: str = "") -> tuple[int | None, bytes]:
        if self.stopped:
            raise Stopped(self.site)
        if self.cap is not None and self.sent >= self.cap:
            self._stop("лимит", "лимит запросов")
            raise Stopped(self.site)
        wait = self._last + self.pause * random.uniform(0.85, 1.25) - time.time()
        if wait > 0:
            time.sleep(wait)
        h = {"User-Agent": UA}
        h.update(headers or {})
        r = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        status, body, final, captcha = None, b"", url, False
        try:
            with self.op.open(r, timeout=40) as resp:
                status, body, final = resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read() or b""
            captcha = bool(e.headers and e.headers.get("x-yandex-captcha"))
        except Exception:
            status = None
        self._last = time.time()
        self.sent += 1
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        self.stats[(kind, status)] += 1
        if self._deny(status, final, body, captcha, kind):
            raise Stopped(self.site)
        self._breaker(status)
        return status, body

    def _stop(self, why: str, stat: str) -> None:
        self.stopped, self.why = True, why
        self.stats[("предохранитель", stat)] += 1

    def _deny(self, status, url: str, body: bytes, captcha: bool = False, kind: str = "") -> bool:
        """Сайт отказывает адресу — закрыть канал (competitors/blocks.py). True — оператор остановлен."""
        bad = captcha or blocks.is_denied(status, url, body)
        self.denied.append(bad)
        if not bad:
            lift = LIFT_KINDS.get(self.site)
            if self.probe and status is not None and status < 400 and (lift is None or kind in lift):
                self.probe = False
                if blocks.clear(self.channel):
                    self.stats[("блокировка", "снялась")] += 1
            return False
        if self.probe or sum(self.denied) >= blocks.DENY_IN_WINDOW:
            rec = blocks.trip(self.channel, status, "%s: отказ сайта (%s)" % (self.channel, status))
            self._stop("отказ", "отказ сайта — закрыт до " + rec["until"][:16])
            return True
        return False

    def _breaker(self, status: int | None) -> None:
        bad = status is None or status >= 500 or status == 429
        self.recent.append(bad)
        self.in_row = self.in_row + 1 if bad else 0
        if self.in_row >= STOP_AFTER:
            self._stop("предохранитель", "стоп")
            return
        share = sum(self.recent) / len(self.recent)
        if len(self.recent) >= 10 and share >= BAD_SHARE:
            self.pause = min(PAUSE_MAX, self.pause * 2)
            self.recent.clear()
            self.stats[("предохранитель", "медленнее")] += 1
        elif not bad and self.pause > self.base:
            self.pause = max(self.base, self.pause * 0.9)
