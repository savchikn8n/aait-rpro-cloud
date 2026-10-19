# -*- coding: utf-8 -*-
"""
Урок 13 ИИТБ: «Создать собственный детектор столкновений».

Ячейка и программа робота — из уроков 8–9. Свой детектор: группа A — тумба с роботом и захватом (они её дочерние компоненты), группа B — всё,
с чем они могут столкнуться (конвейеры, двигатели, датчик). Режимы сравниваются на живой
симуляции (скорость ×5, опрос детектора каждые 0,2 с): допуск 0 и 250 мм, «первое»/«все»; итоговые
настройки: допуск 10 мм, показывать минимальное расстояние, детектор активен. Результат: «Урок_13.rpro».
"""

from __future__ import annotations

import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

SETUP = '''
sim = app.Simulation
I, T, C = VC_NODELIST_INCLUDE, VC_NODELIST_TREE, VC_NODELIST_COMPONENT
det = sim.newCollisionDetector()
det.NodeListA = [(ped, I, T)]                                      # тумба с роботом и захватом (они её дочерние компоненты)
det.NodeListB = [(c1, I, T), (c2, I, T), (m1, I, T), (m2, I, T), (s1, I, T)]   # всё вокруг (тумбу не берём: робот на ней стоит, касание штатное)
info["группа_A"] = [str(x[0].Name) for x in det.NodeListA]
info["группа_B"] = [str(x[0].Name) for x in det.NodeListB]
det.Active = True
import __builtin__
__builtin__.RPRO_DET = det      # объект детектора живёт, пока на него есть ссылка
__builtin__.RPRO_CELL = dict(ped=ped, grip=grip, c1=c1, c2=c2, m1=m1, m2=m2, s1=s1)
result = info
'''

POLL = '''
import __builtin__
det = __builtin__.RPRO_DET
det.Tolerance = %(tol)f
hit = det.testOneCollision() if %(first)s else det.testAllCollisions()
r = {"hit": bool(hit), "n": det.HitCount, "t": round(app.Simulation.SimTime, 1), "pairs": []}
if hit:
    for i in range(det.HitCount):
        r["pairs"].append("%%s x %%s" %% (det.getHitNodeA(i).Name, det.getHitNodeB(i).Name))
result = r
'''


OBSTACLE = '''
import __builtin__
det = __builtin__.RPRO_DET
grip, c1, c2, m1, m2, s1 = [__builtin__.RPRO_CELL[k] for k in ('grip', 'c1', 'c2', 'm1', 'm2', 's1')]
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
ob = load(RD2 + "Products and Containers/EuroPallet_2.rpro")
ob.Name = _b(u"Препятствие")
g = _world_box(grip)
place(ob, (g[0] + g[3]) / 2.0, (g[1] + g[4]) / 2.0, (g[2] + g[5]) / 2.0 - 72.0)
I, T = VC_NODELIST_INCLUDE, VC_NODELIST_TREE
det.NodeListB = [(c1, I, T), (c2, I, T), (m1, I, T), (m2, I, T), (s1, I, T), (ob, I, T)]
det.Tolerance = 0.0
hit = det.testAllCollisions()
r = {"касаний": det.HitCount, "найдено": bool(hit), "пары": []}
for i in range(det.HitCount):
    r["пары"].append("%s x %s" % (det.getHitNodeA(i).Name, det.getHitNodeB(i).Name))
app.deleteComponent(ob)
det.NodeListB = [(c1, I, T), (c2, I, T), (m1, I, T), (m2, I, T), (s1, I, T)]
result = r
'''


def run(client) -> dict:
    import runner
    py = lambda code: runner.exec_in_rpro(client, code)  # noqa: E731
    cell = "\n".join([
        (HERE / "lesson08_cell.py").read_text(encoding="utf-8"),
        (HERE / "lesson09_prog.py").read_text(encoding="utf-8").replace("result = {", "_r9 = {", 1),
        SETUP,
    ])
    out = {"детектор": py(cell)}
    runner.overview(client)
    results = []
    for tol, first in ((0.0, True), (250.0, True), (250.0, False)):
        client.simulation("reset")
        time.sleep(1.0)
        py("app.Simulation.SimSpeed = 5.0; result = 1")
        client.simulation("run_for", seconds=60.0)
        most, pairs, t0 = 0, set(), time.time()
        while time.time() - t0 < 60:
            r = py(POLL % {"tol": tol, "first": str(first)})
            most = max(most, r["n"] if r["hit"] else 0)
            pairs.update(r["pairs"])
            if r["t"] >= 58:
                break
            time.sleep(0.2)
        results.append({"допуск_мм": tol, "первое": first, "макс_касаний": most, "пары": sorted(pairs)[:6]})
    out["сравнение_режимов"] = results
    # контрольный случай: препятствие (поддон) на пути захвата — детектор обязан его найти
    client.simulation("reset")
    time.sleep(1.0)
    out["препятствие"] = py(OBSTACLE)
    # итоговые настройки детектора, как в уроке
    client.simulation("reset")
    out["итог"] = py('''
import __builtin__
det = __builtin__.RPRO_DET
det.Tolerance = 10.0
det.DisplayMinimumDistance = True
det.Active = True
app.Simulation.SimSpeed = 1.0
app.Simulation.setInitialState()
result = {"допуск": det.Tolerance, "показывать_расстояние": det.DisplayMinimumDistance, "активен": det.Active,
          "примечание": "«Первое/все» и «остановка при столкновении» в R-Pro 2.2.2 задаются галочками окна детектора: у объекта API этих свойств нет"}
''')
    return out
