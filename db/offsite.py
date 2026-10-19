"""
Копия вне облака (после аварии Yandex Cloud 11.10.2026): база и данные сборов — зашифрованным архивом в закрытый
репозиторий GitHub `ticket-monitor-backup`. Хранятся последние KEEP копий одним коммитом (без истории — репозиторий
не растёт). На ноутбуке-сервере — каждую ночь в 03:30 (deploy/laptop/tm.sh backup).

    python3 -m db.offsite            сделать копию и отправить
    python3 -m db.offsite --local    только сделать (без отправки)
    python3 -m db.offsite --config   только настройки (config/: карточки проектов, площадки, финмодель, фото, журнал
                                     изменений) — если изменились; каждые 15 минут (12.10: карточка AdrenalinHouse жила
                                     только на сервере и пропала с ним; 19.10 — чаще и глубже, решение пользователя).
                                     Уходят отдельной веткой «config» (только свежие настройки — ~1 МБ, не 0,5 ГБ копий)
    python3 -m db.offsite --check    пробное восстановление: скачать с GitHub последнюю ночную копию и свежие настройки,
                                     расшифровать, сверить с живыми данными (раз в месяц сам; ошибка — код 1 → Telegram)

Глубина: ночные копии (база + данные) — KEEP последних; настройки — снимок за каждый день (KEEP_DAYS) и за каждый
месяц (KEEP_MONTHS) — лежат в ночной копии рядом с архивами (config-day-*, config-month-*).

Что внутри архива backup-<дата>.tar (зашифрован openssl aes-256-cbc, pbkdf2, 200 000 итераций):
    db.dump        pg_dump -Fc всей базы (история продаж, сеансы, итоги)
    data.tar.gz    data/competitors (сборы: афиша рынка, площадки, схемы, архив), config/ (разметка, проекты, настройки),
                   data/operator_blocks*.json, data/qtickets_ramp.json, data/sales_snapshot.json.gz
Пароль — в Связке ключей macOS (служба «ticket-monitor-backup») или в TM_BACKUP_PASS (сервер: /etc/ticket-monitor.env);
без него копия бесполезна — его нужно сохранить у себя отдельно (менеджер паролей). Восстановление — README.md в репозитории копий и HANDOFF.md, «Авария сервера».
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
REMOTE = os.environ.get("TM_BACKUP_REMOTE") or "https://github.com/dddmmmvvv73-stack/ticket-monitor-backup.git"   # другой — только для проверки кода
CFG_DIR = WORK / "cfg"            # снимки настроек: день и месяц
CFG_REPO = WORK / "repo-config"   # ветка config — только свежие настройки
KEEP_DAYS, KEEP_MONTHS = 30, 12
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

## Только настройки (площадки, финмодель, карточки проектов, фото, журнал изменений)
- самые свежие — ветка **config**, файл `config-latest.tar.enc` (обновляется каждые 15 минут, если что-то поменялось);
- на выбранный день — `config-day-ГГГГ-ММ-ДД.tar.enc` (последние 30 дней), на месяц — `config-month-ГГГГ-ММ.tar.enc` (12 месяцев).
`openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass pass:'ПАРОЛЬ' -in config-latest.tar.enc | tar xz` → папка `config/`.
Отдельные правки — в самой папке: `config/history/changes-ГГГГ-ММ.jsonl` (журнал изменений, «было → стало»).
"""
README_CFG = """# Свежие настройки ticket-monitor (ветка config)

`config-latest.tar.enc` — папка config/ (площадки, финмодель, карточки проектов, фото, журнал изменений) на момент последней
правки; обновляется каждые 15 минут, если что-то поменялось. Ночные копии и снимки по дням и месяцам — ветка main.
`openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass pass:'ПАРОЛЬ' -in config-latest.tar.enc | tar xz`
"""


def log(msg: str) -> None:
    print(f"{datetime.now():%d.%m %H:%M:%S}  {msg}", flush=True)


def passphrase() -> str:
    if os.environ.get("TM_BACKUP_PASS"):   # сервер (Linux): пароль — в /etc/ticket-monitor.env
        return os.environ["TM_BACKUP_PASS"]
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


CONFIG_FILE = "config-latest.tar.enc"   # настройки — отдельно, последний вариант (лежит рядом с копиями в репозитории)


