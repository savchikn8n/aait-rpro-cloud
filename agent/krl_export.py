# -*- coding: utf-8 -*-
"""KRL-постпроцессор агента: программа робота R-Pro (JSON-выгрузка) → .src/.dat для KUKA KRC4.

В R-Pro 2.2.2 нет штатного постпроцессора KRL, поэтому агент переводит программу сам.
Вход — JSON, который выгружает мост (подпрограммы, операторы, точки в своих базах
в углах KUKA A/B/C). Выход — модуль KRL в «экспертном» стиле без инлайн-форм:

* каждая подпрограмма R-Pro → DEF в том же .src, Main → DEF <модуль>();
* PTP/LIN → точки FRAME в .dat (P1, P2 …), перед движением — $BASE/$TOOL по номеру;
* SetBin → $OUT[n]=…, Delay → WAIT SEC, Comment → «;», Call → вызов;
* скорости: осевые и по траектории — из параметров (в задании 15 % и 0,1 м/с);
* счётчики: подпрограммы с именем PLACE_* наращивают nCylCount[k] и nTotal.

Запуск:  python krl_export.py program.json out_dir [--module brics_transfer]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _num(name: str) -> int:
    m = re.search(r"\[(\d+)\]", name or "")
    return int(m.group(1)) if m else 0


def _f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0.0" if s in ("-0", "0") else s


def export(program: dict, module: str, vel_axis: int = 15, vel_cp: float = 0.1,
           home=(0.0, -90.0, 90.0, 0.0, 90.0, 0.0)) -> tuple[str, str]:
    routines = program["routines"]
    main = routines[0]
    subs = routines[1:]
    points: list[str] = []
    place_names = [r["name"] for r in subs if r["name"].upper().startswith("PLACE")]

    def body(r: dict) -> list[str]:
        out: list[str] = []
        cur_base = cur_tool = None
        for s in r["statements"]:
            t = s["type"]
            if t == "Comment":
                out.append(f"  ; {s['text']}")
            elif t in ("PtpMotion", "LinMotion"):
                if r["name"].upper() == "GO_HOME" and t == "PtpMotion":
                    out.append("  PTP XHOME           ; A1=0 A2=-90 A3=90 A4=0 A5=90 A6=0")
                    continue
                b, tl = _num(s["base"]), _num(s["tool"])
                if b != cur_base:
                    out.append(f"  $BASE = BASE_DATA[{b}]" if b else "  $BASE = $NULLFRAME")
                    cur_base = b
                if tl != cur_tool:
                    out.append(f"  $TOOL = TOOL_DATA[{tl}]")
                    cur_tool = tl
                n = len(points) + 1
                points.append(
                    f"DECL FRAME XP{n}={{X {_f(s['x'])},Y {_f(s['y'])},Z {_f(s['z'])},"
                    f"A {_f(s['a'])},B {_f(s['b'])},C {_f(s['c'])}}}")
                kw = "PTP" if t == "PtpMotion" else "LIN"
                out.append(f"  {kw} XP{n}")
            elif t == "SetBin":
                out.append(f"  $OUT[{s['port']}] = {'TRUE' if s['value'] else 'FALSE'}")
            elif t == "Delay":
                out.append(f"  WAIT SEC {_f(s['sec'])}")
            elif t == "Call":
                out.append(f"  {s['routine']}()")
            else:
                out.append(f"  ; (оператор {t} не переводится)")
        if r["name"] in place_names:
            k = place_names.index(r["name"]) + 1
            out.append("  ; учёт перенесённых деталей")
            out.append(f"  nCylCount[{k}] = nCylCount[{k}] + 1")
            out.append("  nTotal = nTotal + 1")
        return out

    src = ["&ACCESS RVP", "&REL 1", f"DEF {module}( )"]
    src += [f"  ; Сгенерировано агентом из программы R-Pro ({program.get('robot', '')})"]
    src += ["  INI_CELL()"]
    src += [ln for ln in body(main)]
    src += ["END", ""]
    src += ["DEF INI_CELL( )",
            "  ; Скорости и ускорения; сброс счётчиков",
            "  DECL INT i",
            "  FOR i = 1 TO 6",
            f"    $VEL_AXIS[i] = {vel_axis}   ; осевое перемещение, %",
            "    $ACC_AXIS[i] = 30",
            "  ENDFOR",
            f"  $VEL.CP = {_f(vel_cp)}       ; движение по траектории, м/с",
            "  $VEL.ORI1 = 50",
            "  $VEL.ORI2 = 50",
            "  $ACC.CP = 1.0",
            "  $ACC.ORI1 = 100",
            "  $ACC.ORI2 = 100",
            "  $APO.CPTP = 0",
            "  $APO.CDIS = 0",
            "  nTotal = 0",
            f"  FOR i = 1 TO {max(1, len(place_names))}",
            "    nCylCount[i] = 0",
            "  ENDFOR",
            "END", ""]
    for r in subs:
        src += [f"DEF {r['name']}( )"] + body(r) + ["END", ""]

    h = ",".join(f"A{i + 1} {_f(v)}" for i, v in enumerate(home))
    dat = ["&ACCESS RVP", "&REL 1", f"DEFDAT {module} PUBLIC",
           "; Начальное положение",
           f"DECL E6AXIS XHOME={{{h},E1 0.0,E2 0.0,E3 0.0,E4 0.0,E5 0.0,E6 0.0}}",
           "; Счётчики перенесённых деталей: по каждой и всего",
           f"DECL INT nCylCount[{max(1, len(place_names))}]"]
    dat += [f"nCylCount[{i + 1}]=0" for i in range(max(1, len(place_names)))]
    dat += ["DECL INT nTotal=0", "; Точки программы (в своих базах)"] + points + ["ENDDAT", ""]
    return "\r\n".join(src), "\r\n".join(dat)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("program")
    ap.add_argument("out_dir")
    ap.add_argument("--module", default="brics_transfer")
    ap.add_argument("--vel-axis", type=int, default=15)
    ap.add_argument("--vel-cp", type=float, default=0.1)
    a = ap.parse_args()
    prog = json.loads(Path(a.program).read_text(encoding="utf-8"))
    src, dat = export(prog, a.module, a.vel_axis, a.vel_cp)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # KRC4 читает файлы в однобайтовой кодировке; кириллица комментариев — cp1251
    (out / f"{a.module}.src").write_bytes(src.encode("cp1251", errors="replace"))
    (out / f"{a.module}.dat").write_bytes(dat.encode("cp1251", errors="replace"))
    print(out / f"{a.module}.src")
    print(out / f"{a.module}.dat")


if __name__ == "__main__":
    main()
