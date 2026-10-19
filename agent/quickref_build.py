# -*- coding: utf-8 -*-
"""
Готовит данные для быстрых команд агента (quickref.py): /термин и /совет.

    python agent/quickref_build.py

- kb/ui_terms.json — пары «английское название в интерфейсе → русское в R-Pro».
  Источник — academy/uiterms.json (строки ресурсов Resource.English.dll и
  Resource.Русский.dll, см. academy/build_uiterms.ps1). Уроки Academy и
  форумы Visual Components говорят по-английски, а кнопки у нас русские:
  «Component Container» в R-Pro называется «Контейнер».
- kb/tips.jsonl — советы из docs/12-lajfhaki-rpro.md, по одному на строку,
  с разделом и уроками-источниками.

kb/faq.json (ответы на частые неполадки) пишется руками, этот скрипт его
не трогает.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
KB = HERE / "kb"
UITERMS = HERE / "academy" / "uiterms.json"
TIPS_DOC = HERE.parent / "docs" / "12-lajfhaki-rpro.md"


def build_terms() -> int:
    raw = json.loads(UITERMS.read_text(encoding="utf-8"))
    variants: dict[str, Counter] = defaultdict(Counter)
    shown: dict[str, str] = {}
    for x in raw:
        en, ru = (x.get("en") or "").strip(), (x.get("ru") or "").strip()
        # Только короткие подписи: длинные строки — всплывающие подсказки и
        # сообщения, для перевода названий они бесполезны и забивают выдачу.
        if not en or not ru or en == ru or len(en) > 50 or len(ru) > 60:
            continue
        if "{" in en or "\n" in en or "\n" in ru or not re.search(r"[A-Za-z]", en):
            continue
        key = en.lower().rstrip(":.…")
        variants[key][ru.rstrip(":.…")] += 1
        shown.setdefault(key, en.rstrip(":.…"))
    pairs = []
    for key, ru in variants.items():
        # Самый частый русский вариант первым, остальные — через «/».
        names = [r for r, _ in ru.most_common(3)]
        pairs.append([shown[key], names])
    pairs.sort(key=lambda p: p[0].lower())
    (KB / "ui_terms.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(pairs)


def build_tips() -> int:
    section = ""
    out = []
    for line in TIPS_DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("- ") or not section:
            continue
        text = line[2:].strip()
        lessons = ""
        m = re.search(r"\s*\[([a-z0-9, \-]+)\]\s*$", text)
        if m:
            lessons = m.group(1)
            text = text[:m.start()].rstrip()
        out.append({"section": section, "text": text, "lessons": lessons,
                    "warn": text.startswith("⚠") or "⚠" in text[:3]})
    with (KB / "tips.jsonl").open("w", encoding="utf-8") as f:
        for t in out:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return len(out)


if __name__ == "__main__":
    print(f"kb/ui_terms.json: {build_terms()} названий")
    print(f"kb/tips.jsonl: {build_tips()} советов")