def encrypt(src: Path, dst: Path) -> None:
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-in", str(src), "-out", str(dst),
                    "-pass", "env:TM_BACKUP_PASS"], check=True, env={**os.environ, "TM_BACKUP_PASS": passphrase()})


def make_config() -> str | None:
    """Настройки (config/) → WORK/config-latest.tar.enc. Отпечаток — если изменились (отметить после удачной отправки:
    mark_config), None — с прошлой отправки ничего не изменилось."""
    import hashlib
    files = sorted(p for p in (ROOT / "config").rglob("*") if p.is_file())
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    sig, mark = h.hexdigest(), WORK / "config.sha256"
    if mark.exists() and mark.read_text() == sig and (WORK / CONFIG_FILE).exists():
        return None
    WORK.mkdir(parents=True, exist_ok=True)
    tmp = WORK / "config.tar.gz"
    with tarfile.open(tmp, "w:gz") as tar:
        tar.add(ROOT / "config", arcname="config")
    encrypt(tmp, WORK / CONFIG_FILE)
    tmp.unlink()
    snapshot_config()
    log("настройки изменились — копия config/ (%.1f МБ)" % ((WORK / CONFIG_FILE).stat().st_size / 1e6))
    return sig


def snapshot_config() -> None:
    """Свежие настройки → снимок дня и месяца (последний за день / месяц); старше KEEP_DAYS / KEEP_MONTHS — удаляются."""
    now = datetime.now()
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("config-day-%s.tar.enc" % now.strftime("%Y-%m-%d"), "config-month-%s.tar.enc" % now.strftime("%Y-%m")):
        shutil.copy2(WORK / CONFIG_FILE, CFG_DIR / name)
    for pattern, keep in (("config-day-*.tar.enc", KEEP_DAYS), ("config-month-*.tar.enc", KEEP_MONTHS)):
        for old in sorted(CFG_DIR.glob(pattern))[:-keep]:
            old.unlink()


def mark_config(sig: str | None) -> None:
    if sig:
        (WORK / "config.sha256").write_text(sig)


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
    encrypt(tmp / "backup.tar", enc)
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


def git(*args: str, check: bool = True, cwd: Path = REPO_DIR) -> subprocess.CompletedProcess:
    # Пароль GitHub — через gh (вход уже есть на этом компьютере), без записи токена в настройки git
    return subprocess.run(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args],
                          cwd=cwd, check=check, capture_output=True, text=True)


def _publish(repo: Path, branch: str, files: list, readme: str) -> None:
    """Файлы → одним коммитом без истории в ветку branch закрытого репозитория (принудительно: прежний вариант заменяется)."""
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        git("init", "-q", "-b", branch, cwd=repo)
        git("remote", "add", "origin", REMOTE, cwd=repo)
        git("config", "user.name", "ticket-monitor backup", cwd=repo)
        git("config", "user.email", "backup@ticket-monitor.local", cwd=repo)
    git("remote", "set-url", "origin", REMOTE, cwd=repo)
    git("config", "http.postBuffer", "524288000", cwd=repo)   # копия — десятки МБ одним пакетом (иначе GitHub отвечает 400)
    for p in repo.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (repo / "README.md").write_text(readme, encoding="utf-8")
    for f in files:
        shutil.copy2(f, repo / f.name)
    git("checkout", "-q", "--orphan", "next", cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "Копии на %s" % datetime.now().strftime("%Y-%m-%d %H:%M"), cwd=repo)
    git("branch", "-D", branch, check=False, cwd=repo)
    git("branch", "-m", branch, cwd=repo)
    r = git("push", "-q", "-f", "origin", branch, check=False, cwd=repo)
    if r.returncode != 0:
        raise RuntimeError("не отправилось в GitHub: " + (r.stderr or r.stdout)[-300:])
    git("reflog", "expire", "--expire=now", "--all", cwd=repo)
    git("gc", "-q", "--prune=now", cwd=repo)


