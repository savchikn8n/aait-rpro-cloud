# -*- coding: utf-8 -*-
"""
Две линии в одну: выход первой → робот-перекладчик → вход второй.

Журнал 08.10: «добавь ещё один замкнутый конвейер рядом и соедини их в одну
линию сборки» — модель 8B вместо этого построила свою отдельную линию со
станками. Здесь это делает код.

Линия — то, что начинается подачей (rProductCreator) и имеет маршрут
(группу потока): шаблон «Замкнутый конвейер» (банки → сборка в коробки на
кольце → разборка → лента выхода → «Раковина»), линии строителя и подобные.

Как соединяем A → B (hands27.line_ends знает у каждой вход и выход):
1. вторую линию ставим так, чтобы её вход был напротив выхода первой, в
   GAP по ходу ленты (место под перекладку) — place_beside;
2. сток на конце выхода A убираем, ставим «Операция "С конвейера"»; подачу B
   убираем, на её место — «Операция "К конвейеру"»; между ними — робот на ТК;
3. маршрут A кончается перекладкой; на укладке деталь меняет тип на тип B
   (ChangeProductType) и дальше идёт маршрутом B, который начинается с
   укладки вместо подачи. Вторая линия остаётся целой: у её сборки гнёзда
   принимают только свой тип, а связи её роботов — только свою группу
   (SupportedGroup у связи только для чтения) — опыт 08.10.

Имена процессов второй копии шаблона R-Pro сама делает уникальными
(AssemblyProcess1_2, группа Can_2) — проверено 08.10.
"""

from __future__ import annotations

import math
import time
from typing import Any

import kits
from rpro_client import RProClient

GAP = 1800.0          # выход A → вход B: съём, укладка и робот между ними (как станция строителя)
SIDE_GAP = 2000.0     # просто «рядом», если линии нельзя поставить вход к выходу


def lines(client: RProClient) -> list[dict]:
    """Линии сцены с входом и выходом (подача → … → лента выхода)."""
    got = kits._run(client, "result = [line_ends(f) for f in feeders_in_scene()]") or []
    return [x for x in got if x.get("вход") and x.get("выход")]


def _heading(m: list[float]) -> tuple[float, float]:
    a = math.radians(m[3])
    return math.cos(a), math.sin(a)


def place_beside(client: RProClient, new_names: list[str]) -> str | None:
    """Только что добавленное (new_names) — рядом с уже стоящим, не поверх.

    Если и у нового, и у прежнего есть вход и выход — вход нового напротив
    выхода прежнего (готово к «соедини их»). Иначе — справа от всего, что
    стоит в сцене, с зазором SIDE_GAP. Возвращает, как поставил, или None."""
    new_set = set(new_names)
    all_lines = lines(client)
    new = [x for x in all_lines if x["подача"] in new_set]
    old = [x for x in all_lines if x["подача"] not in new_set]
    if new and old:
        a, b = old[-1], new[0]
        ux, uy = _heading(a["выход_м"])
        tx, ty = a["выход_м"][0] + ux * GAP, a["выход_м"][1] + uy * GAP
        dx, dy = tx - b["вход_м"][0], ty - b["вход_м"][1]
        how = f"вход второй линии напротив выхода первой, в {GAP / 1000:.1f} м — место под робота-перекладчика"
    else:
        r = kits._run(client, (
            "new = set(_u(n_) for n_ in %r)\nold, nw = [], []\n"
            "for x in _top_components():\n"
            "    b = _world_box(x)\n"
            "    if b is None: continue\n"
            "    (nw if _u(x.Name) in new else old).append(b)\n"
            "result = [max(b[3] for b in old) if old else 0.0, min(b[0] for b in nw) if nw else 0.0]") % list(new_set))
        dx, dy = r[0] + SIDE_GAP - r[1], 0.0
        how = "справа от того, что уже стоит"
    kits._run(client, (
        "new = set(_u(n_) for n_ in %r)\n"
        "for x in _top_components():\n"
        "    if _u(x.Name) in new:\n"
        "        m = vcMatrix.new(x.PositionMatrix)\n"
        "        m.translateAbs(%f, %f, 0.0)\n"
        "        x.PositionMatrix = m\n"
        "app.Simulation.setInitialState()\nresult = 1") % (list(new_set), dx, dy))
    return how


def _pair(all_lines: list[dict], prefer_b: set[str]) -> tuple[dict, dict] | None:
    """Какие две линии соединить: A — чей выход ближе всего ко входу B.
    B — по возможности только что добавленная."""
    best = None
    for a in all_lines:
        if a.get("сток") and "С конвейера" in a["сток"]:
            continue      # выход A уже отдан другой связке
        for b in all_lines:
            if a is b:
                continue
            d = math.hypot(a["выход_м"][0] - b["вход_м"][0], a["выход_м"][1] - b["вход_м"][1])
            key = (0 if b["подача"] in prefer_b else 1, d)
            if best is None or key < best[0]:
                best = (key, a, b)
    return (best[1], best[2]) if best else None


