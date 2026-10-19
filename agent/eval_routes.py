# -*- coding: utf-8 -*-
"""
Стенд: какая фраза каким обработчиком отвечается — до модели (intents/skills)
или уходит модели (None). Ловит перехваты вроде 12.10 («оптимизируй» →
/оптимизация удалила людей) и 13.10 (вопрос о браке → clear=true у модели).

Действия, меняющие сцену (очистка, правка, удаление, добавление, симуляция,
оптимизация), подменены заглушками — сцена не меняется. Чтение сцены — живое:
нужна открытая R-Pro (мост 127.0.0.1:8765); лучше со сценой модуля A, тогда
проверяются и ответы «где задаётся» по разливочной и блистерной машинам.

    .venv/Scripts/python.exe agent/eval_routes.py
"""

from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import intents  # noqa: E402
import skills   # noqa: E402

# --- заглушки действий ---------------------------------------------------------------
_did: list[str] = []


def _stub(name):
    def f(*a, **k):
        _did.append(name)
        return f"[{name}]"
    return f


for _n in ("clear_text", "set_prop_text", "delete_text", "move_text", "rotate_text", "rename_text",
           "catalog_add_text", "join_text"):
    setattr(skills, _n, _stub(_n))
skills.sim_text = lambda action, speed=None: (_did.append("sim:" + action), f"[sim {action}]")[1]
skills.look_text = _stub("look_text")
intents.optimize_text = _stub("optimize_text")
intents.sim_text = lambda minutes: (_did.append("sim_for"), "[sim_for]")[1]
intents.report_text = _stub("report_text")

# (фраза, ожидаемый обработчик — имя из on_tool, или None — к модели; подстрока в ответе)
CASES: list[tuple[str, str | None, str]] = [
    # 13.10: вопрос о свойстве компонента — ответ из сцены, не модель
    ("А где я могу посмотреть, где у Роторной разливочной машины задаётся правило, связанное с дефектом "
     "выпускаемой продукции?", "где задаётся", "DefectRate"),
    ("как задаётся брак у блистерной машины?", "где задаётся", "uniform"),
    ("где настраивается скорость конвейера?", "где задаётся", "ConveyorSpeed"),
    ("где задаётся время у ОТК бутылок", "где задаётся", "Delay"),
    # очистка — только командой и «да»
    ("очисти сцену", "очистить", "/очистить"),
    ("удали всё", "очистить", "/очистить"),
    ("Построй линию из 3 станков с нуля", "очистить", "построй рядом"),
    ("/очистить", "очистить", "Вы уверены"),
    ("нет", "очистить", "не трогаю"),
    ("да", None, ""),                      # вопроса не было — не очищать
    ("/очистить", "очистить", "Вы уверены"),
    ("да", "очистить", "[clear_text]"),
    # команды и навыки
    ("/помощь", "команда", "/очистить"),
    ("покажи свойства конвейера", "свойства", "ConveyorSpeed"),
    ("поставь длину конвейера 3000 мм", "свойство", "[set_prop_text]"),
    ("запусти симуляцию", "симуляция", "[sim run]"),
    ("запусти симуляцию на 3 минуты", "симуляция", "[sim_for]"),
    ("удали конвейер", "удалить", "[delete_text]"),
    # TechSkills — к модели (12.10: «оптимизируй» перехватывала /оптимизация)
    ("Выполни модуль C тестового задания: исследуй модель сборки двигателя, оптимизируй её и подготовь VSM",
     None, ""),
    ("Сделай модуль A", None, ""),
    ("Собери все три модуля тестового задания TechSkills на одном поле и проверь их совместным прогоном",
     None, ""),
    # частые неполадки — самая частная запись faq (13.10: погрузчик уходил в общую про людей)
    ("погрузчик пишет Unable to solve path", "проблема", "место ожидания"),
    ("Unable to solve path for \"Мобильный робот 3\"", "проблема", "зон"),
    # вопросы «как сделать» без компонента в сцене — не перехватывать
    ("как сделать конвейерную линию?", None, ""),
]


def main() -> int:
    bad = 0
    for text, want, needle in CASES:
        got: list[str] = []
        _did.clear()
        t0 = time.time()
        try:
            r = intents.handle(text, on_tool=lambda n, a, o: got.append(n))
        except Exception as exc:  # noqa: BLE001
            r, got = f"ИСКЛЮЧЕНИЕ: {exc}", ["исключение"]
        name = got[0] if got else None
        ok = name == want and (not needle or (r or "").find(needle) >= 0)
        if want == "очистить" and needle != "[clear_text]" and "clear_text" in _did:
            ok = False   # очистил без «да»
        bad += not ok
        print(f"{'ок ' if ok else 'НЕТ'} {time.time() - t0:4.1f} с  {text[:70]!r} → {name}"
              + ("" if ok else f" (ждали {want}, «{needle}»)\n      {str(r)[:300]}"))
    print(f"\nИтог: {len(CASES) - bad} из {len(CASES)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
