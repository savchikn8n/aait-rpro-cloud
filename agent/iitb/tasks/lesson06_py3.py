# -*- coding: utf-8 -*-
"""
Урок 6 ИИТБ: «Создание листа статистики».

Планировка и процесс — из уроков 2–3 («загрузим планировку, которую вы создавали ранее»).
Область «Статистика» → шаблон листа 2×2 → четыре графика (круговая диаграмма состояний станка,
линия выпуска, столбцы загрузки, среднее число деталей) → час симуляции на высокой скорости →
выгрузка данных в CSV и лист в PDF (matplotlib по тем же данным, что в графиках).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import lesson03_py3 as l3

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "examples" / "iitb"
RUN_S = 3600.0
SPEED = 100.0


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def run(client) -> dict:
    lb, res, out = l3.build_process(client)
    out["лист"] = _py(client, (HERE / "lesson06_stats.py").read_text(encoding="utf-8"))
    # час симуляции на высокой скорости (в уроке — «время выполнения 1 час», скорость побольше)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = %f; result = 1" % SPEED)
    t0 = time.time()
    client.simulation("run_for", seconds=RUN_S)
    last = 0.0
    while time.time() - t0 < 900:
        st = client.simulation("status")
        last = float(st.get("time_sec", 0))
        if not st.get("running") and last >= RUN_S - 1:
            break
        time.sleep(2.0)
    out["прогон_с"] = round(last, 1)
    out["прогон_реально_с"] = round(time.time() - t0)
    # данные графиков
    data = _py(client, "\n".join([
        "tab = app.Dashboard.SelectedTab",
        "r = []",
        "for ch in tab.Charts:",
        "    try:",
        "        rows = [list(x) for x in ch.DataRows]",
        "        src = [[_u(str(s.SeriesName)) if s.SeriesName else _u(str(s.Name))] for s in ch.Series]",
        "        r.append({'name': _u(ch.Name), 'type': str(ch.ChartType), 'series': [_u(str(s.Name)) for s in ch.Series], 'rows': rows})",
        "    except Exception as e:",
        "        r.append({'error': str(e)[:80]})",
        "result = r",
    ]))
    out["графики"] = [{"название": d.get("name"), "строк": len(d.get("rows", [])), "серии": d.get("series"),
                       "последняя": (d.get("rows") or [None])[-1]} for d in data]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "Урок_6_данные.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "Урок_6_статистика.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        for d in data:
            w.writerow([d.get("name"), *(d.get("series") or [])])
            for row in d.get("rows", []):
                w.writerow(row)
            w.writerow([])
    out["csv"] = str(OUT / "Урок_6_статистика.csv")
    try:
        import stats_pdf
        out["pdf"] = stats_pdf.make(data, OUT / "Урок_6_статистика.pdf")
    except Exception as e:
        out["pdf"] = "не вышло: " + str(e)[:120]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    lb._overview()
    return out
