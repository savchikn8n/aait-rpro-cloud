# -*- coding: utf-8 -*-
"""
Показательный прогон агента по сценарию.

То же, что диалог в chat.py, только вопросы заданы заранее — удобно проверять
всю связку целиком после изменений и показывать, на что агент способен.
История разговора сохраняется между вопросами, как в настоящей беседе.

Запуск: python demo.py
"""

from __future__ import annotations

import sys
import time

import chat
import config

СЦЕНАРИЙ = [
    # --- чтение: агент должен опираться на факты, а не выдумывать
    "Что сейчас открыто в R-Pro? Ответь одним абзацем.",
    "Перечисли роботов в сцене с их координатами.",
    "Сколько в сцене конвейеров и как они называются? Сгруппируй по типу.",

    # --- зрение
    "Посмотри на экран и опиши, что видит пользователь прямо сейчас.",

    # --- подробности
    "Покажи ключевые свойства любого прямого конвейера: длину, ширину, высоту и скорость.",

    # --- действие, не меняющее модель
    "Выдели в 3D-виде обоих роботов, чтобы я их увидел.",

    # --- изменение сцены
    "Склонируй один прямой конвейер и поставь копию на 2 метра левее оригинала по оси Y. "
    "Покажи код, прежде чем выполнять.",

    # --- симуляция и разбор итога
    "Запусти симуляцию на 10 секунд, затем скажи, сколько прошло модельного времени "
    "и появились ли новые сообщения об ошибках.",

    # --- итог
    "Подведи итог: что мы сейчас сделали со сценой и в каком она состоянии.",
]


def main() -> int:
    chat.prepare_console()

    print(f"{chat.BOLD}Показательный прогон агента{chat.RESET}")
    print(f"{chat.DIM}модель: {config.CHAT_MODEL}{chat.RESET}\n")

    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    started = time.time()

    for number, question in enumerate(СЦЕНАРИЙ, 1):
        print(f"\n{chat.CYAN}[{number}/{len(СЦЕНАРИЙ)}] вы ›{chat.RESET} {question}")
        step_started = time.time()

        messages.append({"role": "user", "content": question})
        try:
            answer = chat.ask(messages)
        except Exception as exc:  # noqa: BLE001 — прогон не должен обрываться
            print(f"{chat.RED}Ошибка: {exc}{chat.RESET}")
            continue

        print(f"\n{chat.BOLD}агент ›{chat.RESET} {answer}")
        print(f"{chat.DIM}({time.time() - step_started:.0f} c){chat.RESET}")

    print(f"\n{chat.DIM}весь прогон занял {time.time() - started:.0f} c{chat.RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
