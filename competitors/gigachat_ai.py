"""
Классификация через GigaChat (Сбер) — бесплатный тариф для физлиц,
работает из РФ без VPN и хорошо знает российских исполнителей.

Как получить ключ: developers.sber.ru → «GigaChat API» → создать проект
для физлица → «Ключ авторизации» (Authorization key, длинная строка base64).
Этот ключ вставляется в настройках вкладки «Конкуренты».

Сертификат. Все серверы GigaChat подписаны корневым сертификатом Минцифры
(«Russian Trusted Root CA»), которого нет в стандартном наборе Python.
Скачиваем его с официального адреса Госуслуг один раз и проверяем
SHA-256 отпечаток (совпадает с тем, что отдают сами серверы Сбера).
Этот сертификат используется ТОЛЬКО для соединений с GigaChat — в систему
и в другие запросы программы он не добавляется.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Callable

CERT_URL = "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer"
CERT_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"
CERT_PATH = Path(__file__).resolve().parent.parent / "config" / "certs" / "russian_trusted_root_ca.pem"

DEFAULT_MODEL = "GigaChat-2-Max"
FALLBACK_MODEL = "GigaChat-2"  # Lite — самый большой бесплатный лимит
DEFAULT_SCOPE = "GIGACHAT_API_PERS"  # физлица; для ИП/юрлиц — GIGACHAT_API_B2B / _CORP
BATCH_SIZE = 25

Log = Callable[[str], None]


class GigaChatSetupError(RuntimeError):
    """Понятная пользователю ошибка настройки (ключ, сертификат, пакет)."""


# ---------------------------------------------------------------- сертификат

def _der_fingerprint(pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def _to_pem(raw: bytes) -> str:
    text = raw.decode("ascii", errors="ignore")
    if "BEGIN CERTIFICATE" in text:
        match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)
        return match.group(0) + "\n"
    return ssl.DER_cert_to_PEM_cert(raw)  # файл пришёл в бинарном DER


def ensure_certificate(log: Log) -> str:
    """Путь к проверенному сертификату Минцифры; скачивает при первом вызове."""
    if CERT_PATH.exists():
        pem = CERT_PATH.read_text(encoding="ascii")
        if _der_fingerprint(pem) == CERT_SHA256:
            return str(CERT_PATH)
        CERT_PATH.unlink()  # файл подменён или повреждён — скачаем заново

    log("GigaChat: скачиваю корневой сертификат Минцифры с gu-st.ru (один раз)…")
    try:
        with urllib.request.urlopen(CERT_URL, timeout=30) as response:
            pem = _to_pem(response.read())
    except Exception as e:
        raise GigaChatSetupError(
            f"не удалось скачать сертификат Минцифры ({e}). Скачайте вручную {CERT_URL} "
            f"и положите как {CERT_PATH}")

    if _der_fingerprint(pem) != CERT_SHA256:
        raise GigaChatSetupError("скачанный сертификат не совпал с ожидаемым отпечатком — не использую его")

    CERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CERT_PATH.write_text(pem, encoding="ascii")
    return str(CERT_PATH)


# ---------------------------------------------------------------- клиент

def _client(auth_key: str, scope: str, model: str, log: Log):
    try:
        from gigachat import GigaChat  # импорт здесь: пакет необязательный
    except ImportError:
        raise GigaChatSetupError("не установлен пакет gigachat (python3 -m pip install -r requirements-ai.txt)")
    if not auth_key:
        raise GigaChatSetupError("не задан ключ авторизации GigaChat — вставьте его в настройках")
    options = dict(
        credentials=auth_key,
        scope=scope or DEFAULT_SCOPE,
        model=model,
        ca_bundle_file=ensure_certificate(log),
        timeout=120,
    )
    # Клиент в конструкторе создаёт asyncio.Lock, а на Python 3.9 это требует
    # event loop у текущего потока. У фоновых потоков (сбор, запросы Flask)
    # его нет — создаём временный только на время конструктора. Сами запросы
    # синхронные, этот loop дальше не используется.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return GigaChat(**options)
        finally:
            asyncio.set_event_loop(None)
            loop.close()
    return GigaChat(**options)


def list_models(auth_key: str, scope: str, log: Log) -> list[str]:
    """Проверка подключения: ключ + сертификат + доступные модели."""
    from gigachat.exceptions import AuthenticationError, ResponseError

    try:
        with _client(auth_key, scope, DEFAULT_MODEL, log) as giga:
            return sorted(m.id_ for m in giga.get_models().data)
    except AuthenticationError:
        raise GigaChatSetupError("ключ авторизации не принят — проверьте ключ и тип доступа (scope)")
    except ResponseError as e:
        raise GigaChatSetupError(f"GigaChat ответил ошибкой {e.status_code}")


# ---------------------------------------------------------------- классификация

# Почему не JSON: режим response_format (JSON-схема) у GigaChat в бете и на
# пачках из 20+ мероприятий вставляет мусорные слова прямо внутрь JSON —
# ответ целиком не разбирается. Построчный формат «номер | сфера | формат | жанр»
# устойчивее: каждая строка разбирается отдельно, одна битая строка не губит
# остальные, и токенов уходит примерно в 2 раза меньше.
LINE_INSTRUCTIONS = """Для каждого мероприятия ниже определи сферу, формат и жанр строго из справочника.
Ответ — только строки вида:
номер | сфера | формат | жанр
по одной строке на мероприятие, без пояснений и без заголовка.
Значения пиши точно как в справочнике. Не придумывай новых значений: если точного жанра нет,
выбери ближайший из списка (хоровая и духовная музыка — Классическая музыка).
Жанр указывай всегда, когда он хоть как-то угадывается (для концертов исполнителей — музыкальный жанр);
ставь «-», только если жанр в принципе неприменим (например, творческая встреча)."""

_LINE_RE = re.compile(r"^\W*(\d+)\W*\|(.*)$")


def _describe(item: dict) -> str:
    parts = [f'{item["id"]}. {item["title"]}']
    if item.get("site_types"):
        parts.append("тип на сайте: " + ", ".join(item["site_types"]))
    if item.get("known"):
        names = {"sphere": "сфера", "format": "формат", "genre": "жанр"}
        parts.append("уже известно: " + ", ".join(f"{names[k]} {v}" for k, v in item["known"].items()))
    if item.get("description"):
        parts.append(item["description"][:200])
    return " — ".join(parts)


def _parse_lines(text: str) -> list[dict]:
    answers = []
    for line in text.splitlines():
        match = _LINE_RE.match(line.strip())
        if not match:
            continue
        values = [v.strip().strip("«»\"'") for v in match.group(2).split("|")]
        if len(values) < 3:
            continue
        sphere, format_, genre = (("" if v in ("-", "—") else v) for v in values[:3])
        answers.append({"id": match.group(1), "sphere": sphere, "format": format_, "genre": genre})
    return answers


def _ask(giga, model: str, system_prompt: str, batch: list[dict]) -> list[dict]:
    from gigachat.models import Chat, Messages, MessagesRole

    user_text = LINE_INSTRUCTIONS + "\n\n" + "\n".join(_describe(item) for item in batch)
    chat = Chat(
        model=model,
        messages=[
            Messages(role=MessagesRole.SYSTEM, content=system_prompt),
            Messages(role=MessagesRole.USER, content=user_text),
        ],
        temperature=0.1,
        max_tokens=3000,
    )
    response = giga.chat(chat)
    return _parse_lines(response.choices[0].message.content)


def classify(
    items: list[dict],
    auth_key: str,
    scope: str,
    model: str,
    system_prompt: str,
    log: Log,
) -> list[dict]:
    """
    Возвращает сырые ответы [{id, sphere, format, genre}, …] —
    проверку значений по справочнику делает classifier.py.
    Ошибка одной пачки не останавливает остальные.
    """
    from gigachat.exceptions import AuthenticationError, RateLimitError, ResponseError

    model = model or DEFAULT_MODEL
    answers: list[dict] = []

    with _client(auth_key, scope, model, log) as giga:
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start:start + BATCH_SIZE]
            for _attempt in range(2):
                try:
                    parsed = _ask(giga, model, system_prompt, batch)
                    if not parsed:
                        log("GigaChat: в ответе не нашлось ни одной строки нужного вида — пропускаю пачку.")
                    answers.extend(parsed)
                    break
                except AuthenticationError:
                    raise GigaChatSetupError("ключ авторизации не принят — проверьте ключ в настройках")
                except RateLimitError:
                    log("GigaChat: слишком много запросов — остаток классифицирую в следующий сбор.")
                    return answers
                except ResponseError as e:
                    if e.status_code == 402 and model != FALLBACK_MODEL:
                        log(f"GigaChat: закончился бесплатный лимит {model} — переключаюсь на {FALLBACK_MODEL}.")
                        model = FALLBACK_MODEL
                        continue
                    if e.status_code == 402:
                        log("GigaChat: бесплатный лимит токенов исчерпан.")
                        return answers
                    log(f"GigaChat: ошибка {e.status_code} — пропускаю пачку.")
                    break
    return answers
