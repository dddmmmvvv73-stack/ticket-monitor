"""
Геометрия зала — отдельный запрос, не связанный с hallplan/async.

hallplan/async отдаёт только СВОБОДНЫЕ места. Чтобы знать полный список
номеров мест в каждом ряду (включая давно проданные, до начала слежения) —
нужен другой ответ сайта, который просто рисует схему зала (координаты,
без цен и статусов). Внешне он виден в Network как запрос вида
`mds?key=...`, а отличить его от прочих mds-запросов можно по тому, что
в его JSON есть верхнеуровневый ключ "stage" (сцена) — так его отличали
и вручную через DevTools в начале работы над проектом.

Геометрия зала не меняется день ото дня, поэтому её достаточно забрать
один раз на событие и закэшировать (см. geometry_path в main.py).
"""

from __future__ import annotations

import json


MDS_URL_MARKER = "mds?key="


def _looks_like_geometry(node) -> bool:
    """Признак геометрии: объект с полем levels, где хотя бы у одного уровня
    есть список seats с полями row/place. Не зависит от того, как именно
    площадка обернула этот объект — ищем сам признак, а не конкретный путь."""
    if not isinstance(node, dict):
        return False
    levels = node.get("levels")
    if not isinstance(levels, list) or not levels:
        return False
    for level in levels:
        if not isinstance(level, dict):
            continue
        seats = level.get("seats")
        if isinstance(seats, list) and seats:
            seat0 = seats[0]
            if isinstance(seat0, dict) and "row" in seat0 and "place" in seat0:
                return True
    return False


def _find_geometry_node(data, depth: int = 0, max_depth: int = 6):
    """Рекурсивно ищет объект-геометрию на любой глубине вложенности JSON —
    не важно, обёрнут ли он в result, result.hallplan или как-то ещё.

    Некоторые площадки (например mds-ответ виджета) отдают вложенный объект
    не как настоящий JSON-объект, а как строку с сериализованным JSON внутри
    (data["result"] == '{"stage":..., "levels":[...]}') — поэтому строки,
    похожие на JSON-объект, тоже пытаемся распарсить и обойти рекурсивно."""
    if depth > max_depth:
        return None
    if _looks_like_geometry(data):
        return data
    if isinstance(data, dict):
        for value in data.values():
            found = _find_geometry_node(value, depth + 1, max_depth)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_geometry_node(item, depth + 1, max_depth)
            if found is not None:
                return found
    elif isinstance(data, str) and data[:1] in "{[":
        try:
            parsed = json.loads(data)
        except (ValueError, TypeError):
            return None
        return _find_geometry_node(parsed, depth + 1, max_depth)
    return None


def _describe_shape(data, depth: int = 0, max_depth: int = 3) -> str:
    """Короткое текстовое описание структуры ответа — для диагностики,
    когда геометрию найти не удалось вообще."""
    indent = "  " * depth
    if depth > max_depth:
        return f"{indent}..."
    if isinstance(data, dict):
        lines = [f"{indent}{{{', '.join(data.keys())}}}"]
        for k, v in list(data.items())[:5]:
            if isinstance(v, (dict, list)):
                lines.append(_describe_shape(v, depth + 1, max_depth))
        return "\n".join(lines)
    if isinstance(data, list):
        return f"{indent}[список, {len(data)} элементов]" + (
            "\n" + _describe_shape(data[0], depth + 1, max_depth) if data else ""
        )
    return f"{indent}{type(data).__name__}"


GEOMETRY_RETRY_DELAYS_SECONDS = [5, 15]  # пауза перед 2-й и 3-й попытками соответственно


def fetch_venue_geometry(event_url: str, timeout_ms: int = 20000) -> dict | None:
    """
    Возвращает распознанную геометрию, либо None.

    Делает до трёх попыток с растущей паузой между ними — виджет схемы зала
    иногда не успевает отправить mds-запрос за один заход (та же нестабильность,
    что и у hallplan/async в scraper.py).
    """
    import time

    attempts = len(GEOMETRY_RETRY_DELAYS_SECONDS) + 1
    for attempt_num in range(1, attempts + 1):
        data = _attempt_geometry(event_url, timeout_ms)
        if data is not None:
            return data

        if attempt_num == attempts:
            return None

        delay = GEOMETRY_RETRY_DELAYS_SECONDS[attempt_num - 1]
        print(f'geometry.py: попытка {attempt_num}/{attempts} не удалась, пробую ещё раз через {delay} секунд...')
        time.sleep(delay)


def _attempt_geometry(event_url: str, timeout_ms: int) -> dict | None:
    """Одна попытка получить геометрию. Возвращает данные или None."""
    captured = {"data": None}
    seen_mds_requests = []  # для диагностики, если основной запрос не поймаем
    from playwright.sync_api import sync_playwright  # здесь: на сервере браузера нет, интерфейс без него работает

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            if MDS_URL_MARKER not in response.url:
                return
            try:
                data = response.json()
            except Exception:
                seen_mds_requests.append((response.url, None))
                return

            seen_mds_requests.append((response.url, data))

            if captured["data"] is None:
                found = _find_geometry_node(data)
                if found is not None:
                    captured["data"] = found

        page.on("response", handle_response)
        page.goto(event_url, wait_until="domcontentloaded", timeout=60000)

        for _ in range(6):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(500)

        # Активно ждём именно нужный запрос вместо тупой фиксированной паузы —
        # так же, как ждём hallplan/async в scraper.py.
        try:
            page.wait_for_response(
                lambda r: (
                    MDS_URL_MARKER in r.url and r.status == 200
                    and captured["data"] is not None
                ),
                timeout=timeout_ms,
            )
        except Exception:
            pass

        page.wait_for_timeout(500)
        browser.close()

    if captured["data"] is None:
        print("\n--- Диагностика: geometry.py не нашёл геометрию ни на одном уровне вложенности ---")
        if seen_mds_requests:
            for url, data in seen_mds_requests:
                print(f'{url}')
                if data is None:
                    print("  тело: не JSON или недоступно")
                else:
                    print(_describe_shape(data))
        else:
            print("Ни одного mds-запроса вообще не было замечено на странице.")
        print("--- конец диагностики ---\n")

    return captured["data"]


def parse_geometry(raw: dict) -> dict[str, dict[str, list[int]]]:
    """
    Возвращает {level_name: {row: [номера мест по возрастанию]}}.
    Уровни с admission=True (входные пропуска без places в привычном
    смысле) пропускаются — как и в processor.py для hallplan.
    """
    result: dict[str, dict[str, list[int]]] = {}

    for level in raw.get("levels", []):
        if level.get("admission"):
            continue
        level_name = level.get("name")
        rows: dict[str, list[int]] = {}

        for seat in level.get("seats", []):
            row = str(seat.get("row"))
            place_raw = seat.get("place")
            try:
                place = int(place_raw)
            except (TypeError, ValueError):
                continue
            rows.setdefault(row, []).append(place)

        for row in rows:
            rows[row] = sorted(rows[row])

        result[level_name] = rows

    return result


def sorted_row_labels(rows: dict[str, list[int]]) -> list[str]:
    """Ряды по возрастанию номера — используется для поиска соседних рядов сверху/снизу."""
    def key(r: str):
        try:
            return (0, int(r))
        except ValueError:
            return (1, r)
    return sorted(rows.keys(), key=key)
