"""
Сбор на GitHub Actions из интерфейса: запуск, ход последних сборов и обновление данных на этом компьютере.

    GET  /api/github/runs              последние запуски «Сбора конкурентов» и «Афиши рынка»
    POST /api/github/collect           {"what": "collect" | "market"} — запустить сбор сейчас (gh workflow run)
    POST /api/data/pull                ./pull_data.sh — подтянуть собранное с GitHub в data/competitors

Нужен `gh`, авторизованный в репозитории (на этом компьютере — да, см. HANDOFF, раздел 2).
Расписание сборов задаёт cron-job.org, а не приложение: конкуренты — каждый час в :25, рынок — в 21:00.
"""

from __future__ import annotations

import json
import subprocess

from flask import Blueprint, jsonify, request

from competitors import collector
from competitors.storage import BASE_DIR

bp = Blueprint("github_api", __name__)
WORKFLOWS = {"collect": ("collect.yml", "Сбор конкурентов"), "market": ("market.yml", "Афиша рынка")}


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
    try:
        r = _run("./pull_data.sh", timeout=300)
    except subprocess.TimeoutExpired as e:
        return jsonify({"error": _gh_error(e)}), 502
    if r.returncode != 0:
        return jsonify({"error": _gh_error(r)}), 502
    return jsonify({"ok": True, "message": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "Данные обновлены"})
