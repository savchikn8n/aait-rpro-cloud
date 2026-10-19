# -*- coding: utf-8 -*-
"""
/оптимизация — убрать лишнее и сжать построенное производство.

Что делает (hands27.optimize_scene, rebuild_slabs):

1. удаляет «сироты» — роботов без связей и без операций, склады и процессы вне
   маршрутов, ленты, не подключённые ни с одной стороны (и подставки под ними);
2. сжимает шаг постов прямых линий: лента между постами короче, пока
   оборудование соседних постов не встанет вплотную с зазором 0,4 м. Посты, к
   которым приходит лифт с другого этажа или от которых он уходит, стоят на
   месте, остальные подтягиваются к ним; вместе с постом едут его роботы,
   склады, изоляторы брака, печь, а подпрограммы роботов-технологов
   сдвигаются вслед (они записаны в мировых координатах);
3. перекладывает перекрытия этажей по новому пятну оборудования с проёмами под
   лифты и переставляет колонны.

До правки сцена сохраняется копией «… до оптимизации», после — отдельным файлом
«… после оптимизации»: исходный файл планировки не трогается, вернуть всё —
открыть копию. Отчёт: было → стало, м².
"""

from __future__ import annotations

import os
import time

import kits
from rpro_client import RProClient

BACKUPS = os.path.join(os.path.expanduser("~"), "Documents", "R-Pro", "Оптимизация")


