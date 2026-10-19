# -*- coding: utf-8 -*-
"""
Пройти каталожные планировки и снять наборы изделий со всех, где сборка описана.

Для каждой планировки: очистить сцену, загрузить, найти типы «Сборка», которые
описывают изделие (а не паллету или поднос с деталями и не узел, который сам
входит в другую сборку), и снять с каждого набор (kits.extract). Итог — строка
в журнале на планировку. Запуск: python kit_scan.py [журнал.jsonl] [номер_с]

Долго: каждая планировка скачивается и грузится (секунды — минута). Если R-Pro
перестала отвечать (модальное окно), сканер останавливается, а не долбит мост.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import catalog
import kits
from rpro_client import BridgeError, RProClient

SKIP = ("Engine Assembly Layout", "Door assembly")      # уже есть свои наборы
_CARRIER = re.compile(r"(pallet|паллет|поддон|tray|лоток|inventor|kit\b|rack|стеллаж|"
                      r"container|контейнер|bin\b|магазин|magazine|carrier|носител|fixture)",
                      re.IGNORECASE)

PROBE = r"""
ptm = pc().ProductTypeManager
asm = {}
for t in ptm.ProductTypes:
    if not _safe(t, 'IsAssembly'):
        continue
    tree = asm_tree(t)
    parts, subs = [], []
    for st in tree:
        for sl in st['slots']:
            for tn in sl['types']:
                pt = ptm.findProductType(_b(tn))
                if pt is None:
                    continue
                (subs if _safe(pt, 'IsAssembly') else parts).append(tn)
    root = tree[0]['slots'][0]['types'] if tree and tree[0]['slots'] else []
    asm[_u(t.Name)] = {'steps': len(tree), 'parts': sorted(set(parts)), 'subs': sorted(set(subs)),
                       'root': root, 'slots': sum(len(s['slots']) for s in tree)}
result = asm
"""


def candidates(asm: dict) -> list[str]:
    """Сборки-изделия: не входят в другую сборку, не паллета/поднос, ≥ 2 шагов
    с деталями и ≥ 2 разных детали."""
    used_as_sub = {s for a in asm.values() for s in a["subs"]}
    out = []
    for name, a in asm.items():
        if name in used_as_sub:
            continue
        if _CARRIER.search(name) or any(_CARRIER.search(r) for r in a["root"]):
            continue
        if a["steps"] < 2 or len(a["parts"]) + len(a["subs"]) < 2:
            continue
        out.append(name)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    log_path = sys.argv[1] if len(sys.argv) > 1 else "kit_scan.jsonl"
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    client = RProClient(timeout=600)
    layouts = [m for m in catalog.загрузить() if m["тип"] == "планировка"]
    fails = 0
    for i, m in enumerate(layouts):
        if i < start:
            continue
        rec = {"i": i, "имя": m["имя"], "раздел": m["раздел"], "адрес": m["адрес"]}
        if any(s in m["адрес"] for s in SKIP):
            rec["пропуск"] = "уже есть набор"
        else:
            t0 = time.time()
            try:
                client.simulation("reset")
                kits._run(client, "app.clearWorld()\ntry:\n    app.load(%r)\nexcept Exception:\n"
                                  "    pass\nresult = len(app.Components)" % m["адрес"])
                asm = kits._run(client, PROBE)
                rec["сборки"] = asm
                rec["изделия"] = candidates(asm)
                rec["наборы"] = []
                for name in rec["изделия"]:
                    folder = "Набор — " + re.sub(r'[\\/:*?"<>|]', " ", m["имя"])
                    if len(rec["изделия"]) > 1:
                        folder += " — " + name
                    kit = kits.extract(client, name, folder, title=f"{m['имя']}: {name}",
                                       keywords=[], source=m["адрес"])
                    rec["наборы"].append({"папка": folder, "деталей": len(kit["parts"]),
                                          "шагов": len(kit["steps"]), "подсборок": len(kit["subs"])})
                fails = 0
            except (BridgeError, RuntimeError) as exc:
                rec["ошибка"] = str(exc)[:300]
                fails += 1
            rec["с"] = round(time.time() - t0)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(i, m["имя"], "→", rec.get("изделия", rec.get("пропуск", rec.get("ошибка", ""))[:80]),
              flush=True)
        if fails >= 2:
            print("R-Pro дважды подряд не ответила — останавливаюсь (модальное окно?)", flush=True)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
