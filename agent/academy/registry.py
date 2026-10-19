# -*- coding: utf-8 -*-
"""
Реестр знаний Academy: единственное место, где живут обработанные уроки.

  registry/lessons.jsonl      по строке на урок: метаданные, русский урок (ru),
                              английский конспект (en), применимость, вошёл ли в базу агента
  registry/sources.jsonl.gz   по строке на урок: исходный текст, из которого сделан конспект
                              (транскрипт с минутами или текст PDF) и сырые субтитры
  registry/audit/             отчёты оценки качества (судьи, A/B поиска, сквозной тест)

Отсюда строится поиск агента (`../kb/academy_chunks.jsonl`, academy_to_kb.py). Файлов на
каждый урок в рабочей папке не остаётся: конспекты, транскрипты и входы переезжают сюда,
рабочие папки чистит academy_consolidate.py после проверки.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG = HERE / "registry"
LESSONS = REG / "lessons.jsonl"
SOURCES = REG / "sources.jsonl.gz"
AUDIT = REG / "audit"


def load_lessons() -> dict[str, dict]:
    if not LESSONS.exists():
        return {}
    out = {}
    for line in LESSONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["slug"]] = rec
    return out


def save_lessons(lessons: dict[str, dict]) -> None:
    REG.mkdir(parents=True, exist_ok=True)
    LESSONS.write_text(
        "\n".join(json.dumps(lessons[s], ensure_ascii=False) for s in sorted(lessons)) + "\n",
        encoding="utf-8")


def load_sources() -> dict[str, dict]:
    if not SOURCES.exists():
        return {}
    out = {}
    with gzip.open(SOURCES, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                out[rec["slug"]] = rec
    return out


def save_sources(sources: dict[str, dict]) -> None:
    REG.mkdir(parents=True, exist_ok=True)
    # mtime=0: одинаковое содержимое даёт побайтно одинаковый файл
    with open(SOURCES, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for s in sorted(sources):
            gz.write((json.dumps(sources[s], ensure_ascii=False) + "\n").encode("utf-8"))


def source_text(slug: str) -> str:
    rec = load_sources().get(slug)
    return rec["text"] if rec else ""
