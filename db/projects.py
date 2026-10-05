"""
Проекты на годы (DATA_MODEL.md, 3.1; решение 04.10.2026).

Ваша пометка «гастроль / местное» привязана к проекту или артисту, а не к тексту названия:
  1. у проекта постоянный номер и несколько написаний (project_names: ключ названия → проект);
  2. над проектом — артист / коллектив: пометка артиста действует на все его программы;
  3. новое название, похожее на размеченный проект, — в очередь подсказок, а не молча «новый проект»;
  4. год и слова «юбилейный», «новый», «премьера», «турне», «рок-опера» ключ не меняют;
  5. одноимённые постановки репертуарных театров («Щелкунчик») — разные проекты, по площадке.
"""

from __future__ import annotations

import re
from collections import defaultdict

from competitors.curation import REPERTORY, THEATRE_FORMATS, _STOP as CURATION_STOP

# Слова, которые меняются от сезона к сезону, а проект — тот же (пункт 4)
SEASON_WORDS = {"юбилейный", "юбилейная", "юбилейное", "юбилейные", "новый", "новая", "новое", "новые", "премьера",
                "турне", "гастроли", "гастрольный", "весенний", "осенний", "зимний", "летний", "сезон"}
STOP = CURATION_STOP | SEASON_WORDS
YEAR = re.compile(r"\b(19|20)\d\d\b")
GENRE_PHRASES = re.compile(r"рок[- ]опер\w*|рок[- ]мюзикл\w*|муз\w* спектакл\w*|танцевальн\w* шоу|стенд[- ]?ап\w*", re.I)

# Начало названия, после которого — программа: «Артист. Программа», «Артист — …», «Артист: …», «Артист «Программа»»
ARTIST_SPLIT = re.compile(r"\.\s|\s[—–-]\s|:\s|\s[«\"]|\sс\s(?:новой\s)?(?:концертной\s)?программой", re.I)
NOT_ARTIST = re.compile(r"^(концерт|спектакль|балет|опера|мюзикл|шоу|стендап|лекция|вечер|фестиваль|праздник|ёлка|елка|"
                        r"новогодн|рождеств|сказка|встреча|выставка|мастер|экскурс|детск|музыкальн|симфони|сольный|"
                        r"большой|юбилейн|творческ|программа|абонемент|кино|квест)", re.I)
# Одно общее слово — не артист («Группа. …», «Цирк. …», «Филармония. …»)
GENERIC_HEADS = {"группа", "ансамбль", "цирк", "цирк-шапито", "филармония", "виа", "оркестр", "хор", "театр", "студия"}


def _norm(title: str) -> str:
    t = (title or "").lower().replace("ё", "е")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = GENRE_PHRASES.sub(" ", t)
    return YEAR.sub(" ", t)


def title_key(title: str) -> str:
    """Ключ названия: слова без служебных, сезонных и года, по алфавиту (развитие curation.project_key)."""
    words = sorted({w for w in re.split(r"[^a-zа-я0-9]+", _norm(title)) if len(w) >= 2 and w not in STOP})
    return " ".join(words) if any(len(w) >= 3 for w in words) else ""


def artist_part(title: str) -> str:
    """Начало названия, похожее на артиста / коллектив («Валентин Сидоров. Юбилейный тур» → «Валентин Сидоров»)."""
    t = (title or "").strip()
    m = ARTIST_SPLIT.search(t)
    if not m or m.start() < 3:
        return ""
    head = t[:m.start()].strip(" .,«»\"")
    words = head.split()
    if not 1 <= len(words) <= 4 or NOT_ARTIST.search(head) or head.lower() in GENERIC_HEADS:
        return ""
    return head


def artist_key(name: str) -> str:
    return title_key(name)


def words(key: str) -> set:
    return set(key.split())


def similar(a: str, b: str) -> float:
    """Похожесть ключей: доля общих слов (Жаккар); 0, если общих слов меньше двух."""
    wa, wb = words(a), words(b)
    common = len(wa & wb)
    return common / len(wa | wb) if common >= 2 else 0.0


def homonym_keys(rows: list[dict], venue_kind) -> set:
    """
    Пункт 5: ключи, у которых все мероприятия — спектакли в репертуарных театрах на разных сценах
    («Щелкунчик», «Ревизор»): это разные постановки, проект — по площадке.
    venue_kind(row) -> 'repertory' | 'rental' | 'mixed' | None.
    """
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("_key"):
            by_key[r["_key"]].append(r)
    out = set()
    for k, rs in by_key.items():
        venues = {(r["city"], r["venue"]) for r in rs}
        if len(venues) < 2:
            continue
        theatre = all((r.get("format") in THEATRE_FORMATS) for r in rs)
        repertory = all(venue_kind(r) == "repertory" or (venue_kind(r) is None and REPERTORY.search(r["venue"] or "")) for r in rs)
        if theatre and repertory:
            out.add(k)
    return out