def push() -> None:
    """Ночью: все ночные копии, снимки настроек по дням и месяцам и свежие настройки — ветка main."""
    files = [f for s in (sorted(SETS.iterdir()) if SETS.exists() else []) for f in sorted(s.iterdir())]
    snaps = sorted(CFG_DIR.glob("config-*.tar.enc")) if CFG_DIR.exists() else []
    latest = [WORK / CONFIG_FILE] if (WORK / CONFIG_FILE).exists() else []
    _publish(REPO_DIR, "main", files + snaps + latest, README)
    log("отправлено в закрытый репозиторий: копий %d, снимков настроек %d%s" % (
        len(list(SETS.iterdir())) if SETS.exists() else 0, len(snaps), ", свежие настройки" if latest else ""))


def push_config() -> None:
    """Каждые 15 минут, если настройки изменились: только они — ветка config (~1 МБ вместо всех ночных копий)."""
    _publish(CFG_REPO, "config", [WORK / CONFIG_FILE], README_CFG)
    log("свежие настройки отправлены (ветка config)")


CHECK_TABLES = ("sessions", "observations", "seat_sales", "projects", "venues")   # сверка базы: копия ↔ живая


def _decrypt(src: Path, dst: Path) -> None:
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", str(src), "-out", str(dst),
                    "-pass", "env:TM_BACKUP_PASS"], check=True, env={**os.environ, "TM_BACKUP_PASS": passphrase()}, capture_output=True)


def _dump_counts(dump: Path) -> dict:
    """Строк в каждой таблице копии базы — по COPY-разделам pg_restore (во временную базу не восстанавливаем)."""
    p = subprocess.Popen([_pg_bin("pg_restore") if not os.environ.get("DATABASE_URL") else shutil.which("pg_restore"),
                          "--data-only", "-f", "-", str(dump)], stdout=subprocess.PIPE, text=True, errors="replace")
    counts, cur = {}, None
    for line in p.stdout:
        if cur is None:
            if line.startswith("COPY "):
                cur = line.split()[1].split(".")[-1].strip('"')
                counts[cur] = 0
        elif line.startswith("\\."):
            cur = None
        else:
            counts[cur] += 1
    p.wait()
    if p.returncode:
        raise RuntimeError("pg_restore не прочитал копию базы")
    return counts


def _live_counts(tables) -> dict:
    from db import connect
    out = {}
    with connect.connect() as c, c.cursor() as cur:
        for t in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {t}")
                out[t] = cur.fetchone()[0]
            except Exception:
                c.rollback()
    return out


