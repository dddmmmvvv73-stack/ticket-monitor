"""Чтение и атомарная запись JSON-файлов — общие для сборщика и ручных правок."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import fcntl
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Интерфейс запущен на самом сервере (systemd tm-web): сборы и продажи — здесь же, без SSH
ON_SERVER = os.environ.get("TM_ON_SERVER") == "1"
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data" / "competitors"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


class JsonLock:
    """Одна операция чтение → изменение → запись, включая другие процессы и вложенные вызовы."""

    def __init__(self, path):
        self.path = path
        self.thread = threading.RLock()
        self.depth = 0
        self.file = None

    def acquire(self):
        self.thread.acquire()
        try:
            if not self.depth:
                path = self.path() if callable(self.path) else self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                self.file = open(path.with_suffix(path.suffix + ".lock"), "a")
                fcntl.flock(self.file, fcntl.LOCK_EX)
            self.depth += 1
        except BaseException:
            if self.file:
                self.file.close()
                self.file = None
            self.thread.release()
            raise
        return True

    def release(self):
        self.depth -= 1
        if not self.depth:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None
        self.thread.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()