class Registry:
    """
    Проекты и артисты в памяти для пакетной работы (перенос, ежедневный сбор); запись в базу — db.migrate.
    projects: id → {title, artist, mark, mark_at, scope, names: set[(key, scope)], format, sphere, genre}
    """

    def __init__(self):
        self.projects: dict[int, dict] = {}
        self.names: dict[tuple, int] = {}          # (ключ, scope) → проект
        self.artists: dict[str, dict] = {}        # ключ артиста → {name, mark, mark_at, projects: set}
        self._next = 1

    def add_project(self, title: str, key: str, scope: str = "", source: str = "auto", pid: int | None = None, **extra) -> int:
        """pid — номер проекта в базе (пополнение базы: db.sync); без него — следующий свободный (перенос с нуля)."""
        if pid is None:
            pid = self._next
        self._next = max(self._next, pid + 1)
        self.projects[pid] = {"title": title, "artist": None, "mark": None, "mark_at": None, "scope": scope,
                              "names": {}, **extra}
        self.add_name(pid, key, scope, title, source)
        return pid

    def add_name(self, pid: int, key: str, scope: str, example: str, source: str) -> None:
        if not key or (key, scope) in self.names:
            return
        self.names[(key, scope)] = pid
        self.projects[pid]["names"][(key, scope)] = (example, source)

    def find(self, key: str, scope: str = "", legacy: str = "") -> int | None:
        return self.names.get((key, scope)) or (self.names.get((legacy, "")) if legacy else None)

    def link_artists(self) -> int:
        """
        Пункт 2: артист — начало названия, если у него 2+ проекта или есть проект с его чистым именем
        («Валентин Сидоров» и «Валентин Сидоров. Юбилейный тур «50»»). Возвращает число артистов.
        """
        by_artist: dict[str, list[int]] = defaultdict(list)
        names: dict[str, str] = {}
        for pid, p in self.projects.items():
            head = artist_part(p["title"])
            if head:
                ak = artist_key(head)
                if ak:
                    by_artist[ak].append(pid)
                    names.setdefault(ak, head)
        whole = {k[0]: pid for k, pid in self.names.items() if k[1] == ""}
        for ak, pids in by_artist.items():
            own = whole.get(ak)
            if own and own not in pids:
                pids.append(own)
            if len(set(pids)) < 2:
                continue
            a = self.artists.setdefault(ak, {"name": names[ak], "mark": None, "mark_at": None, "projects": set()})
            for pid in pids:
                a["projects"].add(pid)
                self.projects[pid]["artist"] = ak
        return len(self.artists)

    def suggestions(self, min_score: float = 0.6) -> list[dict]:
        """
        Пункт 3: неразмеченные проекты, похожие на размеченные — «тот же артист» или «почти тот же ключ».
        """
        marked = [(pid, p) for pid, p in self.projects.items() if p["mark"]]
        out = []
        for pid, p in self.projects.items():
            if p["mark"] or (p["artist"] and self.artists[p["artist"]]["mark"]):
                continue
            best = None
            for mid, m in marked:
                if p["scope"] != m["scope"]:
                    continue
                if p["artist"] and p["artist"] == m["artist"]:
                    best = max(best or (0, None, ""), (0.95, mid, "тот же артист: " + self.artists[p["artist"]]["name"]))
                    continue
                for (k, _s) in p["names"]:
                    for (mk, _ms) in m["names"]:
                        sc = similar(k, mk)
                        if sc >= min_score:
                            best = max(best or (0, None, ""), (round(sc, 2), mid, "почти то же название"))
            if best and best[1]:
                key = next(iter(p["names"]))[0]
                out.append({"key": key, "title": p["title"], "project_id": best[1], "reason": best[2], "score": best[0],
                            "for_project": pid})
        return out

    def mark_of(self, pid: int) -> tuple[str | None, str]:
        """Пометка проекта → пометка артиста; ('tour'|'local'|None, источник)."""
        p = self.projects[pid]
        if p["mark"]:
            return p["mark"], "project"
        if p["artist"] and self.artists[p["artist"]]["mark"]:
            return self.artists[p["artist"]]["mark"], "artist"
        return None, ""
