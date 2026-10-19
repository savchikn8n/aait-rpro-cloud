# -*- coding: utf-8 -*-
"""
Слияние обработанных уроков в единый реестр знаний агента.

  python academy_consolidate.py                    # план: что будет слито, что отклонено (ничего не пишет)
  python academy_consolidate.py --apply            # слить в реестр, пересобрать базу агента, проверить
  python academy_consolidate.py --apply --clean    # и убрать рабочие файлы (после успешной проверки)
  python academy_consolidate.py --apply --model "<имя модели>"   # пометить, чем обработаны новые уроки

Что делает --apply:
1. Берёт русский урок и английский конспект из pending/out/{ru,en}/<slug>.md (свежий результат
   запуска) или из digests_{ru,en}/ (старая раскладка). Плохие по структуре (нет разделов, нет
   строки применимости, остались метки времени) НЕ принимает: они остаются в pending/out/ для
   повторной обработки, а скрипт называет их в отчёте.
2. Пишет по строке на урок в registry/lessons.jsonl (метаданные, ru, en, применимость, в базе ли).
3. Пишет исходные тексты (транскрипты с минутами, текст PDF, сырые субтитры) в одну сжатую
   registry/sources.jsonl.gz: по ним потом проверяют и правят уроки.
4. Копирует отчёты оценки качества в registry/audit/.
5. Пересобирает ../kb/academy_chunks.jsonl (поиск агента), обновляет STATUS.md.
6. Проверяет: у каждого урока есть ru, en и исходник, файлы читаются обратно, все уроки,
   попавшие в базу, есть среди фрагментов.

--clean удаляет digests_en/, digests_ru/, transcripts/, work/, pending/ (включая скачанные PDF),
но только если проверка прошла, всё подготовленное к обработке уже в реестре, а все
непустые транскрипты заархивированы. PDF и транскрипты можно получить заново:
academy_pdfs.py fetch --yes и захват через Chrome (grab.js).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import academy_to_kb as to_kb
import registry
import validate_digests as V

HERE = Path(__file__).resolve().parent
CLEAN_DIRS = ["digests_en", "digests_ru", "transcripts", "work", "pending", "__pycache__"]
AUDIT_FILES = [  # (откуда относительно HERE, имя в registry/audit)
    ("work/judge/ab_verdict.md", "ab_verdict.md"),
    ("work/judge/fidelity_1.md", "fidelity_1.md"),
    ("work/judge/fidelity_2.md", "fidelity_2.md"),
    ("work/judge/fidelity_3.md", "fidelity_3.md"),
    ("work/judge/refix_audit_1.md", "refix_audit_1.md"),  # повторный аудит после исправления; имя не fidelity_*, чтобы не затереть оценки «до»
    ("work/judge/lifehacks_part1.md", "lifehacks_part1.md"),
    ("work/judge/lifehacks_part2.md", "lifehacks_part2.md"),
    ("work/judge/lifehacks_part3.md", "lifehacks_part3.md"),
    ("work/judge/sample.json", "sample.json"),
    ("work/e2e_0.json", "e2e_0.json"),
    ("work/e2e_1.json", "e2e_1.json"),
]
LEGACY_MODEL = "claude-haiku-4-5"  # то, чем обработан первый прогон 2026-10-05 (digests_ru/)


def read(p: Path) -> str | None:
    return p.read_text(encoding="utf-8") if p.exists() else None


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def catalog_items() -> dict[str, dict]:
    items: dict[str, dict] = {}
    for l in load_json(HERE / "catalog.json", {"lessons": []})["lessons"]:
        items[l["slug"]] = dict(l, kind="lesson")
    for w in load_json(HERE / "catalog_extra.json", {"webinars": []})["webinars"]:
        items[w["slug"]] = dict(w, kind="webinar")
    return items


def pick(slug: str, lang: str) -> tuple[str | None, str]:
    """Свежий текст из файлов: (текст, откуда: pending | legacy)."""
    for sub, origin in ((Path("pending") / "out" / lang, "pending"), (Path(f"digests_{lang}"), "legacy")):
        t = read(HERE / sub / f"{slug}.md")
        if t is not None:
            return t, origin
    return None, ""


def parse_audit() -> dict[str, dict]:
    out = {}
    row = re.compile(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|\s*(\d)\s*\|\s*(\d)\s*\|\s*([A-Za-z]+)")
    for p in list((HERE / "work" / "judge").glob("fidelity_*.md")) + list(registry.AUDIT.glob("fidelity_*.md")):
        for line in p.read_text(encoding="utf-8").splitlines():
            m = row.match(line)
            if m:
                out[m.group(1)] = {"fidelity": int(m.group(2)), "usefulness": int(m.group(3)), "verdict": m.group(4)}
    return out


def gather(model: str):
    items = catalog_items()
    reg = registry.load_lessons()
    src = registry.load_sources()
    pdfs = {r["slug"]: r["pdf"] for r in load_json(HERE / "pending" / "pdfs.json", [])}
    audit = parse_audit()
    new_slugs, updated, rejected, kept = [], [], {}, 0

    for slug, it in items.items():
        ru, ru_origin = pick(slug, "ru")
        en, _ = pick(slug, "en")
        old = reg.get(slug)
        fresh = ru is not None
        if fresh:
            bad = V.problems(ru, "ru") + ([f"en: {p}" for p in V.problems(en, "en")] if en is not None else [])
            if en is None and not (old and old.get("en")):
                bad.append("нет английского конспекта")
            if bad:
                rejected[slug] = bad
                continue
        elif not old:
            continue  # урок не обрабатывался

        old = old or {}
        origin_file = HERE / ("pending/out/ru" if ru_origin == "pending" else "digests_ru") / f"{slug}.md"
        rec = {
            "slug": slug,
            "title": it["title"],
            "kind": it["kind"],
            "source": "video" if it["youtube"] else "pdf",
            "url": it["url"],
            "version": it.get("version") or "",
            "category": it.get("category") or "",
            "youtube": it["youtube"][0] if it["youtube"] else "",
            "pdf_url": pdfs.get(slug) or old.get("pdf_url", ""),
            "applicability": old.get("applicability", ""),
            "in_kb": old.get("in_kb"),
            "excluded_why": old.get("excluded_why", ""),
            "en": en if en is not None else old.get("en", ""),
            "ru": ru if ru is not None else old.get("ru", ""),
            "processed": old.get("processed") or (
                time.strftime("%Y-%m-%d", time.localtime(origin_file.stat().st_mtime)) if fresh else ""),
            "model": old.get("model") or ((model if ru_origin == "pending" else LEGACY_MODEL) if fresh else ""),
            "audit": audit.get(slug) or old.get("audit"),
        }
        if slug not in reg:
            new_slugs.append(slug)
        elif fresh and (reg[slug].get("ru") != rec["ru"] or reg[slug].get("en") != rec["en"]):
            updated.append(slug)
        else:
            kept += 1
        reg[slug] = rec

        # исходный текст и сырые субтитры
        text = read(HERE / "work" / "lessons" / f"{slug}.txt") or read(HERE / "pending" / "lessons" / f"{slug}.txt")
        if text:
            entry = {"slug": slug, "kind": rec["source"], "id": rec["youtube"], "text": text}
            tr = load_json(HERE / "transcripts" / f"{rec['youtube']}.json", None) if rec["youtube"] else None
            if tr and tr.get("segments"):
                entry["segments"] = tr["segments"]
                entry["seconds"] = tr.get("seconds")
            src[slug] = entry
    return items, reg, src, new_slugs, updated, rejected, kept


def verify(reg: dict[str, dict], src: dict[str, dict], stats: dict) -> list[str]:
    errors = []
    for slug, r in reg.items():
        for k in ("title", "url", "ru", "en"):
            if not r.get(k):
                errors.append(f"{slug}: пустое поле {k}")
        if slug not in src or not src[slug].get("text"):
            errors.append(f"{slug}: нет исходного текста в архиве")
    back = registry.load_lessons()
    back_src = registry.load_sources()
    if set(back) != set(reg) or any(back[s]["ru"] != reg[s]["ru"] for s in reg):
        errors.append("реестр не читается обратно так же, как записан")
    if set(back_src) != set(src):
        errors.append("архив исходников не читается обратно так же, как записан")
    chunk_slugs = {json.loads(l)["slug"] for l in (to_kb.OUT).read_text(encoding="utf-8").splitlines() if l.strip()}
    want = {s for s, r in reg.items() if r.get("in_kb")}
    if want != chunk_slugs:
        errors.append(f"фрагменты базы не совпадают с реестром: {sorted(want ^ chunk_slugs)[:5]}")
    if stats["lessons"] != len(want):
        errors.append("число уроков в базе не сходится со статистикой сборки")
    return errors


def clean_blockers(reg: dict[str, dict], src: dict[str, dict]) -> list[str]:
    """Почему нельзя чистить рабочие файлы."""
    why = []
    prepared = {f.stem for f in (HERE / "pending" / "lessons").glob("*.txt")}
    why += [f"подготовлен, но не слит в реестр: {s}" for s in sorted(prepared - set(reg))]
    for lang in ("ru", "en"):
        d = HERE / "pending" / "out" / lang
        if d.exists():
            why += [f"результат не слит (отклонён проверкой?): pending/out/{lang}/{f.stem}.md"
                    for f in sorted(d.glob("*.md")) if f.stem not in reg]
    archived_ids = {s.get("id") for s in src.values() if s.get("segments")}
    tdir = HERE / "transcripts"
    if tdir.exists():
        for f in sorted(tdir.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("segments") and d.get("id") not in archived_ids:
                why.append(f"транскрипт не заархивирован: {f.name}")
    return why


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="записать реестр и пересобрать базу агента")
    ap.add_argument("--clean", action="store_true", help="после успешной проверки убрать рабочие файлы")
    ap.add_argument("--model", default="", help="чем обработаны новые уроки (для реестра)")
    a = ap.parse_args()
    if a.clean and not a.apply:
        print("--clean только вместе с --apply")
        return 2

    items, reg, src, new_slugs, updated, rejected, kept = gather(a.model)
    print(f"в каталоге {len(items)}; в реестре будет {len(reg)}: новых {len(new_slugs)}, "
          f"обновлено {len(updated)}, без изменений {kept}; отклонено {len(rejected)}")
    for s, bad in rejected.items():
        print(f"  ОТКЛОНЁН {s}: {'; '.join(bad)}")
    if not a.apply:
        print("План показан. Для записи добавьте --apply.")
        return 0

    registry.save_sources(src)
    stats = to_kb.rebuild(reg)           # обновляет in_kb / excluded_why / applicability в записях
    registry.save_lessons(reg)
    registry.AUDIT.mkdir(parents=True, exist_ok=True)
    for rel, name in AUDIT_FILES:
        p = HERE / rel
        if p.exists():
            shutil.copyfile(p, registry.AUDIT / name)
    print(to_kb.report(stats))

    import academy_status
    academy_status.main()

    errors = verify(reg, src, stats)
    if errors:
        print("ПРОВЕРКА НЕ ПРОЙДЕНА:")
        for e in errors[:20]:
            print("  -", e)
        return 1
    print(f"проверка пройдена: уроков {len(reg)}, исходников {len(src)}, фрагментов {stats['chunks']}")

    if not a.clean:
        print("Рабочие файлы оставлены. Убрать: добавьте --clean.")
        return 0
    blockers = clean_blockers(reg, src)
    if blockers:
        print("ЧИСТКА ОТМЕНЕНА, пока есть:")
        for b in blockers[:20]:
            print("  -", b)
        return 1
    freed = 0
    for name in CLEAN_DIRS:
        p = (HERE / name).resolve()
        if HERE.resolve() not in p.parents or not p.exists():
            continue
        freed += dir_size(p)
        shutil.rmtree(p)
        print(f"  удалено {name}/")
    print(f"освобождено {freed / 1e6:.1f} МБ; знания — в registry/ и ../kb/academy_chunks.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
