#!/bin/bash
# Ноутбук как временный сервер (с 12.10.2026 — авария Yandex Cloud): те же сборы, что systemd на сервере (deploy/systemd),
# по расписанию launchd (deploy/laptop/install.sh). Запуск одного дела вручную:
#   deploy/laptop/tm.sh web | collect | market | sales | sync | backup | backupcfg
# Журналы — data/logs/<дело>.log. Одновременно одно и то же дело не запускается (замок в data/locks).
set -uo pipefail
APP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP" || exit 1
JOB="${1:-}"
PY=/usr/bin/python3

# Окружение — как /etc/ticket-monitor.env и systemd-юниты на сервере
export TZ=Europe/Moscow PYTHONUNBUFFERED=1
export TM_ON_SERVER=1                      # сайт берёт продажи и архив из своей базы, сборы — по расписанию launchd
export TM_DISABLED_OPERATORS=yandex        # Яндекс закрыл доступ серверу 06.10 — с домашнего адреса его не собираем
export SALES_BUDGET_YANDEX=0
export SALES_BUDGET_KASSIR=500             # с домашнего адреса Кассир — бережнее, чем с сервера (2 000): 04.10 он ограничивал этот адрес
export SALES_BUDGET_QTICKETS=800           # потолок; сам лимит — ступенями (data/qtickets_ramp.json)
export MARKET_KASSIR_PAUSE=2.0 MARKET_ORG_THREADS=1 MARKET_ORG_PAUSE=3.0
export PATH="$APP/deploy/laptop/bin:$PATH"   # systemctl-заглушка: «Собрать сейчас» в интерфейсе → launchctl

mkdir -p data/logs data/locks
LOG="data/logs/$JOB.log"
if [ -f "$LOG" ] && [ "$(stat -f %z "$LOG")" -gt 5000000 ]; then mv "$LOG" "$LOG.1"; fi
log() { echo "$(date '+%d.%m %H:%M:%S')  $*" >> "$LOG"; }

if [ "$JOB" = "web" ]; then
  exec "$PY" app.py >> "$LOG" 2>&1
fi

LOCK="data/locks/$JOB"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +240 2>/dev/null)" ]; then rm -rf "$LOCK"; mkdir "$LOCK"; else log "уже идёт — пропуск"; exit 0; fi
fi
trap 'rm -rf "$LOCK"' EXIT

log "=== начало: $JOB"
# Свежий код с GitHub — как ExecStartPre у сборов на сервере (правки кода делаются в рабочей копии и пушатся)
case "$JOB" in collect|market|sync) git pull -q --ff-only >> "$LOG" 2>&1 || log "git pull не прошёл — на текущем коде" ;; esac
case "$JOB" in
  collect) "$PY" -m competitors.collector auto >> "$LOG" 2>&1 ;;
  market)  touch data/.market_running
           "$PY" -m competitors.market >> "$LOG" 2>&1
           rm -f data/.market_running ;;
  sales)   "$PY" -m sales.run --budget 50 >> "$LOG" 2>&1
           "$PY" -m sales.export >> "$LOG" 2>&1 ;;
  sync)    "$PY" -m db.sync >> "$LOG" 2>&1
           "$PY" -m sales.results >> "$LOG" 2>&1 ;;
  backup)  "$PY" -m db.offsite >> "$LOG" 2>&1 ;;
  backupcfg) "$PY" -m db.offsite --config >> "$LOG" 2>&1 ;;
  *) echo "дело: web | collect | market | sales | sync | backup | backupcfg"; exit 2 ;;
esac
log "=== конец: $JOB (код $?)"
