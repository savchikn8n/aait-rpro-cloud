# -*- coding: utf-8 -*-
"""
Урок 15 ИИТБ: «Создание процесса паллетирования».

Устройство подачи → конвейер → «Узел процесса» (паллетирование) ← «Процесс подачи» (банки) →
конвейер → выход. Узел: TransportIn поддона, TransportPatternIn (шаблон 6×4, смещение по высоте
поддона 144 мм), Attach банок к поддону, TransportOut. Проверка прогоном; результат — «Урок_15.rpro».
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
    out = {"сцена": _py(client, (HERE / "lesson15_scene.py").read_text(encoding="utf-8"))}
    import runner
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 20.0; result = 1")
    client.simulation("run_for", seconds=900.0)
    # снимок заполненного поддона: через ~200 с после его прихода (поддон в узле, банки уложены)
    while client.simulation("status").get("time_sec", 0) < 620:
        time.sleep(0.5)
    try:
        sys.path.insert(0, str(HERE.parents[2] / "test_task" / "common"))
        import shots
        out["снимок_поддона"] = shots.shot(HERE.parents[2] / "examples" / "iitb" / "shots" / "lesson15_full.png").get("path")
    except Exception as e:
        out["снимок_поддона"] = "не вышел: " + str(e)[:80]
    t0 = time.time()
    while time.time() - t0 < 400:
        st = client.simulation("status")
        if not st.get("running") and st.get("time_sec", 0) >= 890:
            break
        time.sleep(1.0)
    out["статистика"] = _py(client, "result = line_stats()")
    out["сообщения"] = [m for m in (client.messages(tail=80).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "not found", "no path"))][:8]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
