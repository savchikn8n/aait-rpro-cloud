# -*- coding: utf-8 -*-
"""
Урок 5 ИИТБ: «Визуализация модели» — облёт камеры между видами и запись результата.

Планировка и процесс — из уроков 2–3. Затем: 5 видов (редактор видов) → программа аниматора
камеры (1 мин 35 с) → запись видео .mp4 на скорости симуляции ×10 → ещё три экспорта из
области «Экспорт»: изображение (PNG), 3D-PDF с анимацией, геометрия (STL).
Файлы пишутся в examples/iitb/ рядом с «Урок_5.rpro».
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import lesson03_py3 as l3

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "examples" / "iitb"
RUN_S = 95.0


def _py(client, code: str):
    import runner
    return runner.exec_in_rpro(client, code)


def _record(client, kind: str, tmp: Path, width: int = 1280, height: int = 720) -> dict:
    """Запись симуляции (video | pdf) на ×10: включить Recording, дождаться RUN_S, выключить."""
    const = "VC_RECORDER_VIDEO" if kind == "video" else "VC_RECORDER_PDF"
    tmp = Path(str(tmp))
    client.simulation("reset")
    time.sleep(1.0)
    code = ("app.Recorder = %s; app.RecordingFileName = %r; app.RecordingFrameRate = %d; "
            "app.RecordingShow = False; app.RecordScreen = False; app.RecordingWidth = %d; "
            "app.RecordingHeight = %d; app.Simulation.SimSpeed = 10.0; result = 1"
            % (const, str(tmp).replace("\\", "/"), 25 if kind == "video" else 10, width, height))
    _py(client, code)
    t0 = time.time()
    _py(client, "app.Recording = True; result = 1")  # сам запускает симуляцию
    last = 0.0
    while time.time() - t0 < 180:
        st = client.simulation("status")
        last = float(st.get("time_sec", 0))
        if last >= RUN_S:
            break
        time.sleep(0.5)
    _py(client, "app.Recording = False; result = 1")
    time.sleep(2.0)
    client.simulation("reset")
    return {"тип": kind, "дошли_до_с": round(last, 1), "файл": str(tmp), "есть": tmp.exists(),
            "размер_кб": round(tmp.stat().st_size / 1024) if tmp.exists() else None}


def run(client) -> dict:
    lb, res, out = l3.build_process(client)
    # 1. виды и аниматор камеры
    out["виды"] = _py(client, (HERE / "lesson05_views.py").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    # 2. видео (экспорт → Видео). Рекордер R-Pro 2.2.2 пишет «имя.avi» (расширение дописывает
    # сам, кодека mp4 нет) — потом сжимаем в H.264 .mp4 через ffmpeg.
    tmp = OUT / "urok5_tmp"
    out["видео"] = _record(client, "video", tmp)
    avi = OUT / "urok5_tmp.avi"
    try:
        import imageio_ffmpeg
    except ImportError:    # нет ffmpeg в окружении — видео остаётся в .avi
        imageio_ffmpeg = None
        out["видео"]["примечание"] = "нет imageio_ffmpeg: видео осталось в .avi"
    if avi.exists() and imageio_ffmpeg is not None:
        import subprocess
        dst = OUT / "Урок_5.mp4"
        r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(avi),
                            "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", str(dst)],
                           capture_output=True, text=True)
        if r.returncode == 0 and dst.exists():
            avi.unlink()
            out["видео"].update({"файл": str(dst), "есть": True, "размер_кб": round(dst.stat().st_size / 1024)})
    # Не получилось через API (в R-Pro 2.2.2 команды saveBitmap/exportLayoutAsGeometry «выполняются» без файла,
    # а Recorder=PDF не пишет 3D-PDF) — изображение, геометрия и 3D-PDF делаются кнопками области «Экспорт».
    out["ошибки"] = [m for m in (client.messages(tail=40).get("messages") or []) if "rror" in str(m)][:5]
    lb._overview()
    client.simulation("reset")
    return out
