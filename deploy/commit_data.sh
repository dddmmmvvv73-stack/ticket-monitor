#!/bin/bash
# История собранных данных на сервере: после каждого сбора — коммит в data/competitors (локальный git, на GitHub не уходит:
# данные продаж и афиши закрытые). Пересчитать задним числом / посмотреть, что было, — git log / git show в этой папке.
set -euo pipefail
cd /opt/ticket-monitor/data/competitors
git config user.name "ticket-monitor server"
git config user.email "server@ticket-monitor.local"
git add -A
git diff --cached --quiet && exit 0
git commit -q -m "${1:-Сбор} $(date '+%Y-%m-%d %H:%M')"