def check() -> int:
    """Пробное восстановление — как при настоящей аварии: всё берём с GitHub, не из локальных файлов. → 0 / 1 (есть проблемы)."""
    import json
    tmp = WORK / "check"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    problems, report = [], []
    try:
        # 1. Ночная копия (ветка main): скачиваем только последнюю — список файлов без содержимого, потом нужные
        main_dir = tmp / "main"
        git("clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "-b", "main", REMOTE, str(main_dir), cwd=tmp)
        names = git("ls-tree", "--name-only", "HEAD", cwd=main_dir).stdout.split()
        days = sorted({n[len("backup-"):len("backup-") + 10] for n in names if n.startswith("backup-")})
        if not days:
            raise RuntimeError("в репозитории нет ночных копий")
        day = days[-1]
        age = (datetime.now() - datetime.strptime(day, "%Y-%m-%d")).days
        parts = sorted(n for n in names if n.startswith(f"backup-{day}"))
        snaps = sorted(n for n in names if n.startswith("config-day-") or n.startswith("config-month-"))
        report.append(f"ночная копия {day} ({age} дн. назад), частей {len(parts)}; в репозитории копий {len(days)}, "
                      f"снимков настроек: по дням {sum(n.startswith('config-day-') for n in snaps)}, по месяцам {sum(n.startswith('config-month-') for n in snaps)}")
        if age > 2:
            problems.append(f"последняя ночная копия — {day}: копии не обновлялись больше двух суток")
        git("sparse-checkout", "set", "--no-cone", *parts, cwd=main_dir)
        git("checkout", "-q", "main", cwd=main_dir)
        enc = tmp / "backup.tar.enc"
        with open(enc, "wb") as out:
            for n in parts:
                out.write((main_dir / n).read_bytes())
        _decrypt(enc, tmp / "backup.tar")
        enc.unlink()
        shutil.rmtree(main_dir, ignore_errors=True)
        with tarfile.open(tmp / "backup.tar") as t:
            t.extractall(tmp)
        (tmp / "backup.tar").unlink()
        # данные и настройки внутри ночной копии
        with tarfile.open(tmp / "data.tar.gz") as t:
            members = t.getnames()
            need = ["config/venue_book.json", "config/planning.json", "config/my_projects.json"]
            made = datetime.strptime(day, "%Y-%m-%d").timestamp() + 4 * 3600   # ночная копия — около 03:30 того дня
            born = lambda n: getattr((ROOT / n).stat(), "st_birthtime", (ROOT / n).stat().st_mtime) if (ROOT / n).exists() else 0
            miss = [n for n in need if n not in members and born(n) < made]
            late = [n for n in need if n not in members and born(n) >= made]
            if miss:
                problems.append("в ночной копии нет: " + ", ".join(miss))
            if late:
                report.append("появились после ночной копии — войдут в следующую (сейчас — в свежих настройках): " + ", ".join(late))
            for n in need:
                if n in members:
                    json.load(t.extractfile(n))   # файл читается — не обрезан
        report.append(f"данные и настройки: файлов {len(members)}, ключевые читаются")
        # база: строк в копии ↔ в живой (копия ночная — живая с тех пор только росла)
        dc = _dump_counts(tmp / "db.dump")
        lc = _live_counts([t for t in CHECK_TABLES if t in dc])
        for t in CHECK_TABLES:
            if t not in dc:
                continue
            live = lc.get(t)
            report.append(f"база · {t}: в копии {dc[t]:,}, сейчас {live:,}".replace(",", " ") if live is not None else f"база · {t}: в копии {dc[t]}")
            if live and dc[t] == 0:
                problems.append(f"в копии базы таблица {t} пустая, а в живой {live} строк")
            elif live and dc[t] < live * 0.5:
                problems.append(f"в копии базы {t} — {dc[t]} строк, в живой {live}: копия неполная")
        (tmp / "db.dump").unlink()
        # 2. Свежие настройки (ветка config) ↔ живая папка config/
        cfg_dir = tmp / "cfg"
        r = git("clone", "-q", "--depth", "1", "-b", "config", REMOTE, str(cfg_dir), cwd=tmp, check=False)
        if r.returncode != 0:
            report.append("ветки config ещё нет — появится после первой правки настроек")
        else:
            _decrypt(cfg_dir / CONFIG_FILE, tmp / "config.tar.gz")
            with tarfile.open(tmp / "config.tar.gz") as t:
                t.extractall(tmp / "restored")
            same = diff = 0
            changed = []
            for f in sorted((ROOT / "config").rglob("*")):
                if not f.is_file():
                    continue
                g = tmp / "restored" / f.relative_to(ROOT)
                if g.is_file() and g.read_bytes() == f.read_bytes():
                    same += 1
                else:
                    diff += 1
                    changed.append(str(f.relative_to(ROOT / "config")))
            report.append(f"свежие настройки: совпадают с живыми {same} файлов" + (f", отличаются {diff} (правки последних 15 минут): " + ", ".join(changed[:6]) if diff else ""))
    except Exception as e:   # noqa: BLE001 — любая ошибка восстановления и есть то, что ищем
        problems.append(f"восстановление не прошло: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for line in report:
        log(line)
    for p in problems:
        log("ПРОБЛЕМА: " + p)
    log("пробное восстановление: " + ("ПРОБЛЕМЫ — " + "; ".join(problems) if problems else "всё восстановилось"))
    return 1 if problems else 0


def main() -> None:
    if "--check" in sys.argv:
        sys.exit(check())
    if "--config" in sys.argv:   # каждые 15 минут: только настройки, только если изменились
        sig = make_config()
        if sig:
            push_config()
            mark_config(sig)
        return
    day = datetime.now().strftime("%Y-%m-%d")
    make(day)
    sig = make_config()
    if not (CFG_DIR.exists() and any(CFG_DIR.glob("config-day-*"))) and (WORK / CONFIG_FILE).exists():
        snapshot_config()   # первый запуск после перехода на снимки: настройки не менялись, а снимка ещё нет
    if "--local" not in sys.argv:
        push()
        if sig:
            push_config()
        mark_config(sig)


if __name__ == "__main__":
    main()
