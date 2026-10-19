# -*- coding: utf-8 -*-
"""
Урок 12 ИИТБ: «Создание склада» (автоматизированная система хранения).

ТК крана-штабелера (путь), кран-штабелер на нём (PnP), складская полка с оператором Buffer, узел
«Создание поддонов» → буфер полки → узел отгрузки; исполнитель связей — кран. Прогон 15 мин на ×20;
снимок склада в работе. Результат: «Урок_12.rpro».
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def run(client) -> dict:
    out = {"сцена": _py(client, (HERE / "lesson12_scene.py").read_text(encoding="utf-8"))}
    import runner
    runner.NO_OVERVIEW.add(12)   # склад высокий: камера задана вручную
    cam = 'camera([2300.0, 0.0, 2500.0], [2300.0, -16000.0, 9500.0]); result = 1'
    _py(client, cam)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 20.0; result = 1")
    client.simulation("run_for", seconds=900.0)
    shot = False
    t0 = time.time()
    while time.time() - t0 < 300:
        st = client.simulation("status")
        ts = float(st.get("time_sec", 0))
        if not shot and ts >= 400:
            try:
                sys.path.insert(0, str(HERE.parents[2] / "test_task" / "common"))
                import shots
                out["снимок_склада"] = shots.shot(HERE.parents[2] / "examples" / "iitb" / "shots" / "lesson12_mid.png").get("path")
            except Exception as e:
                out["снимок_склада"] = "не вышел: " + str(e)[:80]
            shot = True
        if not st.get("running") and ts >= 890:
            break
        time.sleep(1.0)
    out["статистика"] = _py(client, "result = line_stats()")
    out["сообщения"] = [m for m in (client.messages(tail=80).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "not found", "no path", "unable"))][:8]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    _py(client, cam)
    return out
