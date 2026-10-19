# -*- coding: utf-8 -*-
"""
Урок 14 ИИТБ: «Создать процесс с выражениями «Ожидание сигнала»».

Станок без поведения (корпус + две створки) → звенья Link_1 (поступательное +X, 0…550) и Link_2
(поступательное ведомое −X, драйвер — первое звено), сервоконтроллер, исполнитель процесса, узел процесса,
булев сигнал DoorSignal → процесс «Двери станка»: WaitSignal(True) → MoveJoint(550, 2 с) → WaitSignal(False)
→ MoveJoint(0, 2 с). Результат: «Урок_14.rpro».

Проверка механики: сервоконтроллер ведёт J1 на 550 — ведомая створка идёт навстречу (−X). Станок строится на каталожном «Узле процесса» (иначе процесс не попадает в менеджер процессов) и стоит
между подачей и отгрузкой: процесс начинается с TransportIn. Проверка — сигнал DoorSignal переключается кодом.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def run(client) -> dict:
    import time
    import runner
    out = {"сцена": _py(client, (HERE / "lesson14_scene.py").read_text(encoding="utf-8"))}
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    client.simulation("run_for", seconds=120.0)
    val = ("c = [x for x in app.Components if x.Name == _b(u'Станок')][0]; sv = c.findBehaviour('ServoController'); "
           "result = [round(app.Simulation.SimTime, 1), round(sv.getJointValue(0), 1), round(c.findNode('Link_2').Dof.VALUE, 1)]")
    setsig = ("c = [x for x in app.Components if x.Name == _b(u'Станок')][0]; "
              "c.findBehaviour('DoorSignal').signal(%s); result = 1")   # у vcBoolSignal значение шлёт метод signal()
    log = []
    t0 = time.time()
    while time.time() - t0 < 60:           # изделие доезжает до станка, процесс встаёт на WaitSignal
        n = _py(client, "c = [x for x in app.Components if x.Name == _b(u'Станок')][0]; "
                        "result = len(list(c.findBehavioursByType(VC_COMPONENTCONTAINER)[0].Components))")
        if n:
            break
        time.sleep(0.5)
    time.sleep(2.0)
    log.append(["ждём сигнал"] + _py(client, val))
    _py(client, setsig % "True")
    for _ in range(6):
        time.sleep(0.5)
        log.append(["DoorSignal=True"] + _py(client, val))
    _py(client, setsig % "False")
    for _ in range(6):
        time.sleep(0.5)
        log.append(["DoorSignal=False"] + _py(client, val))
    out["двери_по_сигналу"] = log
    peak = max(r[2] for r in log)
    out["открылись_на_мм"] = peak
    out["вернулись_в_0"] = log[-1][2] <= 1.0
    client.simulation("reset")
    return out
