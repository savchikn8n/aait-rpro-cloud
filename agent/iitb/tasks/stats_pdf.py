# -*- coding: utf-8 -*-
"""Лист статистики (урок 6) в PDF: те же данные, что в графиках дашборда R-Pro.

Кнопка «Печать графика» из API недоступна, поэтому лист рисуем по DataRows графиков.
"""

from __future__ import annotations

from pathlib import Path


def make(data: list[dict], path: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    colors = ["#1a9a33", "#e3c400", "#d11a1a", "#1a66e6", "#cc6600"]
    fig, axes = plt.subplots(2, 2, figsize=(11.7, 8.3))  # A4 альбомная
    fig.suptitle("Лист статистики: состояния и выпуск (симуляция 1 ч)", fontsize=14)
    for ax, d in zip(axes.flat, data):
        ax.set_title(d.get("name", ""), fontsize=11)
        rows = d.get("rows") or []
        series = d.get("series") or []
        if not rows:
            ax.text(0.5, 0.5, "нет данных", ha="center", va="center")
            continue
        last = rows[-1]
        vals = last[1:]
        kind = str(d.get("type"))
        # ChartType: 1 — столбцы? у R-Pro числа произвольные; выбираем вид по названию
        if "состояния" in (d.get("name") or "").lower():
            ax.pie([max(v, 0) for v in vals], labels=series, autopct="%1.0f%%",
                   colors=["#e3c400", "#1a9a33", "#d11a1a"][: len(vals)])
        elif "выпуск" in (d.get("name") or "").lower():
            ax.plot([r[0] / 60.0 for r in rows], [r[1] for r in rows], color="#1a66e6")
            ax.set_xlabel("мин"); ax.set_ylabel("шт."); ax.grid(alpha=0.3)
        else:
            ax.bar(range(len(vals)), vals, color=colors[: len(vals)])
            ax.set_xticks(range(len(vals)))
            ax.set_xticklabels(series, fontsize=9)
            ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    with PdfPages(str(path)) as pdf:
        pdf.savefig(fig)
    plt.close(fig)
    return str(path)
