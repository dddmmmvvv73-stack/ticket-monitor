"""
Подключение к базе.

- DATABASE_URL задан (Яндекс Облако и т. п.) — обычный Postgres по адресу.
- Не задан (ноутбук) — локальный Postgres 16 из пакета pgserver, файлы в data/pgdata (не в git).
  Ставится: python3 -m pip install --user -r requirements-db.txt
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent.parent
PGDATA = ROOT / "data" / "pgdata"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"
DB_NAME = "ticket_monitor"

_server = None


def dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    global _server
    if _server is None:
        import pgserver  # только для ноутбука
        PGDATA.mkdir(parents=True, exist_ok=True)
        _server = pgserver.get_server(str(PGDATA), cleanup_mode=None)  # сервер живёт после выхода — как обычная база
        if not _server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}';").strip().endswith("(1 row)"):
            _server.psql(f"CREATE DATABASE {DB_NAME};")
    return _server.get_uri(DB_NAME)


def connect():
    conn = psycopg2.connect(dsn())
    psycopg2.extras.register_default_jsonb(conn)
    return conn


def ensure_schema(conn) -> None:
    """
    Применяет schema.sql, только если она изменилась с прошлого раза (версия — хэш файла в schema_version).
    ALTER TABLE ждёт свободную таблицу не дольше 15 с: идущий сбор не должен вставать в очередь за ним
    (05.10 сбор продаж простоял так 6 минут).
    """
    text = SCHEMA.read_text(encoding="utf-8")
    version = hashlib.sha1(text.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_version (hash text PRIMARY KEY, applied timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT 1 FROM schema_version WHERE hash = %s", (version,))
        if cur.fetchone():
            conn.commit()
            return
        cur.execute("SET LOCAL lock_timeout = '15s'")
        cur.execute(text)
        cur.execute("INSERT INTO schema_version (hash) VALUES (%s) ON CONFLICT DO NOTHING", (version,))
    conn.commit()
