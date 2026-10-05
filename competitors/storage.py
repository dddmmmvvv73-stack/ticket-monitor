"""Чтение и атомарная запись JSON-файлов — общие для сборщика и ручных правок."""

from __future__ import annotations

import json
import os
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)  # атомарная замена — интерфейс не прочитает полузаписанный файл
