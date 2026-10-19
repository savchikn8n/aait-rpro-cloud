# -*- coding: utf-8 -*-
"""
Подготовка уроков для конспектов: python academy_prep.py

Из catalog.json + transcripts/*.json + uiterms.json делает в work/:
- lessons/<slug>.txt — чистый текст урока для модели: заголовок, версия,
  оглавление страницы, список файлов, транскрипт абзацами с отметкой минуты
  (без JSON-обвязки и без таймкода на каждой фразе — это втрое меньше токенов);
- terms/<slug>.json — русские названия элементов интерфейса R-Pro для тех
  английских терминов, что встречаются в этом уроке (из ресурсов программы,
  см. build_uiterms.ps1), чтобы русская стадия не переводила «на глаз»;
- index.json — список уроков с размером в токенах, для нарезки на пачки.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
PARAGRAPH_SEC = 45  # абзац ≈ 45 секунд речи


def secs(ts: str) -> int:
    return sum(int(p) * 60 ** i for i, p in enumerate(reversed((ts or "0").split(":"))))


def paragraphs(segments: list[list[str]]) -> list[str]:
    out, buf, start = [], [], None
    for ts, text in segments:
        t = secs(ts)
        if start is None:
            start = t
        buf.append((text or "").strip())
        if t - start >= PARAGRAPH_SEC:
            out.append(f"[{start // 60}:{start % 60:02d}] " + " ".join(buf))
            buf, start = [], None
    if buf:
        out.append(f"[{start // 60}:{start % 60:02d}] " + " ".join(buf))
    return out


def load_terms() -> list[tuple[str, str, int]]:
    """(английский термин, русский, число слов) — только похожие на названия
    элементов интерфейса, а не на фразы сообщений об ошибках."""
    pairs = json.loads((HERE / "uiterms.json").read_text(encoding="utf-8"))
    seen: dict[str, list[str]] = defaultdict(list)
    for p in pairs:
        en, ru = (p["en"] or "").strip(), (p["ru"] or "").strip()
        if not en or not ru or en.lower() == ru.lower():
            continue
        if len(en) > 45 or len(en) < 4 or any(c in en for c in "{}\n\r.:;!?") or len(en.split()) > 5:
            continue
        if re.search(r"[а-яА-Я]", en) or not re.search(r"[а-яА-Я]", ru):
            continue
        if ru not in seen[en.lower()]:
            seen[en.lower()].append(ru)
    return [(en, " / ".join(rus[:2]), len(en.split())) for en, rus in seen.items()]


def terms_for(text: str, terms: list[tuple[str, str, int]], limit: int = 45) -> dict[str, str]:
    # считаем n-граммы слов текста один раз и ищем термины по словарю
    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", text.lower())
    grams: dict[str, int] = defaultdict(int)
    for n in range(1, 6):
        for i in range(len(words) - n + 1):
            grams[" ".join(words[i:i + n])] += 1
    hits = []
    for en, ru, nwords in terms:
        key = " ".join(re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", en))
        n = grams.get(key, 0)
        # однословные термины шумят («record», «name»): берём только частые
        if n and (nwords > 1 or (n >= 3 and len(en) >= 6)):
            hits.append((nwords, n, en, ru))
    hits.sort(reverse=True)
    return {en: ru for _, _, en, ru in hits[:limit]}


def main() -> None:
    catalog = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    by_yt = {l["youtube"][0]: l for l in catalog["lessons"] if l["youtube"]}
    terms = load_terms()
    print(f"терминов интерфейса: {len(terms)}")
    (WORK / "lessons").mkdir(parents=True, exist_ok=True)
    (WORK / "terms").mkdir(parents=True, exist_ok=True)

    # Защита от «устаревшей панели»: у двух разных роликов не может быть
    # одинакового транскрипта (так в базу попал текст соседнего ролика).
    # Сверяем начало и конец нормализованного текста по всему набору.
    recs = {}
    for f in sorted((HERE / "transcripts").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["segments"] and r["id"] in by_yt:
            recs[r["id"]] = r
    seen: dict[str, list[str]] = defaultdict(list)
    for vid, r in recs.items():
        n = re.sub(r"[^a-z0-9]", "", " ".join(s[1] or "" for s in r["segments"]).lower())
        seen["h" + n[:250]].append(vid)
        seen["t" + n[-250:]].append(vid)
    dup = {v for ids in seen.values() if len(ids) > 1 for v in ids}
    if dup:
        print("ДУБЛИ ТРАНСКРИПТОВ, пропускаю:", sorted(by_yt[v]["slug"] for v in dup))

    index = []
    for f in sorted((HERE / "transcripts").glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        if not rec["segments"] or rec["id"] not in by_yt or rec["id"] in dup:
            continue
        les = by_yt[rec["id"]]
        body = "\n\n".join(paragraphs(rec["segments"]))
        head = [
            f"LESSON: {les['title']}",
            f"CATEGORY: {les['category'] or '-'}",
            f"VISUAL COMPONENTS VERSION OF THE LESSON: {les['version'] or '-'}",
            f"VIDEO LENGTH: {rec['seconds'] // 60} min",
            f"LESSON PAGE OUTLINE: {'; '.join(les['toc']) or '-'}",
            "DOWNLOADABLE FILES: " + (", ".join(u.rsplit('/', 1)[1] for u in les["files"]) or "-"),
            f"SOURCE: {les['url']}",
            "",
            "TRANSCRIPT (minute marks at paragraph starts):",
            "",
        ]
        text = "\n".join(head) + body + "\n"
        slug = les["slug"]
        (WORK / "lessons" / f"{slug}.txt").write_text(text, encoding="utf-8")
        t = terms_for(les["title"] + " " + " ".join(les["toc"]) + " " + body, terms)
        (WORK / "terms" / f"{slug}.json").write_text(
            json.dumps(t, ensure_ascii=False, indent=0), encoding="utf-8")
        index.append({"slug": slug, "title": les["title"], "version": les["version"],
                      "category": les["category"], "tokens": len(text) // 4, "terms": len(t)})

    (WORK / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    tot = sum(i["tokens"] for i in index)
    print(f"уроков: {len(index)}, всего ~{tot} токенов, в среднем {tot // max(1, len(index))}")


if __name__ == "__main__":
    main()
