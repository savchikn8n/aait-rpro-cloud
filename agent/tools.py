# -*- coding: utf-8 -*-
"""Инструменты, которые агент может вызывать: описания для модели и реализация."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import catalog
import config
import glossary
import kb
import llm
import screen
from rpro_client import BridgeError, RProClient

client = RProClient()


def _kit_titles() -> list[str]:
    """Изделия из наборов — для описания инструмента (снимаются при запуске агента)."""
    try:
        import kits
        return sorted(t.lower() for t in kits.load_kits())
    except Exception:  # noqa: BLE001 — без наборов агент всё равно работает
        return []


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


# --- реализации ------------------------------------------------------------

def t_status(**_: Any) -> dict:
    return client.status()


def t_scene(limit: int = 100, **_: Any) -> dict:
    """Сцена для модели — сводкой. Полный список из сотен компонентов в JSON
    (12 тысяч знаков) вытеснял из контекста 8B-модели системную подсказку, и
    она забывала, что работает в R-Pro. Поэтому: сколько всего, сколько каких
    (по имени без «#N»), а поимённо с координатами — только маленькую сцену."""
    import re
    import kits
    # Если в сцене линии — рассказ о них (этажи, посты, операции роботов, лифты),
    # а не «cell.stl: 240»: детали в работе забивали сводку, и модель на вопрос
    # «что построено» отвечала инструкцией, как запустить симуляцию.
    try:
        summary = kits._run(client, "result = scene_summary()")
    except Exception:  # noqa: BLE001 — сводка необязательна
        summary = None
    if summary and summary.get("линии"):
        return {**summary, "всего_компонентов": client.status().get("component_count"),
                "подсказка": "Так и расскажи: этажи (отметка), что делает каждая линия, сколько "
                             "роботов и лифтов. Выпуск и узкое место — rpro_line_report."}
    raw = client.scene(limit=1000)
    comps = raw.get("components", [])
    kinds: dict[str, int] = {}
    for c in comps:
        base = re.sub(r"\s*#\d+$", "", c.get("name", ""))
        kinds[base] = kinds.get(base, 0) + 1
    out: dict[str, Any] = {"всего": raw.get("total", len(comps)),
                           "по_видам": dict(sorted(kinds.items(), key=lambda kv: -kv[1])[:40])}
    if len(comps) <= min(int(limit), 40):
        out["компоненты"] = [{"имя": c.get("name"),
                              "где_мм": [round(v) for v in (c.get("position") or [])[:3]]}
                             for c in comps]
    else:
        out["подсказка"] = ("сцена большая — подробности о конкретном компоненте: rpro_find или "
                            "rpro_component; линии: rpro_line_check / rpro_line_report")
    return out


def t_find(query: str = "", **_: Any) -> dict:
    return client.find(query)


def t_component(name: str = "", with_behaviours: bool = False, component: str = "",
                **_: Any) -> dict:
    # Модель то и дело называет параметр component, как в rpro_set_property.
    return client.component(name or component, with_behaviours=bool(with_behaviours))


def t_messages(tail: int = 50, **_: Any) -> dict:
    return client.messages(tail=int(tail))


def t_simulation(action: str = "status", seconds: float | None = None,
                 until: float | None = None, **_: Any) -> dict:
    return client.simulation(action=action, seconds=seconds, until=until)


def t_set_property(component: str = "", property: str = "", value: Any = None, **_: Any) -> dict:
    # Модель присылает значения строкой: "false", "300". Мост кладёт их в
    # свойство как есть, и булево свойство на "false" роняет R-Pro-шный Python
    # («error return without exception set», журнал 08.10: четыре попытки
    # скрыть компонент подряд).
    if isinstance(value, str):
        v = value.strip()
        if v.lower() in ("true", "false", "истина", "ложь", "да", "нет"):
            value = v.lower() in ("true", "истина", "да")
        elif re.fullmatch(r"-?\d+", v):
            value = int(v)
        elif re.fullmatch(r"-?\d+[.,]\d+", v):
            value = float(v.replace(",", "."))
    return client.set_property(component, property, value)


def t_select(names: list[str] | str = "", **_: Any) -> dict:
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    return client.select(names)


def t_look(question: str = "Что изображено на виде?", **_: Any) -> dict:
    # Снимаем окно программы целиком: в кадр попадают и 3D-вид, и панели.
    # Штатный снимок через Python-API в этой сборке не работает, см. screen.py.
    image, info = screen.capture_base64()
    answer = llm.look(image, question)
    return {
        "screenshot_path": info["path"],
        "captured_by": info["method"],
        "observation": answer,
    }


def t_catalog_find(query: str = "", limit: int = 10, **_: Any) -> dict:
    найденные = catalog.найти(query, int(limit))
    return {
        "запрос": query,
        "найдено": len(найденные),
        "модели": [
            {"имя": м["имя"], "раздел": м["раздел"], "тип": м["тип"],
             "производитель": м["производитель"]}
            for м in найденные
        ],
    }


def t_catalog_add(name: str = "", **_: Any) -> dict:
    """Ставит модель из каталога в сцену."""
    найденные = catalog.найти(name, 5)
    if not найденные:
        return {"error": f"в каталоге нет модели по запросу «{name}»"}

    модель = найденные[0]

    # Модели ставятся только в исходную сцену, на отметке 0:00:00. Мост после
    # вставки фиксирует расстановку как исходное состояние, иначе сброс
    # сваливает компоненты шаблона в точку (0, 0, 0). Посреди прогона
    # фиксировать нельзя, поэтому сначала возвращаемся в начало.
    сброшено = None
    сим = client.simulation("status")
    if сим.get("running") or сим.get("time_sec", 0) > 0:
        # после самоостановки пустой симуляции часы на 0,001 с — это не прогон
        сброшено = сим.get("time") if сим.get("running") or сим.get("time_sec", 0) >= 1 else None
        client.simulation("reset")

    было = client.status()["component_count"]

    # Загрузку делает сама R-Pro: адрес из каталога она понимает и скачивает
    # модель при необходимости. Шаблон планировки приносит сразу десятки
    # компонентов, поэтому считаем их до и после.
    код = (
        "comp = app.load(%s)\n"
        "result = {'имя_компонента': comp.Name if comp is not None else None,\n"
        "          'компонентов_в_сцене': len(app.Components)}"
    ) % json.dumps(модель["адрес"], ensure_ascii=False)

    итог = client.exec_python(код)
    стало = (итог.get("result") or {}).get("компонентов_в_сцене", было)
    ответ = {
        "добавлено": модель["имя"],
        "тип": модель["тип"],
        "раздел": модель["раздел"],
        "компонентов_было": было,
        "компонентов_стало": стало,
        "новых": стало - было,
    }
    if сброшено:
        ответ["симуляция"] = (f"была на отметке {сброшено}; перед вставкой сброшена на "
                              "0:00:00 — модели ставятся только в исходную сцену")
    return ответ


def t_help(query: str = "", source: str = "", limit: int = 2, **_: Any) -> dict:
    """Поиск по справке R-Pro, справке по API и карте интерфейса (kb/).

    По умолчанию два фрагмента: каждый около тысячи токенов, а контекст
    локальной модели — восемь тысяч на весь разговор.
    """
    источники = {
        "справка": ["help"], "api": ["api", "pyhelp"], "интерфейс": ["ui", "shortcuts"],
        "команды": ["commands"], "уроки": ["academy"], "курс": ["iitb"],
    }.get(source or "", None)
    сколько = max(1, min(int(limit), 4))
    найдено = найденные_без_повторов(kb.search(query, сколько + 8, источники))
    ещё = []
    for f in найдено[сколько:]:
        раздел = f["title"].split(" / ", 1)[-1]
        if раздел not in ещё:
            ещё.append(раздел)
    return {
        "запрос": query,
        "подразумевается": glossary.expand(query),
        "фрагменты": [
            {"раздел": f["title"] + (f" (часть {f['part']})" if f["part"] else ""),
             "источник": f["source"], "текст": f["text"]}
            for f in найдено[:сколько]
        ],
        # Названия других подходящих разделов: запрос с таким названием
        # вернёт этот раздел первым.
        "ещё_разделы": ещё[:5],
    }


def найденные_без_повторов(фрагменты: list[dict]) -> list[dict]:
    """Соседние части одной страницы полезны, одна и та же — нет."""
    видели, итог = set(), []
    for ф in фрагменты:
        ключ = (ф["title"], ф["part"])
        if ключ not in видели:
            видели.add(ключ)
            итог.append(ф)
    return итог


def t_build_line(stations: list[str] | str | None = None, length_m: float = 60.0,
                 row_m: float = 24.0, product: str = "", interval_s: float = 20.0,
                 process_s: float = 4.0, clear: bool = False, run_s: float = 0.0,
                 sim_speed: float = 2.0, robot: str = "", **_: Any) -> dict:
    """Построить производственную линию целиком (line_builder.py)."""
    import line_builder
    if isinstance(stations, str):
        stations = [s.strip() for s in stations.replace(";", ",").split(",") if s.strip()]
    if not stations:
        stations = ["станок"] * 4
    # Защита от фантазий модели: линия в километр строилась бы полчаса.
    spec = line_builder.LineSpec(
        stations=list(stations)[:30], length_m=max(10.0, min(float(length_m), 300.0)),
        row_m=max(10.0, min(float(row_m), 60.0)), product=product or "",
        interval_s=max(3.0, float(interval_s)), process_s=max(1.0, float(process_s)),
        clear=bool(clear), run_s=max(0.0, float(run_s)), sim_speed=max(0.5, min(float(sim_speed), 10.0)),
        robot=robot or "")
    report = line_builder.LineBuilder(client).build(spec)
    # Полный маршрут — десятки шагов; модели с контекстом в 8 тысяч хватит числа.
    report["шагов_маршрута"] = len(report.pop("маршрут", []))
    report["что_дальше"] = ("Линия готова. Чтобы увидеть работу, запусти симуляцию "
                            "(первые детали доходят до станков за 20–30 с).")
    return report


def t_build_plant(product_a: str = "", product_b: str = "коробка",
                  ground_a: list[str] | str | None = None, ground_b: list[str] | str | None = None,
                  upper_a: list[str] | str | None = None, upper_b: list[str] | str | None = None,
                  shared: str = "контроль", interval_s: float = 25.0, process_s: float = 4.0,
                  sim_speed: float = 3.0, robot: str = "", clear: bool = False, **_: Any) -> dict:
    """Двухэтажный цех: две линии внизу, станции наверху, общий хаб и отгрузка."""
    import plant_builder

    def as_list(v, default):
        if isinstance(v, str):
            v = [s.strip() for s in v.replace(";", ",").split(",") if s.strip()]
        return list(v)[:3] if v else default

    ps = plant_builder.PlantSpec(
        product_a=product_a or "", product_b=product_b or "",
        ground_a=as_list(ground_a, ["токарный"]), ground_b=as_list(ground_b, ["фрезерный"]),
        upper_a=as_list(upper_a, ["фрезерный"]), upper_b=as_list(upper_b, ["токарный"]),
        shared=shared or "контроль", interval_s=max(5.0, float(interval_s)),
        process_s=max(1.0, float(process_s)), sim_speed=max(0.5, min(float(sim_speed), 10.0)),
        robot=robot or "", clear=bool(clear))
    report = plant_builder.PlantBuilder(client).build_plant(ps)
    report["что_дальше"] = ("Цех готов. Запусти симуляцию: детали обеих линий поднимаются по "
                            "спиралям, проходят общий контроль и спускаются на общую отгрузку "
                            "(первые доходят до выхода примерно за 4–5 минуты модельного времени).")
    return report


def t_build_assembly(product: str = "двигатель", area_m2: float = 1000.0, hall_x_m: float = 0.0,
                     hall_y_m: float = 0.0, block_every_s: float = 40.0, sim_speed: float = 3.0,
                     robot: str = "", clear: bool = False, **_: Any) -> dict:
    """Сборочная линия: изделие собирается из деталей пост за постом (assembly_builder.py).
    Двигатель — по отлаженному плану, остальное — по набору изделия (kits.py)."""
    import assembly_builder
    import kits
    words = (product or "двигатель").lower()
    engine = any(w in words for w in ("двиг", "мотор", "двс", "v8", "engine"))
    kit = None if engine else kits.find_kit(words)
    if not engine and kit is None:
        known = ["двигатель V8"] + sorted(kits.load_kits())
        return {"ошибка": f"Набора деталей для «{product}» нет.",
                "умею_собирать": known,
                "что_можно": "Собрать одно из этих изделий или линию механообработки со станками. "
                             "Новое изделие появляется, когда его набор снят с каталожной планировки, "
                             "где сборка уже описана."}
    if engine:
        need, where = list(assembly_builder.PARTS.values()), assembly_builder.PARTS_DIR
    else:
        # детали узла (ШПГ в КШМ) лежат в папке своего набора — путь в "path"
        need = [p.get("path") or os.path.join(kit["folder"], p["file"]) for p in kit["parts"].values()]
        where = kit["folder"]
    missing = [os.path.basename(f) for f in need if not os.path.isfile(os.path.join(where, f))]
    if missing:
        return {"ошибка": "Нет моделей деталей: " + ", ".join(missing), "где_ждём": where,
                "что_можно": "Детали сохраняются с каталожной планировки изделия "
                             "(см. docs/09-sborochnaya-liniya.md)."}
    # Двигателю с 11 постами, 6 роботами и участком подсборки нужно ~37 × 21 м,
    # короткой линии в один ряд — меньше.
    min_x, min_y = (37.0, 21.0) if engine else (30.0, 14.0)
    if hall_x_m <= 0 or hall_y_m <= 0:
        area = max(float(area_m2 or 1000.0), 1.0)
        hall_x_m = round((area * 1.6) ** 0.5, 1)
        hall_y_m = round(area / hall_x_m, 1)
    if hall_x_m < min_x or hall_y_m < min_y:
        return {"ошибка": f"Цех {hall_x_m} × {hall_y_m} м мал: этой линии нужно не меньше "
                          f"{min_x:.0f} × {min_y:.0f} м (~{min_x * min_y:.0f} м²).",
                "что_можно": "Увеличить цех."}
    spec = assembly_builder.AssemblySpec(
        hall_x_m=float(hall_x_m), hall_y_m=float(hall_y_m),
        block_every_s=max(10.0, float(block_every_s)), sim_speed=max(0.5, min(float(sim_speed), 10.0)),
        robot=robot or "", clear=bool(clear))
    builder = assembly_builder.AssemblyLineBuilder(client)
    if engine:
        report = builder.build_engine(spec)
        report["что_дальше"] = ("Линия готова. Запусти симуляцию: первый двигатель проходит все посты "
                                "примерно за 8 минут модельного времени, дальше — в среднем раз в 75 с "
                                "(около 48 в час). Самые загруженные — сборщики поршней.")
    else:
        report = builder.build_kit(spec, kit)
        report["что_дальше"] = ("Линия готова. Запусти симуляцию; чтобы узнать выпуск и узкое место — "
                                "отчёт по прогону.")
    return report


def t_assembly_kit(layout: str = "", title: str = "", clear: bool = False, **_: Any) -> dict:
    """Снять набор изделия с каталожной планировки (kits.py + kit_scan.py).
    Планировку нужно открыть в пустой сцене — это очистка, только по просьбе."""
    import kit_scan
    import kits
    found = [m for m in catalog.найти(layout, 8) if m["тип"] == "планировка"]
    if not found:
        return {"ошибка": f"Планировки «{layout}» в каталоге нет."}
    m = found[0]
    # Очищает сцену только человек командой /очистить (intents.py): модель 8B
    # передавала clear=true сама — и сносила чужую работу (журнал 13.10)
    if client.status().get("component_count", 0):
        return {"ошибка": "Чтобы снять набор, планировку нужно открыть в пустой сцене, а в сцене "
                          "есть компоненты. Сам сцену не очищай: предложи пользователю команду "
                          "/очистить, после неё повтори.", "планировка": m["имя"]}
    client.simulation("reset")
    kits._run(client, "app.clearWorld()\ntry:\n    app.load(%r)\nexcept Exception:\n    pass\n"
                      "result = len(app.Components)" % m["адрес"])
    asm = kits._run(client, kit_scan.PROBE)
    names = kit_scan.candidates(asm)
    if not names:
        return {"ошибка": f"В планировке «{m['имя']}» нет описанной сборки изделия "
                          "(тип продукта «Сборка» с деталями).",
                "сборки_в_планировке": list(asm)}
    made = []
    for name in names:
        folder = "Набор — " + m["имя"] + ("" if len(names) == 1 else " — " + name)
        kit = kits.extract(client, name, folder, title=title or f"{m['имя']}: {name}",
                           keywords=[w for w in (title or m["имя"]).lower().split() if len(w) > 3],
                           source=m["адрес"])
        made.append({"набор": kit["title"], "деталей": len(kit["parts"]), "шагов": len(kit["steps"])})
    return {"планировка": m["имя"], "наборы": made,
            "что_дальше": "Теперь это изделие можно собрать сборочной линией (rpro_build_assembly)."}


def t_customer_kit(folder: str = "", title: str = "", **_: Any) -> dict:
    """Набор изделия из моделей заказчика: папка с CAD и спецификацией (customer_kit.py)."""
    import customer_kit
    path = customer_kit.find_folder(folder)
    if path is None:
        known = sorted(os.listdir(customer_kit.CUSTOMERS)) if os.path.isdir(customer_kit.CUSTOMERS) else []
        return {"ошибка": f"Папки заказчика «{folder}» не нашёл.", "папки_заказчиков": known,
                "где_ищу": customer_kit.CUSTOMERS}
    client.simulation("reset")
    kit = customer_kit.build_kit(client, path, title)
    return {"изделие": kit["title"], "кратко": kit["short"], "папка": path,
            "деталей": {n: f"{p['size']:.0f} мм" for n, p in kit["parts"].items()},
            "операций": [s["name"] + (" (без детали)" if s.get("operation") else "")
                         for s in kit["steps"]],
            "ось_вверх_в_CAD": kit["up_axis"], "такт_заказчика_с": kit.get("takt_s"),
            "что_дальше": f"Набор готов. Строй линию: rpro_build_assembly(product=«{kit['short']}»)."}


def t_build_factory(customer: str = "", floor_h_m: float = 0.0, speed: float = 500.0,
                    sim_speed: float = 5.0, clear: bool = False, **_: Any) -> dict:
    """Многоэтажный завод по моделям заказчика (factory_builder.py): на этаже —
    линия своего изделия, узлы едут между этажами на лифтах."""
    import customer_kit
    import factory_builder
    found = factory_builder.find_factory(customer)
    if found is None:
        known = sorted(os.listdir(customer_kit.CUSTOMERS)) if os.path.isdir(customer_kit.CUSTOMERS) else []
        return {"ошибка": f"У заказчика «{customer}» нет описания завода («Завод.csv»: этажи и изделия).",
                "папки_заказчиков": known,
                "что_можно": "Если завод одноэтажный — принять модели (rpro_customer_kit) и построить "
                             "линию (rpro_build_assembly)."}
    spec = factory_builder.FactorySpec(customer=customer, floor_h_m=float(floor_h_m or 0.0),
                                       speed=max(200.0, min(float(speed or 500.0), 1500.0)),
                                       sim_speed=max(0.5, min(float(sim_speed or 5.0), 10.0)),
                                       clear=bool(clear))
    return factory_builder.FactoryBuilder(client).build_factory(spec)


def t_link_lines(supplier: str = "", consumer: str = "", agvs: int = 2, **_: Any) -> dict:
    """Связать участки: готовые узлы поставщика везут мобильные роботы потребителю."""
    import plant_link
    return plant_link.link_lines(client, supplier, consumer, max(1, min(int(agvs or 2), 6)))


def t_line_tune(conveyor_speed: float | None = None, feed_every_s: float | None = None,
                post: str = "", work_s: float | None = None, **_: Any) -> dict:
    """«Что если» правкой на месте: скорость лент, частота подачи, время поста."""
    client.simulation("reset")
    args = "conveyor_speed=%r, feed_every_s=%r, post=%r, work_s=%r" % (
        None if conveyor_speed is None else float(conveyor_speed),
        None if feed_every_s is None else float(feed_every_s),
        post or None, None if work_s is None else float(work_s))
    import kits
    done = kits._run(client, "result = tune_line(%s)" % args)
    return {"изменено": done,
            "что_дальше": "Проверь эффект: отчёт по прогону (minutes 20–30) и сравни выпуск после разгона."}


def t_line_report(run_s: float = 0.0, minutes: float = 0.0, speed: float = 20.0, **_: Any) -> dict:
    """Отчёт по прогону: выпуск, загрузка людей, роботов и постов, узкое место (line_report.py)."""
    import line_report
    run = float(run_s or 0.0) or float(minutes or 0.0) * 60.0
    # Час модельного времени на ×20 — это 3 минуты ожидания. Заводу на этажах
    # нужно до получаса на заполнение, поэтому до двух часов, но не дольше.
    run = max(0.0, min(run, 7200.0))
    rep = line_report.report(client, run_s=run, speed=max(1.0, min(float(speed), 30.0)))
    # Цель заказчика (такт из спецификации) — сравнить прямо: на вопрос «выйдем
    # ли на 60 в час?» модель иначе пересказывает цифры, не отвечая.
    try:
        import kits
        steady = rep.get("после_разгона") or {}
        by_line = steady.get("по_линиям_в_час") or {}
        for kit in kits.load_kits().values():
            takt = kit.get("takt_s")
            if not takt:
                continue
            short = (kit.get("short") or "").lower()
            rate = next((v for k, v in by_line.items() if k.lower().startswith(short)), None)
            if rate is None:
                # этаж завода, отдающий узел на лифт: выпуск участка по его префиксу
                rate = next((v for k, v in (steady.get("участки_в_час") or {}).items()
                             if k.lower() == short), None)
            sinks = [s.lower() for s in rep.get("склады_отгрузки", [])]
            # одна линия в сцене — её склад отгрузки называется «<кратко> отгрузка»
            if rate is None and not by_line and short and sinks == [f"{short} отгрузка"]:
                rate = steady.get("в_час", rep.get("в_час"))
            if rate is None:
                continue
            goal = round(3600.0 / float(takt), 1)
            rep.setdefault("цель_заказчика", {})[kit["title"]] = {
                "нужно_в_час": goal, "есть_в_час": rate,
                "выполняется": rate >= goal,
                "запас_%": round((rate / goal - 1.0) * 100.0)}
    except Exception:  # noqa: BLE001 — сравнение необязательно, отчёт важнее
        pass
    # Полный список процессов модели не нужен — хватит загрузки и вывода.
    procs = rep.pop("процессы", {})
    if procs:
        rep["процессов_учтено"] = len(procs)
    global LAST_REPORT
    LAST_REPORT = rep      # итог отчёта в ответе пишет код (chat._loop), а не модель
    return rep


LAST_REPORT: dict | None = None


def t_line_check(**_: Any) -> dict:
    """Диагноз линии: досягаемость по станциям и ошибки прогона (line_doctor.py)."""
    import line_doctor
    return line_doctor.LineDoctor(client).check()


def t_line_fix(action: str = "auto", station: str | int = "", model: str = "",
               mm: float | None = None, seconds: float | None = None, **_: Any) -> dict:
    """Точечная правка линии: не пересобираем, а чиним станцию."""
    import line_doctor
    doc = line_doctor.LineDoctor(client)
    a = (action or "auto").lower()
    n = str(station).strip()
    if a in ("auto", "авто", "всё", "все"):
        return doc.auto_fix()
    if not n:
        return {"error": "укажи номер станции (station), его видно в rpro_line_check"}
    if a in ("closer", "ближе", "сдвинуть"):
        return doc.closer(n, mm)
    if a in ("replace", "заменить", "замена"):
        return doc.replace(n, model or "")
    if a in ("robot", "робот"):
        return doc.robot(n, model or "")
    if a in ("time", "время"):
        if seconds is None:
            return {"error": "для action=время нужно seconds"}
        return doc.process_time(n, seconds)
    return {"error": f"неизвестное действие {action}: auto, ближе, заменить, время"}


def t_robot_cell(deltas: list[float] | None = None, **_: Any) -> dict:
    """Ячейка переноса цилиндров (Модуль B): ячейка по приложению, программа,
    проверка столкновений с подбором поворота захвата, KRL .src/.dat (robot_cell.py)."""
    import robot_cell
    res = robot_cell.build_cell(RProClient(timeout=600), deltas=tuple(deltas or (0, 15, 30, 45, 60)))
    res.pop("шаги", None)   # подробности шагов модели не нужны — хватит итога
    return res


def _techskills_path() -> None:
    import sys as _sys
    root = Path(__file__).resolve().parent.parent / "test_task"
    for sub in ("common", "moduleA", "moduleC", "field"):
        p = str(root / sub)
        if p not in _sys.path:
            _sys.path.insert(0, p)


def t_lean_c(**_: Any) -> dict:
    """Модуль C (Lean Six Sigma): исходная модель сборки двигателя → замер смены →
    оптимизация → замер → VSM/Yamazumi (PDF), дешборды и презентация (.pptx)."""
    _techskills_path()
    import lean_c
    # название команды и роли в презентации заполняет сама команда (модель
    # 8B придумывала «Команда_Двигатель_Оптимизация»)
    return lean_c.run(client=RProClient(timeout=900))


def t_pharma_plant(minutes: float = 60.0, **_: Any) -> dict:
    """Модуль A: фармпроизводство целиком и прогон minutes минут со статистикой выпуска."""
    _techskills_path()
    import plant_a
    m = max(10, min(480, int(minutes or 60)))
    return plant_a.run(minutes=m, client=RProClient(timeout=1200))


def t_techskills_field(minutes: float = 10.0, **_: Any) -> dict:
    """Все три модуля TechSkills на одном поле и совместный прогон."""
    _techskills_path()
    import field
    return field.build(minutes=max(2.0, min(60.0, float(minutes or 10))), client=RProClient(timeout=1200))


_DRESS_CODE = """
had_floor = any(_u(c.Name).startswith(u"Пол") for c in app.Components)
b = site_bounds()
res = {"подставок_заменено": dress_stands()}
if not had_floor and b[0] < b[2]:
    dress_floor(b[0] - 1500.0, b[1] - 1500.0, b[2] + 1500.0, b[3] + 1500.0, u"цех", [0.40, 0.50, 0.45])
    res["пол_м"] = [round((b[2] - b[0]) / 1000.0 + 3, 1), round((b[3] - b[1]) / 1000.0 + 3, 1)]
res["стен_и_зон_оформлено"] = dress_restyle()
res["скрыто_корпусов_ТК"] = dress_hide_controllers()
app.Simulation.setInitialState()
result = res
"""


def t_dress_scene(**_: Any) -> dict:
    """Оформить построенную сцену: пол, столы вместо подставок-заглушек, стиль
    стен и зон прохода, скрыть служебные диски ТК. Процессы не меняются."""
    _techskills_path()
    from r27 import R27
    r = R27(RProClient(timeout=600), libs=("hands", "pharma", "site", "dress"))
    return r.run(_DRESS_CODE)


def t_exec(code: str = "", **_: Any) -> dict:
    if not config.ALLOW_EXEC:
        return {"error": "Выполнение кода запрещено настройкой RPRO_ALLOW_EXEC=0."}
    return client.exec_python(code)


# --- описания для модели ---------------------------------------------------

TOOLS: list[dict] = [
    _tool("rpro_status",
          "Общее состояние R-Pro: открытый проект, режим, число компонентов, "
          "идёт ли симуляция, что выделено.", {}),
    _tool("rpro_scene",
          "Список компонентов сцены с координатами в мировой системе.",
          {"limit": {"type": "integer", "description": "Сколько компонентов вернуть (по умолчанию 100)."}}),
    _tool("rpro_find",
          "Найти компоненты, в имени которых встречается подстрока.",
          {"query": {"type": "string", "description": "Часть имени компонента."}},
          ["query"]),
    _tool("rpro_component",
          "Подробности компонента: свойства с текущими значениями, при необходимости поведения.",
          {"name": {"type": "string", "description": "Точное имя компонента."},
           "with_behaviours": {"type": "boolean", "description": "Добавить список поведений."}},
          ["name"]),
    _tool("rpro_messages",
          "Последние строки панели вывода R-Pro: предупреждения, ошибки, печать скриптов.",
          {"tail": {"type": "integer", "description": "Сколько последних строк вернуть."}}),
    _tool("rpro_simulation",
          "Управление симуляцией. Все запуски идут в реальном времени, как кнопкой «Пуск», "
          "и сразу возвращают ответ: симуляция продолжает идти сама.\n"
          "status — состояние и текущая отметка времени;\n"
          "run — запустить без остановки;\n"
          "run_for + seconds — идти seconds секунд ОТ ТЕКУЩЕЙ отметки и остановиться "
          "(«запусти на 30 секунд», «погоняй минуту»);\n"
          "run_until + until — оказаться НА ОТМЕТКЕ until на часах симуляции и остановиться "
          "(«запусти до 0:01:35» → until=95). Это же перемотка: «отмотай/перемотай/верни "
          "на первую секунду», «на 0:00:10» → run_until с until=1 / 10. Если часы уже "
          "дальше отметки, мост сам сбросит симуляцию и прогонит её с нуля; reset заранее "
          "не нужен. «На N секунд вперёд» — это run_for, «на N-ю секунду» — run_until;\n"
          "halt — остановить; reset — сбросить в начало (0:00:00).\n"
          "Время в ответе пользователю бери только из полей time и stop_at результата.",
          {"action": {"type": "string",
                      "enum": ["status", "run", "run_for", "run_until", "halt", "reset"]},
           "seconds": {"type": "number",
                       "description": "Для run_for: сколько секунд идти от текущей отметки."},
           "until": {"type": "number",
                     "description": "Для run_until: отметка в секундах, 0:01:35 = 95."}},
          ["action"]),
    _tool("rpro_select",
          "Выделить компоненты в 3D-виде, чтобы показать их пользователю.",
          {"names": {"type": "array", "items": {"type": "string"},
                     "description": "Имена компонентов."}},
          ["names"]),
    _tool("rpro_set_property",
          "Изменить значение свойства компонента. Только по явной просьбе пользователя.",
          {"component": {"type": "string"},
           "property": {"type": "string"},
           "value": {"type": "string", "description": "Новое значение."}},
          ["component", "property", "value"]),
    _tool("rpro_look",
          "Посмотреть на окно R-Pro глазами модели зрения и получить описание: 3D-вид, "
          "дерево компонентов, лента, панель вывода. Полезно, когда нужно понять, что "
          "именно видит пользователь.",
          {"question": {"type": "string", "description": "Вопрос по картинке."}},
          ["question"]),
    _tool("rpro_catalog_find",
          "Найти модель в каталоге R-Pro: роботы, конвейеры, станки, захваты, шаблоны "
          "планировок — около трёх тысяч моделей. Это не сцена, а библиотека готовых "
          "моделей. Сюда стоит заглянуть, если компонента нет в сцене.",
          {"query": {"type": "string", "description": "Слова из названия, например «двойной захват» или «конвейер»."},
           "limit": {"type": "integer", "description": "Сколько моделей вернуть."}},
          ["query"]),
    _tool("rpro_catalog_add",
          "Поставить модель из каталога в сцену. Меняет модель пользователя — только по "
          "явной просьбе. Шаблон планировки приносит сразу десятки компонентов.",
          {"name": {"type": "string", "description": "Название модели из каталога."}},
          ["name"]),
    _tool("rpro_build_line",
          "Построить ЦЕЛУЮ работающую производственную линию одним вызовом: подача "
          "деталей, конвейеры змейкой через цех с поворотами, станции «робот + станок» "
          "(настоящие станки Haas, Hurco, Tongtai, Feeler, Goodway, контроль Mapvision), "
          "финишный робот и выход. Логика процесса настраивается сама: после запуска "
          "симуляции детали идут по линии, роботы загружают станки. Используй на поручения "
          "вроде «собери линию», «построй цех», «сделай конвейерную линию со станками». "
          "Строится 1–2 минуты, линия растёт на глазах.",
          {"stations": {"type": "array", "items": {"type": "string"},
                        "description": "Станции по порядку. Слова: «фрезерный», «токарный», "
                                       "«станок» (чередует фрезерный и токарный), «контроль» "
                                       "(контроль качества), «пятиосевой», «портальный», «сборка», "
                                       "«перекладка» (робот без станка). Например 6 станков и "
                                       "контроль: [\"станок\",\"станок\",\"станок\",\"станок\","
                                       "\"станок\",\"станок\",\"контроль\"]."},
           "length_m": {"type": "number",
                        "description": "Общая длина конвейера в метрах (по умолчанию 60, до 300). "
                                       "«Во весь цех», «длинная» — 100–150."},
           "row_m": {"type": "number", "description": "Длина одного ряда змейки, м (по умолчанию 24)."},
           "product": {"type": "string", "description": "Что едет по линии: «коробка», «банка», "
                                                         "«бутылка»… Пусто — цилиндрическая заготовка."},
           "interval_s": {"type": "number", "description": "Подача детали раз в N секунд (20)."},
           "process_s": {"type": "number", "description": "Время обработки в станке, с (4)."},
           "run_s": {"type": "number",
                     "description": "Сразу запустить симуляцию на N секунд (0 — не запускать)."},
           "sim_speed": {"type": "number", "description": "Ускорение симуляции (2 = вдвое быстрее)."},
           "robot": {"type": "string", "enum": ["", "abb", "kuka", "fanuc", "yaskawa"],
                     "description": "Марка роботов. Пусто — разные марки вперемешку."}},
          []),
    _tool("rpro_build_plant",
          "Построить ДВУХЭТАЖНЫЙ цех со связанными процессами одним вызовом: на первом "
          "этаже две линии (A и B) со своими станциями, спиральные конвейеры поднимают обе "
          "на второй этаж (перекрытие на опорах, лестница), там у каждой своя станция, затем "
          "оба потока сходятся к ОБЩЕМУ роботу и общей станции (контроль качества), общая "
          "лента спускается скатом на первый этаж к общей отгрузке. Используй на просьбы "
          "«двухэтажный цех/линия», «второй этаж», «антресоль», «потоки сходятся», "
          "«общий контроль для двух линий». Строится около минуты.",
          {"product_a": {"type": "string", "description": "Что едет по линии A (пусто — заготовка-цилиндр)."},
           "product_b": {"type": "string", "description": "Что едет по линии B (по умолчанию коробка)."},
           "ground_a": {"type": "array", "items": {"type": "string"},
                        "description": "Станции линии A на первом этаже (1–3): «токарный», «фрезерный», «станок»…"},
           "ground_b": {"type": "array", "items": {"type": "string"}, "description": "То же для линии B."},
           "upper_a": {"type": "array", "items": {"type": "string"},
                       "description": "Станции линии A на втором этаже (1–3)."},
           "upper_b": {"type": "array", "items": {"type": "string"}, "description": "То же для линии B."},
           "shared": {"type": "string", "description": "Общая станция наверху: «контроль» (по умолчанию), «сборка»…"},
           "interval_s": {"type": "number", "description": "Подача детали раз в N секунд на каждой линии (25)."},
           "robot": {"type": "string", "enum": ["", "abb", "kuka", "fanuc", "yaskawa"]}},
          []),
    _tool("rpro_build_assembly",
          "Построить СБОРОЧНУЮ линию одним вызовом: изделие собирается из деталей пост за "
          "постом, а не обрабатывается станками. Умею собирать: двигатель V8, "
          + ", ".join(_kit_titles()) + ". Двигатель: роботы ставят блок, коленвал, 8 поршней и "
          "головки блока, операторы — пластину, прокладки, затяжку, испытание; внутри линии "
          "подсборка поршней; 11 постов + 4 подсборки, цех 1000 м². Остальные изделия: шаг "
          "сборки — пост, крупное ставит робот, мелкое — оператор, в конце контроль и "
          "выгрузка. Используй на просьбы «сборочная линия», «собрать <изделие>», «сборка "
          "из деталей», «конвейер сборки», «компонентная сборка». Строится около минуты.",
          {"product": {"type": "string", "description": "Что собираем: «двигатель», «дверь»… "
                                                          "Если такого набора нет — инструмент скажет, что есть."},
           "area_m2": {"type": "number", "description": "Площадь цеха, м² (по умолчанию 1000, не меньше ~800)."},
           "hall_x_m": {"type": "number", "description": "Длина цеха, м (если названы размеры, а не площадь)."},
           "hall_y_m": {"type": "number", "description": "Ширина цеха, м."},
           "block_every_s": {"type": "number", "description": "Склад выдаёт блок не чаще раза в N секунд (40)."},
           "sim_speed": {"type": "number", "description": "Ускорение симуляции (3)."},
           "robot": {"type": "string", "enum": ["", "abb", "kuka", "fanuc", "yaskawa"]}},
          []),
    _tool("rpro_assembly_kit",
          "Научиться собирать новое изделие: открыть каталожную планировку, где его сборка "
          "уже описана, и снять набор — детали, шаги, гнёзда. После этого изделие можно "
          "собрать сборочной линией. Планировка открывается в ПУСТОЙ сцене; если в сцене "
          "что-то есть, инструмент откажет — тогда предложи пользователю команду /очистить.",
          {"layout": {"type": "string", "description": "Название каталожной планировки, например "
                                                       "«Сборка наружного блока»."},
           "title": {"type": "string", "description": "Как назвать изделие по-русски (необязательно)."}},
          ["layout"]),
    _tool("rpro_customer_kit",
          "Принять модели заказчика: папка с CAD-файлами деталей (STEP, STL, IGES, OBJ…) и "
          "сборочной спецификацией (CSV: операция, деталь, файл, кто, время). Детали "
          "импортируются, места деталей берутся из координат сборки, операции без деталей "
          "(затяжка, контроль) становятся рабочими постами. После этого изделие строится "
          "сборочной линией. Папки заказчиков — в «Документы\\Заказчики»; можно назвать "
          "часть имени («МоторКомплект»).",
          {"folder": {"type": "string", "description": "Папка заказчика: путь или часть имени."},
           "title": {"type": "string", "description": "Название изделия (если нет в спецификации)."}},
          ["folder"]),
    _tool("rpro_build_factory",
          "Построить МНОГОЭТАЖНЫЙ сборочный завод по моделям заказчика одним вызовом: на "
          "каждом этаже — роботизированная линия своего изделия (например, плата BMS → "
          "батарейный модуль → тяговая батарея), узлы едут между этажами на лифтах. Роботы "
          "ставят детали, клеят, наносят герметик и пасту, паяют, сваривают, закручивают "
          "болты и контролируют качество с изолятором брака; швы, пайка и болты появляются "
          "на изделии. Этажи, изделия и цели берутся из «Завод.csv» в папке заказчика; модели "
          "и спецификации принимаются сами. Используй на просьбы «многоэтажный завод», "
          "«завод на N этажей», «завод заказчика <имя>», «склейка/пайка роботами». Строится "
          "несколько минут.",
          {"customer": {"type": "string", "description": "Заказчик: часть имени папки («ЭлектроТяга»)."},
           "floor_h_m": {"type": "number", "description": "Высота этажа, м (0 — из описания завода)."},
           "speed": {"type": "number", "description": "Скорость лент, мм/с (500)."},
           "sim_speed": {"type": "number", "description": "Ускорение симуляции (5)."}},
          ["customer"]),
    _tool("rpro_link_lines",
          "Связать два участка в одной сцене: готовые узлы участка-поставщика (например ШПГ) "
          "мобильные роботы (AGV) возят на участок-потребитель (например КШМ), где их ставят "
          "в изделие. Склады узла у потребителя становятся перевалками, маршрут узла "
          "продолжается до постов потребителя. Поставщик должен быть построен раньше "
          "потребителя. После связки — отчёт по прогону покажет узкое место завода.",
          {"supplier": {"type": "string", "description": "Изделие участка-поставщика: «ШПГ»."},
           "consumer": {"type": "string", "description": "Изделие участка-потребителя: «КШМ»."},
           "agvs": {"type": "integer", "description": "Сколько мобильных роботов (по умолчанию 2)."}},
          ["supplier", "consumer"]),
    _tool("rpro_line_tune",
          "«Что если» правкой на месте, без пересборки: скорость лент (conveyor_speed, мм/с), "
          "как часто подаётся базовая деталь (feed_every_s, с), время операции на посту "
          "(post — часть имени поста, work_s — секунды). После правки — отчёт по прогону "
          "и сравнение выпуска.",
          {"conveyor_speed": {"type": "number", "description": "Скорость всех лент, мм/с (обычно 400–1000)."},
           "feed_every_s": {"type": "number", "description": "Подача базовой детали раз в N секунд."},
           "post": {"type": "string", "description": "Часть имени поста: «Затяжка», «П7»…"},
           "work_s": {"type": "number", "description": "Новое время операции на этом посту, с."}},
          []),
    _tool("rpro_line_report",
          "Отчёт по работе линии или цеха: сколько изделий выпущено и сколько в час, средний "
          "такт, загрузка людей, роботов и постов, УЗКОЕ МЕСТО с советом, недогруженные "
          "бригады, ошибки в выводе. Работает с любой линией в сцене. Используй на вопросы "
          "«сколько выпускает», «какая производительность», «где узкое место», «почему "
          "медленно», «кто перегружен», «проанализируй линию», а также после правки — "
          "проверить, стало ли лучше. Если симуляция не запускалась или нужен свежий "
          "прогон — задай minutes (прогон с нуля, ускоренно; 15–30 минут модельного времени "
          "занимают 1–2 минуты).",
          {"minutes": {"type": "number",
                       "description": "Прогнать с нуля столько минут модельного времени (0 — "
                                      "считать по уже сделанному прогону). Обычно 15–30."},
           "speed": {"type": "number", "description": "Ускорение прогона (20)."}},
          []),
    _tool("rpro_line_check",
          "Проверить построенную линию: по каждой станции — станок, робот и достаёт ли "
          "робот до съёма, станка и укладки; плюс ошибки последнего прогона симуляции, "
          "привязанные к станциям. Вызывай, когда пользователь говорит, что линия "
          "работает не так, робот стоит, есть ошибка, или после стройки для отчёта.", {}),
    _tool("rpro_robot_cell",
          "Робот-ячейка переноса цилиндров (задание Модуля B TechSkills, KUKA KR 10): открыть "
          "выданную ячейку, задать TOOL_DATA[12], BASE_DATA[13]/[14], сигналы захвата OUT7/OUT8, "
          "поставить ложементы и 3 цилиндра, написать программу (подпрограммы, комментарии, "
          "15 % / 0,1 м/с), проверить её прогоном на столкновения, подобрать поворот захвата, "
          "при котором столкновений нет, и выгрузить программу на KRL (.src/.dat). Вызывай, когда "
          "просят ячейку с цилиндрами, перенос цилиндров, программу KRL для KUKA, виртуальную "
          "пусконаладку робота. Сцена при этом заменяется ячейкой.",
          {"deltas": {"type": "array", "items": {"type": "number"},
                      "description": "Какие повороты захвата при укладке перебрать, градусы "
                                     "(по умолчанию 0, 15, 30, 45, 60)."}}),
    _tool("rpro_lean_optimize",
          "Модуль C TechSkills (Lean Six Sigma): открыть выданную модель сборки двигателя, "
          "прогнать смену 480 мин, найти проблемы (перепроизводство, узкое место, ошибки "
          "модели), оптимизировать (канбан на 11 мест, отгрузка по такту 43,6 мин, перебалансировка "
          "людей, исправление сборки, имена процессов, номера ТК, комментарии, стены), прогнать "
          "снова и выпустить VSM и Yamazumi до/после (PDF), дешборды и презентацию .pptx. "
          "Вызывай, когда просят модуль C, бережливое производство, VSM, Yamazumi, оптимизацию "
          "модели двигателя или презентацию L6S. Сцена заменяется моделью.",
          {}),
    _tool("rpro_pharma_plant",
          "Модуль A TechSkills: фармпроизводство целиком — линия сиропа (разлив с браком 5 %, "
          "ОТК с окраской, утилизация, укупорка, укладка по 36), линия таблеток (блистерная "
          "машина с подачей контейнеров по сигналам, ОТК, ручная сборка упаковок 5 блистеров, "
          "короба по 48), паллетизация 6+6, склады, мобильные роботы, погрузчик, стены, забор, "
          "зоны, огнетушители; прогон и статистика выпуска (CSV, XLSX, PDF), планировка. "
          "Вызывай, когда просят модуль A, фармлинию, сироп и таблетки. Сцена заменяется.",
          {"minutes": {"type": "number", "description": "Сколько минут модели прогнать "
                                                         "(по умолчанию 60; смена — 480, это ~40 мин)."}}),
    _tool("rpro_techskills_field",
          "Все три задания TechSkills на одном поле: ячейка KUKA с пусконаладкой и KRL (B), "
          "оптимизированная сборка двигателя (C) и фармпроизводство (A); короткий общий прогон, "
          "снимки и планировка «Поле_TechSkills.rpro». Вызывай, когда просят все модули вместе, "
          "всё тестовое задание, общее поле. Сцена заменяется.",
          {"minutes": {"type": "number", "description": "Минут совместного прогона (10)."}}),
    _tool("rpro_dress_scene",
          "Оформить построенную сцену, чтобы она выглядела как живой цех: пол, столы той же "
          "высоты вместо белых подставок-заглушек, светлые стены высотой 3 м, цветные "
          "полупрозрачные зоны прохода, скрыть служебные диски ТК. Процессы, маршруты и связи "
          "не меняются. Вызывай, когда просят оформить, сделать живее, красивее, реалистичнее.", {}),
    _tool("rpro_line_fix",          "Починить линию ПРАВКОЙ, не пересобирая: action=auto — исправить всё, что нашла "
          "проверка; ближе — подвинуть станок станции к роботу (mm, по умолчанию сколько "
          "нужно); заменить — поставить на станцию другую модель станка (model: «Haas "
          "VF-1», «токарный»… или пусто — следующая модель того же вида); время — время "
          "обработки станка (seconds); робот — сменить робота станции (model: kuka, fanuc, "
          "yaskawa, abb). Остальная линия, маршрут и роботы не трогаются. "
          "НИКОГДА не пересобирай линию из-за ошибки одной станции — чини эту станцию.",
          {"action": {"type": "string", "enum": ["auto", "ближе", "заменить", "время", "робот"]},
           "station": {"type": "string", "description": "Номер станции из проверки: «3», «финиш»."},
           "model": {"type": "string", "description": "Для «заменить»: модель или вид станка; "
                                                       "для «робот»: марка робота."},
           "mm": {"type": "number", "description": "Для «ближе»: на сколько мм (минус — дальше)."},
           "seconds": {"type": "number", "description": "Для «время»: время обработки, с."}},
          ["action"]),
    _tool("rpro_help",
          "Справочник по самой программе R-Pro: как что делается, где кнопка, что "
          "значит свойство, как устроены поведения, операторы процесса и робота, "
          "классы и методы Python-API. Спрашивай своими словами. Загляни сюда ПЕРЕД "
          "тем, как объяснять порядок действий в программе или писать код для rpro_exec: "
          "так ответ опирается на документацию, а не на догадку. Если найденное не про то, "
          "посмотри «ещё_разделы» и спроси ещё раз точным названием раздела оттуда.",
          {"query": {"type": "string",
                     "description": "Вопрос своими словами, например «как подключить сигналы "
                                    "робота к конвейеру» или «vcSimulation setInitialState»."},
           "source": {"type": "string", "enum": ["", "справка", "api", "интерфейс", "команды", "уроки", "курс"],
                      "description": "Где искать: пусто — везде; api — классы и методы "
                                     "Python-API; интерфейс — лента и горячие клавиши; "
                                     "уроки — приёмы и подводные камни из обучающих "
                                     "уроков Visual Components Academy; курс — родной "
                                     "курс ИИТБ Skill Camp по R-Pro (процессы, роботы, "
                                     "склад, сборка, паллетирование, Lean)."},
           "limit": {"type": "integer", "description": "Сколько фрагментов (1–4, по умолчанию 2)."}},
          ["query"]),
    _tool("rpro_exec",
          "Выполнить код Python 2.7 внутри R-Pro. Доступна переменная app (vcApplication) "
          "и весь Python-API. Результат: напечатанное в stdout и переменная result.",
          {"code": {"type": "string", "description": "Код на Python 2.7."}},
          ["code"]),
]

# Инструменты, которые ничего не меняют: их модель получает, когда
# пользователь задал вопрос, а не дал поручение (см. chat._is_question).
# rpro_simulation сюда не входит: через него запускают и сбрасывают.
_CHANGING = {"rpro_simulation", "rpro_set_property", "rpro_catalog_add", "rpro_exec", "rpro_select",
             "rpro_build_line", "rpro_line_fix", "rpro_build_plant", "rpro_build_assembly",
             "rpro_assembly_kit", "rpro_customer_kit", "rpro_line_tune",
             "rpro_link_lines", "rpro_build_factory"}
READ_ONLY_TOOLS: list[dict] = [t for t in TOOLS if t["function"]["name"] not in _CHANGING]

IMPLEMENTATIONS: dict[str, Callable[..., Any]] = {
    "rpro_robot_cell": t_robot_cell,
    "rpro_lean_optimize": t_lean_c,
    "rpro_pharma_plant": t_pharma_plant,
    "rpro_techskills_field": t_techskills_field,
    "rpro_dress_scene": t_dress_scene,
    "rpro_status": t_status,
    "rpro_scene": t_scene,
    "rpro_find": t_find,
    "rpro_component": t_component,
    "rpro_messages": t_messages,
    "rpro_simulation": t_simulation,
    "rpro_select": t_select,
    "rpro_set_property": t_set_property,
    "rpro_look": t_look,
    "rpro_catalog_find": t_catalog_find,
    "rpro_catalog_add": t_catalog_add,
    "rpro_help": t_help,
    "rpro_build_line": t_build_line,
    "rpro_build_plant": t_build_plant,
    "rpro_build_assembly": t_build_assembly,
    "rpro_line_report": t_line_report,
    "rpro_assembly_kit": t_assembly_kit,
    "rpro_customer_kit": t_customer_kit,
    "rpro_line_tune": t_line_tune,
    "rpro_link_lines": t_link_lines,
    "rpro_build_factory": t_build_factory,
    "rpro_line_check": t_line_check,
    "rpro_line_fix": t_line_fix,
    "rpro_exec": t_exec,
}


def run_tool(name: str, arguments: dict) -> str:
    """Выполняет инструмент и возвращает результат текстом для модели."""
    fn = IMPLEMENTATIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"неизвестный инструмент: {name}"}, ensure_ascii=False)

    try:
        result = fn(**(arguments or {}))
    except BridgeError as exc:
        result = {"error": str(exc)}
    except TypeError as exc:
        result = {"error": f"неверные аргументы инструмента: {exc}"}
    except Exception as exc:  # noqa: BLE001 — модель должна увидеть любую ошибку
        result = {"error": f"{type(exc).__name__}: {exc}"}

    text = json.dumps(result, ensure_ascii=False, default=str)
    # Контекст модели — 8 тысяч токенов; длинный ответ инструмента вытесняет
    # системную подсказку. Режем с пометкой, чтобы модель знала, что не всё.
    if len(text) > config.TOOL_OUTPUT_MAX:
        text = text[:config.TOOL_OUTPUT_MAX] + " …(ответ обрезан; уточни запрос)"
    return text
