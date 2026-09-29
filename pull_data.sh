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
