# -*- coding: utf-8 -*-
"""
Поиск источника тика для моста.

Мост получает управление только когда R-Pro рисует кадр, а рисует она по
необходимости. Задача: найти действие, которое заставляет её рисовать
непрерывно, чтобы мост перестал зависеть от движений мыши.

Как работает проверка. Скрипт дожидается одного «окна» (пока вы водите мышью),
через него подменяет способ вызова кадра прямо в работающем мосте, а затем
замолкает и смотрит, отвечает ли мост САМ, без мыши. Если отвечает — способ
найден.

Запуск: python tickhunt.py
"""

from __future__ import annotations

import socket
import sys
import time
from urllib.parse import urlparse

import config
from rpro_client import BridgeError, RProClient

client = RProClient(timeout=30)
quick = RProClient(timeout=3)

# Каждый способ — это код на Python 2.7, выполняемый внутри R-Pro. Он должен
# определить функцию _tick() и поставить её единственным способом вызова кадра.
# ENV — это словарь глобальных имён самого моста, поэтому подмена видна ему.
INSTALL = """
def _tick():
%(body)s

ENV['RENDER_STRATEGIES'] = (('custom', _tick),)
CONFIG['render_strategies'] = ['custom']
CONFIG['render_fps'] = %(fps)s
_stats['last_render_request'] = 0.0
result = 'способ установлен'
"""

CANDIDATES = [
    ("обновление 3D-мира, без ограничителя", """
    app.Simulation.World.update()
""", 0),
    ("обновление 3D-мира, ограничитель 10 кадр/с", """
    app.Simulation.World.update()
""", 10),
    ("подстройка контраста затенения", """
    step = 0.0001 if _stats['render_events'] % 2 else -0.0001
    app.AmbientOcclusionContrast = app.AmbientOcclusionContrast + step
""", 0),
    ("свойство Animate", """
    app.Animate = True
""", 0),
    ("перестроение 3D-мира", """
    app.Simulation.World.rebuild()
""", 0),
    ("переключение на текущий вид", """
    views = app.Views
    if views:
        app.useView(views[0])
""", 0),
    ("сдвиг камеры на 0.01 мм", """
    camera = app.findCamera()
    if camera is not None:
        m = camera.Matrix
        m.translateRel(0.01 if _stats['render_events'] % 2 else -0.01, 0.0, 0.0)
        camera.Matrix = m
""", 0),
    ("мигание видимостью служебного компонента", """
    comp = app.findComponent('__ИИ-мост-тик__')
    if comp is None:
        comp = app.createComponent('__ИИ-мост-тик__')
    comp.Visible = not comp.Visible
""", 0),
]

CLEANUP = """
ENV['RENDER_STRATEGIES'] = ENV['_ORIGINAL_STRATEGIES']
CONFIG['render_strategies'] = ['world_update']
comp = app.findComponent('__ИИ-мост-тик__')
if comp is not None:
    app.deleteComponent(comp)
result = 'исходное поведение возвращено, служебный компонент удалён'
"""

REMEMBER = """
if '_ORIGINAL_STRATEGIES' not in ENV:
    ENV['_ORIGINAL_STRATEGIES'] = ENV['RENDER_STRATEGIES']
result = 'исходный набор способов запомнен'
"""


def port_is_open() -> bool:
    """
    Слушает ли кто-нибудь порт моста.

    Отказ в подключении означает, что R-Pro не запущена. А вот таймаут — это
    не отказ: у спящего моста очередь подключений забита неотвеченными
    попытками, и новое подключение просто виснет. Раньше скрипт принимал это
    за закрытую программу и отказывался работать.
    """
    parsed = urlparse(config.BRIDGE_URL)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1",
                                       parsed.port or 8765), timeout=2):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return True


def wait_for_window(minutes: float = 5.0) -> bool:
    print("ПОВОДИТЕ МЫШЬЮ ПО 3D-ВИДУ — нужно одно окно, дальше мышь не понадобится.")
    deadline = time.time() + minutes * 60
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            quick.health()
            print(f"поймал окно с попытки {attempt}\n")
            return True
        except BridgeError:
            if attempt % 5 == 1:
                print(f"  жду… (осталось {int(deadline - time.time())} с)")
            time.sleep(1.0)
    print("окно так и не поймал")
    return False


def pumps_now(timeout: float = 5.0) -> int | None:
    """Сколько прокачек насчитал мост. None — если мост молчит."""
    probe = RProClient(timeout=timeout)
    try:
        return probe.health().get("pumps")
    except BridgeError:
        return None


def chain_is_alive(before: int, quiet_seconds: float = 12.0) -> tuple[bool, str]:
    """
    Живёт ли цепочка отрисовки сама по себе.

    Первая версия проверки была негодной: она опрашивала мост сразу после
    установки способа и радовалась любому ответу. Но установка сама вызывает
    кадр, этот кадр обслуживает висящий запрос — и мёртвый способ выглядел
    рабочим.

    Теперь скрипт замолкает на десяток секунд и лишь потом спрашивает счётчик
    прокачек. При живой цепочке в 10 кадр/с он вырастает на сотню; одиночный
    кадр от самой установки даёт единицы.
    """
    time.sleep(quiet_seconds)
    after = pumps_now()

    if after is None:
        return False, "мост молчит — цепочки нет"

    grown = after - before
    expected = quiet_seconds * 10 * 0.3   # треть от заявленной частоты — с запасом
    if grown >= expected:
        return True, f"прокачек за {quiet_seconds:.0f} c: +{grown} — цепочка живая"
    return False, f"прокачек за {quiet_seconds:.0f} c: всего +{grown} — одиночные кадры"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    print("Поиск источника тика\n")

    if not port_is_open():
        print(f"R-Pro не запущена: {config.BRIDGE_URL} не отвечает.")
        return 1

    if not wait_for_window():
        return 1

    try:
        size = client.exec_python("result = len(app.Components)")["result"]
        print(f"компонентов в сцене: {size}\n")
    except BridgeError:
        pass

    try:
        client.exec_python(REMEMBER)
    except BridgeError as exc:
        print(f"не удалось запомнить исходное состояние: {exc}")
        return 1

    winners = []
    for title, body, fps in CANDIDATES:
        print(f"=== {title}")
        code = INSTALL % {"body": body.rstrip(), "fps": fps}
        try:
            client.exec_python(code)
        except BridgeError as exc:
            print(f"  установить не вышло: {str(exc)[:200]}")
            print("  (нужно снова поводить мышью, чтобы продолжить)")
            if not wait_for_window(2.0):
                break
            continue

        before = pumps_now()
        if before is None:
            print("  не удалось снять счётчик — нужно снова поводить мышью")
            if not wait_for_window(2.0):
                break
            continue

        print(f"  установлен (прокачек сейчас {before}). НЕ ТРОГАЙТЕ МЫШЬ 12 секунд…")
        alive, note = chain_is_alive(before)
        print(f"  {'РАБОТАЕТ' if alive else 'не работает'}: {note}")
        if alive:
            winners.append(title)
        elif not wait_for_window(2.0):
            break

    print("\n=== уборка")
    try:
        print("  " + str(client.exec_python(CLEANUP).get("result")))
    except BridgeError as exc:
        print(f"  не удалось убрать за собой: {str(exc)[:200]}")
        print("  Поводите мышью и запустите ещё раз — уборка выполнится.")

    print("\nИтог: " + (", ".join(winners) if winners else "ни один способ не сработал"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
