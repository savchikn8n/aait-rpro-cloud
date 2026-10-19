# -*- coding: utf-8 -*-
"""
Конспекты курса ИИТБ (iitb/lessons/*.md) → база знаний агента: python iitb_to_kb.py

Пишет ../kb/iitb_chunks.jsonl (source = "iitb"); kb.py подхватывает файл рядом с
chunks.jsonl и academy_chunks.jsonl. В отличие от Academy это родной курс по R-Pro
(русский интерфейс, тот же продукт и версия), поэтому скидки на оценку нет, а практика
уроков проверена на живой программе — раздел «Как это делает агент» идёт отдельным
фрагментом.

Фрагмент = раздел «## …» конспекта (не длиннее MAX_CHARS, длинные режутся по абзацам);
каждый начинается строкой «Урок ИИТБ N: название», чтобы читаться без контекста.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS = HERE / "lessons"
OUT = HERE.parent / "kb" / "iitb_chunks.jsonl"
MAX_CHARS = 2600


def parse(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S)
    meta, body = {}, raw
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    return meta, body.strip()


def split_sections(body: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## +", body, flags=re.M)
    out = []
    for p in parts:
        if not p.strip():
            continue
        head, _, text = p.partition("\n")
        out.append((head.strip(), text.strip()))
    return out


def cut(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    chunks, cur = [], ""
    for para in re.split(r"\n(?=[-|0-9#])|\n\n", text):
        if cur and len(cur) + len(para) > MAX_CHARS:
            chunks.append(cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def build() -> int:
    rows = []
    for path in sorted(LESSONS.glob("L*.md")):
        meta, body = parse(path)
        n = meta.get("lesson", path.stem[1:])
        title = meta.get("title", path.stem)
        tags = meta.get("tags", "")
        sections = split_sections(body)
        total = 0
        pending = []
        keywords = ""
        for head, text in sections:
            if head.lower().startswith("ключевые слова"):
                keywords = text  # отдельным обрезком не живёт (поиск вернул бы голый список слов)
                continue
            for piece in cut(text):
                pending.append((head, piece))
        total = len(pending)
        for i, (head, piece) in enumerate(pending, 1):
            if head in ("Суть урока", "Лайфхаки и ловушки"):
                head = f"{head} (урок {n})"  # чтобы «/справка <раздел>» находил именно этот урок
            hdr = f"Урок: Курс ИИТБ, урок {n} — {title}\n\n"
            rows.append({
                "source": "iitb",
                "title": f"Курс ИИТБ / Урок {n} / {head}",
                "part": f"{i}/{total}",
                "text": hdr + piece,
                "index_text": f"{head}\n{piece}"
                + (f"\n{tags}\n{keywords}" if i == 1 or head.lower().startswith("лайфхак") else ""),
            })
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("фрагментов:", build())
