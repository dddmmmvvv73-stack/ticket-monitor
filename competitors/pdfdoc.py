"""
PDF документов подбора городов: «Предложение артисту» и «На согласование» (решение пользователя 27.10.2026 — кнопка только
сохраняет PDF, печать — потом сам). Окно документа присылает свой HTML (с правками в рамках), здесь Chromium (Playwright —
тот же, что у сбора Qtickets) печатает его в PDF и отдаёт файлом.

    POST /api/pdf  {"html": документ целиком, "title": имя файла, "landscape": bool} → application/pdf (скачивание)

Только на основном сайте (127.0.0.1:5050, снаружи не виден). Страница рисуется без сети: любые запросы отклоняются.
"""

from __future__ import annotations

import io
import re

from flask import Blueprint, jsonify, request, send_file

HTML_MAX = 3_000_000   # байт

bp = Blueprint("pdfdoc", __name__)


def render(html: str, landscape: bool = False) -> bytes:
    from playwright.sync_api import sync_playwright   # тяжёлый импорт — только когда нужен PDF

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())   # документ самодостаточен: без сети
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", landscape=landscape, print_background=True,
                            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        finally:
            browser.close()


def file_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(title or "")).strip()[:120] or "Документ"
    return name + ".pdf"


@bp.post("/api/pdf")
def api_pdf():
    body = request.get_json(silent=True) or {}
    html = body.get("html")
    if not isinstance(html, str) or not html.strip():
        return jsonify({"error": "нет документа"}), 400
    if len(html.encode()) > HTML_MAX:
        return jsonify({"error": "документ больше 3 МБ"}), 400
    try:
        pdf = render(html, bool(body.get("landscape")))
    except Exception as e:   # Chromium не запустился и т. п. — сказать в окне документа
        return jsonify({"error": f"PDF не получился: {e}"}), 500
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=file_name(body.get("title")))
