# -*- coding: utf-8 -*-
"""Инструкция для оператора по пусконаладке ячейки Модуля B (PDF).

Собирается из тех же данных, что и KRL: программа (program.json), выбранный
при виртуальной пусконаладке поворот захвата и точки из .dat. Оператор на
реальном стенде (KRC4) идёт по ней шаг за шагом в режиме T1."""

from __future__ import annotations

import os
import re
from pathlib import Path


def _font() -> str:
    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    d = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
    for name, f in (("DejaVu", "DejaVuSans.ttf"), ("DejaVu-Bold", "DejaVuSans-Bold.ttf")):
        try:
            pdfmetrics.getFont(name)
        except KeyError:
            pdfmetrics.registerFont(TTFont(name, os.path.join(d, f)))
    return "DejaVu"


def _points(dat_text: str) -> list[list[str]]:
    rows = []
    for m in re.finditer(r"DECL FRAME (XP\d+)=\{X ([-\d.]+),Y ([-\d.]+),Z ([-\d.]+),A ([-\d.]+),B ([-\d.]+),C ([-\d.]+)\}",
                         dat_text):
        rows.append(list(m.groups()))
    return rows


def build(path: Path, src: Path, dat: Path, tune: dict | None = None, routines: list | None = None) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    f = _font()
    H1 = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=15, leading=19, spaceAfter=6)
    H2 = ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=3)
    P = ParagraphStyle("p", fontName=f, fontSize=9.5, leading=13)
    S = ParagraphStyle("s", fontName=f, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    tune = tune or {}
    chosen = tune.get("выбран_поворот_град", 45)
    clean = tune.get("чистые_углы") or []
    hits = (tune.get("без_поворота") or {}).get("столкновения")
    dat_text = Path(dat).read_bytes().decode("cp1251", errors="replace")
    pts = _points(dat_text)

    story = [Paragraph("Инструкция для оператора: пусконаладка ячейки переноса цилиндров", H1),
             Paragraph("Робот KUKA KR 10 R1100-2, контроллер KRC4, захват РКТ-мп3-27-40. Программа "
                       f"<b>{Path(src).stem}</b> (.src/.dat) подготовлена и проверена в цифровом двойнике "
                       "(«Рациональное производство»).", P), Spacer(1, 4)]

    def sec(title, items):
        story.append(Paragraph(title, H2))
        for i, t in enumerate(items, 1):
            story.append(Paragraph(f"{i}. {t}", P))

    sec("1. Что делает ячейка", [
        "Переносит три цилиндра Ø39×40 из стартового ложемента brics_3 (BASE_DATA[13], 3 гнезда) в "
        "конечный ложемент brics_15 (BASE_DATA[14], 15 гнёзд) — в гнёзда 1-2-3 по диагонали.",
        "Порядок подпрограмм: " + ", ".join(routines or []) + ".",
        "Скорости: PTP 15 %, LIN 0,1 м/с; захват: OUT[7] — сжать, OUT[8] — разжать, 1 с на ход."])
    sec("2. Безопасность — до любого движения", [
        "Режим T1 (ручной, сниженная скорость), ключ режима — у оператора.",
        "В ограждённой зоне ячейки людей нет; кнопка аварийного останова на пульте проверена.",
        "Ложементы закреплены, цилиндры стоят в гнёздах 1–3 стартового ложемента.",
        "Первый прогон — только пошагово с удерживанием кнопки разрешения (enabling switch)."])
    sec("3. Данные ячейки (сверить с пультом)", [
        "TOOL_DATA[12] = {X 7,45, Y −80,87, Z 115,63, A 0, B 0, C 0} — TCP на пальце захвата.",
        "BASE_DATA[13] = {X 535,46, Y −500,33, Z −9,91, A 89,98, B 0,01, C 0,03} — стартовый ложемент.",
        "BASE_DATA[14] = {X 564,66, Y 335,92, Z −7,60, A −90, B 0, C −179,98} — конечный ложемент.",
        "HOME: A1 0°, A2 −90°, A3 90°, A4 0°, A5 90°, A6 0°.",
        "Если базы на стенде отличаются — исправить базы, а не точки: точки заданы в системе баз."])
    sec("4. Загрузка программы", [
        f"Скопировать {Path(src).name} и {Path(dat).name} в KRC:\\R1\\Program (через Навигатор, права эксперта).",
        "Выбрать программу (Select); убедиться, что подсветилась строка INI_CELL.",
        "Проверить захват вручную: меню «Индикация → Входы/выходы → Цифровые выходы»: OUT[8] — "
        "захват раскрылся, OUT[7] — сжался."])
    sec("5. Пошаговый прогон в T1", [
        "Override 10 %, режим «пошагово» (Motion). GO_HOME → GRIP_OPEN.",
        "PICK_CYL_1: подход XP1 сверху, спуск XP2 на 80 мм, сжатие захвата, подъём XP3. "
        "Проверить, что пальцы охватывают цилиндр симметрично.",
        f"PLACE_CYL_1: укладка с поворотом захвата A = {90 + chosen:g}° (+{chosen:g}° к оси ложемента). "
        "Поворот найден на виртуальной пусконаладке: без него палец № 3 задевает уже уложенный "
        "соседний цилиндр" + (f" (в модели — {', '.join(hits)})" if isinstance(hits, dict) and hits else "")
        + f". Без столкновений в модели проходят повороты {', '.join(f'+{a:g}°' for a in clean) or '+15…+60°'}.",
        "Повторить для цилиндров 2 и 3; после каждого — визуально: цилиндр сел в гнездо до дна, без перекоса.",
        "GO_HOME. Счётчик nTotal в .dat должен стать 3."])
    sec("6. Корректировка на стенде (связь с цифровым двойником)", [
        "Если цилиндр садится со смещением — скорректировать точку командой Touch-Up только в системе "
        "своей базы (BASE_DATA[13] для взятия, [14] для укладки), записать новые X/Y/Z.",
        "Передать изменённые точки разработчику: их вносят в двойник, повторяют проверку столкновений "
        "и выгружают KRL заново — так модель и стенд не расходятся.",
        "Не менять скорости и ускорения в INI_CELL без согласования."])
    sec("7. Автоматический режим", [
        "После безошибочного полного цикла в T1 — T2 с override 30 %, затем AUT по согласованию.",
        "При любом касании или останове — STOP, режим T1, разбор по шагу, где произошло."])
    story.append(Paragraph("8. Точки программы (из .dat, мм и градусы)", H2))
    data = [["Точка", "X", "Y", "Z", "A", "B", "C"]] + pts
    t = Table(data, colWidths=[20 * mm] + [22 * mm] * 6, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), f, 8), ("FONT", (0, 0), (-1, 0), "DejaVu-Bold", 8),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe8f3"))]))
    story += [t, Spacer(1, 6),
              Paragraph("Точки XP1–XP3, XP7–XP9, XP13–XP15 — взятие (BASE_DATA[13]); XP4–XP6, XP10–XP12, "
                        "XP16–XP18 — укладка (BASE_DATA[14]).", S)]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title="Инструкция оператора — Модуль B")
    doc.build(story)
    return str(path)
