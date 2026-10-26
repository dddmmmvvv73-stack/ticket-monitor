"""
Страница ссылки для руководителя — отдельный маленький сервер (CITY_PICK_PLAN.md, п. 2.8). Снаружи открывается только он
(порт 5070 — 5060 браузеры не открывают: порт SIP; снаружи — Tailscale Funnel), сам сайт (5050) остаётся закрытым. Два адреса и больше ничего:
    GET  /s/<token>           предложение по городам (как PDF «На согласование») + решения и комментарии руководителя
    POST /s/<token>/comment   {"city", "name", "text", "decision"} → все комментарии; не больше 60 записей в минуту на ссылку
Данные — competitors/shares.py (config/shares/). Документ рисует тот же offer-doc.js, что и PDF на сайте.

Запуск: python3 share_app.py (на ноутбуке — служба launchd ru.ticketmonitor.share, deploy/laptop/install.sh).
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, Response, jsonify, request

from competitors import shares

PORT = int(os.environ.get("TM_SHARE_PORT", "5070"))
DOC_JS = Path(__file__).resolve().parent / "Design" / "prototype" / "offer-doc.js"
RATE = 60   # записей в минуту на одну ссылку

app = Flask(__name__, static_folder=None)
_hits: dict[str, deque] = defaultdict(deque)


@app.after_request
def _headers(r: Response) -> Response:
    r.headers["X-Robots-Tag"] = "noindex, nofollow"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "no-store"
    return r


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _page(title: str, body: str, status: int = 200) -> Response:
    html = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>' + title + '</title>'
            '<style>body{font:15px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1c1917;margin:0;padding:40px 20px;text-align:center}</style>'
            '</head><body>' + body + '</body></html>')
    return Response(html, status=status, mimetype="text/html")


PAGE_JS = r"""
var D = JSON.parse(document.getElementById("tmdata").textContent), NAME_KEY = "tm-share-name";
var MGR = [["ok", "Согласовано", "#15803d"], ["ask", "Вопрос", "#b45309"], ["no", "Не согласовано", "#b42318"]];
var css = document.createElement("style");
css.textContent = OFFER_CSS + '.mgr{display:flex;flex-direction:column;gap:6px;padding:4px 0 10px}.mgr-btns{display:flex;flex-wrap:wrap;gap:6px}' +
  '.mgr-btns button{background:#fff;color:#44403c;border:1px solid #d6d3d1;padding:4px 12px;font-size:13px}.mgr-btns button[aria-pressed=true]{background:var(--c);border-color:var(--c);color:#fff}' +
  '.mgr-c{font-size:13px;color:#44403c;border-left:2px solid #e7e5e4;padding-left:8px}.mgr-c b{color:#1c1917}.mgr-row{display:flex;gap:6px;align-items:flex-start}' +
  '.mgr textarea{flex:1;min-width:0;font:inherit;font-size:14px;border:1px solid #d6d3d1;border-radius:8px;padding:6px 8px;resize:vertical;min-height:34px}.mgr-row button{padding:6px 14px;font-size:13px}' +
  '.who{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.who input{font:inherit;border:1px solid #d6d3d1;border-radius:8px;padding:6px 10px;width:200px;max-width:100%}' +
  '.note{background:#fef3c7;border-radius:8px;padding:8px 12px;margin:0 0 12px}.err{color:#b42318;font-size:13px}';
