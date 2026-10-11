"""
Здоровье сервера для внешнего сторожа (.github/workflows/health.yml): страница /health в tm-web — без пароля (Caddy),
поэтому только «да / нет» и минуты, ни данных, ни адресов.

    python3 -m db.health      # то же в терминале

Проблема — база не отвечает, сбор продаж не шёл дольше SALES_LATE, афиша рынка — дольше MARKET_LATE или упала,
свободной памяти меньше MEM_LOW, диска — меньше DISK_LOW. Авария 11.10 (Yandex Cloud, питание зоны ru-central1-a):
сервер лежал часами, а узнали случайно — теперь сторож пишет issue на GitHub, и приходит письмо.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime

from competitors.storage import BASE_DIR, DATA_DIR, load_json

SALES_LATE = 130     # минут: сбор продаж — каждый час в :05
MARKET_LATE = 26     # часов: афиша рынка — раз в сутки в 21:00 (до ~1,5 ч)
MEM_LOW = 300        # МБ свободной памяти (MemAvailable)
DISK_LOW = 2         # ГБ свободного места


def _mem_mb() -> int | None:
    try:
        for line in open("/proc/meminfo", encoding="ascii"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def status() -> tuple[bool, dict]:
    now = datetime.now().astimezone()
    out: dict = {"at": now.isoformat(timespec="minutes"), "problems": []}
    try:
        from db import connect
        conn = connect.connect()
        try:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 5000")
            cur.execute("SELECT max(finished) FROM collection_runs WHERE kind = 'sales'")
            last = cur.fetchone()[0]
        finally:
            conn.close()
        out["db"] = True
        out["sales_min"] = round((now - last).total_seconds() / 60) if last else None
        if last is None or out["sales_min"] > SALES_LATE:
            out["problems"].append("сбор продаж не шёл %s мин" % out["sales_min"])
    except Exception as e:  # база не отвечает — главная проблема
        out["db"] = False
        out["problems"].append("база не отвечает: " + type(e).__name__)
    st = load_json(DATA_DIR / "market" / "status.json", {})
    if st.get("last_run_at"):
        h = (now.replace(tzinfo=None) - datetime.fromisoformat(st["last_run_at"][:19])).total_seconds() / 3600
        out["market_h"] = round(h, 1)
        running = (BASE_DIR / "data" / ".market_running").exists()
        if not running and (h > MARKET_LATE or st.get("last_ok") is False):
            out["problems"].append("афиша рынка: %s ч назад%s" % (out["market_h"], ", с ошибкой" if st.get("last_ok") is False else ""))
    mem = _mem_mb()
    if mem is not None:
        out["mem_mb"] = mem
        if mem < MEM_LOW:
            out["problems"].append("мало памяти: %d МБ" % mem)
    disk = shutil.disk_usage(BASE_DIR).free / 1e9
    out["disk_gb"] = round(disk, 1)
    if disk < DISK_LOW:
        out["problems"].append("мало места на диске: %.1f ГБ" % disk)
    out["ok"] = not out["problems"]
    return out["ok"], out


if __name__ == "__main__":
    ok, data = status()
    print(json.dumps(data, ensure_ascii=False, indent=1))
    raise SystemExit(0 if ok else 1)
