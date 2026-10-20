"""
Пароль на сайт для входа снаружи (решение пользователя 20.10.2026: открыть сайт с телефона без Wi-Fi — ссылка через
Cloudflare Tunnel, deploy/laptop/tm.sh tunnel).

Сайт на ноутбуке слушает только 127.0.0.1. Запрос с самого ноутбука — без пароля, как раньше. Запрос, пришедший через
туннель (cloudflared подключается тоже с 127.0.0.1, но добавляет свои заголовки Cf-…), — только с логином и паролем
(Basic-вход браузера). Пароля не задано — снаружи не пускаем совсем.

Хранится в config/site_auth.json — вне git: {"user", "hash"} (pbkdf2, сам пароль не хранится).

    python3 -m competitors.siteauth new [логин]   новый случайный пароль (печатается один раз)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sys
import time

from werkzeug.security import check_password_hash, generate_password_hash

from competitors.storage import CONFIG_DIR, load_json, save_json

FILE = CONFIG_DIR / "site_auth.json"
TUNNEL_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Visitor", "X-Forwarded-For", "Forwarded")
LOCAL = ("127.0.0.1", "::1")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # без похожих l/1, o/0 — удобно набирать на телефоне
_ok: set = set()                                 # проверенные входы (pbkdf2 медленный — не считать на каждый запрос)


def from_outside(req) -> bool:
    return req.remote_addr not in LOCAL or any(h in req.headers for h in TUNNEL_HEADERS)


def check(auth) -> bool:
    c = load_json(FILE, {})
    user, pw = getattr(auth, "username", None) or "", getattr(auth, "password", None) or ""
    if not (c.get("hash") and user and pw):
        return False
    key = hashlib.sha256(f"{c['hash']}\0{user}\0{pw}".encode()).hexdigest()
    if key in _ok:
        return True
    if hmac.compare_digest(user.encode(), str(c.get("user", "")).encode()) and check_password_hash(c["hash"], pw):
        _ok.add(key)
        return True
    time.sleep(1)   # неверный пароль — с задержкой: подбор становится бессмысленно долгим
    return False


def new(user: str = "tm") -> str:
    pw = "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4))
    save_json(FILE, {"user": user, "hash": generate_password_hash(pw, method="pbkdf2:sha256")})   # scrypt в Python 3.9 на macOS нет
    _ok.clear()
    return pw


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "new":
        u = sys.argv[2] if len(sys.argv) > 2 else "tm"
        print(f"Логин: {u}\nПароль: {new(u)}")
    else:
        print(__doc__)
