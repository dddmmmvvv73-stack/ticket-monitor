#!/bin/bash
# Ноутбук как временный сервер (с 12.10.2026 — авария Yandex Cloud): те же сборы, что systemd на сервере (deploy/systemd),
# по расписанию launchd (deploy/laptop/install.sh). Запуск одного дела вручную:
#   deploy/laptop/tm.sh web | collect | market | sales | sync | backup | backupcfg | check
# Копия или пробное восстановление не прошли — сообщение в Telegram (competitors/telegram.py, если настроен).
# Журналы — data/logs/<дело>.log. Одновременно одно и то же дело не запускается (замок в data/locks).
set -uo pipefail
APP="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP" || exit 1
JOB="${1:-}"
PY=/usr/bin/python3

# Окружение — как /etc/ticket-monitor.env и systemd-юниты на сервере
export TZ=Europe/Moscow PYTHONUNBUFFERED=1
export TM_ON_SERVER=1                      # сайт берёт продажи и архив из своей базы, сборы — по расписанию launchd
export TM_DISABLED_OPERATORS=             # с 13.10 Яндекс собирается и с ноутбука (решение пользователя; отказ закрыл только облачный сервер)
export SALES_BUDGET_YANDEX=2500            # запросов в сутки — решение пользователя 13.10 (с сервера было 4 000)
export SALES_BUDGET_KASSIR=500             # с домашнего адреса Кассир — бережнее, чем с сервера (2 000): 04.10 он ограничивал этот адрес
export SALES_BUDGET_QTICKETS=800           # потолок; сам лимит — ступенями (data/qtickets_ramp.json)
export MARKET_KASSIR_PAUSE=2.0 MARKET_ORG_THREADS=1 MARKET_ORG_PAUSE=3.0
# systemctl-заглушка («Собрать сейчас» → launchctl) и gh (вход в GitHub для правок сайта и копий) — у launchd PATH короткий
export PATH="$APP/deploy/laptop/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

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
trap 'rm -rf "$LOCK"; [ "$JOB" = market ] && rm -f data/.market_running' EXIT   # прервали — не оставлять «идёт афиша»

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
  sync)    "$PY" -m competitors.officialsite >> "$LOG" 2>&1 || log "официальные сайты — ошибка, база пополняется дальше"
           "$PY" -m db.sync >> "$LOG" 2>&1
           "$PY" -m sales.results >> "$LOG" 2>&1 ;;
  backup)  "$PY" -m db.offsite >> "$LOG" 2>&1 ;;
  backupcfg) "$PY" -m db.offsite --config >> "$LOG" 2>&1 ;;
  check)   "$PY" -m db.offsite --check >> "$LOG" 2>&1 ;;
  *) echo "дело: web | collect | market | sales | sync | backup | backupcfg | check"; exit 2 ;;
esac
RC=$?
log "=== конец: $JOB (код $RC)"
if [ "$RC" -ne 0 ]; then
  case "$JOB" in
    backup)    WHAT="ночная копия данных не сохранилась" ;;
    backupcfg) WHAT="копия настроек (площадки, финмодель, проекты) не сохранилась — повторю через 15 минут" ;;
    check)     WHAT="пробное восстановление копии не прошло" ;;
    *)         WHAT="" ;;
  esac
  [ -n "$WHAT" ] && "$PY" -m competitors.telegram send "⚠️ ticket-monitor: $WHAT. $(grep -v '^\s*$' "$LOG" | tail -n 3 | cut -c1-300)" >/dev/null 2>&1
fi
