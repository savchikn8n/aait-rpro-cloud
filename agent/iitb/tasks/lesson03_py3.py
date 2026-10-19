# -*- coding: utf-8 -*-
"""
Урок 3 ИИТБ: «Создание процесса» поверх планировки урока 2.

В «Редакторе технологического процесса» две группы процессов (как в PDF урока):
  #1: С конвейера → К конвейеру                       (деталь идёт мимо станка)
  #2: С конвейера → Параметрический вертикально-фрезерный станок → К конвейеру
и транспортные связи с исполнителем «ТК робота» (шаг 3 урока: исполнитель — робот).
Устройство подачи выпускает деталь группы #2. Затем минутный прогон: деталь должна дойти
до второго конвейера.
"""

from __future__ import annotations

import time

import lesson02_py3 as l2
from line_builder import LineBuilder

G1, G2 = "Группа процессов #1", "Группа процессов #2"


def build_process(client) -> tuple:
    """Планировка урока 2 + процесс урока 3. Возвращает (LineBuilder, имена, итог построения)."""
    res = l2.build_layout(client)
    lb: LineBuilder = res.pop("lb")
    pick, place, mill, tc = res["pick"], res["place"], res["machine"], res["tc"]
    pid_pick, pid_mill, pid_place = '"С конвейера"', res["machine_pid"], '"К конвейеру"'
    # 1. регистрация деталей: два типа в двух группах (шаг 1 урока 3)
    info = lb.run(
        "fm = pc().FlowGroupManager\n"
        "ptm = pc().ProductTypeManager\n"
        "feeder = comp(%r)\n"
        "cr = beh(feeder, typ='rProductCreator')\n"
        "old_uri = cr.SingleFeed.Part.ComponentUri\n"
        "g1 = fm.createGroup(_b(%r))\n"
        "t1 = ptm.createProductType(_b(u'Заготовка А'), g1, False)\n"
        "t1.ComponentUri = old_uri\n"
        "r2 = new_line_group(feeder, %r, u'Заготовка Б', None)\n"
        "result = {'g1': g1.Name, 'g2': r2}" % (res["feeder"], G1, G2))
    # 2. технологический процесс: последовательности операций (шаг 2)
    r1 = lb.run("result = set_flow([%r, %r], %r)" % ("С конвейера", "К конвейеру", G1))
    r2 = lb.run("result = set_flow([%r, %r, %r], %r)" % ("С конвейера", res["machine_pid"], "К конвейеру", G2))
    # 3. транспортные связи с исполнителем «ТК робота» (шаг 3)
    lb.run("link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (pick, place, tc, G1))
    lb.run("link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (pick, mill, tc, G2))
    lb.run("link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (mill, place, tc, G2))
    lb._overview()
    out = {"группы": info, "маршрут_1": r1, "маршрут_2": r2, "компонентов": client.status()["component_count"]}
    return lb, res, out


def run(client) -> dict:
    lb, res, out = build_process(client)
    # 4. проверка: минутный прогон — деталь должна дойти до второго конвейера
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    lb.run("app.Simulation.SimSpeed = 10.0; result = 1")
    out["прогон"] = client.simulation("run_for", seconds=120.0).get("note")
    t0 = time.time()
    while time.time() - t0 < 60:
        st = client.simulation("status")
        if not st.get("running") and st.get("time_sec", 0) >= 100:
            break
        time.sleep(1.0)
    msgs = client.messages(tail=40).get("messages") or []
    out["ошибки"] = [m for m in msgs if "rror" in str(m) or "шибк" in str(m)][:5]
    out["статистика"] = lb.run("result = line_stats()")
    client.simulation("reset")  # файл сохраняется в исходном состоянии, на 0:00:00
    time.sleep(1.0)
    lb.run("app.Simulation.SimSpeed = 1.0; result = 1")
    return out
