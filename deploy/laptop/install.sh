#!/bin/bash
# Ноутбук как временный сервер: расписание launchd — как таймеры systemd на сервере (deploy/systemd).
#   deploy/laptop/install.sh            поставить / обновить
#   deploy/laptop/install.sh remove     убрать (когда сервер снова главный)
# Дела: web — сайт http://127.0.0.1:5050/proto/ (всегда); collect — :25 каждый час; sales — :05 каждый час;
# sync — :58 каждый час; market — 21:00; backup — 03:30 (зашифрованная копия в закрытый репозиторий GitHub);
# backupcfg — :40 каждый час (только config/: карточки проектов, фото, разметка — если изменились);
# awake — не засыпать, пока ноутбук на питании (caffeinate -s; с крышкой закрытой без внешнего экрана Mac всё равно уснёт).
set -euo pipefail
APP="$(cd "$(dirname "$0")/../.." && pwd)"
AG="$HOME/Library/LaunchAgents"
UIDN=$(id -u)
JOBS="web collect sales sync market backup backupcfg awake"
mkdir -p "$AG" "$APP/data/logs"

# Идущий сбор не прерываем (12.10 переустановка убила сбор афиши на 12-й минуте): такое дело оставляем как есть
running() { launchctl list | awk -v l="ru.ticketmonitor.$1" '$3 == l && $1 != "-" {f=1} END {exit !f}'; }
KEEP=""
for j in $JOBS; do
  if [ "${1:-}" != "remove" ] && [ "$j" != web ] && [ "$j" != awake ] && running "$j"; then KEEP="$KEEP $j"; continue; fi
  launchctl bootout "gui/$UIDN/ru.ticketmonitor.$j" 2>/dev/null || true
  rm -f "$AG/ru.ticketmonitor.$j.plist"
done
[ "${1:-}" = "remove" ] && { echo "Расписание ноутбука убрано."; exit 0; }
[ -n "$KEEP" ] && echo "Идут сейчас — не трогаю (переставить после окончания):$KEEP"

cal() {   # cal <минута> [час]
  if [ -n "${2:-}" ]; then echo "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>$2</integer><key>Minute</key><integer>$1</integer></dict>"
  else echo "<key>StartCalendarInterval</key><dict><key>Minute</key><integer>$1</integer></dict>"; fi
}
plist() {   # plist <дело> <программа…> -- <доп. ключи>
  local j="$1" prog="$2" extra="$3"
  case " $KEEP " in *" $j "*) return ;; esac
  cat > "$AG/ru.ticketmonitor.$j.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>ru.ticketmonitor.$j</string>
<key>ProgramArguments</key><array>$prog</array>
<key>WorkingDirectory</key><string>$APP</string>
<key>StandardOutPath</key><string>$APP/data/logs/launchd-$j.log</string>
<key>StandardErrorPath</key><string>$APP/data/logs/launchd-$j.log</string>
$extra
</dict></plist>
P
  launchctl bootstrap "gui/$UIDN" "$AG/ru.ticketmonitor.$j.plist"
}
run() { echo "<string>/bin/bash</string><string>$APP/deploy/laptop/tm.sh</string><string>$1</string>"; }

plist web     "$(run web)"     "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
plist collect "$(run collect)" "$(cal 25)"
plist sales   "$(run sales)"   "$(cal 5)"
plist sync    "$(run sync)"    "$(cal 58)"
plist market  "$(run market)"  "$(cal 0 21)"
plist backup  "$(run backup)"  "$(cal 30 3)"
plist backupcfg "$(run backupcfg)" "$(cal 40)"   # настройки (карточки проектов, фото) — каждый час, если изменились
plist awake   "<string>/usr/bin/caffeinate</string><string>-s</string>" "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
echo "Расписание ноутбука поставлено: $(launchctl list | grep -c ru.ticketmonitor) дел. Сайт — http://127.0.0.1:5050/proto/"
