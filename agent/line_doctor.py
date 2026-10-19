# -*- coding: utf-8 -*-
"""
Доктор линии: находит неисправные станции и чинит их ПРАВКОЙ, а не пересборкой.

Линия, собранная за минуту, стоит дороже одной ошибки. Если робот не
достаёт до станка — станок двигают ближе; если модель станка не подходит —
меняют модель на этой станции. Остальная линия, маршрут и связи остаются
как были.

Структура линии берётся из самой программы (hands27.line_stations): маршрут
деталей и транспортные связи. Поэтому доктор лечит и линию, сохранённую
раньше, и собранную руками — лишь бы станции были устроены как у
line_builder: «Съём N» → станок → «Укладка N».
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from rpro_client import RProClient

_HANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hands27.py")

# IRB 4600-60/2.05: досягаемость 2050 мм от плеча. Рабочие станции на живой
# линии давали 1193–1665 мм; станки, до которых робот не дотягивался
# (Colchester 3000L, лазерная резка), — больше. Цель правки — с запасом.
REACH_WARN = 1850
REACH_TARGET = 1700
MAX_SHIFT = 450          # ближе к роботу не двигаем: станок упрётся в его основание


class LineDoctor:
    def __init__(self, client: RProClient | None = None):
        self.client = client or RProClient()
        with open(_HANDS, encoding="utf-8") as f:
            self.lib = f.read()

    def run(self, code: str) -> Any:
        r = self.client.exec_python(self.lib + "\n" + code)
        return r.get("result")

    # --- диагноз -------------------------------------------------------------

    def check(self) -> dict:
        stations = self.run("result = line_stations()") or []
        by_robot = {s["robot"]: s for s in stations if s.get("robot")}
        by_pid = {}
        for s in stations:
            for key in ("machine_pid",):
                if s.get(key):
                    by_pid[s[key]] = s
            by_pid["Съём " + s["n"]] = s
        problems: list[dict] = []

        for s in stations:
            for target, d in (s.get("reach_mm") or {}).items():
                if d > REACH_WARN:
                    problems.append({"станция": s["n"], "что": "робот не достаёт",
                                     "куда": {"machine": "станок", "pick": "съём", "place": "укладка"}[target],
                                     "расстояние_мм": d, "станок": s.get("machine"),
                                     "исправление": "ближе" if target == "machine" else "вручную"})

        # Ошибки прогона из панели вывода: «IRB …#8::…: вне досягаемости»,
        # «…::<процесс>::Транспорт Из ошибка: …LostFlow»
        seen = set()
        for line in self.client.messages(tail=400).get("lines", []):
            low = line.lower()
            if "ошибка" not in low and "error" not in low and "вне досяг" not in low:
                continue
            head = line.split("::")[0]
            st = by_robot.get(head)
            if st is None:
                for pid, cand in by_pid.items():
                    if "::" + pid + "::" in line:
                        st = cand
                        break
            key = (st["n"] if st else None, re.sub(r"P\d+", "", line[-80:]))
            if key in seen:
                continue
            seen.add(key)
            problems.append({"станция": st["n"] if st else None, "что": "ошибка при прогоне",
                             "текст": line[:200],
                             "исправление": "ближе" if "досяг" in low and st and st.get("machine") else "смотреть"})
        return {"станций": len(stations), "проблем": len(problems), "проблемы": problems,
                "станции": [{"n": s["n"], "станок": s.get("machine"), "робот": s.get("robot"),
                             "досягаемость_мм": s.get("reach_mm")} for s in stations]}

    # --- правки --------------------------------------------------------------

    def _prepare(self) -> None:
        """Правим только исходную сцену: иначе сброс откатит правку."""
        st = self.client.simulation("status")
        if st.get("running") or st.get("time_sec", 0) > 0:
            self.client.simulation("reset")
            time.sleep(1.2)

    def _station(self, n: str) -> dict:
        for s in self.run("result = line_stations()") or []:
            if s["n"] == str(n):
                return s
        raise ValueError(f"нет станции {n}")

    def closer(self, n: str, mm: float | None = None) -> dict:
        """Подвинуть станок станции n к роботу. Без mm — ровно настолько,
        чтобы расстояние стало REACH_TARGET."""
        self._prepare()
        s = self._station(n)
        if not s.get("machine"):
            raise ValueError(f"на станции {n} нет станка")
        d = (s.get("reach_mm") or {}).get("machine")
        if mm is None:
            mm = max(0.0, (d or REACH_TARGET) - REACH_TARGET + 50)
        mm = min(float(mm), MAX_SHIFT)
        at = self.run("result = move_machine(%r, %r, %f)" % (s["machine"], s["tc"], mm))
        time.sleep(0.5)  # мировые матрицы обновятся со следующим кадром
        after = (self._station(n).get("reach_mm") or {}).get("machine")
        return {"станция": n, "станок": s["machine"], "сдвинут_на_мм": round(mm),
                "было_мм": d, "стало_мм": after, "позиция": at,
                "достаёт": after is not None and after <= REACH_WARN}

    def replace(self, n: str, model: str = "") -> dict:
        """Заменить станок станции n. model — название из MACHINES или вид
        («токарный»); пусто — следующая модель того же вида."""
        import line_builder as lb
        self._prepare()
        s = self._station(n)
        if not s.get("machine"):
            raise ValueError(f"на станции {n} нет станка")
        # «Л2 Haas VF-1 5» → «Haas VF-1»
        current = re.sub(r"^Л\d+ ", "", s["machine_pid"]).rsplit(" ", 1)[0]
        choice = None
        for kind, pool in lb.MACHINES.items():
            titles = [t for t, _ in pool]
            if model and (model.lower() in kind or any(model.lower() in t.lower() for t in titles)):
                pool_ok = [p for p in pool if model.lower() in p[0].lower()] or pool
                choice = next((p for p in pool_ok if p[0] != current), pool_ok[0])
                break
            if not model and current in titles:
                i = titles.index(current)
                choice = pool[(i + 1) % len(pool)]
                break
        if choice is None:
            raise ValueError(f"не знаю станка «{model or current}»")
        title, uri = choice
        res = self.run("result = replace_machine(%r, %r, %r)" % (s, uri, title))
        time.sleep(0.5)
        after = (self._station(n).get("reach_mm") or {}).get("machine")
        return {"станция": n, "было": s["machine"], "стало": res["machine"],
                "процесс": res["pid"], "досягаемость_мм": after}

    def robot(self, n: str, model: str = "") -> dict:
        """Сменить робота станции: «kuka», «fanuc», «yaskawa», «abb»."""
        import line_builder as lb
        self._prepare()
        s = self._station(n)
        key = (model or "").lower()
        choice = next(((t, u) for t, u in lb.ROBOTS if key and (key in t.lower())), None)
        if choice is None:
            raise ValueError(f"не знаю робота «{model}»: " + ", ".join(t for t, _ in lb.ROBOTS))
        res = self.run("result = swap_robot(%r, %r)" % (s["tc"], choice[1]))
        time.sleep(0.5)
        after = self._station(n).get("reach_mm")
        return {"станция": n, "было": s.get("robot"), "стало": res["robot"],
                "посажен": res["mounted"], "досягаемость_мм": after}

    def process_time(self, n: str, seconds: float) -> dict:
        self._prepare()
        s = self._station(n)
        v = self.run("p = comp(%r).getProperty('ProcessTime')\n"
                     "p.Value = %f\nresult = p.Value" % (s["machine"], float(seconds)))
        return {"станция": n, "станок": s["machine"], "время_обработки_с": v}

    def auto_fix(self) -> dict:
        """Всё, что лечится само: недостающая досягаемость — сдвигом, а если
        сдвига не хватает — заменой модели на этой станции."""
        report = self.check()
        done = []
        for p in report["проблемы"]:
            if p.get("исправление") != "ближе" or not p.get("станция"):
                continue
            if any(d.get("станция") == p["станция"] for d in done):
                continue
            # Ошибка прогона при расстоянии «в норме» (точка чуть выше или
            # сбоку) — всё равно придвигаем, на 250 мм.
            mm = 250.0 if p.get("что") == "ошибка при прогоне" else None
            r = self.closer(p["станция"], mm)
            if not r["достаёт"]:
                r = {"сдвиг": r, "замена": self.replace(p["станция"])}
            done.append({"станция": p["станция"], **r})
        if done:
            # Ошибки в выводе описывают линию до правки — иначе следующая
            # проверка «лечила» бы уже здоровые станции.
            self.client.messages(clear=True)
        after = self.check()["проблемы"]
        return {"исправлено": done, "проверка_после": after,
                "примечание": "запусти симуляцию, чтобы убедиться в работе" if done else ""}


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    doc = LineDoctor()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    args = sys.argv[2:]
    out = {"check": doc.check, "fix": doc.auto_fix}.get(cmd)
    if out:
        print(json.dumps(out(), ensure_ascii=False, indent=1))
    elif cmd == "closer":
        print(json.dumps(doc.closer(*args), ensure_ascii=False, indent=1))
    elif cmd == "replace":
        print(json.dumps(doc.replace(*args), ensure_ascii=False, indent=1))
