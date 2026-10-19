# -*- coding: utf-8 -*-
"""
Урок 7 ИИТБ: «Создание процесса» с людьми (ручные операции).

Компоненты из PDF: Зона прохода, Вилочная тележка (инструмент), Человек, Процесс подачи, Процесс
утилизации, ТК человека (+ две ручные рабочие станции и места ожидания). Люди подключены к ТК
через «Интерфейсы» (Resources / Pathways / Idle / Tools), зоны прохода образуют коридоры,
у транспортной связи задан инструмент ToolName. Результат: «Урок_7.rpro» и видео «Урок_7.mp4».
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
    out = {}
    out["сцена"] = _py(client, (HERE / "lesson07_scene.py").read_text(encoding="utf-8"))
    import runner
    runner.overview(client)
    client.messages(clear=True)
    # проверка: 3 мин симуляции — детали должны дойти до утилизации, ошибок «нет пути» быть не должно
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 20.0; result = 1")
    client.simulation("run_for", seconds=240.0)
    t0 = time.time()
    while time.time() - t0 < 120:
        st = client.simulation("status")
        if not st.get("running") and st.get("time_sec", 0) >= 200:
            break
        time.sleep(1.0)
    out["статистика"] = _py(client, "result = line_stats()")
    msgs = client.messages(tail=60).get("lines") or []
    out["сообщения"] = [m for m in msgs if any(k in str(m).lower() for k in ("error", "ошиб", "not found", "no path"))][:8]
    client.simulation("reset")
    OUT.mkdir(parents=True, exist_ok=True)
    out["видео"] = video.record(client, OUT / "Урок_7.mp4", seconds=120.0, speed=10.0)
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
