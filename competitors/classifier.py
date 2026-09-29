"""
Классификация мероприятий по справочнику «Сфера / Формат / Жанр».

Три слоя, в порядке приоритета:
  1. manual — ручная правка из интерфейса (хранится по названию, поэтому
              применяется ко всем датам одного и того же спектакля)
  2. rules  — ключевые слова в названии («Балет…», «Спектакль…», «Стендап…»)
     site   — тип, который проставил сам билетный сайт (Спектакль / Концерт / …)
  3. ai     — нейросеть заполняет только то, что правила не смогли определить
              (чаще всего жанр: «Александр Малинин» → Музыка / Концерт / Эстрада).
              Провайдер выбирается в настройках: GigaChat (бесплатно) или Claude.

ИИ-слой необязательный: без пакета или без ключа поля просто остаются
пустыми, и их можно заполнить вручную в интерфейсе. Любой ответ ИИ
проверяется по справочнику — значения не из списков отбрасываются.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

SPHERES = [
    "Музыка", "Театр", "Танец", "Комедия и юмор", "Фокусы и иллюзия",
    "Разговорный жанр", "Литература / поэзия", "Перформанс / современное искусство",
    "Зрелищные / смешанные", "Детские", "Спортивно-зрелищные", "Шоу",
]
FORMATS = [
    "Концерт", "Фестиваль", "DJ-сет", "Музыкальное шоу", "Спектакль", "Мюзикл",
    "Опера", "Музыкальный спектакль", "Пластический спектакль", "Иммерсивный спектакль",
    "Балет", "Танцевальное представление", "Танцевальное шоу", "Стендап",
    "Юмористическое шоу", "Импровизация", "Скетч-шоу", "Иллюзионное шоу", "Фокусы",
    "Лекция", "Публичная беседа", "Интервью", "Творческая встреча", "Литературный вечер",
    "Шоу",
]
GENRES = [
    "Драма", "Комедия", "Трагедия", "Трагикомедия", "Мелодрама", "Хоррор", "Фарс",
    "Сатира", "Абсурд", "Приключение", "Исторический", "Документальный", "Поп", "Рок",
    "Рэп / хип-хоп", "Электронная музыка", "Джаз", "Блюз", "Шансон", "Классическая музыка",
    "Неоклассика", "R&B", "Соул", "Фанк", "Панк", "Метал", "Инди", "Фолк / этника",
    "Альтернатива", "Классическая хореография", "Современная хореография",
    "Народная хореография", "Стендап", "Импровизационная комедия", "Скетч",
    "Сатирическая комедия", "Эстрада", "Шоу", "Научно популярное", "Роман",
]
FIELDS = ("sphere", "format", "genre")
ALLOWED = {"sphere": SPHERES, "format": FORMATS, "genre": GENRES}

# Граница слова для кириллицы (\b в Python для кириллицы работает,
# но явная запись надёжнее и не цепляет «рока» в слове «рок»)
_W = r"(?<![а-яёa-z])"
_E = r"(?![а-яёa-z])"

# Правила по названию: первое совпадение для каждого поля побеждает,
# поэтому более специфичные шаблоны стоят выше общих.
TITLE_RULES: list[tuple[str, dict[str, str]]] = [
    (r"для детей|детск|сказк", {"sphere": "Детские"}),
    (r"музыкальн\w* спектакл", {"sphere": "Театр", "format": "Музыкальный спектакль"}),
    (r"музыкальн\w* (представлени|шоу)", {"format": "Музыкальное шоу"}),
    (r"пластическ\w* спектакл", {"sphere": "Театр", "format": "Пластический спектакль"}),
    (r"иммерсивн", {"sphere": "Театр", "format": "Иммерсивный спектакль"}),
    (r"мюзикл", {"sphere": "Театр", "format": "Мюзикл"}),
    (_W + r"опер[аеыу]?" + _E, {"sphere": "Музыка", "format": "Опера", "genre": "Классическая музыка"}),
    (r"балет", {"sphere": "Танец", "format": "Балет", "genre": "Классическая хореография"}),
    (r"спектакл", {"sphere": "Театр", "format": "Спектакль"}),
    (r"стендап|стенд-ап|stand[\s-]?up", {"sphere": "Комедия и юмор", "format": "Стендап", "genre": "Стендап"}),
    (r"импровизац", {"sphere": "Комедия и юмор", "format": "Импровизация", "genre": "Импровизационная комедия"}),
    (r"скетч", {"sphere": "Комедия и юмор", "format": "Скетч-шоу", "genre": "Скетч"}),
    (r"иллюзи", {"sphere": "Фокусы и иллюзия", "format": "Иллюзионное шоу"}),
    (r"фокус", {"sphere": "Фокусы и иллюзия", "format": "Фокусы"}),
    (_W + r"(dj|диджей)" + _E, {"sphere": "Музыка", "format": "DJ-сет", "genre": "Электронная музыка"}),
    (r"фестивал", {"format": "Фестиваль"}),
    (r"творческ\w* (вечер|встреч)", {"sphere": "Разговорный жанр", "format": "Творческая встреча"}),
    (r"литературн|поэтическ|поэзи", {"sphere": "Литература / поэзия", "format": "Литературный вечер"}),
    (r"лекци", {"sphere": "Разговорный жанр", "format": "Лекция", "genre": "Научно популярное"}),
    (r"интервью", {"sphere": "Разговорный жанр", "format": "Интервью"}),
    (r"нео ?класси|neo ?class", {"sphere": "Музыка", "format": "Концерт", "genre": "Неоклассика"}),
    (r"оркестр|симфони|камерн\w* музык", {"sphere": "Музыка", "format": "Концерт", "genre": "Классическая музыка"}),
    (_W + r"хор[аоу]?" + _E, {"sphere": "Музыка", "format": "Концерт"}),
    (r"концерт", {"sphere": "Музыка", "format": "Концерт"}),
    (r"народн\w* (танц|хореограф|ансамбл\w* танц)", {"sphere": "Танец", "genre": "Народная хореография"}),
    (r"современн\w* (танц|хореограф)", {"sphere": "Танец", "genre": "Современная хореография"}),
    (r"танц|хореограф", {"sphere": "Танец", "format": "Танцевальное представление"}),
    (r"юмор", {"sphere": "Комедия и юмор", "format": "Юмористическое шоу"}),
    (_W + r"шоу" + _E, {"sphere": "Шоу", "format": "Шоу"}),
    # Жанровые слова
    (r"трагикомеди", {"genre": "Трагикомедия"}),
    (r"комеди", {"genre": "Комедия"}),
    (r"трагеди", {"genre": "Трагедия"}),
    (r"мелодрам", {"genre": "Мелодрама"}),
    (_W + r"фарс", {"genre": "Фарс"}),
    (r"джаз|jazz", {"genre": "Джаз"}),
    (r"блюз|blues", {"genre": "Блюз"}),
    (_W + r"(рок|rock)" + _E, {"genre": "Рок"}),
    (r"рэп|хип-хоп|hip-hop", {"genre": "Рэп / хип-хоп"}),
    (r"шансон", {"genre": "Шансон"}),
    (r"фолк|этно", {"genre": "Фолк / этника"}),
    (r"эстрад", {"genre": "Эстрада"}),
]

# Тип от билетного сайта (vladimirkoncert.ru) -> поля справочника
SITE_TYPE_RULES: dict[str, dict[str, str]] = {
    "Для детей": {"sphere": "Детские"},
    "Спектакль": {"sphere": "Театр", "format": "Спектакль"},
    "Мюзикл": {"sphere": "Театр", "format": "Мюзикл"},
    "Балет": {"sphere": "Танец", "format": "Балет", "genre": "Классическая хореография"},
    "Концерт": {"sphere": "Музыка", "format": "Концерт"},
    "Юмор": {"sphere": "Комедия и юмор", "format": "Юмористическое шоу"},
    "Стендапы": {"sphere": "Комедия и юмор", "format": "Стендап", "genre": "Стендап"},
}

AI_MODEL = "claude-opus-5-5"
AI_BATCH_SIZE = 30
PROVIDER_NAMES = {"gigachat": "GigaChat", "claude": "Claude"}

Log = Callable[[str], None]


def title_key(title: str) -> str:
    """Ключ для ручных правок и кэша ИИ: одно и то же шоу в разные даты = один ключ."""
    key = title.lower().replace("ё", "е")
    key = re.sub(r"[«»\"'“”„]", "", key)
    return re.sub(r"\s+", " ", key).strip()


def _apply(target: dict, sources: dict, values: dict[str, str], source: str) -> None:
    for field, value in values.items():
        if not target.get(field):
            target[field] = value
            sources[field] = source


def classify_by_rules(title: str, site_types: list[str]) -> tuple[dict, dict]:
    result: dict[str, str] = {}
    sources: dict[str, str] = {}
    lowered = title.lower().replace("ё", "е")
    for pattern, values in TITLE_RULES:
        if re.search(pattern, lowered):
            _apply(result, sources, values, "rules")
    for site_type in site_types:
        if site_type in SITE_TYPE_RULES:
            _apply(result, sources, SITE_TYPE_RULES[site_type], "site")
    return result, sources


# ---------------------------------------------------------------- ИИ-слой

SYSTEM_PROMPT = f"""Ты классифицируешь культурные мероприятия (афиша площадок города) по фиксированному справочнику.

