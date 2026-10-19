# -*- coding: utf-8 -*-
"""
Урок 11 ИИТБ: «Сборка роутера» из 5 компонентов.

Пять деталей (платформа, плата, крышка, WAN-порт, антенна) создаются блоками и пишутся в
examples/iitb/parts/Router_N.rpro. Во вкладке «Детали»: группа деталей и группа «Роутер» с типом-сборкой
из 5 шагов; пять «Процессов подачи»; ручная рабочая станция с логикой 5×TransportIn → GetAssembly →
Construct → TransportOut; человек (ТК человека) переносит детали и собранный роутер. Результат: «Урок_11.rpro».
"""

from __future__ import annotations

import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "examples" / "iitb"
PARTS = OUT / "parts"

# (длина, ширина, высота, материал) — мм
PARTS_SPEC = [(180, 120, 20, "white"), (150, 100, 6, "green"), (180, 120, 30, "black"),
              (25, 20, 15, "yellow"), (10, 10, 150, "blue")]


def _py(client, code):
    import runner
    return runner.exec_in_rpro(client, code)


def make_parts(client) -> list[str]:
    PARTS.mkdir(parents=True, exist_ok=True)
    made = []
    for i, (l, w, h, mat) in enumerate(PARTS_SPEC, 1):
        path = (PARTS / f"Router_{i}.rpro").as_posix()
        # vcComponent.save принимает ТОЛЬКО адрес file:/// байтами UTF-8 (обычный путь молча ничего не пишет)
        code = "\n".join([
            "c = app.createComponent()",
            "c.Name = _b(u'Router_%d')" % i,
            "b = c.RootFeature.createFeature(VC_BLOCK, 'Block')",
            "b.getProperty('Length').Value = '%d'; b.getProperty('Width').Value = '%d'; b.getProperty('Height').Value = '%d'" % (l, w, h),
            "m = app.findMaterial('%s')" % mat,
            "if m is not None:",
            "    b.getProperty('Material').Value = m",
            "c.save(_b(u'file:///%s'))" % path,
            "app.deleteComponent(c)",
            "result = 1",
        ])
        _py(client, code)
        made.append(path)
    return made


def run(client) -> dict:
    out = {"детали": [Path(p).name for p in make_parts(client)]}
    code = f"PARTS_DIR = {PARTS.as_posix()!r}\n" + (HERE / "lesson11_scene.py").read_text(encoding="utf-8")
    out["сцена"] = _py(client, code)
    import runner
    runner.overview(client)
    client.messages(clear=True)
    client.simulation("reset")
    time.sleep(1.0)
    _py(client, "app.Simulation.SimSpeed = 20.0; result = 1")
    client.simulation("run_for", seconds=600.0)
    t0 = time.time()
    while time.time() - t0 < 200:
        st = client.simulation("status")
        if not st.get("running") and st.get("time_sec", 0) >= 590:
            break
        time.sleep(1.0)
    out["статистика"] = _py(client, "result = line_stats()")
    out["сообщения"] = [m for m in (client.messages(tail=80).get("lines") or [])
                        if any(k in str(m).lower() for k in ("error", "ошиб", "not found", "no path", "unable"))][:8]
    client.simulation("reset")
    _py(client, "app.Simulation.SimSpeed = 1.0; result = 1")
    return out
