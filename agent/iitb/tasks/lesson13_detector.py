# Python 2.7 внутри R-Pro. Урок 13: детектор столкновений — выполняется после lesson08_cell.py + lesson09_prog.py
# (ячейка с роботом и готовой программой). Создаёт свой детектор, сравнивает режимы, оставляет итоговые настройки.
sim = app.Simulation
SET_OK = {}


def _set(o, name, v):
    try:
        setattr(o, name, v)
        SET_OK[name] = True
    except Exception:
        SET_OK[name] = False   # в R-Pro 2.2.2 у детектора этого свойства нет (в окне — галочка «Остановка при столкновении»)


I, T, C = VC_NODELIST_INCLUDE, VC_NODELIST_TREE, VC_NODELIST_COMPONENT

# --- «добавить свой детектор» и две группы компонентов ---------------------------------------
det = sim.newCollisionDetector()
# группа A: всё, что связано с роботом — сам робот (всё дерево) и захват
det.NodeListA = [(rob, I, T), (grip, I, T)]
# группа B: всё, с чем робот может столкнуться в рабочей зоне — подставка, оба конвейера, двигатели, датчик
det.NodeListB = [(ped, I, C), (c1, I, C), (c2, I, C), (m1, I, C), (m2, I, C), (s1, I, C)]
info["группа_A"] = [str(x[0].Name) for x in det.NodeListA]
info["группа_B"] = [str(x[0].Name) for x in det.NodeListB]


def sweep(tol, first, stop_t=45.0):
    """Прогон программы шагами 0,05 с; возвращает макс. число касаний и пары узлов."""
    det.Active = True
    det.Tolerance = float(tol)
    _set(det, 'FirstCollision', bool(first))
    _set(det, 'StopOnCollision', False)
    sim.reset()
    t = 0.0
    most = 0
    pairs = {}
    zs = []
    fl = beh(rob, typ='rRobotExecutor').Controller.FlangeNode
    while t < stop_t:
        t += 0.05
        sim.run(t)
        zs.append(fl.WorldPositionMatrix.P.Z)
        if (det.testOneCollision() if first else det.testAllCollisions()):
            most = max(most, det.HitCount)
            for i in range(det.HitCount):
                k = "%s x %s" % (det.getHitNodeA(i).Name, det.getHitNodeB(i).Name)
                pairs[k] = pairs.get(k, 0) + 1
    info['ход_фланца_z_мм_%d_%s' % (tol, first)] = [round(min(zs)), round(max(zs)), round(sim.SimTime, 1)]
    return most, pairs


res = []
# допуск = 0: касания по-настоящему; допуск 250 мм: предупреждение «ещё до касания»
for tol, first in ((0.0, True), (250.0, True), (250.0, False)):
    most, pairs = sweep(tol, first)
    res.append({"допуск_мм": tol, "первое": first, "макс_касаний": most,
                "пары": sorted(pairs.keys())[:6]})
info["сравнение_режимов"] = res
# итоговые настройки детектора (как в уроке): допуск 10 мм, показывать мин. расстояние, остановка при столкновении
det.Tolerance = 10.0
_set(det, 'FirstCollision', False)
det.DisplayMinimumDistance = True
_set(det, 'StopOnCollision', True)
det.Active = True
sim.reset()
app.Simulation.setInitialState()
info["детектор"] = {"допуск": det.Tolerance, "показывать_расстояние": det.DisplayMinimumDistance,
                    "активен": det.Active, "первое/остановка_заданы": SET_OK}
result = info
