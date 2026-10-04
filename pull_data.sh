#!/bin/bash
# Подтягивает собранные на GitHub данные (ветка data) в data/competitors.
# Сервер — источник правды: локальные изменения в data/competitors перезаписываются.
# Первый запуск: прежняя папка сохраняется рядом как data/competitors.before-github-<дата>.
set -e
cd "$(dirname "$0")"
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
# Продажи гастролей — сводка с сервера в Яндекс Облаке (только если на этом компьютере есть config/server.json:
# {"ssh": "tm@<адрес>", "key": "~/.ssh/ticket_monitor_yc"}). В публичный репозиторий данные продаж не попадают.
if [ -f config/server.json ]; then
  SSH_HOST=$(python3 -c "import json; print(json.load(open('config/server.json'))['ssh'])")
  SSH_KEY=$(python3 -c "import json, os; print(os.path.expanduser(json.load(open('config/server.json')).get('key', '')))")
  if scp -q -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST:/opt/ticket-monitor/data/sales_snapshot.json.gz" data/sales_snapshot.json.gz.tmp 2>/dev/null; then
    mv data/sales_snapshot.json.gz.tmp data/sales_snapshot.json.gz
    echo "Продажи обновлены с сервера"
  else
    rm -f data/sales_snapshot.json.gz.tmp
    echo "Продажи: сервер недоступен (адрес сменился или нет сети) — остались прежние"
  fi
fi
