# -*- coding: utf-8 -*-
"""
Урок 9 ИИТБ: «Перемещение продукции» — программа робота.

Ячейка урока 8 + программа: остановка продукта по датчику (сигналы 102/105), взятие банки
(PTP над банкой → LIN вниз → сигнал 1 → LIN вверх), 4 подпрограммы укладки партии 2×2 на конвейер 2,
отправка партии (сигнал 106), всё в цикле While. Результат: «Урок_9.rpro» и видео «Урок_9.mp4».
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "examples" / "iitb"
sys.path.insert(0, str(HERE.parent))
import video  # noqa: E402


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def run(client) -> dict:
    code = (HERE / "lesson08_cell.py").read_text(encoding="utf-8") + "\n" + (HERE / "lesson09_prog.py").read_text(encoding="utf-8")
    out = {"программа": _py(client, code)}
    import runner
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 5.0; result = 1")
    client.simulation("run_for", seconds=90.0)
    t0 = time.time()
    while time.time() - t0 < 120:
        st = client.simulation("status")
        if not st.get("running") and st.get("time_sec", 0) >= 85:
            break
        time.sleep(1.0)
    out["сообщения"] = [m for m in (client.messages(tail=80).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "unreach", "cannot", "singular", "limit"))][:10]
    out["деталей_на_конвейере_2"] = _py(client, "result = len([c for c in app.Components if c.Name.startswith(u'Банка')])")
    client.simulation("reset")
    OUT.mkdir(parents=True, exist_ok=True)
    out["видео"] = video.record(client, OUT / "Урок_9.mp4", seconds=60.0, speed=5.0)
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
