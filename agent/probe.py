# -*- coding: utf-8 -*-
"""
Диагностика моста на живой R-Pro.

Проверяет то, что нельзя проверить без запущенной программы: реальные ответы
Python-API, снимок 3D-вида и поведение отрисовки. Пока мост прокачивается
событием OnRender, во время работы скрипта нужно водить мышью по 3D-виду.

Запуск: python probe.py
"""

from __future__ import annotations

import json
import socket
import sys
import time
from urllib.parse import urlparse

import config

from rpro_client import BridgeError, RProClient

client = RProClient(timeout=90)


def step(title, fn):
    print(f"\n=== {title}")
    started = time.time()
    try:
        result = fn()
    except BridgeError as exc:
        print(f"  ОШИБКА за {time.time() - started:.1f} c: {str(exc)[:600]}")
        return None
    print(f"  готово за {time.time() - started:.1f} c")
    return result


def short(value, limit=600):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "…"


# Проба поведения отрисовки: синхронна ли app.render().
# Если счётчик событий вырос, значит render() отрисовывает немедленно и
# вызывать его из обработчика OnRender опасно рекурсией.
RENDER_PROBE = """
import time
before = _stats['render_events']
t0 = time.time()
app.render()
result = {
    'render_events_before': before,
    'render_events_after': _stats['render_events'],
    'sync': _stats['render_events'] > before,
    'seconds': round(time.time() - t0, 4),
}
"""

# Какие свойства приложения могут влиять на непрерывность отрисовки.
PROPS_PROBE = """
out = {}
for name in ('Animate', 'RealTime', 'RealTimeMode', 'Recording', 'RecordScreen',
             'RecordingFrameRate', 'IsStreamingOn'):
    try:
        out[name] = repr(getattr(app, name))
    except Exception, exc:
        out[name] = 'нет такого: %s' % exc
result = out
"""

# Почему способы вызвать кадр молчат. Главное подозрение: findCamera()
# возвращает пустоту, и шевеление камеры просто не происходит.
CAMERA_PROBE = """
out = {}
camera = app.findCamera()
out['камера найдена'] = camera is not None
if camera is not None:
    out['имя'] = repr(camera.Name)
    m = camera.Matrix
    out['положение до'] = [round(m.P.X, 4), round(m.P.Y, 4), round(m.P.Z, 4)]
    m.translateRel(0.01, 0.0, 0.0)
    camera.Matrix = m
    m2 = app.findCamera().Matrix
    out['положение после'] = [round(m2.P.X, 4), round(m2.P.Y, 4), round(m2.P.Z, 4)]
    out['сдвиг принят'] = out['положение до'] != out['положение после']
out['views'] = [repr(v.Name) for v in app.Views][:10]
result = out
"""

# Растёт ли счётчик кадров сам по себе: два замера с паузой.
GROWTH_PROBE = """
import time
before = _stats['render_events']
t0 = time.time()
result = {'кадров на старте замера': before, 'отметка времени': round(t0, 1)}
"""


def port_is_open() -> bool:
    """
    Открыт ли порт моста.

    Различает два похожих снаружи состояния: R-Pro не запущена (соединение
    отвергается) и R-Pro работает, но не отдаёт нам управление (соединение
    устанавливается, ответа нет). Без этой проверки скрипт может честно
    прождать пять минут закрытую программу.
    """
    parsed = urlparse(config.BRIDGE_URL)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 8765
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        # Таймаут — не отказ: у спящего моста очередь подключений забита
        # неотвеченными попытками, и новое подключение виснет.
        return True


def wait_for_bridge(minutes: float = 5.0) -> dict | None:
    """
    Ждёт, пока мост отзовётся.

    Пока прокачка держится на событии OnRender, мост оживает только когда
    пользователь шевелит мышью в 3D-виде. Скрипт не пытается угадать этот
    момент, а терпеливо опрашивает мост, пока тот не ответит.
    """
    quick = RProClient(timeout=3)
    deadline = time.time() + minutes * 60
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            health = quick.health()
            print(f"\nмост отозвался с попытки {attempt}")
            return health
        except BridgeError:
            if attempt % 5 == 1:
                left = int(deadline - time.time())
                print(f"  жду… (осталось {left} с) — поводите мышью по 3D-виду")
            time.sleep(1.0)

    print("\nмост так и не отозвался")
    return None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    print("Диагностика моста на живой R-Pro")

    if not port_is_open():
        print(f"\nR-Pro не запущена или мост не установлен: {config.BRIDGE_URL} не отвечает.")
        print("Запустите R-Pro и повторите.")
        return 1

    print("ПОВОДИТЕ МЫШЬЮ ПО 3D-ВИДУ — скрипт сам поймает момент и всё сделает.")
    health = wait_for_bridge()
    if not health:
        return 1
    print("  " + short(health, 400))

    ping = step("ping: версия и счётчики", client.ping)
    if ping:
        print("  " + short(ping, 500))

    status = step("status: что открыто", client.status)
    if status:
        print("  " + short(status, 700))

    scene = step("scene: компоненты сцены", lambda: client.scene(limit=30))
    if scene:
        print(f"  всего компонентов: {scene.get('total')}")
        for comp in scene.get("components", [])[:15]:
            print(f"    {comp.get('name')}  {comp.get('position')}")

    shot = step("screenshot: снимок 3D-вида",
                lambda: client.screenshot(width=960, height=540, as_base64=False))
    if shot:
        print(f"  файл: {shot.get('path')}")

    probe = step("проба: синхронна ли отрисовка",
                 lambda: client.exec_python(RENDER_PROBE))
    if probe:
        print("  " + short(probe.get("result"), 400))

    props = step("проба: свойства отрисовки",
                 lambda: client.exec_python(PROPS_PROBE))
    if props:
        print("  " + short(props.get("result"), 600))

    camera = step("проба: есть ли камера и принимает ли она сдвиг",
                  lambda: client.exec_python(CAMERA_PROBE))
    if camera:
        print("  " + short(camera.get("result"), 600))
    if camera and camera.get("stderr"):
        print("  ошибки: " + camera["stderr"][:300])

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
