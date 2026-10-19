# -*- coding: utf-8 -*-
"""
Запуск практических заданий курса ИИТБ в живой R-Pro.

Задание N — файл tasks/lessonNN.py: код Python 2.7, который выполняется ВНУТРИ R-Pro
после hands27.py (общие приёмы агента) и iitb_lib.py (приёмы курса). Результат —
словарь в переменной `result`. Раннер: чистит сцену, выполняет задание, пишет файл
«Урок_N.rpro» в examples/iitb/ и снимок в examples/iitb/shots/.

    python agent/iitb/runner.py 1            # одно задание
    python agent/iitb/runner.py 1 2 3 --keep  # без очистки сцены перед заданием
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent
sys.path.insert(0, str(AGENT))

from rpro_client import BridgeError, RProClient  # noqa: E402

OUT = AGENT.parent / "examples" / "iitb"
SHOTS = OUT / "shots"
HANDS = AGENT / "hands27.py"
LIB = HERE / "iitb_lib.py"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def exec_in_rpro(client: RProClient, code: str, with_lib: bool = True) -> dict:
    src = read(HANDS) + "\n" + (read(LIB) + "\n" if with_lib and LIB.exists() else "") + code
    r = client.exec_python(src)
    if r.get("stderr"):
        raise RuntimeError(r["stderr"])
    return r.get("result")


def clear_scene(client: RProClient) -> None:
    client.exec_python("app.clearWorld()\n")


def uri(p: Path) -> str:
    return str(p).replace("\\", "/")


NO_OVERVIEW: set[int] = set()  # уроки, где камеру ставит само задание


def overview(client: RProClient, tilt: float = 0.55) -> None:
    """Камера на всю сцену: вид сверху под углом (как в shots.camera_on)."""
    code = "\n".join([
        "bs = [b for b in [_world_box(c) for c in app.Components] if b]",
        "if bs:",
        "    x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)",
        "    x1, y1 = max(b[3] for b in bs), max(b[4] for b in bs)",
        "    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0",
        "    span = max(x1 - x0, (y1 - y0) * 1.3, 4000.0) * 1.15",
        "    camera([cx, cy, 0.0], [cx, cy - %f * span, span * 0.95])" % tilt,
        "result = 1",
    ])
    exec_in_rpro(client, code, with_lib=False)


def run(n: int, keep: bool = False, save: bool = True) -> dict:
    client = RProClient(timeout=900)
    task = HERE / "tasks" / f"lesson{n:02d}.py"
    task3 = HERE / "tasks" / f"lesson{n:02d}_py3.py"
    if not task.exists() and not task3.exists():
        raise SystemExit(f"нет файла задания {task}")
    sim = client.simulation("status")
    if sim.get("running") or sim.get("time_sec", 0) > 0:
        client.simulation("reset")
    if not keep:
        clear_scene(client)
    t0 = time.time()
    if task3.exists():  # задание на Python 3: оркестрирует R-Pro через мост
        import importlib
        sys.path.insert(0, str(HERE / "tasks"))
        result = importlib.import_module(task3.stem).run(client)
    else:
        result = exec_in_rpro(client, read(task))
    info = {"урок": n, "результат": result, "секунд": round(time.time() - t0, 1)}
    if save:
        OUT.mkdir(parents=True, exist_ok=True)
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = OUT / f"Урок_{n}.rpro"
        try:
            client.layout("save", uri(path))
        except BridgeError as e:  # кириллица в пути — запасное имя
            path = OUT / f"Urok_{n}.rpro"
            client.layout("save", uri(path))
            info["имя_файла_запасное"] = str(e)[:120]
        info["файл"] = str(path)
        info["размер_кб"] = round(path.stat().st_size / 1024) if path.exists() else None
        try:
            sys.path.insert(0, str(AGENT.parent / "test_task" / "common"))
            import shots
            if n not in NO_OVERVIEW:
                overview(client)
            client.exec_python("app.render()")
            info["снимок"] = shots.shot(SHOTS / f"lesson{n:02d}.png").get("path")
        except Exception as e:  # снимок — украшение, не повод ронять задание
            info["снимок"] = "не вышел: " + str(e)[:100]
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for a in args:
        print(json.dumps(run(int(a), keep="--keep" in sys.argv), ensure_ascii=False, indent=1))
