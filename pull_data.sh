#!/bin/bash
# Подтягивает собранные данные в data/competitors (источник правды — место сбора, локальные изменения перезаписываются).
#
# С 05.10.2026 сборы идут на сервере в Яндекс Облаке. Если на этом компьютере есть config/server.json
# ({"ssh": "tm@<адрес>", "key": "~/.ssh/ticket_monitor_yc"} — не в git, репозиторий публичный), данные и сводка продаж
# берутся с сервера по SSH. Без него — как раньше, из ветки data на GitHub (данные там — по 05.10, дальше не обновляются).
# На самом сервере этот скрипт не нужен: данные собираются прямо в его data/competitors.
set -e
cd "$(dirname "$0")"
if [ "$(pwd)" = "/opt/ticket-monitor" ]; then  # на сервере данные собираются на месте — сброс на GitHub их бы стёр
  echo "Это сервер: данные собираются здесь, pull_data.sh не нужен" >&2
  exit 1
fi

if [ -f config/server.json ]; then
  SSH_HOST=$(python3 -c "import json; print(json.load(open('config/server.json'))['ssh'])")
  SSH_KEY=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('config/server.json')).get('key', '')))")
  SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=15"
  mkdir -p data/competitors
  if ! rsync -az --delete --exclude .git -e "$SSH" "$SSH_HOST:/opt/ticket-monitor/data/competitors/" data/competitors/; then
    echo "Сервер недоступен (адрес сменился или нет сети) — данные остались прежние" >&2
    exit 1
  fi
  STAMP=$($SSH "$SSH_HOST" "git -C /opt/ticket-monitor/data/competitors log -1 --format='%s'" 2>/dev/null || true)
  echo "Данные обновлены с сервера: ${STAMP:-последний сбор}"
  if scp -q -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST:/opt/ticket-monitor/data/sales_snapshot.json.gz" data/sales_snapshot.json.gz.tmp 2>/dev/null; then
    mv data/sales_snapshot.json.gz.tmp data/sales_snapshot.json.gz
    echo "Продажи обновлены с сервера"
  else
    rm -f data/sales_snapshot.json.gz.tmp
  fi
  exit 0
fi

# Без сервера — ветка data на GitHub. Первый запуск: прежняя папка сохраняется рядом как data/competitors.before-github-<дата>.
REPO_URL="$(git remote get-url origin)"
if [ ! -d data/competitors/.git ]; then
  if [ -d data/competitors ]; then
    mv data/competitors "data/competitors.before-github-$(date +%Y%m%d-%H%M)"
  fi
  git clone -q -b data --single-branch "$REPO_URL" data/competitors
else
  git -C data/competitors fetch -q origin data
  git -C data/competitors reset -q --hard origin/data
fi
echo "Данные обновлены: $(git -C data/competitors log -1 --format='%s (%cd)' --date=format:'%d.%m %H:%M')"
