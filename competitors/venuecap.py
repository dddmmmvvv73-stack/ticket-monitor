"""
Вместимость площадок — автоматически из схем касс (вкладка «Планирование → Карта», решение пользователя 13.10.2026:
«вместимость — автоматикой, но то, что я внёс вручную, — в первую очередь»; ручная — в «Площадках», config/planning.json).

    python3 -m competitors.venuecap                       пополнить из data/sales_snapshot.json.gz (и показать итог)
    python3 -m competitors.venuecap <снимок.json.gz>      пополнить из другого снимка (например, старого — с облачного сервера)

Откуда: сводка продаж (sales/export.py) по каждой карточке рынка — hall (мест в зале по схеме Яндекса, без уровней-услуг)
и exp (мест в схеме кассы — только её квота). Площадка — по карточке из афиши рынка (events.json: город, площадка).
По площадке храним наибольшее: «зал целиком» (hall) важнее «схемы кассы» (exp) — касса видит только свою квоту
(TICKET_PLATFORMS, правило 1). Значения копятся: сеанс ушёл из афиши — вместимость его зала остаётся.

Хранится:
    config/venue_capacity_seed.json   — отправная точка (выгрузка с облачного сервера 05.10.2026; в git — это не продажи,
                                        а число мест залов)
    data/competitors/venue_capacity.json — пополняется после каждого сбора продаж (sales.export зовёт update)
    {ключ площадки «город|название без кавычек и пробелов»: {"name", "cap", "src": "hall" | "scheme", "at", "n"}}
Для прототипа — /proto/venue-cap.js (MVCAP = {ключ: [мест, источник, название]}).
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import date
from pathlib import Path

from competitors import curation
from competitors.storage import CONFIG_DIR, DATA_DIR, load_json, save_json

FILE = DATA_DIR / "venue_capacity.json"
SEED = CONFIG_DIR / "venue_capacity_seed.json"
SNAPSHOT = DATA_DIR.parent / "sales_snapshot.json.gz"
EVENTS = DATA_DIR / "market" / "events.json"
RANK = {"hall": 2, "scheme": 1}


def _better(old: dict | None, cap: int, src: str) -> bool:
    if not old:
        return True
    return (RANK[src], cap) > (RANK.get(old.get("src"), 0), old.get("cap", 0))


def update(rows: dict, events: list | None = None, out: Path = FILE, log=print) -> dict:
    """Пополнить справочник из строк сводки продаж {ключ карточки: {hall, exp, …}}. Возвращает весь справочник."""
    events = load_json(EVENTS, []) if events is None else events
    where = {k: (e["city"], e["venue"]) for e in events for k in e.get("keys", [])}
    data, today, n_new, n_up = load_json(out, {}), date.today().isoformat(), 0, 0
    seen: dict[str, int] = {}
    for key, r in rows.items():
        cv = where.get(key)
        if not cv or not cv[1]:
            continue
        cap, src = (int(r["hall"]), "hall") if r.get("hall") else (int(r["exp"]), "scheme") if r.get("exp") else (0, "")
        if cap < 20 or cap > 60000:   # не зал: служебные сеансы, ошибки схемы
            continue
        vk = curation.venue_key(cv[0], cv[1])
        seen[vk] = seen.get(vk, 0) + 1
        old = data.get(vk)
        if _better(old, cap, src):
            n_new += old is None
            n_up += old is not None
            data[vk] = {"city": cv[0], "name": cv[1], "cap": cap, "src": src, "at": today, "n": (old or {}).get("n", 0)}
    for vk, n in seen.items():
        data[vk]["n"] = max(data[vk].get("n", 0), n)
    if n_new or n_up:
        save_json(out, data)
    log(f"Вместимость площадок: новых {n_new}, уточнено {n_up}, всего {len(data)}")
    return data


def update_from_snapshot(path: Path = SNAPSHOT, out: Path = FILE, log=print) -> dict:
    try:
        rows = json.load(gzip.open(path)).get("rows", {})
    except (OSError, ValueError):
        log(f"Вместимость площадок: нет сводки продаж {path}")
        return load_json(out, {})
    return update(rows, out=out, log=log)


def merged() -> dict:
    """Отправная точка + накопленное (накопленное уточняет)."""
    data = dict(load_json(SEED, {}))
    for vk, v in load_json(FILE, {}).items():
        if _better(data.get(vk), v.get("cap", 0), v.get("src", "scheme")):
            data[vk] = v
    return data


def export_js() -> str:
    out = {vk: [v["cap"], v["src"], v.get("name", "")] for vk, v in merged().items()}
    return ("// Вместимость площадок по схемам касс (competitors/venuecap.py): [мест, hall — зал целиком | scheme — схема кассы, название]\n"
            f"var MVCAP = {json.dumps(out, ensure_ascii=False, separators=(',', ':'))};\n")


if __name__ == "__main__":
    update_from_snapshot(Path(sys.argv[1]) if len(sys.argv) > 1 else SNAPSHOT)
