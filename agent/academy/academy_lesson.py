# -*- coding: utf-8 -*-
"""
Работа с одним уроком реестра знаний (там, где раньше был «открой digests_ru/<slug>.md»).

  python academy_lesson.py find <часть названия или slug>
  python academy_lesson.py show <slug>             # метаданные и русский урок, как его получает агент
  python academy_lesson.py show <slug> --source    # плюс исходный текст (транскрипт или PDF) для сверки
  python academy_lesson.py set <slug> <файл.md>    # заменить русский урок и пересобрать базу агента
  python academy_lesson.py setdir <папка>          # применить пачку: <slug>.md (+ <slug>.log с описанием правок)

Типичный случай: агент дал плохой совет, в трассировке чата видно «справка подложена: Уроки Academy /
<название>». find → show --source → сверить с исходником → исправить текст в файле → set.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import academy_to_kb as to_kb
import registry
import validate_digests as V


def find(q: str) -> None:
    q = q.lower()
    hits = [r for r in registry.load_lessons().values() if q in r["slug"] or q in r["title"].lower()]
    for r in hits:
        print(f"{r['slug']} | {r['title']} | версия {r['version'] or '?'} | в базе: {'да' if r.get('in_kb') else 'нет'}")
    if not hits:
        print("не найдено")


def show(slug: str, with_source: bool) -> None:
    r = registry.load_lessons().get(slug)
    if not r:
        sys.exit(f"нет урока {slug}; поиск: python academy_lesson.py find <текст>")
    a = r.get("audit")
    print(f"# {r['title']}  ({r['kind']}, {r['source']}, версия {r['version'] or '?'}, обработан {r['processed']}, "
          f"{r['model'] or 'модель не указана'})")
    print(f"# {r['url']}")
    if a:
        print(f"# аудит: верность {a['fidelity']}/5, полезность {a['usefulness']}/5, вердикт {a['verdict']}")
    if not r.get("in_kb"):
        print(f"# В БАЗУ АГЕНТА НЕ ВХОДИТ: {r.get('excluded_why')}")
    print("\n" + r["ru"])
    if with_source:
        print("\n" + "=" * 70 + "\nИСХОДНЫЙ ТЕКСТ\n" + "=" * 70 + "\n")
        print(registry.source_text(slug) or "(исходник не заархивирован)")


def set_ru(slug: str, path: str) -> None:
    reg = registry.load_lessons()
    if slug not in reg:
        sys.exit(f"нет урока {slug}")
    text = Path(path).read_text(encoding="utf-8")
    bad = V.problems(text, "ru")
    if bad:
        sys.exit("урок не принят: " + "; ".join(bad))
    reg[slug]["ru"] = text
    reg[slug]["fixed"] = time.strftime("%Y-%m-%d")
    stats = to_kb.rebuild(reg)
    registry.save_lessons(reg)
    print(f"урок {slug} заменён; " + to_kb.report(stats))


def set_dir(folder: str) -> None:
    """Применить пачку исправленных уроков: <folder>/<slug>.md (русский урок), необязательно
    <slug>.log (что изменено). Один проход по реестру — безопасно для файлов от нескольких агентов."""
    reg = registry.load_lessons()
    today = time.strftime("%Y-%m-%d")
    applied, rejected = [], {}
    for f in sorted(Path(folder).glob("*.md")):
        slug = f.stem
        if slug not in reg:
            rejected[slug] = ["нет такого урока в реестре"]
            continue
        text = f.read_text(encoding="utf-8")
        bad = V.problems(text, "ru")
        if bad:
            rejected[slug] = bad
            continue
        reg[slug]["ru"] = text
        reg[slug]["fixed"] = today
        log = f.with_suffix(".log")
        if log.exists():
            reg[slug]["fix_note"] = log.read_text(encoding="utf-8").strip()[:600]
        applied.append(slug)
    stats = to_kb.rebuild(reg)
    registry.save_lessons(reg)
    print(f"применено: {len(applied)}, отклонено: {len(rejected)}; " + to_kb.report(stats))
    for slug, bad in rejected.items():
        print(f"  ОТКЛОНЁН {slug}: {'; '.join(bad)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "find":
        find(" ".join(a[1:]))
    elif len(a) >= 2 and a[0] == "show":
        show(a[1], "--source" in a)
    elif len(a) == 3 and a[0] == "set":
        set_ru(a[1], a[2])
    elif len(a) == 2 and a[0] == "setdir":
        set_dir(a[1])
    else:
        print(__doc__)
