# -*- coding: utf-8 -*-
"""
Материалы для оценки конспектов сильной моделью: python academy_judge_prep.py

Пишет в work/judge/:
- all_tips.md — все «Лайфхаки и ловушки» из русских уроков, что попали в базу
  (по одному разделу на урок, с применимостью). Из этого файла собирается
  итоговый список лайфхаков для работы с R-Pro;
- sample/<slug>.md — выборка уроков для проверки на верность: исходный
  транскрипт + английский конспект + русский урок в одном файле;
- sample.json — список выбранных уроков;
- ab_questions.md — вопросы новичка и что находит поиск без уроков (OFF)
  и с уроками (ON): оценщик решает, помогают ли уроки или мешают.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

import registry
from pathlib import Path

HERE = Path(__file__).resolve().parent
JUDGE = HERE / "work" / "judge"
SAMPLE_SIZE = 16


def kb_lessons() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in (HERE.parent / "kb" / "academy_chunks.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        out.setdefault(c["slug"], {"applicability": c["applicability"], "title": c["title"].split(" / ", 1)[1]})
    return out


def tips_of(text: str) -> list[str]:
    m = re.search(r"## Лайфхаки и ловушки\n(.*?)(?=\n## |\Z)", text, re.S)
    return [ln for ln in (m.group(1).splitlines() if m else []) if ln.strip().startswith("-")]


def main() -> None:
    (JUDGE / "sample").mkdir(parents=True, exist_ok=True)
    lessons = kb_lessons()
    index = registry.load_lessons()

    # 1. все советы
    parts, n_tips = [], 0
    for slug in sorted(lessons):
        tips = tips_of(index[slug]["ru"])
        if not tips:
            continue
        n_tips += len(tips)
        meta = index.get(slug, {})
        parts.append(f"### {lessons[slug]['title']} | {slug} | версия {meta.get('version') or '?'} | "
                     f"применимость: {lessons[slug]['applicability']}\n" + "\n".join(tips))
    (JUDGE / "all_tips.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(f"советов: {n_tips} в {len(parts)} уроках")

    # 2. выборка: детерминированная, по категориям поровну
    by_cat: dict[str, list[str]] = {}
    for slug in sorted(lessons):
        by_cat.setdefault((index.get(slug, {}).get("category") or "?").split("|")[0].strip(), []).append(slug)
    for v in by_cat.values():
        v.sort(key=lambda s: hashlib.md5(s.encode()).hexdigest())
    chosen: list[str] = []
    while len(chosen) < SAMPLE_SIZE and any(by_cat.values()):
        for cat in sorted(by_cat):
            if by_cat[cat] and len(chosen) < SAMPLE_SIZE:
                chosen.append(by_cat[cat].pop(0))
    for slug in chosen:
        text = (
            f"# ВЫБОРКА: {slug}\n\n## 1. ИСХОДНЫЙ ТРАНСКРИПТ (истина)\n\n"
            + registry.source_text(slug)
            + "\n\n## 2. АНГЛИЙСКИЙ КОНСПЕКТ (стадия 1, Haiku)\n\n"
            + index[slug]["en"]
            + "\n\n## 3. РУССКИЙ УРОК (стадия 2, Haiku) — этот текст получит агент\n\n"
            + index[slug]["ru"]
        )
        (JUDGE / "sample" / f"{slug}.md").write_text(text, encoding="utf-8")
    (JUDGE / "sample.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    print("выборка:", ", ".join(chosen))

    # 3. A/B поиска: два прогона в разных процессах (флаг читается при импорте)
    code = r"""
import json, sys
sys.path.insert(0, %r)
sys.stdout.reconfigure(encoding='utf-8')
import kb
sys.path.insert(0, %r)
from retrieval_probe import QUESTIONS
res = {}
for q in QUESTIONS:
    hits = [h for h in kb.search(q, 4) if h['score'] >= 1.0][:2]
    res[q] = [{'source': h['source'], 'title': h['title'], 'part': h['part'], 'score': h['score'],
               'text': h['text'][:700]} for h in hits]
print(json.dumps(res, ensure_ascii=False))
""" % (str(HERE.parent), str(HERE))
    runs = {}
    for mode in ("0", "1"):
        env = dict(os.environ, RPRO_KB_ACADEMY=mode, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        runs[mode] = json.loads(r.stdout)
    lines = ["# A/B поиска: что агент получает на вопрос новичка\n",
             "OFF — только справка R-Pro. ON — справка + уроки Academy. Показаны топ-2 фрагмента "
             "(как в автоподстановке чата), текст обрезан до 700 знаков.\n"]
    for q in runs["0"]:
        lines.append(f"\n## Вопрос: {q}\n")
        for label, key in (("OFF", "0"), ("ON", "1")):
            lines.append(f"### {label}")
            for h in runs[key][q]:
                lines.append(f"**[{h['source']}] {h['title']} {h['part']}** (score {h['score']})\n{h['text']}\n")
    (JUDGE / "ab_questions.md").write_text("\n".join(lines), encoding="utf-8")
    print("A/B записан")


if __name__ == "__main__":
    main()
