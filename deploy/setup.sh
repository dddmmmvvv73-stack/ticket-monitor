#!/bin/bash
# Настройка сервера в Яндекс Облаке (Ubuntu 24.04). Запускать от пользователя tm; повторный запуск безопасен.
#   bash /opt/ticket-monitor/deploy/setup.sh
# Секреты — в /etc/ticket-monitor.env (кладутся отдельно, не из git): S3_KEY_ID, S3_SECRET, S3_BUCKET.
set -euo pipefail
APP=/opt/ticket-monitor
REPO=https://github.com/dddmmmvvv73-stack/ticket-monitor.git

# Код
if [ ! -d "$APP/.git" ]; then
  sudo mkdir -p "$APP" && sudo chown tm:tm "$APP"
  git clone -q "$REPO" "$APP"
fi
git -C "$APP" pull -q --ff-only

# Python
[ -d "$APP/.venv" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/deploy/requirements-server.txt"

# База: роль tm (вход по сокету без пароля) и база ticket_monitor
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'tm'" | grep -q 1 || sudo -u postgres createuser tm
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'ticket_monitor'" | grep -q 1 || sudo -u postgres createdb -O tm ticket_monitor

# Окружение: адрес базы (секреты S3 добавляются отдельно)
if ! sudo grep -q '^DATABASE_URL=' /etc/ticket-monitor.env 2>/dev/null; then
  echo 'DATABASE_URL=postgresql:///ticket_monitor' | sudo tee -a /etc/ticket-monitor.env >/dev/null
fi
sudo chown root:tm /etc/ticket-monitor.env && sudo chmod 640 /etc/ticket-monitor.env

# Расписание (systemd): сборы (площадки прямого сбора — каждый час, рынок — в 21:00, продажи — каждый час),
# пересборка базы каждый час, копия базы каждую ночь
sudo cp "$APP"/deploy/systemd/*.service "$APP"/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
for t in tm-sync tm-backup tm-sales tm-collect tm-market; do sudo systemctl enable --now "$t.timer"; done
systemctl list-timers 'tm-*' --no-pager
