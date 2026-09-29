"""
Выгрузка накопленных данных в Google Таблицу.

Запускать отдельно от main.py и реже — раз в 5-15 минут, не каждую минуту
(у Google Sheets API есть лимит запросов).

Разовая настройка перед первым запуском (сделать один раз):
1. Зайти в console.cloud.google.com, создать проект.
2. Включить Google Sheets API и Google Drive API для проекта.
3. Создать Service Account (IAM & Admin -> Service Accounts -> Create).
4. Создать для него ключ в формате JSON, скачать файл,
   положить рядом со скриптом как service_account.json.
5. Открыть свою Google Таблицу -> кнопка "Настройки доступа" ->
   выдать доступ email-адресу сервисного аккаунта (он выглядит как
   что-то@project-id.iam.gserviceaccount.com) с правами Редактор.
6. Скопировать ID таблицы из её URL (длинная строка между /d/ и /edit)
   и вставить в SPREADSHEET_ID ниже.

    pip install gspread google-auth
"""

from __future__ import annotations

import json
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

BASE_DIR = Path(__file__).parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"
SPREADSHEET_ID = "ВСТАВЬ_СЮДА_ID_ТАБЛИЦЫ"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = [
    "timestamp", "event_id", "date", "sale_status",
    "sellable_total", "sellable_available", "sellable_sold_cumulative",
    "sold_today_count", "revenue_today", "revenue_cumulative_tracked",
    "discounts_count", "operators",
]


def get_client():
    creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_sheet(spreadsheet, event_id: str):
    try:
        return spreadsheet.worksheet(event_id)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=event_id, rows=1000, cols=len(HEADER))
        ws.append_row(HEADER)
        return ws


def row_from_record(event_id: str, record: dict) -> list:
    return [
        record.get("timestamp"),
        event_id,
        record.get("date"),
        record.get("sale_status"),
        record.get("sellable_total"),
        record.get("sellable_available"),
        record.get("sellable_sold_cumulative"),
        record.get("sold_today_count"),
        record.get("revenue_today"),
        record.get("revenue_cumulative_tracked"),
        len(record.get("discounts_detected", [])),
        ", ".join(record.get("operators", [])),
    ]


def main():
    if not SERVICE_ACCOUNT_FILE.exists():
        print("Не найден service_account.json — см. инструкцию в шапке файла.")
        return
    if SPREADSHEET_ID == "ВСТАВЬ_СЮДА_ID_ТАБЛИЦЫ":
        print("Не указан SPREADSHEET_ID — вставь ID своей таблицы в начало файла.")
        return

    client = get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    processed_dir = BASE_DIR / "data" / "processed"
    for file in processed_dir.glob("*.json"):
        event_id = file.stem
        with open(file, "r", encoding="utf-8") as f:
            history = json.load(f)

        ws = ensure_sheet(spreadsheet, event_id)
        already_uploaded = len(ws.get_all_values()) - 1  # минус заголовок

        new_records = history[max(already_uploaded, 0):]
        if not new_records:
            continue

        rows = [row_from_record(event_id, r) for r in new_records]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f'[{event_id}] Выгружено {len(rows)} новых строк.')


if __name__ == "__main__":
    main()
