# -*- coding: utf-8 -*-
"""
Стенд: подхватывает ли агент знания курса ИИТБ из обычных просьб (без слов «урок»/«курс»).

Каждая фраза уходит на живой агент (127.0.0.1:8766) после очистки сцены. Пишем: какие
инструменты вызвал, что осталось в сцене, ответ. Критерий успеха у каждой фразы свой —
проверка по сцене (check), а не по тону ответа.

    python agent/eval_course.py            # все
    python agent/eval_course.py L14 L11    # выбранные
Результат: agent/eval_course_result.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "iitb"))
from rpro_client import RProClient  # noqa: E402

AGENT = "http://127.0.0.1:8766/ask"
client = RProClient(timeout=120)


def scene_names() -> list[str]:
    import runner
    r = runner.exec_in_rpro(client, "result = [str(c.Name) for c in app.Components]")
    return r if isinstance(r, list) else []


def check_has(*words):
    """Успех — в сцене есть компонент, в имени которого встретилось любое из слов."""
    def f(names, answer, steps):
        low = [n.lower() for n in names]
        return any(w.lower() in n for n in low for w in words)
    return f


def check_any_tool(*tools):
    def f(names, answer, steps):
        return any(s["tool"] in tools for s in steps)
    return f


def check_text(*words):
    """Агент ответил проверенным умением (course_skills): в ответе есть нужная фраза, ошибок нет."""
    def f(names, answer, steps):
        return all(w in answer for w in words) and "не создан" not in answer and "не получилось" not in answer.lower()
    return f


def check_code(*words):
    """Модель выполнила rpro_exec, и в её коде есть нужный вызов API из рецепта."""
    def f(names, answer, steps):
        blob = json.dumps([s.get("arguments") for s in steps if s["tool"] == "rpro_exec"], ensure_ascii=False)
        return all(w in blob for w in words)
    return f


def check_done(names, answer, steps):
    """Задание выполнено кодом курса: ответ «Урок N … выполнено», в сцене что-то появилось, ошибок нет."""
    return "выполнено" in answer and bool(names) and "не выполнилось" not in answer


# (код, фраза, проверка)
CASES = [
    ("L14", "Сделай станок, у которого двери открываются и закрываются по сигналу DoorSignal через процесс с ожиданием сигнала.",
     check_done),
    ("L11", "Собери роутер из пяти деталей: платформа, плата, крышка, WAN-порт и антенна. Сборку сделай на ручной рабочей станции.",
     check_done),
    ("L12", "Построй автоматизированный склад с краном-штабелером и складской полкой.",
     check_done),
    ("L13", "Поставь детектор столкновений для робота и захвата против конвейеров.",
     check_text("Детектор столкновений создан")),
    ("L15", "Запаллетируй банки: 6 на 4 на поддон, робот берёт с конвейера.",
     check_done),
    ("L5", "Запиши видео симуляции в файл C:/Temp/test_video.", check_text("Записал")),
    ("L10", "Сделай свой компонент — позиционер с кареткой на сервоприводе, и поставь на него робота.",
     check_done),
    ("L6", "Покажи статистику загрузки оборудования на дашборде диаграммой.", check_text("Создал вкладку")),
    ("H14", "Как настроить ожидание сигнала у дверей станка, чтобы они открывались по сигналу?", None),
    ("H11", "Как собрать изделие из нескольких деталей в процессе на ручной станции — Construct и GetAssembly?", None),
]


def main(argv: list[str]) -> None:
    want = set(a.upper() for a in argv)
    out = []
    for code, q, check in CASES:
        if want and code.upper() not in want:
            continue
        client.exec_python("app.clearWorld(); result = 1")
        if code in ("L13", "L5", "L6"):
            import runner
            runner.run(8, save=False)          # учебная ячейка: робот, конвейеры, датчик — сцена пользователя
        requests.post(AGENT, json={"message": "/сброс"}, timeout=60)
        t0 = time.time()
        try:
            r = requests.post(AGENT, json={"message": q}, timeout=900).json()
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "error": str(exc)}
        steps = r.get("steps") or []
        answer = r.get("answer") or r.get("error") or ""
        names = scene_names()
        ok = check(names, answer, steps) if check else None
        rec = {"код": code, "вопрос": q, "успех": ok, "сек": round(time.time() - t0),
               "инструменты": [s["tool"] for s in steps], "сцена": names[:12], "ответ": answer[:600]}
        out.append(rec)
        print(f"[{code}] успех={ok} за {rec['сек']} с; инструменты: {rec['инструменты']}; сцена: {len(names)}", flush=True)
        print("   ", answer[:200].replace("\n", " "), flush=True)
    Path(__file__).with_name("eval_course_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
