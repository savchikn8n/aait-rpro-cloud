# -*- coding: utf-8 -*-
"""
Сборка базы знаний о R-Pro для агента: python kb_build.py

Источники — то, что ставится вместе с программой:

- Help\\Help_RP_ru.chm — русская справка пользователя: интерфейс, задачи,
  все операторы процесса и робота, все поведения и элементы;
- Help\\Python_API.chm — справка по Python-API с примерами;
- SrcTemplates\\Python Editor\\Auto Complete\\api.xml — машиночитаемый список
  классов, методов и свойств API;
- Python\\Commands — встроенные Python-команды и мастера;
- Shortcutkeys\\Default_Shortcutkeys.xml — горячие клавиши.

Карта ленты (kb/ui_ribbon.md) снимается с живого окна отдельно, скриптом
kb_ui_dump.ps1: для неё нужна запущенная R-Pro.

Результат — kb/chunks.jsonl: фрагменты по несколько тысяч символов с путём
в оглавлении. По ним ищет kb.py. Фрагменты короткие намеренно: локальная
модель работает с контекстом в 8 тысяч токенов, целая глава справки в него
не влезает.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

INSTALL = Path(os.environ.get("RPRO_INSTALL_DIR", r"C:\Program Files (x86)\RProv222"))
OUT = Path(__file__).resolve().parent / "kb"

# Размер фрагмента в символах. Около тысячи токенов: три-четыре таких
# фрагмента помещаются в контекст модели вместе с разговором.
CHUNK = 3000


# --- распаковка CHM ---------------------------------------------------------

def _unpack_chm(chm: Path, dst: Path) -> None:
    """CHM — архив. 7-Zip распаковывает его сразу; hh.exe — запасной путь."""
    dst.mkdir(parents=True, exist_ok=True)
    seven = shutil.which("7z") or r"C:\Program Files\7-Zip\7z.exe"
    if os.path.isfile(seven):
        subprocess.run([seven, "x", str(chm), f"-o{dst}", "-y"],
                       check=True, capture_output=True)
        return
    # hh.exe не любит длинные пути с пробелами и возвращается раньше, чем
    # закончит: копируем файл рядом и ждём появления страниц.
    local = dst / "h.chm"
    shutil.copy(chm, local)
    subprocess.run(["hh.exe", "-decompile", "out", "h.chm"], cwd=dst)
    local.unlink(missing_ok=True)
    out = dst / "out"
    if out.is_dir():
        for p in out.iterdir():
            shutil.move(str(p), dst / p.name)


def _read(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def _page_text(p: Path) -> str:
    """HTML-страница справки → чистый текст с сохранением таблиц и списков."""
    s = _read(p)
    s = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", s)
    s = re.sub(r"(?is)<img[^>]*>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|h\d|li|tr|table|ul|ol)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<(td|th)[^>]*>", " | ", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    # Мусор сворачиваемых оглавлений внутри страниц справки.
    s = re.sub(r"(?m)^\s*\|\s*$", "", s)
    s = re.sub(r"(?mi)^.*\b(CO|СО)ДЕРЖАНИЕ\b.*$", "", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def _toc(src: Path) -> list[dict]:
    """Оглавление .hhc: уровни вложенности <UL> и пункты <OBJECT>."""
    hhc = next(src.glob("*.hhc"))
    tokens = re.findall(r"(<ul>|</ul>|<object.*?</object>)", _read(hhc), re.I | re.S)
    depth, items = 0, []
    for t in tokens:
        tl = t.lower()
        if tl == "<ul>":
            depth += 1
        elif tl == "</ul>":
            depth -= 1
        else:
            name = re.search(r'name="Name"\s+value="([^"]*)"', t, re.I)
            local = re.search(r'name="Local"\s+value="([^"]*)"', t, re.I)
            items.append({"depth": depth,
                          "name": html.unescape(name.group(1)) if name else "",
                          "file": local.group(1).split("#")[0] if local else ""})
    return items


def _split(text: str, size: int = CHUNK) -> list[str]:
    """Режем по абзацам, не разрывая их, пока это возможно."""
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > size:
            parts.append(cur)
            cur = ""
        while len(para) > size:
            parts.append(para[:size])
            para = para[size:]
        cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        parts.append(cur)
    return parts


def help_chunks(chm: Path, source: str, tmp: Path) -> list[dict]:
    src = tmp / source
    _unpack_chm(chm, src)
    chunks, path, seen = [], [], set()
    for item in _toc(src):
        del path[item["depth"] - 1:]
        path.append(item["name"])
        f = item["file"]
        if not f or f in seen or not (src / f).exists():
            continue
        seen.add(f)
        text = _page_text(src / f)
        # Первая строка страницы повторяет заголовок — убираем.
        text = re.sub(r"^\s*" + re.escape(item["name"]) + r"\s*\n", "", text)
        if len(text) < 40:
            continue
        parts = _split(text)
        for i, part in enumerate(parts, 1):
            title = " / ".join(p for p in path if p)
            chunks.append({"source": source, "title": title,
                           "part": f"{i}/{len(parts)}" if len(parts) > 1 else "",
                           "text": part})
    return chunks


# --- api.xml ----------------------------------------------------------------

def api_chunks() -> tuple[list[dict], dict]:
    """Каждый класс API — фрагмент со свойствами, методами и событиями."""
    tree = ET.parse(INSTALL / "SrcTemplates" / "Python Editor" / "Auto Complete" / "api.xml")
    chunks, index = [], {}

    def txt(el, tag):
        x = el.find(tag)
        return (x.text or "").strip() if x is not None and x.text else ""

    for t in tree.getroot().findall("type"):
        name = txt(t, "name")
        lines, info = [], {"parents": txt(t, "parents"), "methods": [], "properties": [], "events": []}
        if info["parents"]:
            lines.append(f"Наследует: {info['parents']}")
        props = t.find("properties")
        if props is not None and len(props):
            lines.append("Свойства:")
            for p in props:
                pn, pt, acc, d = txt(p, "name"), txt(p, "type"), txt(p, "access"), txt(p, "description")
                info["properties"].append(pn)
                lines.append(f"- {pn}: {pt} [{acc}] — {d}")
        meths = t.find("methods")
        if meths is not None and len(meths):
            lines.append("Методы:")
            for m in meths:
                mn, mt, d = txt(m, "name"), txt(m, "type"), txt(m, "description")
                args = []
                ps = m.find("parameters")
                if ps is not None:
                    for a in ps:
                        args.append(f"{txt(a, 'name')}: {txt(a, 'type')}")
                info["methods"].append(mn)
                lines.append(f"- {mn}({', '.join(args)}) -> {mt} — {d}")
        evs = t.find("events")
        if evs is not None and len(evs):
            lines.append("События:")
            for e in evs:
                info["events"].append(txt(e, "name"))
                lines.append(f"- {txt(e, 'name')} — {txt(e, 'description')}")
        index[name] = info
        parts = _split("\n".join(lines).replace("\n- ", "\n\n- "), CHUNK)
        for i, part in enumerate(parts, 1):
            chunks.append({"source": "api", "title": f"Python API / {name}",
                           "part": f"{i}/{len(parts)}" if len(parts) > 1 else "",
                           "text": part.replace("\n\n- ", "\n- ")})
    return chunks, index


# --- встроенные команды и горячие клавиши ------------------------------------

def command_chunks() -> list[dict]:
    """Какие Python-команды регистрирует программа и куда кладёт их на ленте."""
    root = INSTALL / "Python" / "Commands"
    lines = []
    for init in sorted(root.glob("*/__init__.py")):
        text = _read(init)
        loads = re.findall(r'loadCommand\(\s*["\']?([\w\.]+)["\']?', text)
        menus = re.findall(r"addMenuItem\(([^\n]+)\)", text)
        files = sorted(p.name for p in init.parent.glob("*.py") if p.name != "__init__.py")
        lines.append(f"## {init.parent.name}\nкоманды: {', '.join(loads) or '—'}\n"
                     f"пункты меню: {'; '.join(m.strip() for m in menus) or '—'}\n"
                     f"файлы: {', '.join(files)}")
    text = ("Встроенные Python-команды R-Pro (папка Python\\Commands установки). "
            "Выполнить из кода: app.findCommand('ИМЯ').execute().\n\n" + "\n\n".join(lines))
    return _numbered("commands", "Встроенные Python-команды и мастера", _split(text))


def _numbered(source: str, title: str, parts: list[str]) -> list[dict]:
    return [{"source": source, "title": title,
             "part": f"{i}/{len(parts)}" if len(parts) > 1 else "", "text": p}
            for i, p in enumerate(parts, 1)]


def shortcut_chunks() -> list[dict]:
    tree = ET.parse(INSTALL / "Shortcutkeys" / "Default_Shortcutkeys.xml")
    rows = [f"- {k.get('modifiers') + '+' if k.get('modifiers') else ''}{k.get('key')}: "
            f"{k.get('actionItemId')} (контекст {k.get('contextId')})"
            for k in tree.getroot()]
    return _numbered("shortcuts", "Горячие клавиши", ["\n".join(rows)])


def ui_chunks() -> list[dict]:
    """Карта ленты, снятая с живого окна (kb_ui_dump.ps1), — по вкладке на фрагмент."""
    path = OUT / "ui_ribbon.md"
    if not path.is_file():
        print("нет kb/ui_ribbon.md — снимите его kb_ui_dump.ps1 при запущенной R-Pro")
        return []
    chunks = []
    for block in re.split(r"(?m)^## ", path.read_text(encoding="utf-8")):
        if not block.strip() or block.startswith("#"):
            continue
        head, _, body = block.partition("\n")
        chunks += _numbered("ui", "Лента / " + head.strip(), _split(body.strip()))
    return chunks


def main() -> None:
    OUT.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="rpro_kb_"))
    try:
        chunks = help_chunks(INSTALL / "Help" / "Help_RP_ru.chm", "help", tmp)
        print(f"справка: {len(chunks)} фрагментов")
        py = help_chunks(INSTALL / "Help" / "Python_API.chm", "pyhelp", tmp)
        print(f"справка по Python-API: {len(py)} фрагментов")
        api, index = api_chunks()
        print(f"api.xml: {len(index)} классов, {len(api)} фрагментов")
        rest = command_chunks() + shortcut_chunks() + ui_chunks()
        allc = chunks + py + api + rest
        for n, c in enumerate(allc):
            c["id"] = n
        with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in allc:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        (OUT / "api_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        size = (OUT / "chunks.jsonl").stat().st_size
        print(f"итого {len(allc)} фрагментов, {size / 1e6:.1f} МБ → {OUT}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
