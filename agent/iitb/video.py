# -*- coding: utf-8 -*-
"""Запись видео симуляции R-Pro (область «Экспорт» → «Видео») из кода.

Что выяснено на R-Pro 2.2.2:
- app.Recorder = VC_RECORDER_VIDEO; имя файла БЕЗ расширения — программа сама дописывает «.avi»
  (формат — несжатый-ish AVI, 1 минута ≈ 45 МБ), кодека mp4 нет → сжимаем ffmpeg в H.264 .mp4;
- app.Recording = True сама запускает симуляцию; выключать (False) нужно ПОКА симуляция идёт —
  иначе (для PDF) запись теряется;
- запись идёт по времени симуляции: 95 с симуляции при скорости ×10 — видео 95 с, делается за ~10 с;
- RecordScreen=False + Width/Height — размер кадра задаём сами (1280×720).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


def _py(client, code: str):
    import runner
    return runner.exec_in_rpro(client, code)


def record(client, mp4: Path, seconds: float, speed: float = 10.0, width: int = 1280, height: int = 720,
           fps: int = 25, timeout_s: float = 600.0) -> dict:
    """Записать `seconds` секунд симуляции в mp4 (H.264). Симуляция перед записью сбрасывается."""
    mp4 = Path(mp4)
    tmp = mp4.with_name("_rec_tmp")
    avi = mp4.with_name("_rec_tmp.avi")
    if avi.exists():
        avi.unlink()
    client.simulation("reset")
    time.sleep(1.5)
    _py(client, ("app.Recorder = VC_RECORDER_VIDEO; app.RecordingFileName = %r; app.RecordingFrameRate = %d; "
                 "app.RecordingShow = False; app.RecordScreen = False; app.RecordingWidth = %d; "
                 "app.RecordingHeight = %d; app.Simulation.SimSpeed = %f; result = 1")
         % (str(tmp).replace("\\", "/"), fps, width, height, float(speed)))
    t0 = time.time()
    _py(client, "app.Recording = True; result = 1")
    time.sleep(1.5)
    st = client.simulation("status")
    if not st.get("running"):  # запись иногда симуляцию не стартует — запускаем сами, но без остановки в конце
        client.simulation("run_for", seconds=seconds + 600.0)
    last = 0.0
    while time.time() - t0 < timeout_s:
        last = float(client.simulation("status").get("time_sec", 0))
        if last >= seconds:
            break
        time.sleep(0.5)
    _py(client, "app.Recording = False; result = 1")
    time.sleep(2.5)
    client.simulation("reset")
    info = {"симуляции_с": round(last, 1), "реально_с": round(time.time() - t0)}
    if not avi.exists():
        info["файл"] = None
        info["ошибка"] = "рекордер не записал файл"
        return info
    try:
        import imageio_ffmpeg
    except ImportError:   # нет ffmpeg в окружении агента — оставляем avi как есть
        info.update({"файл": str(avi), "ошибка": "нет imageio_ffmpeg: видео осталось в .avi"})
        return info
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(avi),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", str(mp4)],
                       capture_output=True, text=True)
    if r.returncode == 0 and mp4.exists():
        avi.unlink()
        info.update({"файл": str(mp4), "размер_кб": round(mp4.stat().st_size / 1024)})
    else:
        info.update({"файл": str(avi), "ошибка": "ffmpeg: " + r.stderr[:100]})
    return info
