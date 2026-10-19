# -*- coding: utf-8 -*-
"""
PDF-мануалы документных уроков Academy.

  python academy_pdfs.py links        — найти ссылки на PDF в страницах уроков без видео,
                                        узнать размеры по заголовкам (HEAD), ничего не
                                        скачивать; пишет pending/pdfs.json
  python academy_pdfs.py fetch        — показать план скачивания (файлов, МБ)
  python academy_pdfs.py fetch --yes  — скачать в pending/pdf/<slug>.pdf (уже
                                        скачанные пропускаются)

У 43 уроков вместо видео встроен PDF (плагин PDF Embedder): в странице есть
`pdfemb-data=<base64 от JSON с адресом файла>`. Скачивание — только с
academy.visualcomponents.com и только по явному решению пользователя.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PENDING = HERE / "pending"
UA = {"User-Agent": "Mozilla/5.0"}
ALLOWED_HOST = "academy.visualcomponents.com"


def get(url: str) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")


def pdf_links(page: str) -> list[str]:
    out = []
    for m in re.finditer(r"pdfemb-data=([A-Za-z0-9_%=\-]+)", page):
        raw = urllib.parse.unquote(m.group(1))
        raw += "=" * (-len(raw) % 4)
        try:
            url = json.loads(base64.urlsafe_b64decode(raw))["url"].replace("\\/", "/")
        except (ValueError, KeyError):
            continue
        if urllib.parse.urlparse(url).hostname == ALLOWED_HOST:
            out.append(url)
    return sorted(set(out))


def head_size(url: str) -> int:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"), timeout=30)
        return int(r.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001
        return -1


def cmd_links() -> None:
    catalog = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    docs = [l for l in catalog["lessons"] if not l["youtube"]]

    def one(l: dict) -> tuple[str, list[str]]:
        return l["slug"], pdf_links(get(l["url"]))

    with ThreadPoolExecutor(8) as ex:
        found = dict(ex.map(one, docs))
    rows = []
    for l in docs:
        for u in found[l["slug"]]:
            rows.append({"slug": l["slug"], "title": l["title"], "version": l["version"],
                         "pdf": u, "bytes": head_size(u)})
    PENDING.mkdir(exist_ok=True)
    (PENDING / "pdfs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(max(0, r["bytes"]) for r in rows)
    print(f"уроков без видео: {len(docs)}; PDF найдено: {len(rows)}; общий размер {total / 1e6:.1f} МБ")
    print("без PDF:", [l["slug"] for l in docs if not found[l["slug"]]])


def cmd_fetch(yes: bool) -> None:
    rows = json.loads((PENDING / "pdfs.json").read_text(encoding="utf-8"))
    out = PENDING / "pdf"
    todo = [r for r in rows if not (out / f"{r['slug']}.pdf").exists()]
    total = sum(max(0, r["bytes"]) for r in todo)
    print(f"к скачиванию: {len(todo)} файлов, {total / 1e6:.1f} МБ, с {ALLOWED_HOST} в {out}")
    if not yes:
        print("План показан. Для скачивания добавьте --yes.")
        return
    out.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(todo, 1):
        req = urllib.request.Request(r["pdf"], headers=UA)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            print(f"  ПРОПУСК {r['slug']}: ответ не похож на PDF")
            continue
        (out / f"{r['slug']}.pdf").write_bytes(data)
        print(f"  {i}/{len(todo)} {r['slug']}: {len(data) / 1e6:.1f} МБ", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "links":
        cmd_links()
    elif cmd == "fetch":
        cmd_fetch("--yes" in sys.argv)
    else:
        print(__doc__)
