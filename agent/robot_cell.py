# -*- coding: utf-8 -*-
"""
Робот-ячейка переноса цилиндров (Модуль B TechSkills): от выданных файлов до KRL.

Шаги — проверенные скрипты examples/techskills/moduleB, выполняются внутри R-Pro
через мост:

1. ячейка по приложению: HOME, TOOL_DATA[12], BASE_DATA[13]/[14], захват
   (OUT7 сжать, OUT8 разжать, 1 с), ложементы по базам, 3 цилиндра в гнёздах;
2. программа штатными операторами R-Pro: подпрограммы, комментарии, PTP 15 %,
   LIN 0,1 м/с, проверка захвата в начале;
3. действия по сигналам: OUT[7]=TRUE берёт по TCP захвата;
4. виртуальная пусконаладка: прогон шагами 20 мс с детектором столкновений,
   перебор поворота захвата при укладке; выбирается чистый угол из середины
   чистого диапазона;
5. выгрузка программы и перевод в KRL (krl_export.py) — .src/.dat.

Результат — словарь для модели: что найдено при проверке, куда легли цилиндры,
какие файлы записаны.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import krl_export
from rpro_client import RProClient

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "examples" / "techskills" / "moduleB"
CELL_DIR = Path(os.path.expanduser("~")) / "Documents" / "R-Pro" / "techskills" / "B"

TUNE = r'''
import math, vcMatrix, vcVector
DELTAS = %(deltas)r
sim = app.Simulation
comps = dict((c.Name, c) for c in app.Components)
stand = comps["Простая подставка для робота"]
rob = [ch for ch in stand.ChildComponents if ch.findBehaviour("Executor") is not None][0]
ex = rob.findBehaviour("Executor"); ctrl = ex.Controller; prog = ex.Program
RW = rob.WorldPositionMatrix
B14 = ctrl.Bases[13]
tbl = comps["Таблица А #2"]; t3 = comps["brics_3"]; t15 = comps["brics_15"]
cyls = [c for c in app.Components if c.Name.startswith("Цилиндр")]
I, T, C = VC_NODELIST_INCLUDE, VC_NODELIST_TREE, VC_NODELIST_COMPONENT
HOLES = [(27.5 + 55.0 * k, 35.5 + 55.0 * k) for k in range(3)]
OFF = (80.87, 7.45)

def kuka(x, y, z, a, b, c):
    m = vcMatrix.new(); m.setWPR(c, b, a); m.P = vcVector.new(x, y, z); return m

def apply(delta):
    r_ = math.radians(delta)
    for k in range(3):
        ox = OFF[0] * math.cos(r_) - OFF[1] * math.sin(r_)
        oy = OFF[0] * math.sin(r_) + OFF[1] * math.cos(r_)
        x, y = HOLES[k][0] + ox, HOLES[k][1] + oy
        r = prog.findRoutine("PLACE_CYL_%%d" %% (k + 1))
        for i in range(len(r.Statements)):
            s = r.Statements[i]
            if s.Type not in ("PtpMotion", "LinMotion"): continue
            z = -93.6 if i in (1, 4) else -13.6
            s.Positions[0].PositionInWorld = RW * B14.PositionMatrix * kuka(x, y, z, 90.0 + delta, 0.0, 0.0)

def sweep():
    det = sim.newCollisionDetector()
    det.NodeListA = [(rob, I, T)]
    det.NodeListB = [(tbl, I, C), (t3, I, C), (t15, I, C)] + [(c, I, C) for c in cyls]
    sim.reset()
    hits = {}
    t = 0.0
    while t < 32.5:
        t += 0.02
        sim.run(t)
        if det.testAllCollisions():
            for i in range(det.HitCount):
                a = det.getHitNodeA(i).Name; b = det.getHitNodeB(i).Name
                if a.startswith("Цилиндр") or b == a: continue
                k = "%%s x %%s" %% (a, b)
                hits.setdefault(k, [round(t, 2), round(t, 2)]); hits[k][1] = round(t, 2)
    det.Active = False
    inv = vcMatrix.new(RW * B14.PositionMatrix); inv.invert()
    pos = [[round((inv * c.WorldPositionMatrix).P.X, 1), round((inv * c.WorldPositionMatrix).P.Y, 1)] for c in cyls]
    return hits, round(sim.SimTime, 1), pos

res = []
for d in DELTAS:
    apply(d)
    hits, tend, pos = sweep()
    res.append({"delta": d, "hits": hits, "end_s": tend, "cyl_in_base14": sorted(pos)})
clean = [r["delta"] for r in res if not r["hits"]]
best = clean[len(clean) // 2] if clean else None
if best is not None:
    apply(best)
    hits, tend, pos = sweep()
sim.reset()
result = {"tried": res, "chosen_delta": best,
          "final": {"hits": hits, "cyl_in_base14": sorted(pos)} if best is not None else None}
'''


def _exec(client: RProClient, code: str, label: str):
    r = client.exec_python(code)
    if r.get("stderr"):
        raise RuntimeError(f"{label}: {r['stderr'][-800:]}")
    return r.get("result")


def build_cell(client: RProClient | None = None, deltas=(0, 15, 30, 45, 60),
               module: str = "brics_transfer") -> dict:
    client = client or RProClient(timeout=600)
    out: dict = {"шаги": []}
    client.simulation("reset")
    for name, label in (("01_setup_cell.py", "ячейка по приложению"),
                        ("02_build_program.py", "программа робота"),
                        ("03_grasp_actions.py", "захват по сигналам OUT7/OUT8")):
        res = _exec(client, (STEPS / name).read_text(encoding="utf-8"), label)
        out["шаги"].append({"шаг": label, "итог": res})
    tune = _exec(client, TUNE % {"deltas": list(deltas)}, "проверка столкновений")
    first = tune["tried"][0]
    out["пусконаладка"] = {
        "без_поворота": {"столкновения": first["hits"] or "нет",
                         "цилиндры_в_BASE14": first["cyl_in_base14"]},
        "чистые_углы": [r["delta"] for r in tune["tried"] if not r["hits"]],
        "выбран_поворот_град": tune["chosen_delta"],
        "длительность_цикла_с": first["end_s"],
        "после_поворота": {"столкновения": (tune["final"] or {}).get("hits") or "нет",
                           "цилиндры_в_BASE14": (tune["final"] or {}).get("cyl_in_base14")},
    }
    if tune["chosen_delta"] is None:
        out["ошибка"] = "ни один угол не дал прогона без столкновений"
        return out
    _exec(client, (STEPS / "05_dump_program.py").read_text(encoding="utf-8"), "выгрузка программы")
    prog = json.loads((CELL_DIR / "program.json").read_text(encoding="utf-8"))
    src, dat = krl_export.export(prog, module)
    kdir = CELL_DIR / "krl_agent"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / f"{module}.src").write_bytes(src.encode("cp1251", errors="replace"))
    (kdir / f"{module}.dat").write_bytes(dat.encode("cp1251", errors="replace"))
    client.call("layout", action="save", uri=str(CELL_DIR / "Module_B_by_agent.rpro").replace("\\", "/"))
    out["подпрограммы"] = [r["name"] for r in prog["routines"]]
    out["файлы"] = [str(kdir / f"{module}.src"), str(kdir / f"{module}.dat"),
                    str(CELL_DIR / "Module_B_by_agent.rpro")]
    try:
        import operator_pdf
        out["файлы"].append(operator_pdf.build(kdir / "Инструкция_оператора_Модуль_B.pdf",
                                               kdir / f"{module}.src", kdir / f"{module}.dat",
                                               out["пусконаладка"], out["подпрограммы"]))
    except Exception as exc:  # noqa: BLE001 — инструкция не должна ронять ячейку
        out["инструкция_ошибка"] = str(exc)[:200]
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build_cell(), ensure_ascii=False, indent=1))
