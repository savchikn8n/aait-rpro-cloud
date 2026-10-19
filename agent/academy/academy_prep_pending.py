# -*- coding: utf-8 -*-
"""
Подготовка НЕобработанных уроков к запуску моделью: python academy_prep_pending.py

Необработанные = нет урока в реестре (registry/lessons.jsonl). Входы кладутся в
отдельную папку pending/:

  pending/lessons/<slug>.txt   текст для модели (формат как у work/lessons)
  pending/terms/<slug>.json    русские названия интерфейса, найденные в тексте
  pending/index.json           что готово к запуску и сколько токенов
  pending/batches/v01.json…    пачки видеоуроков и вебинаров
  pending/batches/d01.json…    пачки PDF-мануалов
  pending/skipped.json         что пропущено и почему

Источники:
- уроки и вебинары с транскриптом в transcripts/ (захват через Chrome, grab.js);
- документные уроки: PDF в pending/pdf/<slug>.pdf (academy_pdfs.py fetch --yes).
Результат модель пишет в pending/out/{en,ru}/ (запуск — prompts/HAIKU_RUN_ALL.md);
academy_consolidate.py сливает его в реестр и убирает pending/.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import academy_prep as P
import registry

HERE = Path(__file__).resolve().parent
PENDING = HERE / "pending"
BATCH_TOKENS, BATCH_MAX = 26000, 8


def pdf_text(pdf: Path) -> tuple[str, int]:
    """Текст PDF с отметками страниц [стр. N]; pdftotext (с раскладкой таблиц) или pypdf."""
    pages: list[str] = []
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
                             capture_output=True, check=True).stdout.decode("utf-8", "ignore")
        pages = out.split("\f")
    else:
        from pypdf import PdfReader
        pages = [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    if pages and not pages[-1].strip():
        pages.pop()
    parts = []
    for n, t in enumerate(pages, 1):
        t = re.sub(r"[ \t]{3,}", "  ", t)          # раскладка таблиц раздувает пробелы
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        if t:
            parts.append(f"[стр. {n}]\n{t}")
    return "\n\n".join(parts), len(pages)


def head(item: dict, kind: str, extra: str) -> str:
    return "\n".join([
        f"LESSON: {item['title']}",
        f"CATEGORY: {item.get('category') or '-'}",
        f"VISUAL COMPONENTS VERSION OF THE LESSON: {item.get('version') or '-'}",
        extra,
        f"LESSON PAGE OUTLINE: {'; '.join(item.get('toc') or []) or '-'}",
        "DOWNLOADABLE FILES: " + (", ".join(u.rsplit('/', 1)[1] for u in item.get("files", [])) or "-"),
        f"SOURCE: {item['url']}",
        "",
    ])


def main() -> None:
    catalog = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    extra_p = HERE / "catalog_extra.json"
    webinars = json.loads(extra_p.read_text(encoding="utf-8"))["webinars"] if extra_p.exists() else []
    items = [dict(l, kind="lesson") for l in catalog["lessons"]] + [dict(w, kind="webinar") for w in webinars]
    # обработанное — в реестре (после слияния) или ещё лежит файлами digests_ru/
    legacy = {f.stem for f in (HERE / "digests_ru").glob("*.md")} if (HERE / "digests_ru").exists() else set()
    done = set(registry.load_lessons()) | legacy

    # все транскрипты — и заархивированные в реестре, и свежие в transcripts/;
    # дубли по началу/концу — признак «устаревшей панели»
    recs = {}
    for s in registry.load_sources().values():
        if s.get("segments") and s.get("id"):
            recs[s["id"]] = {"id": s["id"], "segments": s["segments"], "seconds": s.get("seconds") or 0}
    for f in (HERE / "transcripts").glob("*.json") if (HERE / "transcripts").exists() else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["segments"]:
            recs[r["id"]] = r
    seen: dict[str, list[str]] = defaultdict(list)
    for vid, r in recs.items():
        n = re.sub(r"[^a-z0-9]", "", " ".join(s[1] or "" for s in r["segments"]).lower())
        seen["h" + n[:250]].append(vid)
        seen["t" + n[-250:]].append(vid)
    dup = {v for ids in seen.values() if len(ids) > 1 for v in ids}

    for sub in ("lessons", "terms", "batches"):
        d = PENDING / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            f.unlink()
    # сюда модель складывает результат; academy_consolidate.py слила и убрала
    for lang in ("en", "ru"):
        (PENDING / "out" / lang).mkdir(parents=True, exist_ok=True)
    terms = P.load_terms()
    ready: list[dict] = []
    skipped: dict[str, str] = {}

    for it in items:
        slug = it["slug"]
        if slug in done:
            continue
        if it["youtube"]:
            vid = it["youtube"][0]
            r = recs.get(vid)
            if not r:
                skipped[slug] = "у ролика нет транскрипта (субтитров нет или захват не удался)"
                continue
            if vid in dup:
                skipped[slug] = "транскрипт совпадает с другим роликом (устаревшая панель), нужен перезахват"
                continue
            body = "\n\n".join(P.paragraphs(r["segments"]))
            text = (head(it, "video", f"VIDEO LENGTH: {r['seconds'] // 60} min")
                    + "TRANSCRIPT (minute marks at paragraph starts):\n\n" + body + "\n")
            mode, batch_kind = "video", "v"
        else:
            pdf = PENDING / "pdf" / f"{slug}.pdf"
            if not pdf.exists():
                skipped[slug] = "PDF-мануал не скачан (academy_pdfs.py fetch --yes)"
                continue
            body, pages = pdf_text(pdf)
            if len(body) < 400:
                skipped[slug] = "из PDF не извлёкся текст (скан или картинки)"
                continue
            text = (head(it, "pdf", f"DOCUMENT: PDF manual, {pages} pages")
                    + "DOCUMENT TEXT (page marks [стр. N]; figures and screenshots are not available):\n\n"
                    + body + "\n")
            mode, batch_kind = "pdf", "d"
        (PENDING / "lessons" / f"{slug}.txt").write_text(text, encoding="utf-8")
        t = P.terms_for(it["title"] + " " + " ".join(it.get("toc") or []) + " " + body, terms)
        (PENDING / "terms" / f"{slug}.json").write_text(json.dumps(t, ensure_ascii=False, indent=0), encoding="utf-8")
        ready.append({"slug": slug, "title": it["title"], "kind": it["kind"], "source": mode,
                      "batch_kind": batch_kind, "version": it.get("version") or "", "tokens": len(text) // 4,
                      "terms": len(t)})

    for kind in ("v", "d"):
        cur, tok, n = [], 0, 0
        group = sorted((r for r in ready if r["batch_kind"] == kind), key=lambda r: (r["source"], r["slug"]))
        for r in group + [None]:
            if r is None or (cur and (tok + r["tokens"] > BATCH_TOKENS or len(cur) >= BATCH_MAX)):
                if cur:
                    n += 1
                    (PENDING / "batches" / f"{kind}{n:02d}.json").write_text(json.dumps(cur), encoding="utf-8")
                cur, tok = [], 0
            if r:
                cur.append(r["slug"])
                tok += r["tokens"]
    (PENDING / "index.json").write_text(json.dumps(ready, ensure_ascii=False, indent=1), encoding="utf-8")
    (PENDING / "skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=1), encoding="utf-8")
    nb = len(list((PENDING / "batches").glob("*.json")))
    print(f"готово к запуску: {len(ready)} (~{sum(r['tokens'] for r in ready)} токенов), пачек: {nb}; "
          f"пропущено: {len(skipped)}")
    for slug, why in skipped.items():
        print(f"  пропуск {slug}: {why}")


if __name__ == "__main__":
    main()
