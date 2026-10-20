"""
Маленький пересыльщик DNS для cloudflared (20.10.2026).

Почему: на ноутбуке работает VPN (Happ), он забирает DNS себе, и системный список DNS-серверов пуст. cloudflared
(программа на Go) ищет свои серверы мимо системы — в /etc/resolv.conf, — не находит там ни одного сервера и спрашивает
localhost:53, где никто не отвечает. Ссылка для телефона не поднимается.

Что делает: слушает UDP-порт 53 (без прав администратора macOS даёт занять его только «на всех адресах») и отвечает
ТОЛЬКО запросам с самого ноутбука (127.0.0.1 / ::1) — остальные молча отбрасывает; запрос пересылает DNS-серверу сети
(upstream()) и возвращает ответ. Уже запущен другой экземпляр (порт занят) — тихо выходит.

Запускается из deploy/laptop/tm.sh tunnel перед cloudflared.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time

LOCAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
FALLBACK = ["1.1.1.1", "8.8.8.8"]
_up = {"list": [], "at": 0.0}


def upstream() -> list:
    """Куда пересылать: DNS-серверы сети из настроек macOS (scutil --dns; при VPN Happ прямой 1.1.1.1 не проходит, а роутер —
    да), обновляются раз в 5 минут — сменилась сеть, сменится и сервер. TM_DNS_UPSTREAM — задать вручную."""
    if os.environ.get("TM_DNS_UPSTREAM"):
        return [(a, 53) for a in os.environ["TM_DNS_UPSTREAM"].split(",") if a]
    if time.time() - _up["at"] > 300:
        try:
            out = subprocess.run(["scutil", "--dns"], capture_output=True, text=True, timeout=5).stdout
            found = list(dict.fromkeys(re.findall(r"nameserver\[\d+\] : (\d+\.\d+\.\d+\.\d+)", out)))
        except (OSError, subprocess.SubprocessError):
            found = []
        _up.update(list=[(a, 53) for a in found + FALLBACK], at=time.time())
    return _up["list"]


def _answer(sock, data: bytes, client) -> None:
    for up in upstream():
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.settimeout(2)
        try:
            u.sendto(data, up)
            resp, _ = u.recvfrom(4096)
            sock.sendto(resp, client)
            return
        except OSError:
            continue
        finally:
            u.close()


def _serve(sock) -> None:
    while True:
        try:
            data, client = sock.recvfrom(4096)
        except OSError:
            continue
        if client[0] not in LOCAL:   # только сам ноутбук
            continue
        threading.Thread(target=_answer, args=(sock, data, client), daemon=True).start()


def main() -> None:
    socks = []
    for fam, addr in ((socket.AF_INET6, "::"), (socket.AF_INET, "0.0.0.0")):
        s = socket.socket(fam, socket.SOCK_DGRAM)
        if fam == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            s.bind((addr, 53))
        except OSError:
            s.close()
            continue
        socks.append(s)
    if not socks:
        sys.exit(0)   # порт уже занят — пересыльщик работает
    for s in socks[1:]:
        threading.Thread(target=_serve, args=(s,), daemon=True).start()
    _serve(socks[0])


if __name__ == "__main__":
    main()
