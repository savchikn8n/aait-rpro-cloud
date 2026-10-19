# -*- coding: utf-8 -*-
"""
Подготовка пачек для исправления уроков: python academy_fix_prep.py [--slugs a,b,c] [--limit N]

Цели (если не заданы --slugs):
  A. уроки с вердиктом «fix» из аудитов (registry/audit/fidelity_*.md) — замечания судьи уже есть;
  B. уроки, где идентификатор из раздела «Скрипты и API» не встречается в исходном тексте
     (детерминированный признак искажения или выдумки; без этой проверки такие уроки не видны).

На каждый урок пишется work/fix/in/<slug>.txt: замечания судьи (если есть), текущий русский урок
и исходный текст. Пачки (до ~30 тыс. токенов, до 6 уроков) — work/fix/batches/f01.json…
Исправленные уроки агенты кладут в work/fix/out/<slug>.md (+ <slug>.log), применяются командой
`python academy_lesson.py setdir work/fix/out`. Запуск агентов — prompts/FIX_LESSONS.md.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import registry

HERE = Path(__file__).resolve().parent
FIX = HERE / "work" / "fix"
BATCH_TOKENS, BATCH_MAX = 30000, 6


def audit_sections() -> dict[str, str]:
    """slug → текст замечаний судьи из registry/audit/fidelity_*.md."""
    out: dict[str, str] = {}
    for p in sorted(registry.AUDIT.glob("fidelity_*.md")):
        for sec in re.split(r"\n## (?=[a-z0-9][a-z0-9-]*\n)", p.read_text(encoding="utf-8"))[1:]:
            slug, _, body = sec.partition("\n")
            body = "\n".join(l for l in body.splitlines() if not l.startswith("|")).strip()
            out[slug.strip()] = body
    return out


def suspicious_identifiers(reg: dict[str, dict], src: dict[str, dict]) -> dict[str, list[str]]:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    res: dict[str, list[str]] = {}
    for slug, r in reg.items():
        m = re.search(r"## Скрипты и API\n(.*?)(?=\n## |\Z)", r["ru"], re.S)
        if not m or slug not in src:
            continue
        s = norm(src[slug]["text"])
        ids = {i for tok in re.findall(r"`([^`\n]+)`", m.group(1)) for i in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", tok)}
        miss = sorted(i for i in ids if norm(i) not in s)
        if miss:
            res[slug] = miss
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    reg, src, audit = registry.load_lessons(), registry.load_sources(), audit_sections()
    sus = suspicious_identifiers(reg, src)
    if a.slugs:
        targets = [s.strip() for s in a.slugs.split(",") if s.strip()]
    else:
        A = [s for s, r in reg.items() if (r.get("audit") or {}).get("verdict") == "fix"]
        B = [s for s in sus if s not in A]
        targets = A + B
        print(f"A (аудит «fix»): {len(A)}; B (идентификаторы вне исходника, без аудита): {len(B)}; всего {len(targets)}")
    targets = [t for t in targets if t in reg and not reg[t].get("fixed")]  # уже исправленные не трогаем
    if a.limit:
        targets = targets[: a.limit]

    for sub in ("in", "out", "batches"):
        d = FIX / sub
        d.mkdir(parents=True, exist_ok=True)
        if sub != "out":
            for f in d.iterdir():
                f.unlink()
    sizes = {}
    for slug in targets:
        r = reg[slug]
        notes = audit.get(slug)
        parts = [f"SLUG: {slug}\nTITLE: {r['title']}\nVERSION: {r['version'] or '?'}  KIND: {r['kind']}  SOURCE: {r['source']}\n"]
        if notes:
            parts.append("=== 1. ЗАМЕЧАНИЯ НЕЗАВИСИМОГО АУДИТА (проверены по исходнику; вердикт и список правок в конце) ===\n" + notes)
        else:
            parts.append("=== 1. ЗАМЕЧАНИЙ АУДИТА НЕТ ===\nУрок не аудировался. Автоматическая проверка нашла в разделе «Скрипты и API» "
                         f"идентификаторы, которых нет в исходном тексте: {', '.join(sus.get(slug, [])) or '—'}. "
                         "Проверьте весь урок по исходнику сами.")
        parts.append("=== 2. ТЕКУЩИЙ РУССКИЙ УРОК ===\n" + r["ru"])
        parts.append("=== 3. ИСХОДНЫЙ ТЕКСТ (истина) ===\n" + src[slug]["text"])
        text = "\n\n".join(parts) + "\n"
        (FIX / "in" / f"{slug}.txt").write_text(text, encoding="utf-8")
        sizes[slug] = len(text) // 4

    batches, cur, tok = [], [], 0
    for slug in targets:
        if cur and (tok + sizes[slug] > BATCH_TOKENS or len(cur) >= BATCH_MAX):
            batches.append(cur)
            cur, tok = [], 0
        cur.append(slug)
        tok += sizes[slug]
    if cur:
        batches.append(cur)
    for n, b in enumerate(batches, 1):
        (FIX / "batches" / f"f{n:02d}.json").write_text(json.dumps(b), encoding="utf-8")
    print(f"к исправлению: {len(targets)} уроков, ~{sum(sizes.values())} токенов входа, пачек: {len(batches)}")
    for n, b in enumerate(batches, 1):
        print(f"  f{n:02d}: {len(b)} уроков, ~{sum(sizes[s] for s in b)} токенов")


if __name__ == "__main__":
    main()
