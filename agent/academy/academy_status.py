# -*- coding: utf-8 -*-
"""
Состояние всех уроков Academy: python academy_status.py

Пишет по фактам на диске (поэтому не расходится с реальностью):
- status.json — по каждому уроку и вебинару: состояние и причина;
- STATUS.md — человекочитаемая сводка: что в реестре знаний, что ждёт обработки.

Состояния:
  done            урок в реестре (registry/lessons.jsonl); in_kb — вошёл ли в базу агента
  ready           вход подготовлен в pending/lessons/, ждёт запуска модели
  need_pdf        документный урок: PDF ещё не скачан (academy_pdfs.py fetch --yes)
  need_transcript у ролика нет транскрипта (захват не удался: проверьте обе вёрстки панели)
"""

from __future__ import annotations

import json
from pathlib import Path

import registry

HERE = Path(__file__).resolve().parent
PENDING = HERE / "pending"


def load(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def main() -> None:
    cat = load(HERE / "catalog.json", {"lessons": []})["lessons"]
    web = load(HERE / "catalog_extra.json", {"webinars": []})["webinars"]
    items = [dict(x, kind="lesson") for x in cat] + [dict(x, kind="webinar") for x in web]
    reg = registry.load_lessons()
    legacy = {f.stem for f in (HERE / "digests_ru").glob("*.md")} if (HERE / "digests_ru").exists() else set()
    excluded = load(HERE / "work" / "kb_excluded.json", {})
    ready = {r["slug"]: r for r in load(PENDING / "index.json", [])}
    skipped = load(PENDING / "skipped.json", {})
    pdfs = {r["slug"]: r for r in load(PENDING / "pdfs.json", [])}

    status = {}
    for it in items:
        slug = it["slug"]
        if slug in reg or slug in legacy:
            r = reg.get(slug) or {}
            in_kb = r["in_kb"] if r.get("in_kb") is not None else slug not in excluded
            st = {"state": "done", "in_kb": bool(in_kb)}
            why = r.get("excluded_why") or excluded.get(slug, "")
            if why:
                st["why"] = why
            if r.get("audit"):
                st["audit"] = r["audit"]
        elif slug in ready:
            st = {"state": "ready", "input": f"pending/lessons/{slug}.txt", "terms": f"pending/terms/{slug}.json",
                  "batch_kind": ready[slug]["batch_kind"], "tokens": ready[slug]["tokens"]}
        elif not it["youtube"]:
            st = {"state": "need_pdf", "pdf_url": (pdfs.get(slug) or {}).get("pdf"),
                  "mb": round(max(0, (pdfs.get(slug) or {}).get("bytes", 0)) / 1e6, 1)}
        else:
            st = {"state": "need_transcript", "youtube": it["youtube"][0],
                  "why": skipped.get(slug, "транскрипт не захвачен")}
        st.update(kind=it["kind"], title=it["title"], version=it.get("version") or "", url=it["url"])
        status[slug] = st
    (HERE / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")

    by: dict[str, list[str]] = {}
    for slug, st in status.items():
        by.setdefault(st["state"], []).append(slug)
    n = {k: len(v) for k, v in by.items()}
    in_kb = sum(1 for s in by.get("done", []) if status[s]["in_kb"])
    out = [
        "# Реестр знаний Academy: состояние", "",
        "Файл строит `python academy_status.py` по фактам на диске. Машинный вариант — `status.json`.", "",
        "| Состояние | Сколько | Что это |", "|---|---|---|",
        f"| done | {n.get('done', 0)} | урок в реестре `registry/lessons.jsonl` (в базе агента: {in_kb}) |",
        f"| ready | {n.get('ready', 0)} | вход подготовлен в `pending/lessons/`, ждёт запуска модели |",
        f"| need_pdf | {n.get('need_pdf', 0)} | документные уроки без видео: PDF не скачан |",
        f"| need_transcript | {n.get('need_transcript', 0)} | у ролика нет транскрипта |", "",
        "Где что лежит: знания — `registry/lessons.jsonl` (русский урок, английский конспект, метаданные), "
        "исходные тексты — `registry/sources.jsonl.gz`, отчёты оценки — `registry/audit/`, поиск агента — "
        "`../kb/academy_chunks.jsonl`. Рабочие папки `pending/`, `digests_*`, `transcripts/`, `work/` "
        "существуют только во время обработки и убираются командой `academy_consolidate.py --apply --clean`.", "",
    ]
    excl = [s for s in by.get("done", []) if not status[s]["in_kb"]]
    if excl:
        out.append("В реестре, но не в базе агента: " + "; ".join(f"`{s}` ({status[s].get('why', '')})" for s in excl))
        out.append("")

    def table(title: str, slugs: list[str], cols: list[tuple[str, str]], note: str = "") -> None:
        if not slugs:
            return
        out.append(f"## {title} ({len(slugs)})")
        out.append("")
        if note:
            out.extend([note, ""])
        out.append("| slug | " + " | ".join(c for c, _ in cols) + " |")
        out.append("|---|" + "---|" * len(cols))
        for s in slugs:
            st = status[s]
            out.append(f"| `{s}` | " + " | ".join(str(st.get(k, "")) for _, k in cols) + " |")
        out.append("")

    table("Готовы к запуску модели", by.get("ready", []),
          [("название", "title"), ("версия", "version"), ("тип", "kind"), ("токенов", "tokens"), ("вход", "input")],
          "Запуск — `prompts/HAIKU_RUN_ALL.md`.")
    table("Документные уроки: PDF не скачан", by.get("need_pdf", []),
          [("название", "title"), ("версия", "version"), ("МБ", "mb"), ("PDF", "pdf_url")],
          "Скачать: `python academy_pdfs.py fetch --yes`, затем `python academy_prep_pending.py`.")
    table("У ролика нет транскрипта", by.get("need_transcript", []),
          [("название", "title"), ("ролик", "youtube"), ("причина", "why")])
    (HERE / "STATUS.md").write_text("\n".join(out), encoding="utf-8")
    print(n)


if __name__ == "__main__":
    main()
