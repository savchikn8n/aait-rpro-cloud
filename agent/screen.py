# -*- coding: utf-8 -*-
"""
Снимок окна R-Pro.

Штатный снимок 3D-вида через Python-API в этой сборке не работает:
beginFrameGrab отрабатывает без единой ошибки, но файла не создаёт ни при каком
написании пути, а функции saveBitmap и saveScreen из справки в модуль vcCommand
попросту не выставлены. Поэтому снимок делается снаружи, средствами Windows.

Так даже полезнее: агент видит всё окно — 3D-вид, дерево компонентов, ленту и
панель вывода, — а не только сцену.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

CAPTURE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture.ps1")


class CaptureError(RuntimeError):
    """Снимок сделать не удалось."""


def capture_window(path: str | None = None, process_name: str = "rpro_starter",
                   timeout: float = 30.0) -> dict:
    """
    Снимает окно программы и возвращает сведения о снимке.

    path — куда сохранить PNG; по умолчанию во временную папку.
    """
    if path is None:
        folder = os.path.join(tempfile.gettempdir(), "rpro-agent")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"window_{int(time.time() * 1000)}.png")

    command = ["pwsh", "-NoProfile", "-NonInteractive", "-File", CAPTURE_SCRIPT,
               "-Path", path, "-ProcessName", process_name]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", timeout=timeout)
    except FileNotFoundError:
        # На машине может не быть PowerShell 7 — пробуем встроенный.
        command[0] = "powershell.exe"
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"снимок не уложился в {timeout} с") from exc

    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "").strip()
        raise CaptureError(error.splitlines()[-1] if error else "неизвестная ошибка")

    # Скрипт печатает: способ|ширина|высота|путь
    line = (completed.stdout or "").strip().splitlines()[-1] if completed.stdout else ""
    parts = line.split("|")
    if len(parts) != 4 or not os.path.isfile(parts[3]):
        raise CaptureError(f"непонятный ответ скрипта снимка: {line[:200]}")

    return {
        "method": parts[0],
        "width": int(parts[1]),
        "height": int(parts[2]),
        "path": parts[3],
        "size_bytes": os.path.getsize(parts[3]),
    }


def capture_base64(**kwargs) -> tuple[str, dict]:
    """Снимок сразу в виде base64 — в таком виде его ждёт модель со зрением."""
    import base64

    info = capture_window(**kwargs)
    with open(info["path"], "rb") as f:
        return base64.b64encode(f.read()).decode("ascii"), info