document.head.appendChild(css);
function esc(s) { return ofEsc(s); }
function when(at) { return new Date(at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }
function nameVal() { var el = document.getElementById("mgrName"); return el ? el.value.trim() : ""; }
function slot(el) {
  var city = el.getAttribute("data-mgr"), cs = D.comments.filter(function (c) { return c.city === city; });
  var dec = ""; cs.forEach(function (c) { if (c.decision) dec = c.decision; });
  el.innerHTML = '<div class="mgr">' + (city ? '<div class="mgr-btns" role="group" aria-label="Решение по городу">' + MGR.map(function (m) {
      return '<button data-dec="' + m[0] + '" aria-pressed="' + (dec === m[0]) + '" style="--c:' + m[2] + '">' + m[1] + '</button>'; }).join("") + '</div>' : '') +
    cs.map(function (c) { var m = MGR.filter(function (x) { return x[0] === c.decision; })[0];
      return '<div class="mgr-c"><b>' + esc(c.name) + '</b> · ' + when(c.at) + (m ? ' · ' + m[1].toLowerCase() : '') + (c.text ? '<div>' + esc(c.text).replace(/\n/g, "<br>") + '</div>' : '') + '</div>'; }).join("") +
    (D.closed ? '' : '<div class="mgr-row"><textarea rows="1" placeholder="' + (city ? 'Комментарий по городу' : 'Общий комментарий') + '" aria-label="Комментарий"></textarea><button data-send>Отправить</button></div><div class="err" hidden></div>') + '</div>';
}
function send(el, text, decision) {
  var city = el.getAttribute("data-mgr"), err = el.querySelector(".err");
  if (!nameVal()) { var n = document.getElementById("mgrName"); n.focus(); if (err) { err.hidden = false; err.textContent = "Укажите имя вверху страницы"; } return; }
  try { localStorage.setItem(NAME_KEY, nameVal()); } catch (e) { /* хранилище недоступно */ }
  fetch(location.pathname.replace(/\/$/, "") + "/comment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ city: city, name: nameVal(), text: text, decision: decision || "" }) })
    .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
    .then(function (x) { if (!x.ok) throw new Error(x.j.error || "не сохранилось"); D.comments = x.j.comments; slot(el); })
    .catch(function (e) { if (err) { err.hidden = false; err.textContent = "Не сохранилось: " + e.message; } });
}
var name0 = ""; try { name0 = localStorage.getItem(NAME_KEY) || ""; } catch (e) { /* хранилище недоступно */ }
document.getElementById("app").innerHTML =
  '<div class="bar"><div class="who"><label for="mgrName">Ваше имя</label><input id="mgrName" value="' + esc(name0) + '" placeholder="для комментариев" autocomplete="name"></div>' +
    '<span style="flex-grow:1"></span><button onclick="window.print()">Скачать PDF</button></div>' +
  (D.next ? '<p class="note">Есть более новая версия предложения — <a href="/s/' + encodeURIComponent(D.next) + '">открыть её</a>.</p>' : '') +
  (D.closed ? '<p class="note">Ссылка закрыта — комментарии больше не принимаются.</p>' : '') +
  offerDocBody(D.snap, "boss", { share: true });
document.querySelectorAll("[data-mgr]").forEach(slot);
document.addEventListener("click", function (ev) {
  var el = ev.target.closest("[data-mgr]"); if (!el || D.closed) return;   // и карточки городов, и общий комментарий
  var b = ev.target.closest("[data-dec]"); if (b) { send(el, "", b.getAttribute("data-dec")); return; }
  if (ev.target.closest("[data-send]")) { var t = el.querySelector("textarea"); if (t.value.trim()) send(el, t.value.trim(), ""); }
});
"""


@app.get("/s/<token>")
def share_page(token: str):
    d = shares.load(token)
    if not d:
        return _page("Ссылка не найдена", "<h1>Ссылка не найдена</h1><p>Проверьте адрес или попросите прислать новую.</p>", 404)
    if d.get("closed"):
        nxt = '<p><a href="/s/' + d["next"] + '">Открыть новую версию</a></p>' if d.get("next") else ""
        return _page("Ссылка закрыта", "<h1>Ссылка закрыта</h1><p>Организатор закрыл это предложение.</p>" + nxt, 410)
    data = json.dumps({"snap": d["snapshot"], "comments": d.get("comments", []), "next": d.get("next"), "closed": bool(d.get("closed"))},
                      ensure_ascii=False).replace("</", "<\\/")
    doc_js = DOC_JS.read_text(encoding="utf-8").replace("</script", "<\\/script")
    title = "На согласование — " + str(d["snapshot"].get("who") or "")
    html = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>' + _esc(title) + '</title></head><body><div id="app">Загрузка…</div>'
            '<script type="application/json" id="tmdata">' + data + '</script><script>' + doc_js + '</script><script>' + PAGE_JS + '</script></body></html>')
    return Response(html, mimetype="text/html")


@app.post("/s/<token>/comment")
def share_comment(token: str):
    if not request.is_json:
        return jsonify({"error": "нужен JSON"}), 415
    now, q = time.time(), _hits[token]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE:
        return jsonify({"error": "слишком часто — подождите минуту"}), 429
    q.append(now)
    b = request.get_json(silent=True) or {}
    try:
        d = shares.add_comment(token, b.get("city"), b.get("name"), b.get("text"), b.get("decision"))
    except shares.ShareError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "comments": d["comments"]})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
