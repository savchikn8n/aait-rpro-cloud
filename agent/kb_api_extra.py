# -*- coding: utf-8 -*-
"""
Недостающие классы Python-API в справочнике агента: python kb_api_extra.py

kb/api_index.json строится по автодополнению (api.xml) и знает 133 класса, а в Python_API.chm их ~215:
нет процессов (vcProcessController, vcProductType, vcTransportSystem…), дашборда статистики
(vcStatisticsDashboard/Tab/Chart/Series), аниматора камеры (vcViewAnimation) и др. Команда
`/api vcStatisticsChart` отвечала «нет такого класса». Скрипт разбирает страницы CHM и пишет
kb/api_extra.json: {класс: {parents, properties[], methods[], events[], rows{имя: описание}}};
quickref.py подмешивает его в /api. Распаковка — 7-Zip, как в kb_build.py.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
KB = HERE / "kb"
INSTALL = Path(r"C:\Program Files (x86)\RProv222")


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif tag == "tr" and self._depth == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("br", "p") and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self.tables and self._row:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _unpack(chm: Path, dst: Path) -> None:
    seven = shutil.which("7z") or r"C:\Program Files\7-Zip\7z.exe"
    subprocess.run([seven, "x", str(chm), f"-o{dst}", "-y"], check=True, capture_output=True)


def parse_page(path: Path) -> dict:
    p = _Tables()
    p.feed(path.read_text(encoding="utf-8", errors="replace"))
    out = {"parents": "", "properties": [], "methods": [], "events": [], "rows": {}}
    txt = re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace"))
    m = re.search(r"Inherits:\s*([\w. ,]+)", html.unescape(txt))
    if m:
        out["parents"] = re.sub(r"\s+", " ", m.group(1)).strip().split(" ")[0]
    for t in p.tables:
        if not t or not t[0]:
            continue
        head = [h.lower() for h in t[0]]
        if "name" not in head[0]:
            continue
        if len(head) >= 4 and head[1] == "type" and "access" in head[2]:
            kind = "properties"
        elif len(head) >= 3 and ("return" in head[1]) and "param" in head[2]:
            kind = "methods"
        elif len(head) >= 2 and head[0] == "name" and "description" in head[-1] and len(head) == 2:
            kind = "events"
        else:
            continue
        for r in t[1:]:
            if not r or not r[0]:
                continue
            name = r[0].strip()
            out[kind].append(name)
            if kind == "properties":
                out["rows"][name] = f"{name}: {r[1]} [{r[2]}] — {r[3] if len(r) > 3 else ''}"[:600]
            elif kind == "methods":
                out["rows"][name] = f"{name}({r[2] if len(r) > 2 else ''}) -> {r[1]} — {r[3] if len(r) > 3 else ''}"[:600]
            else:
                out["rows"][name] = f"{name} — {r[-1]}"[:300]
    return out


def build() -> int:
    index = json.loads((KB / "api_index.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="rpro_api_"))
    try:
        _unpack(INSTALL / "Help" / "Python_API.chm", tmp)
        extra = {}
        for f in sorted(tmp.glob("vc*.htm")):
            name = f.stem
            if name in index:
                continue
            d = parse_page(f)
            if d["properties"] or d["methods"] or d["events"]:
                extra[name] = d
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (KB / "api_extra.json").write_text(json.dumps(extra, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(extra)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("классов добавлено:", build())
