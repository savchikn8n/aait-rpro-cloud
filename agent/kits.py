# -*- coding: utf-8 -*-
"""
Наборы изделий для сборочной линии: из каких деталей и как собирается.

Набор — kit.json в «Мои модели\\<изделие>»: детали (файл модели и габарит),
шаги сборки с гнёздами и, если есть, подсборки (узел, который сам собирается
из деталей и потом ставится в изделие целиком). Строитель (assembly_builder)
раскладывает по набору посты: шаг сборки — пост, крупную деталь ставит робот,
мелкую — оператор.

Набор не пишется руками: его снимают с каталожной планировки, где сборка уже
описана (тип продукта «Сборка»), — extract(). Детали сохраняются отдельными
моделями, позиции гнёзд берутся как есть.
"""

from __future__ import annotations

import json
import os
from typing import Any

from rpro_client import RProClient

MY_MODELS = os.path.join(os.path.expanduser("~"), "Documents", "R-Pro", "0.2", "My Models")
_HANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hands27.py")


def _run(client: RProClient, code: str) -> Any:
    with open(_HANDS, encoding="utf-8") as f:
        lib = f.read()
    r = client.exec_python(lib + "\n" + code)
    if r.get("stderr"):
        raise RuntimeError(r["stderr"])
    return r.get("result")


def load_kits() -> dict[str, dict]:
    """Все наборы из «Моих моделей»: ключ — название изделия."""
    kits = {}
    if not os.path.isdir(MY_MODELS):
        return kits
    for folder in os.listdir(MY_MODELS):
        path = os.path.join(MY_MODELS, folder, "kit.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                kit = json.load(f)
            kit["folder"] = os.path.join(MY_MODELS, folder)
            kits[kit["title"]] = kit
    return kits


def find_kit(words: str) -> dict | None:
    """Набор по словам пользователя: «дверь» → «Дверь автомобиля»."""
    words = (words or "").lower()
    for title, kit in load_kits().items():
        keys = [title.lower()] + [k.lower() for k in kit.get("keywords", [])]
        if any(k in words or words in k for k in keys if k):
            return kit
    return None


def extract(client: RProClient, asm_name: str, folder: str, title: str,
            names: dict[str, str] | None = None, keywords: list[str] | None = None,
            source: str = "") -> dict:
    """Снять набор с планировки, которая сейчас открыта: тип «Сборка» asm_name,
    его детали и подсборки. names — русские названия деталей и шагов."""
    out_dir = os.path.join(MY_MODELS, folder)
    os.makedirs(out_dir, exist_ok=True)
    data = _run(client, """
ptm = pc().ProductTypeManager
def grab(name, seen):
    t = ptm.findProductType(_b(name))
    tree = asm_tree(t)
    res = {'name': _u(t.Name), 'steps': tree, 'subs': {}, 'parts': {}}
    for st in tree:
        for sl in st['slots']:
            for tn in sl['types']:
                if tn in seen:
                    continue
                seen.add(tn)
                pt = ptm.findProductType(_b(tn))
                if _safe(pt, 'IsAssembly'):
                    res['subs'][tn] = grab(tn, seen)
                else:
                    res['parts'][tn] = save_template(pt, OUT + u'/' + tn + u'.rpro')
    return res
OUT = %r
result = grab(%r, set())
""" % (out_dir.replace("\\", "/"), asm_name))

    def parts_of(node: dict) -> dict:
        parts = {name: {"file": f"{name}.rpro", "size": size} for name, size in node["parts"].items()}
        for sub in node["subs"].values():
            parts.update(parts_of(sub))
        return parts

    kit = {"title": title, "keywords": keywords or [], "names": names or {}, "source": source,
           "assembly": data["name"], "steps": data["steps"],
           "subs": {k: {"steps": v["steps"]} for k, v in data["subs"].items()},
           "parts": parts_of(data)}
    with open(os.path.join(out_dir, "kit.json"), "w", encoding="utf-8") as f:
        json.dump(kit, f, ensure_ascii=False, indent=1)
    return kit
