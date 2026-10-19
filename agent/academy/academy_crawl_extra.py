# -*- coding: utf-8 -*-
"""
Вебинары Academy: python academy_crawl_extra.py

В основной каталог (catalog.json, academy_crawl.py) вебинары не входят: это
отдельный раздел портала, у каждого одно длинное видео на YouTube. Пишет
catalog_extra.json в том же формате, что и уроки (slug, title, version,
оглавление, ID ролика), плюс "kind": "webinar".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from academy_crawl import BASE, get, parse_lesson  # noqa: E402

OUT = HERE / "catalog_extra.json"


def main() -> None:
    sitemap = get(BASE + "/sitemap.xml")
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap)
            if "/webinars/" in u and u.rstrip("/").count("/") >= 4]
    items = []
    for u in urls:
        it = parse_lesson(u)
        it["kind"] = "webinar"
        # у вебинаров вместо названия парсер находит «‹ Back to all webinars»:
        # название берём из тега <title> страницы
        m = re.search(r"<title>(.*?)</title>", get(u), re.S)
        if m:
            it["title"] = re.sub(r"\s*[-–|]\s*Visual Components Academy.*$", "", m.group(1)).strip()
        items.append(it)
    OUT.write_text(json.dumps({"webinars": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    for it in items:
        print(f"{it['slug']} | {it['version'] or '?'} | {it['title'][:60]} | {it['youtube']}")


if __name__ == "__main__":
    main()
