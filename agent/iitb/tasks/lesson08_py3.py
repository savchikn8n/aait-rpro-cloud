# -*- coding: utf-8 -*-
"""
Урок 8 ИИТБ: «Подготовка ячейки к программированию».

Загрузить робота и элементы ячейки из библиотеки → подключить сигналы (SensorBooleanSignal →
вход робота 102, выход 105/106 → MotorSignal двигателей) → настроить TOOL_1 (центр чашки) и
BASE_1/BASE_2 (на конвейерах) → сохранить .rpro. Проверка: за 40 с симуляции банка доходит до
датчика и сигнал 102 становится истинным.
"""

from __future__ import annotations

import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def cell_code(extra_file: str = "lesson08_py27_run.py") -> str:
    return (HERE / "lesson08_cell.py").read_text(encoding="utf-8") + "\n" + (HERE / extra_file).read_text(encoding="utf-8")


def run(client) -> dict:
    out = {"ячейка": _py(client, cell_code())}
    import runner
    runner.overview(client)
    # проверка датчика: банка едет по конвейеру 1 и упирается в конец — датчик даёт сигнал 102
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 5.0; result = 1")
    client.simulation("run_for", seconds=40.0)
    seen = []
    t0 = time.time()
    while time.time() - t0 < 60:
        st = client.simulation("status")
        v = _py(client, "result = [str(beh(app.findComponent(u'Датчик конвейера'), 'SensorBooleanSignal').Value)]")
        seen.append(v[0])
        if not st.get("running") and st.get("time_sec", 0) >= 38:
            break
        time.sleep(1.0)
    out["сигнал_102_значения"] = sorted(set(seen))
    out["сообщения"] = [m for m in (client.messages(tail=40).get("lines") or []) if "rror" in str(m)][:5]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