def join(client: RProClient, prefer_b: list[str] | None = None, progress=None) -> str:
    """Соединить две линии сцены: выход одной → робот → вход другой."""
    import line_builder

    client.simulation("reset")
    time.sleep(1.0)
    all_lines = lines(client)
    if len(all_lines) < 2:
        return ("Соединять нечего: в сцене " + ("одна линия" if all_lines else "нет линий")
                + " с подачей и выходом. Добавьте вторую: «добавь ещё один замкнутый конвейер рядом».")
    pair = _pair(all_lines, set(prefer_b or []))
    if pair is None:
        return "Не нашёл, какие линии соединить: у всех выход уже занят связкой."
    a, b = pair
    d = math.hypot(a["выход_м"][0] - b["вход_м"][0], a["выход_м"][1] - b["вход_м"][1])
    moved = ""
    if abs(d - GAP) > 150.0:
        # вход B не там, где нужно: переставим B целиком, если знаем её состав
        if prefer_b and b["подача"] in prefer_b:
            place_beside(client, prefer_b)
            moved = " Вторую линию переставил: вход — напротив выхода первой."
            all_lines = lines(client)
            a = next(x for x in all_lines if x["подача"] == a["подача"])
            b = next(x for x in all_lines if x["подача"] == b["подача"])
        else:
            return (f"Вход линии от «{b['подача']}» в {d / 1000:.1f} м от выхода линии от «{a['подача']}» — "
                    f"робот столько не перенесёт. Поставьте их рядом (вход напротив выхода, ~{GAP / 1000:.1f} м) "
                    f"или добавьте вторую через меня: «добавь ещё один … рядом» — поставлю как надо.")

    lb = line_builder.LineBuilder(client, progress=progress)
    lb._pace = 0.05
    lb.spec = line_builder.LineSpec()
    lb.robots_used = 0
    n = int(kits._run(client, "result = len([1 for c in app.Components if _u(c.Name).startswith(u'ТК связки')])")) + 1
    pick_id, place_id = f"Связка {n} Съём", f"Связка {n} Укладка"
    height = float(a["выход_м"][2])

    # 1. сток A и подача B уступают место перекладке
    kits._run(client, (
        "for nm in %r:\n"
        "    c = app.findComponent(_b(nm))\n"
        "    if c is not None: c.delete()\n"
        "result = 1") % [x for x in (a.get("сток"), b["подача"]) if x])
    # 2. съём на конце выхода A, укладка перед входом B, робот сбоку
    p = lb._node("pick", pick_id, height,
                 "snap(comp(%r), 'OutInterface', n_, 'InInterface')\n" % a["выход"])
    q = lb._node("place", place_id, height,
                 "put_frame_at(n_, 'OutInterface', ahead(frame_world(comp(%r), 'OutInterface'), %f))\n"
                 "beh(n_, 'OutInterface').connect(beh(comp(%r), 'InInterface'))\n"
                 % (a["выход"], GAP, b["вход"]))
    ax, ay = (p["at"][0] + q["at"][0]) / 2.0, (p["at"][1] + q["at"][1]) / 2.0
    ux, uy = _heading(a["выход_м"])
    # сторона, где свободнее: меньше оборудования в 2,5 м от места робота
    side = kits._run(client, (
        "best = None\n"
        "for s in (1, -1):\n"
        "    x, y = %f + s * %f, %f + s * %f\n"
        "    k = 0\n"
        "    for c in _top_components():\n"
        "        b = _world_box(c)\n"
        "        if b is not None and b[0] - 2500 < x < b[3] + 2500 and b[1] - 2500 < y < b[4] + 2500: k += 1\n"
        "    if best is None or k < best[0]: best = (k, s)\n"
        "result = best[1]") % (ax, -uy * line_builder.ROBOT_OFFSET, ay, ux * line_builder.ROBOT_OFFSET))
    rx, ry = ax - side * uy * line_builder.ROBOT_OFFSET, ay + side * ux * line_builder.ROBOT_OFFSET
    facing = math.degrees(math.atan2(ay - ry, ax - rx))
    rb = lb._robot_at(rx, ry, 0.0, facing)
    kits._run(client, "rename(comp(%r), _b(%r))\nresult = 1" % (rb["tc"], f"ТК связки {n}"))
    tc = f"ТК связки {n}"

    # 3. маршрут A кончается перекладкой; на укладке деталь становится типом B
    # и идёт маршрутом B, который теперь начинается с укладки, а не с подачи
    res_a = kits._run(client, "result = set_flow(%r, %r)" % (list(a["шаги"]) + [pick_id, place_id], a["группа"]))
    res_b = kits._run(client, "result = set_flow(%r, %r)" % ([place_id] + list(b["шаги"][1:]), b["группа"]))
    kits._run(client, "link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (p["name"], q["name"], tc, a["группа"]))
    kits._run(client, "change_type_on(comp(%r), %r)\napp.Simulation.setInitialState()\nresult = 1"
              % (q["name"], b["тип"]))
    lb._overview()
    out = [f"Соединил в одну линию: выход «{a['выход']}» → робот {rb['robot']} → вход «{b['вход']}».{moved}",
           f"Детали первой линии после перекладки идут по второй как её собственные (тип «{a['тип']}» → "
           f"«{b['тип']}»). Подачу второй убрал — детали ей даёт первая"
           + (f", сток «{a['сток']}» на выходе первой — тоже." if a.get("сток") else ".")]
    missing = (res_a or {}).get("missing", []) + (res_b or {}).get("missing", [])
    if missing:
        out.append(f"⚠ Нет процессов: {', '.join(missing)}.")
    out.append("Проверить: /симуляция 3, или «запусти симуляцию».")
    return "\n".join(out)
