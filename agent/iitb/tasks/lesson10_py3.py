# -*- coding: utf-8 -*-
"""
Урок 10 ИИТБ: «Создание позиционера».

Компонент «Позиционер» создаётся целиком из кода: геометрия (плита + две направляющие), звено «Каретка»
с поступательным движением J1 (0…1500 − длина каретки), свойство-параметр CarriageLength (длина каретки
управляет геометрией), сервоконтроллер, мастер «Позиционер робота» (MountInterface). Затем робот
подключается к позиционеру и получает программу с движением внешней оси. Результат: «Урок_10.rpro»,
«Позиционер.rpro» (компонент отдельным файлом) и видео «Урок_10.mp4».
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
    code = (HERE / "lesson10_scene.py").read_text(encoding="utf-8")
    out["компонент"] = _py(client, code)
    OUT.mkdir(parents=True, exist_ok=True)
    pos_path = (OUT / "Позиционер.rpro").as_posix()
    # vcComponent.save() в R-Pro 2.2.2 файл не пишет; планировка из одного компонента сохраняется
    # как обычный .rpro и грузится как компонент
    client.layout("save", pos_path)
    out["сохранён_компонент"] = pos_path
    code = "info = {}\n" + (HERE / "lesson10_robot.py").read_text(encoding="utf-8")
    out["робот"] = _py(client, code)
    import runner
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    out["ось_J1_в_конце"] = None
    out["видео"] = video.record(client, OUT / "Урок_10.mp4", seconds=40.0, speed=2.0)
    out["сообщения"] = [m for m in (client.messages(tail=60).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "unreach", "limit"))][:8]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