Для каждого мероприятия выбери ровно одно значение в каждом из трёх полей — строго из списков ниже.
Если ни одно значение честно не подходит (например, жанр для творческой встречи), верни пустую строку.

СФЕРА: {", ".join(SPHERES)}
ФОРМАТ: {", ".join(FORMATS)}
ЖАНР: {", ".join(GENRES)}

Подсказки:
- Сольный концерт известного исполнителя эстрады, романсов, авторской песни — Музыка / Концерт / Эстрада (или точнее: Шансон, Рок, Поп…).
- Антрепризный спектакль со звёздами — Театр / Спектакль, жанр по описанию (чаще Комедия или Мелодрама).
- Детские сказки и мероприятия для детей — сфера «Детские».
- Если в данных уже заполнено поле (known), не противоречь ему."""


def _ai_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "sphere": {"type": "string", "enum": SPHERES + [""]},
                        "format": {"type": "string", "enum": FORMATS + [""]},
                        "genre": {"type": "string", "enum": GENRES + [""]},
                    },
                    "required": ["id", "sphere", "format", "genre"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def _make_client(api_key: str | None):
    import anthropic  # импорт здесь: пакет необязательный

    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def _normalize(field: str, value) -> str:
    """Значение ИИ -> точное значение справочника (без учёта регистра/ё), иначе ''."""
    if not isinstance(value, str):
        return ""
    wanted = value.strip().lower().replace("ё", "е")
    for allowed in ALLOWED[field]:
        if allowed.lower().replace("ё", "е") == wanted:
            return allowed
    return ""


def classify_with_ai(items: list[dict], ai: dict, log: Log) -> dict[str, dict]:
    """
    items: [{id, title, venue, site_types, description, known}]
    ai: {provider: gigachat|claude, …ключи и модель}
    Возвращает {id: {sphere, format, genre}} — только значения из справочника.
    Ошибки ИИ не роняют сбор данных: непрошедшие пачки просто остаются пустыми.
    """
    # В запрос уходят короткие номера вместо названий: модель может «исправить»
    # кавычки в названии, и тогда ответ не сопоставился бы с мероприятием
    key_by_number = {str(n): item["id"] for n, item in enumerate(items, 1)}
    items = [{**item, "id": n} for n, item in zip(key_by_number, items)]
    try:
        if ai["provider"] == "gigachat":
            from competitors import gigachat_ai
            try:
                raw = gigachat_ai.classify(
                    items, ai.get("gigachat_auth_key", ""), ai.get("gigachat_scope", ""),
                    ai.get("gigachat_model", ""), SYSTEM_PROMPT, log)
            except gigachat_ai.GigaChatSetupError as e:
                log(f"ИИ-классификация (GigaChat) пропущена: {e}")
                return {}
        elif ai["provider"] == "claude":
            raw = _classify_claude(items, ai.get("anthropic_api_key") or None, log)
        else:
            return {}
    except Exception as e:  # сеть, неожиданный ответ SDK и т.п.
        log(f"ИИ-классификация: непредвиденная ошибка — {e}")
        return {}

    results: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or str(item.get("id")) not in key_by_number:
            continue
        values = {f: _normalize(f, item.get(f)) for f in FIELDS}
        results[key_by_number[str(item["id"])]] = {f: v for f, v in values.items() if v}
    return results


def _classify_claude(items: list[dict], api_key: str | None, log: Log) -> list[dict]:
    try:
        import anthropic
        client = _make_client(api_key)
    except ImportError:
        log("ИИ-классификация пропущена: не установлен пакет anthropic "
            "(python3 -m pip install anthropic).")
        return []

    results: list[dict] = []
    for start in range(0, len(items), AI_BATCH_SIZE):
        batch = items[start:start + AI_BATCH_SIZE]
        try:
            response = client.beta.messages.create(
                model=AI_MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": _ai_schema()},
                },
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": "Классифицируй мероприятия:\n"
                               + json.dumps(batch, ensure_ascii=False, indent=1),
                }],
            )
        except anthropic.AuthenticationError:
            log("ИИ-классификация: ключ Claude API не принят — проверь его в настройках.")
            return results
        except anthropic.RateLimitError:
            log("ИИ-классификация: превышен лимит запросов Claude API, остаток — в следующий сбор.")
            return results
        except anthropic.APIStatusError as e:
            log(f"ИИ-классификация: ошибка Claude API ({e.status_code}): {e.message}")
            continue
        except anthropic.APIConnectionError:
            log("ИИ-классификация: нет связи с Claude API.")
            return results

        if response.stop_reason == "refusal":
            log("ИИ-классификация: модель отказалась обрабатывать пачку — пропускаю.")
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results.extend(json.loads(text).get("items", []))
        except json.JSONDecodeError:
            log("ИИ-классификация: ответ не разобрался как JSON — пропускаю пачку.")

    return results


# ---------------------------------------------------------------- общий вход

def classify_rows(
    rows: list[dict],
    overrides: dict[str, dict],
    ai_cache_path: Path,
    ai: dict | None,
    log: Log,
) -> None:
    """
    Заполняет у каждой строки sphere/format/genre и class_source (на месте).
    ai — настройки провайдера ({provider, ключи, модель}) или None, чтобы не
    обращаться к ИИ (тогда используются только уже закэшированные ответы).
    """
    ai_cache: dict[str, dict] = {}
    if ai_cache_path.exists():
        ai_cache = json.loads(ai_cache_path.read_text(encoding="utf-8"))

    need_ai: dict[str, dict] = {}
    for row in rows:
        key = title_key(row["title"])
        result: dict[str, str] = {}
        sources: dict[str, str] = {}

        _apply(result, sources, {f: v for f, v in overrides.get(key, {}).items() if v}, "manual")
        full_title = " ".join(filter(None, [row["title"], row.get("alt_title")]))
        rule_values, rule_sources = classify_by_rules(full_title, row.get("site_types", []))
        for field, value in rule_values.items():
            _apply(result, sources, {field: value}, rule_sources[field])
        _apply(result, sources, {f: v for f, v in ai_cache.get(key, {}).items() if v}, "ai")

        row["_key"] = key
        row["_partial"] = (result, sources)
        missing = [f for f in FIELDS if not result.get(f)]
        if missing and key not in ai_cache and key not in need_ai:
            need_ai[key] = {
                "id": key,
                "title": full_title,
                "venue": row.get("venue"),
                "site_types": row.get("site_types", []),
                "description": (row.get("description") or "")[:400],
                "known": result,
            }

    if need_ai and ai and ai.get("provider") in PROVIDER_NAMES:
        log(f"ИИ-классификация: отправляю {len(need_ai)} названий в {PROVIDER_NAMES[ai['provider']]}…")
        answers = classify_with_ai(list(need_ai.values()), ai, log)
        if answers:
            ai_cache.update(answers)
            ai_cache_path.parent.mkdir(parents=True, exist_ok=True)
            ai_cache_path.write_text(json.dumps(ai_cache, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"ИИ-классификация: получено {len(answers)} ответов.")
    elif need_ai and ai is not None:
        log(f"ИИ-классификация выключена — {len(need_ai)} названий без полной классификации "
            f"(можно заполнить вручную).")

    for row in rows:
        result, sources = row.pop("_partial")
        key = row.pop("_key")
        _apply(result, sources, {f: v for f, v in ai_cache.get(key, {}).items() if v}, "ai")
        for field in FIELDS:
            row[field] = result.get(field, "")
        row["class_source"] = sources
