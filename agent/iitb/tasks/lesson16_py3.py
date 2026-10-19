# -*- coding: utf-8 -*-
"""
Урок 16 ИИТБ: «Создание процесса депаллетизации» (продолжение урока 15).

Конвейер 2 → «Узел процесса» с Detach (отсоединить все банки) → конвейер 3; банки уходят на приёмку,
пустой поддон — на конвейер 3. Исполнитель связей — человек (ТК человека + «Человек (Иван)»).
Результат: «Урок_16.rpro» и снимок.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "examples" / "iitb"


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def run(client) -> dict:
    code = (HERE / "lesson15_scene.py").read_text(encoding="utf-8") + "\n" + (HERE / "lesson16_ext.py").read_text(encoding="utf-8")
    out = {"сцена": _py(client, code)}
    import runner
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 20.0; result = 1")
    client.simulation("run_for", seconds=1500.0)
    shot_done = False
    t0 = time.time()
    while time.time() - t0 < 500:
        st = client.simulation("status")
        ts = float(st.get("time_sec", 0))
        if not shot_done and ts >= 900:
            try:
                sys.path.insert(0, str(HERE.parents[2] / "test_task" / "common"))
                import shots
                out["снимок_разгрузки"] = shots.shot(OUT / "shots" / "lesson16_mid.png").get("path")
            except Exception as e:
                out["снимок_разгрузки"] = "не вышел: " + str(e)[:80]
            shot_done = True
        if not st.get("running") and ts >= 1490:
            break
        time.sleep(1.0)
    out["статистика"] = _py(client, "result = line_stats()")
    out["сообщения"] = [m for m in (client.messages(tail=80).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "not found", "no path"))][:8]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
