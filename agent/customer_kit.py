# -*- coding: utf-8 -*-
"""
Набор изделия из моделей заказчика: CAD-файлы + сборочная спецификация.

Заказчик присылает папку: модели деталей (STEP, STL, IGES, OBJ, glTF…) и,
по возможности, спецификацию сборки — таблицу для Excel (CSV через «;»):

    # Изделие: Шатунно-поршневая группа (ШПГ) двигателя 1,6 л
    # Ось вверх в CAD: Y
    # Координаты деталей: сборки
    Поз;Операция;Деталь;Файл;Кол-во;Кто;Время, с;Примечание
    1;Установка поршня в спутник;Поршень;CAD/piston.stl;1;робот;;базовая деталь
    4;Установка стопорных колец;;;;оператор;10;операция без детали

Строки с файлом — шаги сборки (деталь ставится в гнездо), строки без файла —
рабочие операции (пост, где оператор или робот работает заданное время).
Первая деталь — базовая: с неё начинается изделие на линии.

Положения деталей. Самый частый случай — детали выгружены из сборки «на своих
местах» (так делает SolidWorks, Inventor, Компас при сохранении сборки по
деталям): тогда гнездо каждой детали — одно и то же преобразование всего
изделия: сдвиг, чтобы изделие стояло на ленте низом по центру, и поворот, если
в CAD «вверх» — не Z. Без спецификации берём все CAD-файлы папки, по порядку
имён, и тоже считаем их выгруженными из сборки.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from typing import Any

import cad_path
import kits
from rpro_client import RProClient

CAD_EXT = (".stl", ".step", ".stp", ".igs", ".iges", ".obj", ".gltf", ".glb", ".fbx", ".3mf",
           ".jt", ".sat", ".x_t", ".sldprt", ".ipt", ".catpart", ".3ds", ".dae", ".wrl")
CUSTOMERS = os.path.join(os.path.expanduser("~"), "Documents", "Заказчики")


def find_folder(name_or_path: str) -> str | None:
    """Папка заказчика: полный путь или часть имени в «Документы\\Заказчики»."""
    if name_or_path and os.path.isdir(name_or_path):
        return name_or_path
    if not os.path.isdir(CUSTOMERS):
        return None
    key = (name_or_path or "").lower()
    for d in sorted(os.listdir(CUSTOMERS)):
        if key and key in d.lower():
            return os.path.join(CUSTOMERS, d)
    return None


def read_spec(folder: str) -> dict[str, Any]:
    """Спецификация: шапка «# Ключ: значение» и строки операций."""
    specs = [f for f in os.listdir(folder) if f.lower().endswith(".csv")]
    specs.sort(key=lambda f: ("специф" not in f.lower(), f))
    if not specs:
        return {"meta": {}, "rows": []}
    with open(os.path.join(folder, specs[0]), encoding="utf-8-sig") as f:
        text = f.read()
    meta, body = {}, []
    for line in text.splitlines():
        if line.startswith("#"):
            k, _, v = line[1:].partition(":")
            meta[k.strip().lower()] = v.strip()
        elif line.strip():
            body.append(line)
    rows = list(csv.DictReader(io.StringIO("\n".join(body)), delimiter=";"))
    return {"meta": meta, "rows": rows, "file": specs[0]}


def _col(row: dict, *names: str) -> str:
    for k, v in row.items():
        if k and any(k.strip().lower().startswith(n) for n in names):
            return (v or "").strip()
    return ""


def _who(text: str) -> str | None:
    t = (text or "").lower()
    if "робот" in t or "robot" in t or "автомат" in t:
        return "robot"
    if "опер" in t or "челов" in t or "ручн" in t or "manual" in t:
        return "operator"
    return None


def _sub_ref(file_cell: str) -> str:
    """«узел: ШПГ» в колонке «Файл» — готовый узел из другого набора заказчика."""
    m = re.match(r"\s*узел\s*[:—-]\s*(.+)", file_cell or "", re.IGNORECASE)
    return m.group(1).strip() if m else ""


