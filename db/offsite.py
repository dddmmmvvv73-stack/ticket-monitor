"""
Копия вне облака (после аварии Yandex Cloud 11.10.2026): база и данные сборов — зашифрованным архивом в закрытый
репозиторий GitHub `ticket-monitor-backup`. Хранятся последние KEEP копий одним коммитом (без истории — репозиторий
не растёт). На ноутбуке-сервере — каждую ночь в 03:30 (deploy/laptop/tm.sh backup).

    python3 -m db.offsite            сделать копию и отправить
    python3 -m db.offsite --local    только сделать (без отправки)

Что внутри архива backup-<дата>.tar (зашифрован openssl aes-256-cbc, pbkdf2, 200 000 итераций):
    db.dump        pg_dump -Fc всей базы (история продаж, сеансы, итоги)
    data.tar.gz    data/competitors (сборы: афиша рынка, площадки, схемы, архив), config/ (разметка, проекты, настройки),
                   data/operator_blocks*.json, data/qtickets_ramp.json, data/sales_snapshot.json.gz
Пароль — в Связке ключей macOS (служба «ticket-monitor-backup»); без него копия бесполезна — его нужно сохранить
у себя отдельно (менеджер паролей). Восстановление — README.md в репозитории копий и HANDOFF.md, «Авария сервера».
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "offsite"
SETS = WORK / "sets"
REPO_DIR = WORK / "repo"
REMOTE = "https://github.com/dddmmmvvv73-stack/ticket-monitor-backup.git"
KEYCHAIN = ("ticket-monitor", "ticket-monitor-backup")   # учётная запись, служба
KEEP = 7
PART = 90 * 1024 * 1024   # GitHub не берёт файлы больше 100 МБ
INCLUDE = ["data/competitors", "config", "data/operator_blocks.json", "data/operator_blocks_log.jsonl",
           "data/qtickets_ramp.json", "data/sales_snapshot.json.gz"]
EXCLUDE_DIRS = {"market.local-0410"}

README = """# Копии ticket-monitor (закрытый репозиторий)

Каждую ночь — зашифрованный архив базы и данных сборов; здесь последние 7 копий, история коммитов не хранится.
Сделано `db/offsite.py` в основном репозитории (после аварии Yandex Cloud 11.10.2026).

## Восстановить
1. Пароль — в Связке ключей Mac, служба «ticket-monitor-backup» (`security find-generic-password -s ticket-monitor-backup -w`)
   или там, где вы его сохранили.
2. Собрать и расшифровать:
   `cat backup-ГГГГ-ММ-ДД.tar.enc.part* | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass pass:'ПАРОЛЬ' > backup.tar`
