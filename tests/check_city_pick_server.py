"""Проверка серверной части «Подбора городов» без pytest: python3 tests/check_city_pick_server.py
Связь списка с «Работой» (competitors/planning.py) и сводка ссылок для руководителя (competitors/shares.py) — на временной папке."""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import competitors.shares as sh  # noqa: E402
from competitors.planning import PlanningError, _validate  # noqa: E402

assert _validate("lists", {"title": "t", "work": {"project": "pmvfgss1kp7x6", "task": ""}})["work"] == {"project": "pmvfgss1kp7x6"}
for bad in ({"project": "Bad Id!"}, {"foo": "abc"}, "x"):
    try:
        _validate("lists", {"title": "t", "work": bad})
    except PlanningError:
        continue
    raise AssertionError(f"не отсечено: {bad}")

tmp = pathlib.Path(tempfile.mkdtemp())
sh.DIR, sh.SETTINGS = tmp, tmp / "_settings.json"
snap = {"who": "A", "rows": [{"city": "Тула"}, {"city": "Орёл"}]}
a = sh.create("l1", snap)
sh.add_comment(a["token"], "Тула", "Иван", "", "ok")
sh.add_comment(a["token"], "Тула", "Иван", "", "ask")   # последнее решение по Туле — «вопрос»
sh.add_comment(a["token"], "Орёл", "Иван", "нет", "no")
sh.create("l1", snap)
sh.close(a["token"])
s = sh.summary()["l1"]
assert (s["versions"], s["open"], s["comments"], s["ok"], s["ask"], s["no"]) == (2, True, 3, 0, 1, 1), s
assert len(s["tokens"]) == 2
print("ok")