# Технологическая операция робота — по колонке «Процесс» или по названию
# операции. Порядок важен: «Пайка оплавлением» — печь, а не пайка роботом.
PROCESS_WORDS = [
    ("oven", ("печь", "оплавлен", "сушк", "отвержд", "термообраб")),
    ("dispense", ("нанесен", "склейк", "клей", "герметиз", "герметик", "паст", "дозир", "грунт")),
    ("solder", ("пайк", "припа")),
    ("weld", ("сварк", "свар")),
    ("screw", ("завинч", "винт", "затяжк", "гайковерт", "гайковёрт", "болт")),
    ("inspect", ("контрол", "провер", "инспекц", "aoi", "оптическ")),
    ("test", ("испыт", "тест", "eol")),
]
BEAD_KINDS = ("dispense", "solder", "weld", "screw")   # после них на изделии что-то появляется
PROCESS_RU = {"oven": "печь", "dispense": "нанесение", "solder": "пайка", "weld": "сварка",
              "screw": "завинчивание", "inspect": "контроль", "test": "испытание"}


def process_kind(text: str) -> str:
    t = (text or "").lower()
    for kind, words in PROCESS_WORDS:
        if any(w in t for w in words):
            return kind
    return ""


# Цвет детали из спецификации (колонка «Цвет»): STL приходит без материалов.
# Берём готовый материал R-Pro (у неё их 215: металлы с текстурой, пластики),
# цвет в RGB — на случай, если такого нет.
COLORS = {
    "синий": ("blue_metallic", (0.12, 0.30, 0.75)), "голубой": ("light_blue", (0.40, 0.70, 0.95)),
    "зеленый": ("plastic_green", (0.05, 0.45, 0.15)), "темно-зеленый": ("dark_green", (0.02, 0.28, 0.10)),
    "желтый": ("plastic_yellow", (0.95, 0.80, 0.10)), "оранжевый": ("orange", (1.0, 0.45, 0.0)),
    "красный": ("red", (0.85, 0.10, 0.10)), "розовый": ("light_pink_matte", (0.95, 0.55, 0.65)),
    "белый": ("white_matte", (0.95, 0.95, 0.95)), "бежевый": ("beige_matte", (0.85, 0.75, 0.60)),
    "черный": ("plastic_black", (0.08, 0.08, 0.08)), "темно-серый": ("dark_grey_matte", (0.25, 0.25, 0.27)),
    "серый": ("grey_metallic", (0.50, 0.50, 0.52)), "светло-серый": ("light_grey", (0.75, 0.75, 0.77)),
    "алюминий": ("aluminium_brushed", (0.78, 0.80, 0.82)), "сталь": ("steel_brushed", (0.60, 0.62, 0.65)),
    "медь": ("copper_brushed", (0.85, 0.45, 0.20)), "золото": ("gold", (0.90, 0.75, 0.25)),
    "серебро": ("nickel", (0.85, 0.85, 0.88)), "серебристый": ("nickel", (0.85, 0.85, 0.88)),
    "графит": ("gunmetal", (0.18, 0.19, 0.21)),
}


def color_rgb(name: str) -> tuple | None:
    """Цвет → (материал R-Pro, RGB) или None."""
    key = (name or "").strip().lower().replace("ё", "е")
    return COLORS.get(key)


def _num(text: str) -> float | None:
    try:
        return float((text or "").replace(",", "."))
    except ValueError:
        return None


def _product_box(steps: list[dict], parts: dict, sub_boxes: dict) -> list | None:
    """Габарит готового изделия в его системе: каждая деталь — своим габаритом
    из CAD на своём месте в сборке; узел — габаритом своего набора. Нужен
    постам (длина и ширина ленты) и камере контроля (проход над изделием)."""
    lo, hi = [1e18] * 3, [-1e18] * 3

    def add(blo, bhi, pos):
        a, b = cad_path.transform_box(blo, bhi, pos)
        for k in range(3):
            lo[k], hi[k] = min(lo[k], a[k]), max(hi[k], b[k])
    for st in steps:
        for sl in st.get("slots", []):
            t = sl["types"][0]
            if t in parts:
                c, h = parts[t]["center"], parts[t]["half"]
                add([c[k] - h[k] for k in range(3)], [c[k] + h[k] for k in range(3)], sl["pos"])
            elif t in sub_boxes:
                add(sub_boxes[t][0], sub_boxes[t][1], sl["pos"])
        if st.get("bead") in parts:
            c, h = parts[st["bead"]]["center"], parts[st["bead"]]["half"]
            add([c[k] - h[k] for k in range(3)], [c[k] + h[k] for k in range(3)], st["bead_pos"])
    if lo[0] > hi[0]:
        return None
    return [[round(v, 1) for v in lo], [round(v, 1) for v in hi]]


