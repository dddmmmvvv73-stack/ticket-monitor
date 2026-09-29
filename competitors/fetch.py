"""
Загрузка HTML-страниц обычными HTTP-запросами (без браузера).

Оба сайта конкурентов отдают готовый HTML с сервера, поэтому Playwright
здесь не нужен — urllib из стандартной библиотеки в разы быстрее и не
требует установки дополнительных пакетов.
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Пауза между запросами к одному сайту — чтобы не создавать заметной нагрузки
POLITE_DELAY_SECONDS = 0.7
RETRY_DELAYS_SECONDS = [3, 10]

_last_request_at = 0.0


def fetch_html(url: str, timeout: int = 30) -> str:
    """Возвращает HTML страницы. Делает до трёх попыток, между запросами — пауза."""
    global _last_request_at

    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        wait = POLITE_DELAY_SECONDS - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)

        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            _last_request_at = time.time()
            return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _last_request_at = time.time()
            last_error = e
            if attempt < len(RETRY_DELAYS_SECONDS):
                time.sleep(RETRY_DELAYS_SECONDS[attempt])

    raise RuntimeError(f"не удалось загрузить {url}: {last_error}")


def clean_text(fragment: str | None) -> str:
    """HTML-фрагмент -> плоский текст без тегов и лишних пробелов."""
    if not fragment:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()
