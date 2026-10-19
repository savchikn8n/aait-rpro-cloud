# -*- coding: utf-8 -*-
"""
Проверка конспектов без участия модели: python validate_digests.py [en|ru]

Отчётам агентов не верим (они считают байты, а не знаки): смотрим на сами тексты.
Где ищется конспект урока: pending/out/<язык>/<slug>.md (свежий результат запуска),
digests_<язык>/<slug>.md (старая раскладка), затем реестр (registry/lessons.jsonl).

Что проверяется:
- структурные ошибки (блокируют слияние в реестр): нет раздела, нет строки применимости;
  в русском — остались минутные метки [м:сс], метки страниц [p.N], английские TIP:/PITFALL:;
- длина (не блокирует, русские уроки режутся на фрагменты при загрузке в базу): en — слов,
  ru — знаков.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import registry

HERE = Path(__file__).resolve().parent

SECTIONS = {
    "en": ["## Purpose", "## Steps", "## Scripting / API", "## Tips and pitfalls", "## Keywords"],
    "ru": ["## Задача", "## Как сделать", "## Лайфхаки и ловушки", "## Ключевые слова"],
}
# справочные PDF вместо «Steps» могут иметь «Reference»
ALT_SECTIONS = {"## Steps": "## Reference"}
MAX_EN_WORDS = 1000  # английский — промежуточный: русская стадия сожмёт до 2500 знаков
MAX_RU_CHARS = 3200  # около 1000 токенов: два таких фрагмента влезают в контекст 8k


def problems(text: str, lang: str, lengths: bool = False) -> list[str]:
    """Список замечаний; пустой — урок годится. Длина — только при lengths=True."""
    bad = []
    for s in SECTIONS[lang]:
        alt = ALT_SECTIONS.get(s)
        if s not in text and not (alt and alt in text):
            bad.append(f"нет раздела {s}")
    if lang == "en":
        if not re.search(r"^applicability:", text, re.M):
            bad.append("нет строки applicability")
        if lengths and len(text.split()) > MAX_EN_WORDS:
            bad.append(f"длинный: {len(text.split())} слов")
    else:
        if "Применимость к R-Pro:" not in text:
            bad.append("нет строки применимости")
        if lengths and len(text) > MAX_RU_CHARS:
            bad.append(f"длинный: {len(text)} знаков")
        if re.search(r"\[\d+:\d{2}\]|\[p\.\d+\]|\[стр\. ?\d+\]", text):
            bad.append("остались метки времени или страниц")
        if re.search(r"\b(TIP|PITFALL):", text):
            bad.append("остались английские TIP/PITFALL")
    return bad


def find_text(slug: str, lang: str, reg: dict[str, dict]) -> str | None:
    for p in (HERE / "pending" / "out" / lang / f"{slug}.md", HERE / f"digests_{lang}" / f"{slug}.md"):
        if p.exists():
            return p.read_text(encoding="utf-8")
    rec = reg.get(slug)
    return rec.get(lang) if rec else None


def universe(reg: dict[str, dict]) -> list[str]:
    slugs = set(reg)
    for p in (HERE / "pending" / "index.json", HERE / "work" / "index.json"):
        if p.exists():
            slugs |= {i["slug"] for i in json.loads(p.read_text(encoding="utf-8"))}
    for lang in ("en", "ru"):
        for d in (HERE / "pending" / "out" / lang, HERE / f"digests_{lang}"):
            if d.exists():
                slugs |= {f.stem for f in d.glob("*.md")}
    return sorted(slugs)


def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    reg = registry.load_lessons()
    slugs = universe(reg)
    missing, bad, ok = [], {}, 0
    for slug in slugs:
        text = find_text(slug, lang, reg)
        if text is None:
            missing.append(slug)
            continue
        pr = problems(text, lang, lengths=True)
        if pr:
            bad[slug] = pr
        else:
            ok += 1
    print(f"[{lang}] уроков {len(slugs)}: чисто {ok}, с замечаниями {len(bad)}, нет текста {len(missing)}")
    for slug, pr in list(bad.items())[:15]:
        print("  ", slug, "—", "; ".join(pr))
    if missing:
        print("  нет текста:", ", ".join(missing[:15]) + (" …" if len(missing) > 15 else ""))


if __name__ == "__main__":
    main()