def build_kit(client: RProClient, folder: str, title: str = "") -> dict:
    spec = read_spec(folder)
    meta, rows = spec["meta"], spec["rows"]
    if not rows:
        # без спецификации — все CAD-файлы по порядку имён, первый — базовый
        files = sorted(os.path.relpath(os.path.join(dp, f), folder)
                       for dp, _, fs in os.walk(folder) for f in fs
                       if f.lower().endswith(CAD_EXT))
        rows = [{"Операция": f"Установка: {os.path.splitext(os.path.basename(f))[0]}",
                 "Деталь": os.path.splitext(os.path.basename(f))[0], "Файл": f} for f in files]
    # название из спецификации заказчика главнее: модель любит передавать своё
    # короткое («ШПГ»), и набор сохранялся бы второй раз под другим именем
    title = meta.get("изделие") or title or os.path.basename(folder)
    abbr = re.search(r"\(([A-ZА-ЯЁ0-9]{2,6})\)", title)
    short = abbr.group(1) if abbr else title.split()[0]
    up = (meta.get("ось вверх в cad") or "Z").strip().upper()[:1]

    out_dir = os.path.join(kits.MY_MODELS, "Заказчик — " + re.sub(r'[\\/:*?"<>|]', " ", title)[:80])
    os.makedirs(out_dir, exist_ok=True)

    # 1. детали: импорт CAD → модели R-Pro, габариты в координатах CAD
    client.simulation("reset")
    parts: dict[str, dict] = {}
    for row in rows:
        f, name = _col(row, "файл"), _col(row, "деталь")
        if not f or name in parts or _sub_ref(f):
            continue
        cad = os.path.join(folder, f)
        if not os.path.isfile(cad):
            raise FileNotFoundError(f"нет файла детали «{name}»: {f}")
        model = re.sub(r'[\\/:*?"<>|]', " ", name) + ".rpro"
        color = _col(row, "цвет")
        mat = color_rgb(color)
        b = kits._run(client, "result = import_part(%r, %r, %r, %r)"
                      % (cad.replace("\\", "/"), os.path.join(out_dir, model).replace("\\", "/"),
                         mat[0] if mat else None, list(mat[1]) if mat else None))
        size = round(2.0 * max(b["half"]), 1)
        parts[name] = {"file": model, "size": size, "center": b["center"], "half": b["half"], "cad": cad}
        if mat:
            parts[name]["color"] = color
        if process_kind(_col(row, "процесс")) in BEAD_KINDS:
            parts[name]["bead"] = True     # не деталь в гнездо, а след операции робота

    # 2. общее преобразование изделия: низом на ленту, по центру; «вверх» → Z.
    # Базовая деталь — внизу: она первой ложится в спутник, и без остальных
    # деталей не должна висеть в воздухе (поршень — днищем вниз). Если в CAD
    # она сверху — изделие переворачивается.
    lo = [min(p["center"][a] - p["half"][a] for p in parts.values()) for a in range(3)]
    hi = [max(p["center"][a] + p["half"][a] for p in parts.values()) for a in range(3)]
    mid = [(lo[a] + hi[a]) / 2.0 for a in range(3)]
    base = parts[next(iter(parts))]
    axis = {"X": 0, "Y": 1, "Z": 2}.get(up, 2)
    flip = base["center"][axis] > mid[axis]
    if up == "Y" and not flip:
        ref = [mid[0], lo[1], mid[2]]
        slot = [-ref[0], ref[2], -ref[1], 90.0, 0.0, 0.0]      # X+90°: Y → Z
    elif up == "Y":
        ref = [mid[0], hi[1], mid[2]]
        slot = [-ref[0], -ref[2], ref[1], -90.0, 0.0, 0.0]     # X−90°: Y → −Z
    elif up == "X":
        ref = [lo[0], mid[1], mid[2]]
        slot = [-ref[2], -ref[1], -ref[0], 0.0, -90.0, 0.0]
    elif flip:
        ref = [mid[0], mid[1], hi[2]]
        slot = [-ref[0], ref[1], ref[2], 180.0, 0.0, 0.0]      # X 180°: Z → −Z
    else:
        ref = [mid[0], mid[1], lo[2]]
        slot = [-ref[0], -ref[1], -ref[2], 0.0, 0.0, 0.0]
    slot = [round(v, 2) for v in slot]

    # 3. шаги: деталь — шаг сборки (цепочкой от базовой), операция — пост работы.
    # Если деталь выгружена в своих координатах, её место в изделии задают
    # колонки X, Y, Z (мм от низа базовой детали по центру) и RX, RY, RZ (°).
    def own_pos(row: dict) -> list[float] | None:
        vals = [_num(_col(row, k)) for k in ("x", "y", "z")]
        if any(v is None for v in vals):
            return None
        rot = [_num(_col(row, k)) or 0.0 for k in ("rx", "ry", "rz")]
        return [round(v, 2) for v in vals + rot]

    steps: list[dict] = []
    subs: dict[str, dict] = {}
    sub_parts: dict[str, dict] = {}
    sub_boxes: dict[str, list] = {}
    parent = None
    for row in rows:
        op = _col(row, "операц") or _col(row, "деталь")
        name, f = _col(row, "деталь"), _col(row, "файл")
        who, t = _who(_col(row, "кто")), _num(_col(row, "время"))
        # технологическая операция: в колонке «Процесс» или, у строки без детали,
        # по названию («Затяжка болтов», «Контроль модуля»)
        kind = process_kind(_col(row, "процесс")) or ("" if f else process_kind(op))
        scrap = _num(_col(row, "брак")) or 0.0
        if not f or (kind in BEAD_KINDS and not _sub_ref(f)):
            step = {"name": op, "who": who, "work_s": t, "operation": True, "parent": None, "slots": []}
            if kind:
                step["process"] = kind
            if scrap:
                step["scrap"] = scrap
            if f:
                # след операции (валик клея, пайка, швы, болты) — где он в изделии
                # и как по нему идёт инструмент робота
                pos = own_pos(row) or slot
                step.update(bead=name, bead_pos=pos, path=cad_path.bead_strokes(
                    os.path.join(folder, f), pos, as_points=kind in ("solder", "weld", "screw"),
                    limit=40 if kind == "screw" else cad_path.MAX_POINTS))
            steps.append(step)
            continue
        ref = _sub_ref(f)
        if ref:
            # готовый узел из другого набора заказчика (ШПГ на коленвал): место —
            # где узел стоит в CAD изделия относительно своего CAD-положения
            sub = kits.find_kit(ref)
            if sub is None:
                raise ValueError(f"узел «{ref}» не найден — сначала прими модели узла (его папку)")
            sub_title = sub["title"]
            sub_steps = [s for s in sub["steps"] if not s.get("operation")]
            sub_slot = sub_steps[0]["slots"][0]["pos"]
            move = own_pos(row) or [0.0] * 6
            pos = kits._run(client, "result = compose_slot(%r, %r, %r)" % (slot, move, sub_slot))
            subs[sub_title] = {"steps": sub_steps, "supply": "store"}
            if sub.get("bbox"):
                sub_boxes[sub_title] = sub["bbox"]
            for n, p in sub["parts"].items():
                sub_parts[n] = {**{k: p[k] for k in ("file", "size", "half", "color", "bead") if k in p},
                                "path": p.get("path") or os.path.join(sub["folder"], p["file"])}
            name = sub_title
        else:
            pos = own_pos(row) or slot
        # строки подряд с одной операцией — один шаг с несколькими местами
        if steps and not steps[-1].get("operation") and steps[-1]["name"] == op:
            steps[-1]["slots"].append({"types": [name], "pos": pos,
                                       "order": len(steps[-1]["slots"]) + 1})
            continue
        steps.append({"name": op, "who": who, "work_s": t, "parent": parent, "rel": None,
                      "slots": [{"types": [name], "pos": pos, "order": 1}]})
        parent = op

    all_parts = {n: {k: p[k] for k in ("file", "size", "half", "color", "bead") if k in p}
                 for n, p in parts.items()}
    all_parts.update(sub_parts)
    kit = {"title": title, "short": short, "source": folder, "spec": spec.get("file", ""),
           "keywords": [w for w in re.findall(r"[a-zа-яё0-9]{3,}", title.lower())],
           "names": {}, "assembly": title, "steps": steps, "subs": subs,
           "parts": all_parts, "bbox": _product_box(steps, parts, sub_boxes),
           "takt_s": _num(meta.get("такт заказчика, с", "")), "up_axis": up}
    with open(os.path.join(out_dir, "kit.json"), "w", encoding="utf-8") as fh:
        json.dump(kit, fh, ensure_ascii=False, indent=1)
    kit["folder"] = out_dir
    return kit


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    k = build_kit(RProClient(timeout=300), find_folder(sys.argv[1]) or sys.argv[1])
    print(json.dumps({x: k[x] for x in ("title", "short", "parts", "up_axis", "takt_s")},
                     ensure_ascii=False, indent=1))
    for s in k["steps"]:
        print(" ", s["name"], "|", s.get("who"), s.get("work_s"), "| операция" if s.get("operation") else "")
