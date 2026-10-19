# -*- coding: utf-8 -*-
"""
Сквозная проверка с настоящей моделью: python e2e_probe.py <0|1>

Задаёт агенту (chat.ask, qwen3:8b из Ollama) вопросы новичка с уроками Academy
(1) и без них (0) и пишет ответы в work/e2e_<режим>.json. Мост R-Pro не нужен:
на вопросы «как…» агенту доступны только инструменты чтения.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MODE = sys.argv[1] if len(sys.argv) > 1 else "1"
os.environ["RPRO_KB_ACADEMY"] = MODE
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.stdout.reconfigure(encoding="utf-8")

import chat  # noqa: E402
import config  # noqa: E402

QUESTIONS = [
    "Как создать у компонента свойство-кнопку, чтобы по нажатию что-то происходило?",
    "Как посчитать время цикла и загрузку оборудования в моей линии?",
    "Как скрыть компонент в сцене, чтобы он не мешал, но остался в планировке?",
    "Как запрограммировать робота, который складывает коробки на паллету?",
]


def main() -> None:
    out = []
    for q in QUESTIONS:
        messages = [{"role": "system", "content": config.SYSTEM_PROMPT},
                    {"role": "user", "content": q}]
        t0 = time.time()
        try:
            answer = chat.ask(messages)
        except Exception as exc:  # noqa: BLE001
            answer = f"ОШИБКА: {exc}"
        used = [m["content"].split("\n")[0][:100] for m in messages if m.get("role") == "system"][1:]
        out.append({"question": q, "answer": answer, "seconds": round(time.time() - t0),
                    "context_note": used})
        print(f"[{MODE}] {round(time.time() - t0)} с: {q[:50]}", flush=True)
    (HERE / "work").mkdir(exist_ok=True)
    (HERE / "work" / f"e2e_{MODE}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
