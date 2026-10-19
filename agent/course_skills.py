# -*- coding: utf-8 -*-
"""
Умения из курса ИИТБ, которые применяются к СЦЕНЕ ПОЛЬЗОВАТЕЛЯ (а не строят учебную сцену):
детектор столкновений (урок 13), запись видео симуляции (урок 5), лист статистики на дашборде (урок 6).

Почему кодом, а не моделью: 15.10 на живом агенте модель 8B получила рецепт урока 13 и 8 раз подряд
подставляла в NodeListA строки-имена вместо объектов (компонент-родитель с деревом узлов); закрепляем
проверенный на R-Pro 2.2.2 код (см. docs/19-kurs-iitb.md).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

HOME_OUT = Path.home() / "Documents" / "R-Pro-Agent"


def _py(code: str):
    import sys
    import tools
    sys.path.insert(0, str(Path(__file__).resolve().parent / "iitb"))   # video.py и задания курса делают «import runner»
    from iitb import runner
    return runner.exec_in_rpro(tools.client, code)


# --- урок 13: детектор столкновений -------------------------------------------------------------------

_DETECTOR = '''
import __builtin__
I, T = VC_NODELIST_INCLUDE, VC_NODELIST_TREE
want = %(want)r
def top(c):
    # верхний компонент: робот и захват — дочерние компоненты тумбы, детектору нужен родитель с деревом узлов
    while True:
        p = _safe(c, "Parent")
        if p is None or _safe(p, "Name") in (None, "ROOT"):
            return c
        c = p
comps = list(app.Components)
robots = [c for c in comps if len(list(c.findBehavioursByType(VC_ROBOTEXECUTOR))) > 0]
if not robots:
    result = {"ошибка": "в сцене нет роботов"}
else:
    A = []
    for r in robots:
        t = top(r)
        if all(t.Name != a.Name for a in A):
            A.append(t)
    names_a = [a.Name for a in A]
    B = []
    for c in comps:
        t = top(c)
        if t.Name in names_a or any(t.Name == b.Name for b in B):
            continue
        if want and not any(_u(w) in _u(t.Name).lower() for w in want):
            continue
        B.append(t)
    if not B:
        result = {"ошибка": "не нашёл, с чем сравнивать (группа B пуста)"}
    else:
        det = app.Simulation.newCollisionDetector()
        det.NodeListA = [(a, I, T) for a in A]
        det.NodeListB = [(b, I, T) for b in B]
        det.Tolerance = 10.0
        det.DisplayMinimumDistance = True
        det.Active = True
        # объект детектора живёт, пока на него есть ссылка
        lst = getattr(__builtin__, "RPRO_DETECTORS", [])
        lst.append(det)
        __builtin__.RPRO_DETECTORS = lst
        hit = bool(det.testAllCollisions())
        pairs = []
        if hit:
            for i in range(det.HitCount):
                pairs.append("%%s x %%s" %% (det.getHitNodeA(i).Name, det.getHitNodeB(i).Name))
        result = {"A": [_u(a.Name) for a in A], "B": [_u(b.Name) for b in B], "касание": hit, "пары": pairs[:8]}
'''


def collision_text(text: str) -> str:
    low = text.lower().replace("ё", "е")
    want = []
    for key, stems in (("конвейер", ["конвейер"]), ("станок", ["станок", "станк"]), ("стол", ["стол"]),
                       ("ограждени", ["огражд"]), ("тумб", ["тумб"])):
        if key in low:
            want += stems
    r = _py(_DETECTOR % {"want": want})
    if r.get("ошибка"):
        return "Детектор столкновений не создан: " + r["ошибка"] + "."
    lines = [f"Детектор столкновений создан и включён (допуск 10 мм, минимальное расстояние показывается).",
             "Группа A (робот с тумбой и захватом): " + ", ".join(r["A"]) + ".",
             "Группа B (с чем сравниваем): " + ", ".join(r["B"]) + "."]
    if r["касание"]:
        lines.append("Сейчас касаются: " + "; ".join(r["пары"]) + ".")
    else:
        lines.append("В исходном положении касаний нет. Запустите симуляцию — детектор покажет, если программа робота "
                     "заденет окружение.")
    lines.append("Параметры «первое/все столкновения» и «остановка при столкновении» в R-Pro 2.2.2 — галочки окна "
                 "детектора (через API их нет).")
    return "\n".join(lines)


# --- урок 5: видео симуляции --------------------------------------------------------------------------

def _seconds(low: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(мин|м\b|сек|с\b)", low)
    if m:
        v = float(m.group(1).replace(",", "."))
        return v * 60.0 if m.group(2).startswith("м") else v
    if "минут" in low:
        return 60.0
    return 30.0


def video_text(text: str) -> str:
    import sys
    import tools
    sys.path.insert(0, str(Path(__file__).resolve().parent / "iitb"))
    from iitb import video
    low = text.lower().replace("ё", "е")
    seconds = max(5.0, min(_seconds(low), 300.0))
    m = re.search(r"([A-Za-z]:[\\/][^\s\"']+)", text)
    HOME_OUT.mkdir(parents=True, exist_ok=True)
    mp4 = Path(m.group(1).rstrip(".,;")) if m else HOME_OUT / time.strftime("video_%Y%m%d_%H%M%S.mp4")
    if mp4.suffix.lower() not in (".mp4", ".avi"):
        mp4 = mp4.with_suffix(".mp4")
    mp4.parent.mkdir(parents=True, exist_ok=True)
    info = video.record(tools.client, mp4, seconds)
    if not info.get("файл"):
        return "Видео не записалось: " + str(info.get("ошибка") or "рекордер не создал файл") + "."
    if str(info["файл"]).lower().endswith(".avi") and Path(info["файл"]).name == "_rec_tmp.avi":
        # без ffmpeg видео остаётся во временном .avi — отдаём под запрошенным именем
        final = mp4.with_suffix(".avi")
        if final.exists():
            final.unlink()
        Path(info["файл"]).replace(final)
        info["файл"] = str(final)
    out = f"Записал {info['симуляции_с']} с симуляции в видео: `{info['файл']}`"
    if info.get("размер_кб"):
        out += f" ({info['размер_кб'] // 1024 or 1} МБ)"
    out += "."
    if info.get("ошибка"):
        out += " Примечание: " + str(info["ошибка"]) + "."
    return out


# --- урок 6: лист статистики --------------------------------------------------------------------------

_DASH = '''
import vcVector
dash = app.Dashboard
for t in list(dash.Tabs):
    if t.Name == _b(u"Статистика (агент)"):
        dash.deleteTab(t)
tab = dash.createTab(_b(u"Статистика (агент)"), True)
for i, l in enumerate(tab.Layouts):
    if _u(str(l[0])).startswith(u"2-Столбец 1-Строка"):
        tab.SelectedLayout = i
        break
tab.clearLayout()
stats = []
for c in app.Components:
    b = c.findBehavioursByType(VC_STATISTICS)
    if len(b) > 0 and _safe(_safe(c, "Parent"), "Name") in ("ROOT", None):
        stats.append((c, b[0]))
stats = stats[:8]
if not stats:
    result = {"ошибка": "в сцене нет компонентов со статистикой"}
else:
    tiles = list(tab.Charts)
    palette = [(0.1, 0.7, 0.2), (0.1, 0.4, 0.9), (0.85, 0.1, 0.1), (1.0, 0.7, 0.0), (0.5, 0.2, 0.7), (0.0, 0.7, 0.8),
               (0.6, 0.4, 0.2), (0.4, 0.4, 0.4)]
    made = []
    for tile, (prop, title) in zip(tiles, (("Utilization", u"Загрузка оборудования, %"), ("BusyPercentage", u"Занят, % времени"))):
        ch = tab.createChart(tile, VC_CHARTTYPE_COLUMN, True)
        ch.Name = _b(title)
        ch.TitleVisibility = True
        ch.LegendVisibility = True
        for k, (c, st) in enumerate(stats):
            s = ch.addSeries()
            s.Name = _b(_u(c.Name))
            s.Property = st.getProperty(prop)
            s.Colors = [vcVector.new(*palette[k % len(palette)])]
        made.append(_u(title))
    app.Simulation.Statistics.SamplingInterval = 60.0
    result = {"графики": made, "компонентов": [_u(c.Name) for c, st in stats]}
'''


def dashboard_text(text: str) -> str:
    r = _py(_DASH)
    if r.get("ошибка"):
        return "Лист статистики не создан: " + r["ошибка"] + "."
    return ("Создал вкладку «Статистика (агент)» в дашборде: " + "; ".join(r["графики"]) + ". Оборудование: "
            + ", ".join(r["компонентов"]) + ". Графики заполнятся после прогона симуляции (область «Статистика»).")


def run(n: int, text: str) -> str:
    try:
        if n == 13:
            return collision_text(text)
        if n == 5:
            return video_text(text)
        if n == 6:
            return dashboard_text(text)
    except Exception as exc:  # noqa: BLE001
        return f"Не получилось: {type(exc).__name__}: {str(exc)[-300:]}"
    return ""
