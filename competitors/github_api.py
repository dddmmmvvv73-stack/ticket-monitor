"""
Сборы из интерфейса: запуск, ход последних сборов и обновление данных на этом компьютере.

    GET  /api/github/runs              последние запуски «Сбора конкурентов» и «Афиши рынка»
    POST /api/github/collect           {"what": "collect" | "market"} — запустить сбор сейчас
    POST /api/data/pull                ./pull_data.sh — подтянуть собранное в data/competitors

С 05.10.2026 сборы идут на сервере в Яндекс Облаке (systemd: tm-collect — каждый час в :25, tm-market — в 21:00).
Если есть config/server.json — всё через сервер по SSH; на самом сервере (tm-web, TM_ON_SERVER=1) — те же команды
на месте; иначе — как раньше, GitHub Actions через `gh` (адреса /api/github/* оставлены, чтобы прототип не менять).
"""

from __future__ import annotations

import json
import os
import subprocess

from flask import Blueprint, jsonify, request

from competitors import collector
from competitors.storage import BASE_DIR, ON_SERVER

bp = Blueprint("github_api", __name__)
WORKFLOWS = {"collect": ("collect.yml", "Сбор конкурентов"), "market": ("market.yml", "Афиша рынка")}
UNITS = {"collect": "tm-collect", "market": "tm-market"}   # те же сборы на сервере
SERVER_FILE = BASE_DIR / "config" / "server.json"


def _server():
    if ON_SERVER:
        return {"local": True}
    try:
        cfg = json.loads(SERVER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cfg if cfg.get("ssh") else None


def _ssh(cfg: dict, command: str, timeout: int = 40) -> subprocess.CompletedProcess:
    if cfg.get("local"):  # на сервере: та же команда здесь (запуск сборов разрешён tm правилом polkit, без sudo)
        return _run("bash", "-c", command, timeout=timeout)
    return _run("ssh", "-i", os.path.expanduser(cfg.get("key", "")), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                cfg["ssh"], command, timeout=timeout)


def _server_runs(cfg: dict):
    """Ход сборов на сервере — в том же виде, что gh run list (status / conclusion / createdAt / updatedAt)."""
    props = "Id,ActiveState,Result,ExecMainStartTimestamp,ExecMainExitTimestamp"
    r = _ssh(cfg, "systemctl show %s -p %s --timestamp=utc" % (" ".join(u + ".service" for u in UNITS.values()), props))
    if r.returncode != 0:
        return None
    blocks, cur = [], {}
    for line in r.stdout.splitlines():
        if not line.strip():
            blocks.append(cur); cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    blocks.append(cur)
    by_unit = {b.get("Id", "").removesuffix(".service"): b for b in blocks if b.get("Id")}

    def iso(ts: str) -> str | None:  # «Mon 2026-10-05 08:25:00 UTC» → ISO
        parts = ts.split()
        return parts[1] + "T" + parts[2] + "Z" if len(parts) >= 3 else None
    out = {}
    for key, unit in UNITS.items():
        b = by_unit.get(unit, {})
        start = iso(b.get("ExecMainStartTimestamp", ""))
        runs = []
        if start:
            active = b.get("ActiveState") in ("activating", "active")
            runs.append({"status": "in_progress" if active else "completed",
                         "conclusion": None if active else ("success" if b.get("Result") == "success" else "failure"),
                         "createdAt": start, "updatedAt": iso(b.get("ExecMainExitTimestamp", "")) or start, "url": ""})
        out[key] = {"label": WORKFLOWS[key][1] + " · сервер", "runs": runs}
    return out


@bp.before_request
def _json_only():
    # Команды — только из интерфейса (fetch с JSON): обычная HTML-форма чужого сайта так запрос не отправит
    if request.method == "POST" and not request.is_json:
        return jsonify({"error": "нужен запрос из интерфейса"}), 415


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout)


def _gh_error(e: Exception | subprocess.CompletedProcess) -> str:
    if isinstance(e, FileNotFoundError):
        return "не найдена программа gh (GitHub CLI) — установите её и выполните gh auth login"
    if isinstance(e, subprocess.TimeoutExpired):
        return "GitHub не ответил вовремя — попробуйте ещё раз"
    text = (getattr(e, "stderr", "") or str(e)).strip()
    return text.splitlines()[-1][:200] if text else "неизвестная ошибка"


@bp.get("/api/github/runs")
def github_runs():
    cfg = _server()
    if cfg:
        try:
            runs = _server_runs(cfg)
        except subprocess.TimeoutExpired:
            runs = None
        return jsonify(runs) if runs is not None else (jsonify({"error": "сервер недоступен (адрес сменился или нет сети)"}), 502)
    out = {}
    for key, (file, label) in WORKFLOWS.items():
        try:
            r = _run("gh", "run", "list", f"--workflow={file}", "--limit", "5",
                     "--json", "status,conclusion,createdAt,updatedAt,databaseId,url")
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return jsonify({"error": _gh_error(e)}), 502
        if r.returncode != 0:
            return jsonify({"error": _gh_error(r)}), 502
        out[key] = {"label": label, "runs": json.loads(r.stdout or "[]")}
    return jsonify(out)


@bp.post("/api/github/collect")
def github_collect():
    what = (request.get_json(silent=True) or {}).get("what", "collect")
    if what not in WORKFLOWS:
        return jsonify({"error": "неизвестный сбор"}), 400
    file, label = WORKFLOWS[what]
    cfg = _server()
    if cfg:  # сбор на сервере: запустить сейчас, не дожидаясь расписания
        try:
            r = _ssh(cfg, ("" if cfg.get("local") else "sudo ") + "systemctl start --no-block %s.service" % UNITS[what])
        except subprocess.TimeoutExpired:
            return jsonify({"error": "сервер не ответил вовремя"}), 502
        if r.returncode != 0:
            return jsonify({"error": "сервер недоступен (адрес сменился или нет сети)"}), 502
        collector.log(f"Запущен сбор на сервере вручную: {label}")
        return jsonify({"ok": True, "label": label})
    try:
        r = _run("gh", "workflow", "run", file, "--ref", "main")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return jsonify({"error": _gh_error(e)}), 502
    if r.returncode != 0:
        return jsonify({"error": _gh_error(r)}), 502
    collector.log(f"Запущен сбор на GitHub вручную: {label}")
    return jsonify({"ok": True, "label": label})


@bp.post("/api/data/pull")
def data_pull():
    if ON_SERVER:  # сборы идут здесь же — данные всегда свежие, подтягивать нечего
        return jsonify({"ok": True, "message": "Данные на сервере — всегда свежие"})
    try:
        r = _run("./pull_data.sh", timeout=300)
    except subprocess.TimeoutExpired as e:
        return jsonify({"error": _gh_error(e)}), 502
    if r.returncode != 0:
        return jsonify({"error": _gh_error(r)}), 502
    return jsonify({"ok": True, "message": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "Данные обновлены"})
