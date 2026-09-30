"""
Отправка списка площадок на GitHub.

Сбор идёт на GitHub Actions и берёт площадки из config/competitors.json ветки main.
Поэтому после каждого сохранения списка в интерфейсе файл коммитится и отправляется
(в фоне — интерфейс не ждёт). Итог пишется в журнал сбора.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable

from competitors.storage import BASE_DIR

SOURCES_PATH = "config/competitors.json"
_lock = threading.Lock()


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(BASE_DIR), *args], capture_output=True, text=True, timeout=180)


def _publish(summary: str, log: Callable[[str], None]) -> None:
    with _lock:
        if _git("diff", "--quiet", "HEAD", "--", SOURCES_PATH).returncode == 0:
            return  # файл совпадает с последним коммитом — отправлять нечего
        commit = _git("commit", "-q", "-m", f"Площадки: {summary}", "--", SOURCES_PATH)
        if commit.returncode != 0:
            log(f"✖ Список площадок не отправлен на GitHub: не удался коммит — {commit.stderr.strip()[:200]}")
            return
        # Большой буфер: без него GitHub иногда обрывает отправку с HTTP 400
        push = _git("-c", "http.postBuffer=524288000", "push", "-q", "origin", "main")
        if push.returncode != 0:
            log(f"✖ Список площадок сохранён, но не отправлен на GitHub: {push.stderr.strip()[:200]}")
            return
        log(f"Список площадок отправлен на GitHub ({summary}) — сбор подхватит его со следующего запуска.")


def publish_sources(summary: str, log: Callable[[str], None]) -> None:
    threading.Thread(target=_publish, args=(summary, log), daemon=True, name="publish-sources").start()