def _m2(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ") + " м²"


def _m(v: float) -> str:
    r = round(float(v), 1)
    return (str(int(r)) if r == int(r) else str(r).replace(".", ",")) + " м"


def _selected(client: RProClient) -> list[str]:
    return kits._run(client, "result = [_u(c.Name) for c in "
                             "app.SelectionManager.getSelection(VC_SELECTION_COMPONENT)]") or []


def _line_lines(recs: list[dict]) -> list[str]:
    out = []
    for r in recs:
        if not r.get("укорочено_лент"):
            continue
        w0, h0 = r["пятно_было"]
        w1, h1 = r["пятно_стало"]
        pct = f" (−{round(100.0 * (1 - (w1 * h1) / (w0 * h0)))} %)" if w0 * h0 > w1 * h1 else ""
        out.append(f"• линия от «{r['подача']}»: {_m(w0)} × {_m(h0)} = {_m2(w0 * h0)} → "
                   f"{_m(w1)} × {_m(h1)} = {_m2(w1 * h1)}{pct}; ленты {_m(r['лент_м_было'])} → "
                   f"{_m(r['лент_м_стало'])} (укорочено {r['укорочено_лент']})")
        if r.get("упоры"):
            out.append("  дальше не сжать: " + "; ".join(r["упоры"].values()))
    return out


def run(client: RProClient, dry: bool = False, selected: bool = False) -> str:
    """dry — только показать план; selected — только линии, где есть выделенное."""
    client.simulation("reset")
    time.sleep(1.0)
    only = _selected(client) if selected else []
    if selected and not only:
        return ("В сцене ничего не выделено. Выделите мышью любой элемент линии (станок, робота, ленту) "
                "и повторите /оптимизация выделенное — или /оптимизация для всей сцены.")
    before = kits._run(client, "result = layout_dims()")
    if not before.get("этажи"):
        return "В сцене нет построенного производства — оптимизировать нечего."
    # Два вида построенного: заводы (посты «… П1 …», factory_builder) и линии
    # строителя (line_builder: подача → ленты → посты со станками). Раньше
    # /оптимизация знала только заводы, и на линии отвечала «лишнего не нашёл»
    # (журнал 08.10).
    plan = kits._run(client, "result = optimize_scene(apply=False)") if not only else {}
    plan_l = kits._run(client, "result = optimize_lines(apply=False, only=%r)" % (only or None))
    lines = []
    for p in plan.get("линии", []):
        lines.append(f"• линия {p['линия']}: длина {_m(p['длина_было_м'])} → {_m(p['длина_стало_м'])} "
                     f"(шаг постов короче, на месте посты {', '.join('П' + str(a) for a in p['якоря'])})")
    lines += _line_lines(plan_l)
    orph = plan.get("сироты", [])
    if only and not plan_l:
        return (f"Выделенное ({', '.join(only[:4])}) не входит ни в одну построенную линию от подачи. "
                "Выделите станок, робота или ленту линии.")
    loops = [r["подача"] for r in plan_l if r.get("пропущено")]
    if dry:
        out = ["Что можно сократить:"]
        out += lines or ["• линии уже плотные"]
        if not only:
            out.append(f"• лишних элементов: {len(orph)}" + (f" ({', '.join(orph[:6])}…)" if len(orph) > 6
                                                               else f" ({', '.join(orph)})" if orph else ""))
        out.append(f"Сейчас под оборудованием {_m2(before['площадь_под_оборудованием_м2'])}. "
                   "Применить — /оптимизация" + (" выделенное" if only else "") + ".")
        return "\n".join(out)
    if not lines and not orph:
        return ("Сжимать нечего: " + ("ленты между постами уже короткие, оборудование стоит вплотную."
                                      if plan_l or plan.get("линии") is not None else "линий не нашёл.")
                + (f" Замкнутые петли ({', '.join(loops)}) не сжимаю — их ленты замкнуты в кольцо." if loops else ""))

    # копия до правки — отдельным файлом; исходный файл планировки не трогаем
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H-%M")
    uri = lambda name: "file:///" + os.path.join(BACKUPS, name).replace("\\", "/")
    before_file = f"{stamp} до оптимизации.rpro"
    client.layout("save", uri(before_file))
    done = kits._run(client, "result = optimize_scene(apply=True)") if not only else {}
    kits._run(client, "result = optimize_lines(apply=True, only=%r)" % (only or None))
    slabs = kits._run(client, "result = rebuild_slabs()") if not only else {}
    after = kits._run(client, "result = layout_dims()")
    after_file = f"{stamp} после оптимизации.rpro"
    client.layout("save", uri(after_file))

    a0, a1 = before["площадь_под_оборудованием_м2"], after["площадь_под_оборудованием_м2"]
    if only:
        # своя линия — главное; габарит всей сцены держит то, что стоит в другом
        # углу (журнал 08.10: «вся сцена 1 447 → 1 446 м², −0 %» при линии −62 %)
        out = ["Оптимизация выделенной линии:"]
    else:
        out = [f"Оптимизация: под оборудованием было {_m2(a0)}, стало {_m2(a1)}"
               + (f" (−{round(100.0 * (a0 - a1) / a0)} %)." if a0 > a1 else ".")]
    if not only and before.get("пятно_м2") and after.get("пятно_м2") and before["пятно_м2"] != after["пятно_м2"]:
        out.append(f"Пятно здания: {_m(before['пятно_м'][0])} × {_m(before['пятно_м'][1])} = "
                   f"{_m2(before['пятно_м2'])} → {_m(after['пятно_м'][0])} × {_m(after['пятно_м'][1])} = "
                   f"{_m2(after['пятно_м2'])}.")
    out += lines
    if done.get("удалено"):
        out.append(f"• удалено лишнего: {len(done['удалено'])} ({', '.join(done['удалено'][:8])})")
    if slabs.get("перекрытий"):
        out.append(f"• перекрытия переложены по оборудованию: плиты {_m2(slabs['плит_было_м2'])} → "
                   f"{_m2(slabs['плит_стало_м2'])}")
    if loops:
        out.append(f"_Замкнутые петли ({', '.join(loops)}) не сжимал — их ленты замкнуты в кольцо._")
    out.append(f"Копия до оптимизации: «{before_file}», результат — «{after_file}» "
               f"(папка Документы\\R-Pro\\Оптимизация). Проверь выпуск: /отчёт 60.")
    return "\n".join(out)