3. `tar xf backup.tar` → `db.dump` и `data.tar.gz`.
4. Данные: `tar xzf data.tar.gz -C <папка проекта>`.
5. База: `pg_restore --clean --if-exists --no-owner -d <адрес базы> db.dump` (на сервере — `postgresql:///ticket_monitor`).
"""


def log(msg: str) -> None:
    print(f"{datetime.now():%d.%m %H:%M:%S}  {msg}", flush=True)


def passphrase() -> str:
    acct, svc = KEYCHAIN
    r = subprocess.run(["security", "find-generic-password", "-a", acct, "-s", svc, "-w"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    pw = secrets.token_urlsafe(32)
    subprocess.run(["security", "add-generic-password", "-a", acct, "-s", svc, "-w", pw, "-U"], check=True)
    log("пароль копий создан и положен в Связку ключей (служба «ticket-monitor-backup») — сохраните его у себя отдельно")
    return pw


def _pg_bin(name: str) -> str:
    import pgserver
    return str(Path(pgserver.__file__).parent / "pginstall" / "bin" / name)


def dump_db(out: Path) -> None:
    from db import connect
    env = dict(os.environ)
    dsn = os.environ.get("DATABASE_URL") or connect.dsn()
    tool = shutil.which("pg_dump") if os.environ.get("DATABASE_URL") else _pg_bin("pg_dump")
    subprocess.run([tool, "-Fc", "-Z", "6", "-f", str(out), dsn], check=True, env=env, capture_output=True)


def pack_data(out: Path) -> None:
    def skip(t: tarfile.TarInfo):
        return None if any(part in EXCLUDE_DIRS for part in Path(t.name).parts) else t
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for rel in INCLUDE:
            p = ROOT / rel
            if p.exists():
                tar.add(p, arcname=rel, filter=skip)


def make(day: str) -> Path:
    """Архив за день → SETS/<день>/backup-<день>.tar.enc.partNN; старше KEEP — удаляются."""
    tmp = WORK / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    dump_db(tmp / "db.dump")
    pack_data(tmp / "data.tar.gz")
    with tarfile.open(tmp / "backup.tar", "w") as tar:
        tar.add(tmp / "db.dump", arcname="db.dump")
        tar.add(tmp / "data.tar.gz", arcname="data.tar.gz")
    enc = tmp / ("backup-%s.tar.enc" % day)
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-in", str(tmp / "backup.tar"),
                    "-out", str(enc), "-pass", "env:TM_BACKUP_PASS"], check=True, env={**os.environ, "TM_BACKUP_PASS": passphrase()})
    dest = SETS / day
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with open(enc, "rb") as f:
        n = 0
        while True:
            chunk = f.read(PART)
            if not chunk:
                break
            (dest / ("%s.part%02d" % (enc.name, n))).write_bytes(chunk)
            n += 1
    sizes = {p.name: os.path.getsize(tmp / p.name) for p in (tmp / "db.dump", tmp / "data.tar.gz")}
    shutil.rmtree(tmp, ignore_errors=True)
    for old in sorted(SETS.iterdir())[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    total = sum(p.stat().st_size for p in dest.iterdir())
    log("копия %s: база %.1f МБ, данные %.1f МБ → зашифровано %.1f МБ, частей %d" % (
        day, sizes["db.dump"] / 1e6, sizes["data.tar.gz"] / 1e6, total / 1e6, len(list(dest.iterdir()))))
    return dest


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Пароль GitHub — через gh (вход уже есть на этом компьютере), без записи токена в настройки git
    return subprocess.run(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args],
                          cwd=REPO_DIR, check=check, capture_output=True, text=True)


def push() -> None:
    """Все хранимые копии — одним коммитом (без истории) в закрытый репозиторий."""
    if not (REPO_DIR / ".git").exists():
        REPO_DIR.mkdir(parents=True, exist_ok=True)
        git("init", "-q", "-b", "main")
        git("remote", "add", "origin", REMOTE)
        git("config", "user.name", "ticket-monitor backup")
        git("config", "user.email", "backup@ticket-monitor.local")
    git("config", "http.postBuffer", "524288000")   # копия — десятки МБ одним пакетом (иначе GitHub отвечает 400)
    for p in REPO_DIR.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (REPO_DIR / "README.md").write_text(README, encoding="utf-8")
    for s in sorted(SETS.iterdir()):
        for f in s.iterdir():
            shutil.copy2(f, REPO_DIR / f.name)
    git("checkout", "-q", "--orphan", "next")
    git("add", "-A")
    git("commit", "-q", "-m", "Копии на %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    git("branch", "-D", "main", check=False)
    git("branch", "-m", "main")
    r = git("push", "-q", "-f", "origin", "main", check=False)
    if r.returncode != 0:
        raise RuntimeError("не отправилось в GitHub: " + (r.stderr or r.stdout)[-300:])
    git("reflog", "expire", "--expire=now", "--all")
    git("gc", "-q", "--prune=now")
    log("отправлено в закрытый репозиторий: копий %d" % len(list(SETS.iterdir())))


def main() -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    make(day)
    if "--local" not in sys.argv:
        push()


if __name__ == "__main__":
    main()
