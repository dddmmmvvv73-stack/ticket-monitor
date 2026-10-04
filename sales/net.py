"""
HTTP для сбора продаж: у каждого оператора свой темп и «предохранитель».

Кассир после нескольких сотен запросов подряд часами отвечает адресу ошибкой 500 (пробный сбор 04.10,
TICKET_PLATFORMS.md, 8.6). Поэтому: ровный темп; если среди последних ответов много 500 — пауза растёт
(до PAUSE_MAX), подряд много ошибок — оператор на этот прогон останавливается.
"""

from __future__ import annotations

import gzip
import http.cookiejar
import random
import time
import urllib.error
import urllib.request
from collections import Counter, deque

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
PAUSE = {"kassir": 6.0, "yandex": 1.3}       # секунд между запросами
PAUSE_MAX = 120.0
WINDOW, BAD_SHARE, STOP_AFTER = 20, 0.3, 25   # окно ответов, доля 500 для замедления, подряд ошибок для остановки


class Stopped(Exception):
    """Оператор остановлен на этот прогон (предохранитель)."""


class Net:
    def __init__(self, site: str, deadline: float):
        self.site, self.deadline = site, deadline
        self.base = self.pause = PAUSE[site]
        self.recent: deque = deque(maxlen=WINDOW)
        self.in_row = 0
        self.stats: Counter = Counter()
        self.stopped = False
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._last = 0.0

    def time_left(self) -> float:
        return self.deadline - time.time()

    def req(self, url: str, data: bytes | None = None, headers: dict | None = None, kind: str = "") -> tuple[int | None, bytes]:
        if self.stopped:
            raise Stopped(self.site)
        wait = self._last + self.pause * random.uniform(0.85, 1.25) - time.time()
        if wait > 0:
            time.sleep(wait)
        h = {"User-Agent": UA}
        h.update(headers or {})
        r = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        status, body = None, b""
        try:
            with self.op.open(r, timeout=40) as resp:
                status, body = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read() or b""
        except Exception:
            status = None
        self._last = time.time()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        self.stats[(kind, status)] += 1
        self._breaker(status)
        return status, body

    def _breaker(self, status: int | None) -> None:
        bad = status is None or status >= 500 or status == 429
        self.recent.append(bad)
        self.in_row = self.in_row + 1 if bad else 0
        if self.in_row >= STOP_AFTER:
            self.stopped = True
            self.stats[("предохранитель", "стоп")] += 1
            return
        share = sum(self.recent) / len(self.recent)
        if len(self.recent) >= 10 and share >= BAD_SHARE:
            self.pause = min(PAUSE_MAX, self.pause * 2)
            self.recent.clear()
            self.stats[("предохранитель", "медленнее")] += 1
        elif not bad and self.pause > self.base:
            self.pause = max(self.base, self.pause * 0.9)
