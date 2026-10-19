# -*- coding: utf-8 -*-
"""
Проверка связки: Ollama → модели → мост → R-Pro.

Запуск: python selfcheck.py
Показывает по шагам, что работает, а что нет, и что делать дальше.
"""

from __future__ import annotations

import sys

import config
import llm
import screen
from rpro_client import BridgeError, RProClient

OK, FAIL, WARN = "[ ok ]", "[ fail ]", "[ warn ]"


def check_ollama() -> list[str]:
    print(f"1. Модель: {llm.provider()} ({config.OPENROUTER_URL if llm.provider() != 'ollama' else config.OLLAMA_URL})")
    try:
        models = llm.list_models()
    except llm.LLMError as exc:
        print(f"   {FAIL} {exc}")
        print("   Что делать: запустите Ollama (она обычно стартует вместе с Windows).")
        return []

    names = [m.get("name", "") for m in models]
    print(f"   {OK} доступна, моделей: {len(names)}")
    for m in models:
        size_gb = m.get("size", 0) / (1024 ** 3)
        print(f"        {m.get('name')}  ({size_gb:.1f} ГБ)")
    return names


def check_models(names: list[str]) -> None:
    print(f"\n2. Модели агента")
    cloud = llm.provider() != "ollama"
    for title, wanted in (("основная", config.OPENROUTER_MODEL if cloud else config.CHAT_MODEL),
                          ("зрение", config.OPENROUTER_VISION_MODEL if cloud else config.VISION_MODEL)):
        if not wanted:
            print(f"   {WARN} {title}: не задана")
            continue
        if any(n == wanted or n.startswith(wanted.split(":")[0] + ":") for n in names):
            print(f"   {OK} {title}: {wanted}")
        else:
            print(f"   {FAIL} {title}: {wanted} не установлена")
            print(f"        ollama pull {wanted}")


def check_bridge() -> bool:
    print(f"\n3. Мост в R-Pro ({config.BRIDGE_URL})")
    client = RProClient()
    try:
        health = client.health()
    except BridgeError as exc:
        print(f"   {FAIL} {exc}")
        print("   Что делать: установите мост (bridge/install.ps1) и запустите R-Pro.")
        return False

    version = health.get("bridge_version")
    if version == config.EXPECTED_BRIDGE_VERSION:
        print(f"   {OK} отвечает, версия {version}")
    else:
        print(f"   {FAIL} отвечает, но версия {version}, а агенту нужна "
              f"{config.EXPECTED_BRIDGE_VERSION}")
        print("   Что делать: закройте R-Pro, выполните bridge/install.ps1 и запустите R-Pro снова.")
    since = health.get("seconds_since_pump")
    if since is None:
        print(f"   {WARN} очередь ещё ни разу не прокачивалась — проверим следующим шагом")
    else:
        print(f"   {OK} очередь живая (последняя прокачка {since} с назад)")

    try:
        status = client.status()
    except BridgeError as exc:
        print(f"   {FAIL} R-Pro не отвечает на запрос состояния: {exc}")
        return False

    print(f"   {OK} проект: {status.get('layout_uri') or 'новый (не сохранён)'}")
    print(f"        компонентов: {status.get('component_count')}, "
          f"режим: {status.get('context')}, "
          f"симуляция: {'идёт' if status['simulation']['running'] else 'остановлена'}")
    return True


def check_screenshot() -> None:
    # Снимок делается снаружи, средствами Windows: штатный кадр-граббер R-Pro
    # в этой сборке файла не создаёт. Подробности — в agent/screen.py.
    print("\n4. Снимок окна программы")
    try:
        shot = screen.capture_window()
    except screen.CaptureError as exc:
        print(f"   {FAIL} {exc}")
        return
    print(f"   {OK} сохранён: {shot['path']}")
    print(f"        способ: {shot['method']}, {shot['width']}x{shot['height']}, "
          f"{shot['size_bytes'] // 1024} КБ")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    print("Проверка связки ИИ-агент ↔ R-Pro\n")
    names = check_ollama()
    check_models(names)
    if check_bridge():
        check_screenshot()
    print("\nГотово. Запуск диалога: python chat.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
