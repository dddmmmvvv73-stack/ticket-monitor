"""
Уведомления в Telegram (решение пользователя 19.10.2026: нужен телефон и уведомления). Сейчас — только сбои копий и
пробного восстановления (deploy/laptop/tm.sh); дальше — дедлайны задач. Сигнала «ноутбук жив» нет — пользователь
решил, что это лишнее.

Настройка один раз (в Терминале, на ноутбуке-сервере):
  1. В Telegram — @BotFather → /newbot → имя → получить токен вида 123456:ABC…
  2. Написать своему новому боту любое сообщение (например /start).
  3. cd ~/tm-server && python3 -m competitors.telegram setup   — спросит токен (не виден при вводе), сам найдёт ваш чат,
     пришлёт проверочное сообщение.

Хранится в config/telegram.json — вне git (токен — секрет), в закрытых копиях вместе с config/.

    python3 -m competitors.telegram send "текст"    отправить
    python3 -m competitors.telegram test            проверочное сообщение
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.parse
import urllib.request

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "telegram.json"   # {"token", "chat"}
API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, params: dict | None = None) -> dict:
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    with urllib.request.urlopen(API.format(token=token, method=method), data=data, timeout=20) as r:
        return json.load(r)


def configured() -> bool:
    c = load_json(FILE, {})
    return bool(c.get("token") and c.get("chat"))


def send(text: str) -> bool:
    """Отправить сообщение; не настроено или не ушло — False (сбор и копии от этого не останавливаются)."""
    c = load_json(FILE, {})
    if not (c.get("token") and c.get("chat")):
        return False
    try:
        return bool(_call(c["token"], "sendMessage", {"chat_id": c["chat"], "text": text[:4000], "disable_web_page_preview": "true"}).get("ok"))
    except Exception:   # noqa: BLE001 — нет интернета, бот заблокирован: уведомление теряется, работа идёт
        return False


def setup() -> None:
    token = getpass.getpass("Токен бота от @BotFather (при вводе не виден): ").strip()
    if not token:
        sys.exit("токен не введён")
    try:
        me = _call(token, "getMe")
    except Exception as e:   # noqa: BLE001
        sys.exit(f"Telegram не принял токен: {e}")
    upd = _call(token, "getUpdates").get("result", [])
    chats = [u["message"]["chat"] for u in upd if u.get("message")]
    if not chats:
        sys.exit(f"Напишите своему боту @{me['result']['username']} любое сообщение (например /start) и запустите setup ещё раз")
    chat = chats[-1]
    save_json(FILE, {"token": token, "chat": chat["id"], "bot": me["result"]["username"]})
    ok = send("✅ ticket-monitor: уведомления подключены. Сюда придёт сообщение, если не сохранилась копия данных "
              "или не прошло пробное восстановление; позже — дедлайны задач.")
    print(f"Бот @{me['result']['username']} → чат {chat.get('first_name') or chat['id']}: " + ("проверочное сообщение отправлено" if ok else "сообщение не ушло"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "send" and len(sys.argv) > 2:
        sys.exit(0 if send(" ".join(sys.argv[2:])) else 1)
    elif cmd == "test":
        sys.exit(0 if send("ticket-monitor: проверка уведомлений") else 1)
    else:
        print(__doc__)
