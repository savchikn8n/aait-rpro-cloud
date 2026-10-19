# -*- coding: utf-8 -*-
"""
Каталог Visual Components Academy: python academy_crawl.py

Обходит sitemap academy.visualcomponents.com и пишет catalog.json:
по каждому уроку — заголовок, категория, версия ПО, оглавление, ID ролика
на YouTube, ссылки на файлы для скачивания и курсы, в которые урок входит.

Не тратит токены модели и не требует YouTube: всё берётся с самого портала.
Тексты роликов добываются отдельно (см. README.md в этой папке).
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://academy.visualcomponents.com"
OUT = Path(__file__).resolve().parent / "catalog.json"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def main_text(page: str) -> str:
    m = re.search(r"<main.*?</main>", page, re.S)
    t = m.group(0) if m else page
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S)
    t = re.sub(r"<(li|p|h\d|br|div)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t\xa0]+", " ", t)


def parse_lesson(url: str) -> dict:
    page = get(url)
    text = main_text(page)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = next((ln for ln in lines if "Back to all lessons" not in ln), "")
    ver = re.search(r"Software Version:\s*([\d.]+)", text)
    cat = next((ln for ln in lines[:8] if re.fullmatch(r"[A-Z0-9 &|/,.\-]{4,}", ln)), "")
    toc: list[str] = []
    if "Table of contents" in lines:
        for ln in lines[lines.index("Table of contents") + 1:]:
            if ln in ("Download files", "Forum") or ln.startswith("What did you think"):
                break
            toc.append(ln)
    files = sorted(set(re.findall(r'/app/uploads/[^"\']+\.(?:zip|vcmx|vcax|py|pdf)', page)))
    files = [BASE + f for f in files if "data-protection" not in f]
    return {
        "slug": url.rstrip("/").rsplit("/", 1)[1],
        "url": url,
        "title": title,
        "category": cat,
        "version": ver.group(1) if ver else "",
        "toc": toc,
        "youtube": sorted(set(re.findall(r"youtube\.com/embed/([\w-]+)", page))),
        "files": files,
        "courses": [],
    }


def main() -> None:
    sitemap = get(BASE + "/sitemap.xml")
    urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    lessons = [u for u in urls if "/lessons/" in u and u.rstrip("/").count("/") >= 4]
    courses = [u for u in urls if "/courses/" in u and u.rstrip("/").count("/") >= 4]
    print(f"уроков: {len(lessons)}, курсов: {len(courses)}", flush=True)

    with ThreadPoolExecutor(8) as pool:
        items = list(pool.map(parse_lesson, lessons))
        course_pages = list(pool.map(get, courses))

    by_slug = {it["slug"]: it for it in items}
    course_list = []
    for url, page in zip(courses, course_pages):
        cslug = url.rstrip("/").rsplit("/", 1)[1]
        slugs = list(dict.fromkeys(re.findall(r"/lessons/([a-z0-9-]+)/", page)))
        for s in slugs:
            if s in by_slug and cslug not in by_slug[s]["courses"]:
                by_slug[s]["courses"].append(cslug)
        course_list.append({"slug": cslug, "url": url, "lessons": slugs})

    OUT.write_text(json.dumps({"lessons": items, "courses": course_list},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    no_video = [it["slug"] for it in items if not it["youtube"]]
    print(f"записано {OUT.name}; без ролика: {len(no_video)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
