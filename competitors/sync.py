"""
Отправка настроек на GitHub.

Сбор идёт на GitHub Actions и берёт настройки из ветки main: список площадок (config/competitors.json),
ручную разметку рынка (config/market_curation.json), ручные ниши (config/classification_overrides.json).
Поэтому после сохранения в интерфейсе файл коммитится и отправляется в фоне — интерфейс не ждёт.
Итог пишется в журнал.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable, Iterable

from competitors.storage import BASE_DIR

SOURCES_PATH = "config/competitors.json"
_lock = threading.Lock()


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(BASE_DIR), *args], capture_output=True, text=True, timeout=180)


def _publish(paths: list[str], message: str, log: Callable[[str], None]) -> None:
    with _lock:
        changed = [p for p in paths if _git("diff", "--quiet", "HEAD", "--", p).returncode != 0
                   or _git("ls-files", "--error-unmatch", p).returncode != 0]
        if not changed:
            return  # файлы совпадают с последним коммитом — отправлять нечего
        _git("add", "--", *changed)
        commit = _git("commit", "-q", "-m", message, "--", *changed)
        if commit.returncode != 0:
            log(f"✖ Не отправлено на GitHub: не удался коммит — {commit.stderr.strip()[:200]}")
            return
        # Большой буфер: без него GitHub иногда обрывает отправку с HTTP 400
        push = _git("-c", "http.postBuffer=524288000", "push", "-q", "origin", "main")
        if push.returncode != 0:
            log(f"✖ Сохранено, но не отправлено на GitHub: {push.stderr.strip()[:200]}")
            return
        log(f"Отправлено на GitHub: {message} — сбор подхватит со следующего запуска.")


def publish_files(paths: Iterable[str], message: str, log: Callable[[str], None]) -> None:
    threading.Thread(target=_publish, args=(list(paths), message, log), daemon=True, name="publish").start()


def publish_sources(summary: str, log: Callable[[str], None]) -> None:
    publish_files([SOURCES_PATH], f"Площадки: {summary}", log)
