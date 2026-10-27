"""Проверка справочника площадок без pytest: python3 tests/check_venuebook_server.py
Новая площадка с сайта (op "add", 27.10) и повторная загрузка таблицы — на временной папке."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import competitors.venuebook as vb  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp()) / "venue_book.json"
tmp.write_text(json.dumps({"rows": [{"id": "v1", "city": "Пенза", "name": "ККЗ Пенза"},
                                    {"id": "v7", "city": "Пенза", "name": "ДК"}]}, ensure_ascii=False))
vb.FILE = tmp

r = vb.apply_op({"op": "add", "data": {"city": "Пенза", "name": "Буртасы", "seats": "2500", "stage": "12 × 8 м"}})
assert (r["id"], r["seats"], r["stage"], r["added"], r["phone"]) == ("v8", "2500", "12 × 8 м", True, ""), r
for bad in ({"city": "пенза", "name": "ККЗ  «Пенза»"},   # та же пара город + название
            {"city": "Пенза", "name": ""}, {"city": "", "name": "X"}, {"city": "Пенза", "name": "X", "zzz": "1"}, "x"):
    try:
        vb.apply_op({"op": "add", "data": bad})
    except vb.VenueBookError:
        continue
    raise AssertionError(f"не отсечено: {bad}")
assert vb.apply_op({"op": "set", "id": "v8", "data": {"rent": "100 тыс."}})["rent"] == "100 тыс."

# повторная загрузка таблицы: добавленная на сайте остаётся, новая строка таблицы получает следующий номер
vb.read_xlsx = lambda p: ([list(vb.HEAD), ["Пенза", "ККЗ Пенза"], ["Пенза", "Новая"]], {})
rows = vb.import_xlsx(pathlib.Path("x.xlsx"))["rows"]
assert [(x["id"], x["name"]) for x in rows] == [("v1", "ККЗ Пенза"), ("v9", "Новая"), ("v8", "Буртасы")], rows
assert rows[2]["rent"] == "100 тыс."
print("ok")
