"""
Скрапер одного события с Яндекс Афиши.

Открывает страницу события, ждёт сетевой запрос .../hallplan/async
(его делает виджет схемы зала) и возвращает сырой JSON-ответ целиком,
без какой-либо обработки — обработкой занимается processor.py.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

HALLPLAN_URL_MARKER = "hallplan/async"

# hallplan/async — это АСИНХРОННАЯ операция: сайт сам опрашивает этот же
# адрес по нескольку раз подряд, пока сервер считает ответ. Промежуточные
# ответы приходят с operationStatus="running" и без самих данных о местах —
# нам нужен только финальный, где internal result.hallplan уже заполнен.

BLOCK_MARKERS = [
    "captcha", "капча", "подтвердите, что вы не робот",
    "unusual traffic", "необычную активность", "access denied", "доступ ограничен",
]

DEBUG_DIR = Path(__file__).parent / "data" / "debug"


BUTTON_LABELS_TO_TRY = ["Далее", "Продолжить", "Выбрать место", "Выбрать", "Показать зал"]


def _is_hallplan_complete(data) -> bool:
    """Финальный ответ — тот, где result.hallplan уже есть. Промежуточные
    ответы (operationStatus="running") этого поля не содержат."""
    if not isinstance(data, dict):
        return False
    result = data.get("result")
    return isinstance(result, dict) and isinstance(result.get("hallplan"), dict)


def _looks_blocked(page_text: str) -> bool:
    lowered = page_text.lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _try_click_continue_button(page) -> bool:
    """
    Некоторые площадки грузят схему зала только после клика на кнопку
    внутри виджета (например "Повод остаться" — там сначала показывается
    просто кнопка "Далее", и без клика запрос вообще не отправляется).

    Виджет живёт в отдельном iframe с другого домена (widget.afisha.yandex.ru),
    поэтому ищем кнопку именно внутри него, а не на основной странице —
    там уже есть своя (нерабочая для наших целей) кнопка "Купить билеты".

    Возвращает True, если что-то нашли и нажали.
    """
    try:
        frame = page.frame_locator('iframe[src*="widget.afisha.yandex.ru"]')
        for label in BUTTON_LABELS_TO_TRY:
            button = frame.get_by_text(label, exact=False)
            if button.count() > 0:
                button.first.click(timeout=3000)
                return True
    except Exception:
        pass
    return False


def _attempt(event_url: str, timeout_ms: int) -> tuple[dict | None, str | None]:
    """
    Одна попытка получить данные.
    Возвращает (данные_или_None, причина_неудачи_или_None).
    """
    captured = {"data": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            if HALLPLAN_URL_MARKER in response.url and response.status == 200:
                try:
                    data = response.json()
                except Exception:
                    return
                # Не перезаписываем уже пойманный финальный ответ и
                # игнорируем промежуточные "ещё считаю" (operationStatus=running)
                if captured["data"] is None and _is_hallplan_complete(data):
                    captured["data"] = data

        page.on("response", handle_response)

        try:
            page.goto(event_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            browser.close()
            return None, f"страница не загрузилась вообще: {e}"

        # Скроллим, пока не увидим нужный запрос или не закончатся попытки —
        # выходим сразу, как только данные пришли, а не крутим вслепую до конца.
        for _ in range(6):
            if captured["data"] is not None:
                break
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(500)

        if captured["data"] is None:
            try:
                page.wait_for_response(
                    lambda r: captured["data"] is not None,
                    timeout=timeout_ms,
                )
            except Exception:
                pass

        # Запрос так и не пришёл — возможно, виджет ждёт клика (см. кейс
        # "Повод остаться": пустая область с кнопкой "Далее" вместо схемы).
        if captured["data"] is None:
            clicked = _try_click_continue_button(page)
            if clicked:
                try:
                    page.wait_for_response(
                        lambda r: captured["data"] is not None,
                        timeout=timeout_ms,
                    )
                except Exception:
                    pass

        page.wait_for_timeout(1000)

        if captured["data"] is None:
            # Не поймали нужный запрос — смотрим, не капча ли это,
            # и сохраняем скриншот + HTML виджета, чтобы увидеть глазами,
            # что случилось (в т.ч. задним числом, без повторного запуска).
            page_text = ""
            try:
                page_text = page.inner_text("body")
            except Exception:
                pass

            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            screenshot_path = DEBUG_DIR / "last_failed_hallplan.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                screenshot_path = None

            widget_html_path = DEBUG_DIR / "last_failed_widget.html"
            try:
                frame = page.frame_locator('iframe[src*="widget.afisha.yandex.ru"]')
                widget_html = frame.locator("body").inner_html(timeout=2000)
                widget_html_path.write_text(widget_html, encoding="utf-8")
            except Exception:
                widget_html_path = None

            browser.close()

            debug_note = f'Скриншот: {screenshot_path}'
            if widget_html_path:
                debug_note += f', HTML виджета: {widget_html_path}'

            if _looks_blocked(page_text):
                return None, f"похоже на антибот-проверку (капча/подозрительная активность). {debug_note}"
            return None, (
                "запрос hallplan/async не пришёл за отведённое время, даже после "
                f"попытки нажать кнопку продолжения внутри виджета. {debug_note}"
            )

        browser.close()
        return captured["data"], None


RETRY_DELAYS_SECONDS = [5, 15]  # пауза перед 2-й и 3-й попытками соответственно


def fetch_hallplan(event_url: str, timeout_ms: int = 20000) -> tuple[dict | None, str | None]:
    """
    Возвращает (данные, причина_неудачи). Если данные получены — причина None.
    Если не получены — данные None, а в причине человекочитаемое объяснение
    (в т.ч. путь к скриншоту, если удалось его сохранить).

    Делает до трёх попыток с растущей паузой между ними: если попытка не
    удалась (в том числе похоже на временную антибот-проверку или просто
    медленную холодную загрузку виджета) — ждём и пробуем ещё раз. Это
    частая причина сбоя при первом обращении к странице или при частых
    повторных запросах к одной и той же.
    """
    import time

    attempts = len(RETRY_DELAYS_SECONDS) + 1
    for attempt_num in range(1, attempts + 1):
        data, reason = _attempt(event_url, timeout_ms)
        if data is not None:
            if attempt_num > 1:
                print(f'Получилось с попытки {attempt_num}.')
            return data, None

        if attempt_num == attempts:
            print(f'Попытка {attempt_num}/{attempts} тоже не удалась: {reason}')
            return None, reason

        delay = RETRY_DELAYS_SECONDS[attempt_num - 1]
        print(f'Попытка {attempt_num}/{attempts} не удалась ({reason}). Пробую ещё раз через {delay} секунд...')
        time.sleep(delay)
