# -*- coding: utf-8 -*-
"""
Строитель сборочной линии: изделие собирается из деталей пост за постом.

В отличие от линии механообработки (line_builder.py), здесь деталь не
обрабатывают, а к ней ДОБАВЛЯЮТ детали. Механика — штатная сборка R-Pro:

- тип продукта «Сборка» — дерево шагов (блок → коленвал → поршни …), у шага
  гнёзда: где лежит деталь относительно изделия и какие типы в него кладут;
- пост — «Операция на конвейере» (отрезок ленты со своим процессом):
  «Транспорт В» принимает изделие, «Получить сборку» выбирает шаг,
  второй «Транспорт В» в режиме сборки заказывает детали в пустые гнёзда —
  их приносит робот или человек и кладёт ровно в гнездо; «Работа» —
  время оператора на посту; «Транспорт Из» отдаёт изделие дальше;
- склады деталей — «Узлы процесса» с «Создать»; подсборка (поршень из
  головки, шатуна и пальца) — свой тип «Сборка», который потом сам
  становится деталью главного изделия.

Сейчас изделие одно — двигатель V8 (детали из каталожной планировки
«Сборка двигателя», сохранены в «Мои модели»). Линия — буква П в цехе
заданного размера: первый ряд — роботы (блок, коленвал, поршни) и
операторы, разворот, второй ряд — прокладки, головки блока, затяжка,
испытание, выгрузка. Внутри П — участок подсборки поршней.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import cad_path
from line_builder import RD, URI, LineBuilder
from rpro_client import RProClient

MY_MODELS = os.path.join(os.path.expanduser("~"), "Documents", "R-Pro", "0.2", "My Models")
PARTS_DIR = os.path.join(MY_MODELS, "Сборка двигателя", "Детали")

A_URI = {
    "post": RD + "PM Flow Components/Inline Process.rpro",
    "node": RD + "PM Flow Components/Flow Node Process.rpro",
    "human_tc": RD + "PM Transport Controllers/Human Transport Controller.rpro",
    "pathway": RD + "PM Resource Utilities/Pathway Area.rpro",
    "idle": RD + "PM Resource Utilities/Idle Location.rpro",
    "man": RD + "PM Resources/Human (R-Pro Operator Male).rpro",
    "woman": RD + "PM Resources/Human (R-Pro Operator Female).rpro",
}


def _file_uri(name: str) -> str:
    return "file:///" + os.path.join(PARTS_DIR, name).replace("\\", "/")


# --- изделие: двигатель V8 --------------------------------------------------
# Позиции гнёзд сняты с каталожной планировки «Сборка двигателя»: детали там
# смоделированы по месту, так что гнездо = точка привязки детали в блоке.
# [x, y, z, W, P, R] — мм и градусы относительно шага.

PARTS = {   # тип детали → файл модели
    "Блок цилиндров": "EngineBlock.rpro",
    "Коленвал": "EngineCrankshaft.rpro",
    "Нижняя пластина": "EngineBottomPlate.rpro",
    "Прокладка ГБЦ": "HeadGasket.rpro",
    "Головка блока": "EngineCylinderHead.rpro",
    "Головка поршня": "PistonHead.rpro",
    "Шатун": "PistonRod.rpro",
    "Поршневой палец": "PistonShaft.rpro",
}
ENGINE_PARTS = ["Блок цилиндров", "Коленвал", "Нижняя пластина", "Прокладка ГБЦ", "Головка блока"]
PISTON_PARTS = ["Головка поршня", "Шатун", "Поршневой палец"]

_BANK_X = [-159.9, -57.7, 45.2, 146.0]
# шаг: (имя, родитель, относительное положение шага, гнёзда [(тип, позиция, порядок)])
PISTON_STEPS = [
    ("Головка поршня", None, None, [("Головка поршня", [0, 0, 0, 0, 0, 0], 1)]),
    ("Шатун", "Головка поршня", None, [("Шатун", [0, 0, 0, 0, 0, 0], 1)]),
    ("Поршневой палец", "Шатун", None, [("Поршневой палец", [0, 0, 0, 0, 0, 0], 1)]),
]
ENGINE_STEPS = [
    ("Блок", None, None, [("Блок цилиндров", [0, 0, 0, 0, 0, 0], 1)]),
    ("Коленвал", "Блок", None, [("Коленвал", [0, 0, 26.9, 0, 0, 0], 1)]),
    ("Поршни левого ряда", "Коленвал", None,
     [("Поршень", [x, -140.1, 210.6, -180, -45, 90], 1) for x in _BANK_X]),
    ("Поршни правого ряда", "Коленвал", None,
     [("Поршень", [x, 140.8, 210.6, 180, -45, -90], 1) for x in _BANK_X]),
    ("Нижняя пластина", "Коленвал", [-4.8, 0, 0, 0, 0, 0],
     [("Нижняя пластина", [0, 0, -26.3, 0, 0, 0], 1)]),
    ("Прокладки ГБЦ", "Нижняя пластина", [-2.2, -112.9, 257.1, 45, 0, 0],
     [("Прокладка ГБЦ", [0, 0, 0, 0, 0, 0], 1), ("Прокладка ГБЦ", [0, 157.3, -157.3, 90, 0, 180], 2)]),
    ("Головки блока", "Прокладки ГБЦ", [0, -24.7, 4.3, 0, 0, 0],
     [("Головка блока", [0, 0, 0, 0, 0, 0], 1), ("Головка блока", [0, 187.3, -187.3, 90, 0, 180], 2)]),
]

# Посты главной линии по порядку. who: robot — робот приносит детали со
# склада src (или изделие целиком), operator — человек: приносит детали и
# работает work_s секунд; side: +1 — оборудование внутри буквы П, −1 — снаружи.
POSTS = [
    dict(pid="П0 Загрузка блока", who="robot", side=-1),
    dict(pid="П1 Коленвал", who="robot", side=-1, steps=["Коленвал"], src="Стеллаж коленвалов",
         part="Коленвал"),
    dict(pid="П2 Поршни левого ряда", who="robot", side=1, steps=["Поршни левого ряда"],
         sub="ПА Сборка поршня"),
    dict(pid="П3 Поршни правого ряда", who="robot", side=1, steps=["Поршни правого ряда"],
         sub="ПБ Сборка поршня"),
    dict(pid="П4 Затяжка шатунов", who="operator", side=-1, work_s=20, crew=1),
    dict(pid="П5 Нижняя пластина", who="operator", side=-1, work_s=15, crew=1,
         steps=["Нижняя пластина"], src="Стеллаж пластин", part="Нижняя пластина"),
    dict(pid="П6 Прокладки ГБЦ", who="operator", side=-1, work_s=12, crew=1,
         steps=["Прокладки ГБЦ"], src="Стеллаж прокладок", part="Прокладка ГБЦ"),
    dict(pid="П7 Головки блока", who="robot", side=-1, steps=["Головки блока"],
         src="Стеллаж головок блока", part="Головка блока"),
    dict(pid="П8 Затяжка ГБЦ", who="operator", side=-1, work_s=25, crew=1),
    dict(pid="П9 Испытание", who="operator", side=-1, work_s=30, crew=1),
    dict(pid="П10 Выгрузка", who="robot", side=-1),
]
LEG_A = 6                      # постов в первом ряду, остальные — после разворота

POST_PITCH = 4500.0            # шаг постов вдоль ленты, мм
ROBOT_OFF = 1400.0             # робот от оси ленты
SRC_OFF = 1400.0               # склад деталей — ещё дальше за роботом
NODE_H = 800.0                 # высота, на которой лежат детали на складах
OPERATOR_OFF = 700.0           # место оператора от оси ленты
CELL_DX = 1000.0               # ячейки подсборки — по обе стороны от робота


PROC_OFF = 1150.0              # робот технологической операции — ближе к ленте, ему не нужен склад
REJECT_OFF = 2600.0            # изолятор брака — за роботом поста контроля

# Инструмент робота по виду операции. К фланцу встают только те, что прошли
# canConnect: горелки (дозатор, сварка, пайка), отвёртка, захват; пистолеты-
# герметики и камера Eyes — нет. Робот контроля носит захват: он же убирает брак.
TOOLS = {
    "dispense": RD + "Robot Tools/ParametricMigTorch.rpro",
    "weld": RD + "Robot Tools/weld_torch.rpro",
    "solder": RD + "Robot Tools/weld_torch.rpro",
    "screw": "https://download.r-pro.digital/v204/Components/OnRobot/Robot Tools/Screwdriver.rpro",
    "inspect": RD + "Robot Tools/Gripper.rpro",
    "test": RD + "Robot Tools/Gripper.rpro",
}
# скорость прохода, мм/с; ожидание в точке, с; подъём инструмента между штрихами, мм
MOTION = {"dispense": (150.0, 0.0, 60.0), "weld": (120.0, 0.4, 40.0), "solder": (120.0, 0.8, 40.0),
          "screw": (150.0, 1.0, 60.0), "inspect": (350.0, 0.0, 100.0), "test": (350.0, 0.0, 100.0)}
# оборудование над постом: печь — туннель над лентой, контроль — камера-портал
DECOR = {"oven": "https://download.r-pro.digital/v204/Components/Item/Facilities - Factory/"
                 "Machine cabin for linear applications.rpro",
         "inspect": RD + "Facilities - Factory/quality_check_camera.rpro"}
PROCESS_RU = {"oven": "печь", "dispense": "нанесение", "solder": "пайка", "weld": "сварка",
              "screw": "завинчивание", "inspect": "контроль", "test": "испытание"}


@dataclass
class AssemblySpec:
    product: str = "двигатель V8"
    hall_x_m: float = 40.0        # цех 40 × 25 м = 1000 м²
    hall_y_m: float = 25.0
    block_every_s: float = 40.0   # склад выдаёт блок не чаще, чем раз в N секунд
    speed: float = 400.0          # скорость лент, мм/с
    sim_speed: float = 3.0
    robot: str = ""               # марка роботов; пусто — вперемешку
    piston_cells_per_robot: int = 2  # ячеек подсборки поршней у каждого робота (1 или 2)
    clear: bool = False
    pace_s: float = 0.05
    # --- завод на этажах (factory_builder): где и как ставить линию ---
    origin: tuple | None = None   # (x, y) первого поста; None — к северу от того, что уже стоит
    level: float = 0.0            # отметка этажа, мм: всё ставится на перекрытие
    hall: bool = True             # размечать пол цеха (на этажах пол — перекрытие завода)
    straight: bool = False        # в одну линию, без разворота
    ship: str = "robot"           # "robot" — выгрузка роботом на склад; "lift" — изделие уходит лентой дальше
    external: tuple = ()          # узлы, которые приезжают лентой с другого этажа (склада у поста нет)
    north_x: tuple | None = None  # (x0, x1): хозяйство постов здесь — к северу, южную полосу занимает лента


class AssemblyLineBuilder(LineBuilder):
    def __init__(self, client: RProClient | None = None,
                 progress: Callable[[str], None] | None = None):
        super().__init__(client, progress)
        self.level = 0.0

    # --- мелкие элементы -------------------------------------------------------

    def _stand_node(self, x: float, y: float, pid: str, rz: float = 0.0,
                    op_dy: float | None = None, size: float = 700.0, color: tuple | None = None) -> str:
        """Склад/место детали: «Узел процесса» на подставке высотой NODE_H.

        op_dy — где встаёт человек, который здесь берёт или кладёт деталь: на
        op_dy мм по Y от узла. По умолчанию узел ставит его в 0,5 м — это в
        15 см от края подставки 0,7 м, и навигация людей считает точку
        препятствием («Unable to solve path»). Поэтому 0,9 м и с той стороны,
        откуда человек подходит. color — покрасить подставку (изолятор брака)."""
        z = self.level
        extra = ("set_prop(n, 'ResourceOffset', mat(0.0, %f, 0.0, 90.0))\n" % op_dy
                 if op_dy is not None else "")
        paint_code = "paint(s, 'Изолятор брака', %r)\n" % list(color) if color else ""
        res = self.step(
            "s = load(%r)\nset_prop(s, 'Length_X', %f)\nset_prop(s, 'Width_Y', %f)\n"
            "set_prop(s, 'Height_Z', %f)\nplace(s, %f, %f, %f, %f)\n%s"
            "n = load(%r)\nset_prop(n, 'ConveyorHeight', %f)\nplace(n, %f, %f, %f, %f)\n"
            # значок узла (серая плашка) на подставке только мешает
            "set_prop(n, 'ShowGeo', False)\nset_prop(n, 'ShowResourceLocation', False)\n"
            "%sset_process_id(n, %r)\n"
            "result = {'name': n.Name, 'at': [%f, %f, %f]}"
            % (URI["slab"], size, size, NODE_H - 20.0, x, y, z + (NODE_H - 20.0) / 2.0, rz, paint_code,
               A_URI["node"], NODE_H, x, y, z, rz, extra, pid, x, y, z + NODE_H))
        return res["name"]

    def _people(self, title: str, x: float, y: float, spots: list[tuple[float, float]]) -> str:
        """ТК человека, операторы и их места ожидания (по одному на точку).

        Человек стоит в полуметре от своего места ожидания, а не на нём, и
        место ожидания — не на рабочей точке поста: путь нулевой длины роняет
        скрипт оператора (int('') в _create_path_from_schema), и упавший
        оператор больше не работает — линия встаёт."""
        z = self.level
        code = ["tc = load(%r)\nplace(tc, %f, %f, %f)\n" % (A_URI["human_tc"], x, y, z),
                "for nm, v in (('LinkDefaults::PickTime', 2.0), ('LinkDefaults::PlaceTime', 2.0)):\n"
                "    p = tc.getProperty(nm)\n    if p is not None: p.Value = v\n",
                "people = []\nidle = []\n"]
        for i, (px, py) in enumerate(spots):
            code.append(
                "h = load(%r)\nplace(h, %f, %f, %f, 0.0)\npeople.append(h)\n"
                "i_ = load(%r)\nplace(i_, %f, %f, %f, 0.0)\nidle.append(i_)\n"
                % (A_URI["man" if i % 2 == 0 else "woman"], px + 500.0, py, z, A_URI["idle"], px, py, z))
        # Карта путей по всей сцене (UseGlobalArea) на больших сценах считается
        # минутами, и R-Pro на каждом пересчёте спрашивает модальным окном.
        # Выключаем; зону прохода по участку бригады ставит _crew_areas().
        code.append("connect_people(tc, people, idle)\n"
                    "p = tc.getProperty('UseGlobalArea')\n"
                    "if p is not None: p.Value = False\n"
                    "result = {'name': tc.Name, 'at': [%f, %f, %f]}" % (x, y, z))
        name = self.step("".join(code))["name"]
        self.crews.append(name)
        return name

    def _robot(self, x: float, y: float, face_y: float) -> str:
        """Робот на ТК, лицом к ленте."""
        facing = 90.0 if face_y > y else -90.0
        return self._robot_at(x, y, self.level, facing)["tc"]

    def _process_robot(self, p: dict, plan: dict, index: int) -> dict:
        """Робот технологической операции у поста p: инструмент по виду
        операции и подпрограмма «Process» — проход по шву, точкам или
        сканирование над изделием. У поста контроля робот на «ТК робота»: он же
        уносит брак в изолятор."""
        kind = p["process"]
        d = p["dir"]
        rx, ry = p["x"], p["y"] + d * PROC_OFF
        facing = 90.0 if p["y"] > ry else -90.0
        tc = None
        if p.get("scrap"):
            r = self._robot_at(rx, ry, self.level, facing)
            tc = r["tc"]
            get = "rb = robot_on(comp(%r))\n" % tc
        else:
            res = self.step("rb = load(%r)\nplace(rb, %f, %f, %f, %f)\n"
                            "result = {'name': rb.Name, 'at': [%f, %f, %f]}"
                            % (self._robot_uri(), rx, ry, self.level, facing, rx, ry, self.level))
            get = "rb = comp(%r)\n" % res["name"]
        bb = plan.get("bbox") or [[-300.0, -200.0, 0.0], [300.0, 200.0, 150.0]]
        strokes = p.get("path") or cad_path.scan_strokes(bb[0], bb[1])
        speed, dwell, lift = MOTION.get(kind, (200.0, 0.0, 80.0))
        park = [0.0, 0.0, bb[1][2] + 400.0]
        out = self.run(get + "tool = mount_tool(rb, %r)\n"
                       "res = robot_path(rb, 'Process', comp(%r), %r, tool, %f, %f, %f, %r)\n"
                       "res['robot'] = rb.Name\nres['tool'] = tool\nresult = res"
                       % (TOOLS.get(kind, TOOLS["inspect"]), p["name"], strokes, speed, dwell, lift, park))
        if kind in DECOR:
            self._decor(DECOR[kind], p)
        return {"robot": out["robot"], "tc": tc, "tool": out["tool"], "points": out["points"]}

    def _decor(self, uri: str, p: dict) -> None:
        """Оборудование над постом (туннель печи, камера контроля) — вид, без логики."""
        self.step("c_ = load(%r)\nm_ = post_center(comp(%r))\n"
                  "place(c_, m_.P.X, m_.P.Y, %f, m2l(comp(%r).PositionMatrix)[3])\n"
                  "result = {'name': c_.Name, 'at': m2l(c_.PositionMatrix)}"
                  % (uri, p["name"], self.level, p["name"]), camera=False)

    # --- стройка ---------------------------------------------------------------

    def build_engine(self, spec: AssemblySpec) -> dict:
        """Двигатель V8 по отлаженному плану (посты затяжки, испытания и т. п.)."""
        return self._build(spec, engine_plan())

    def build_kit(self, spec: AssemblySpec, kit: dict) -> dict:
        """Любое изделие из набора (kits.py): посты раскладываются по шагам сборки."""
        return self._build(spec, kit_plan(kit, ship=spec.ship, straight=spec.straight))

    def _build(self, spec: AssemblySpec, plan: dict) -> dict:
        t0 = time.time()
        self._pace = spec.pace_s
        self.spec = spec
        self.robots_used = 0
        self.crews: list[str] = []
        self.level = float(spec.level)
        self.conv_w = plan.get("conv_w")
        report: dict[str, Any] = {"изделие": plan["title"], "предупреждения": []}
        self.client.simulation("reset")
        time.sleep(1.0)
        oy = 0.0
        if spec.clear:
            self.run("app.clearWorld()\nresult = 1")
        else:
            # Вторая такая же линия в той же сцене слилась бы с первой: те же
            # имена процессов, группы и типы. Чужое не трогаем — строим за
            # северной границей сцены.
            if self.run("result = pc().ProcessManager.findProcessGroup(_b(%r)) is not None"
                        % plan["posts"][0]["pid"]):
                raise ValueError(f"в сцене уже есть сборочная линия «{plan['title']}», вторую такую же "
                                 "в той же сцене не строю. Сцену не очищай сам — скажи об этом "
                                 "пользователю и спроси, очистить ли сцену.")
            if spec.origin is None:
                top = self.run("ys = [c.PositionMatrix.P.Y for c in app.Components]\n"
                               "result = max(ys) if ys else None")
                oy = 0.0 if top is None else float(top) + 8000.0
        hx, hy = spec.hall_x_m * 1000.0, spec.hall_y_m * 1000.0

        # 0. пол цеха — видно, что всё уместилось в заданную площадь
        if spec.hall:
            self.progress("размечаю цех")
            self.step("f = load(%r)\nset_prop(f, 'Length_X', %f)\nset_prop(f, 'Width_Y', %f)\n"
                      "set_prop(f, 'Height_Z', 20.0)\nplace(f, %f, %f, -10.0)\n"
                      "result = {'name': f.Name, 'at': [%f, %f, 0.0]}"
                      % (URI["slab"], hx, hy, hx / 2, oy + hy / 2, hx / 2, oy + hy / 2), camera=False)

        # 1. изделие: типы деталей, подсборки и само изделие (тип «Сборка»)
        self.progress(f"описываю изделие «{plan['title']}»: детали, шаги, гнёзда")
        self.run(plan["product_code"])
        POSTS_, LEG_A_ = plan["posts"], plan["leg_a"]
        G, GP = plan["group"], plan["parts_group"]

        # 2. лента с постами: ряд A по +X, разворот, ряд B по −X
        self.progress("ставлю посты сборки")
        if spec.origin is not None:
            xa, ya = float(spec.origin[0]), float(spec.origin[1])
        else:
            xa, ya = 4000.0, oy + 8000.0
        posts: list[dict] = []
        res = self.step("p = load(%r)\nplace(p, %f, %f, %f)\n" % (A_URI["post"], xa, ya, self.level) +
                        self._post_props_code(plan) +
                        "result = {'name': p.Name, 'at': m2l(frame_world(p, 'OutInterface'))}")
        posts.append({"name": res["name"], **POSTS_[0]})
        last, last_out = res["name"], "OutInterface"
        conveyor_mm = 0.0
        for i, post in enumerate(POSTS_[1:], start=1):
            if i == LEG_A_:
                self.progress("разворот ленты")
                last, last_out = self._conveyor(last, last_out, 2000.0, spec.speed)
                last, last_out = self._curve(last, last_out, "Left", spec.speed)
                last, last_out = self._conveyor(last, last_out, 5000.0, spec.speed)
                last, last_out = self._curve(last, last_out, "Left", spec.speed)
                last, last_out = self._conveyor(last, last_out, 1200.0, spec.speed)
                conveyor_mm += 8200.0 + 2 * 1571
            else:
                gap = plan.get("pitch", POST_PITCH) - plan.get("post_len", 800.0)
                last, last_out = self._conveyor(last, last_out, gap, spec.speed)
                conveyor_mm += gap
            self.progress(post["pid"])
            res = self.step("a = comp(%r)\np = load(%r)\nsnap(a, %r, p, 'InInterface')\n"
                            % (last, A_URI["post"], last_out) + self._post_props_code(plan) +
                            "result = {'name': p.Name, 'at': m2l(frame_world(p, 'OutInterface'))}")
            posts.append({"name": res["name"], **post})
            last, last_out = res["name"], "OutInterface"

        # где стоят посты и куда у каждого «наружу»: у ряда B направление
        # ленты обратное, поэтому «снаружи» — это +Y
        centers = self.run("result = [m2l(p.PositionMatrix * frame(p, 'Center').NodePositionMatrix) "
                           "for p in [comp(n) for n in %r]]" % [p["name"] for p in posts])
        for p, c in zip(posts, centers):
            p["x"], p["y"] = c[0], c[1]
            # наружу от П: у ряда A это −Y, у ряда B — +Y; side=+1 — внутрь.
            # Короткая линия — один ряд A без разворота.
            outward = -1.0 if abs(c[1] - ya) < 1000.0 else 1.0
            p["dir"] = outward if p["side"] < 0 else -outward
            # На этаже, куда лентой приезжает узел с другого этажа, южная полоса
            # складов занята этой лентой: хозяйство постов на её отрезке — к северу
            if spec.north_x and spec.north_x[0] - 2500.0 <= c[0] <= spec.north_x[1] + 2500.0 \
                    and not (p.get("sub_store") and p.get("part") in spec.external):
                if p["who"] == "robot" or (p["who"] == "process" and p.get("scrap")):
                    p["dir"] = 1.0

        # 3. роботы и склады деталей
        flows_parts: list[str] = []
        links: list[tuple[str, str, str, str]] = []   # src, dst, исполнитель, группа
        self.external: dict[str, dict] = {}
        for p in posts:
            if p["who"] != "robot":
                continue
            d = p["dir"]
            rx, ry = p["x"], p["y"] + d * ROBOT_OFF
            self.progress(f"{p['pid']}: робот")
            p["tc"] = self._robot(rx, ry, p["y"])
            if p.get("sub_store") and p.get("part") in spec.external:
                # узел приедет лентой с другого этажа: склад у поста — конец этой
                # ленты, его ставит строитель завода
                self.external[p["part"]] = {"post": p["name"], "pid": p["pid"], "tc": p["tc"],
                                            "store_pid": p["src"], "x": p["x"], "y": p["y"],
                                            "dir": d, "store_y": ry + d * SRC_OFF}
                continue
            stores = [(p["src"], p["part"])] + list(p.get("more", [])) if p.get("src") else []
            for k, (src, part) in enumerate(stores):
                dx = (k - (len(stores) - 1) / 2.0) * 1000.0
                n = self._stand_node(rx + dx, ry + d * SRC_OFF, src, size=plan.get("stand", 700.0))
                if k == 0:
                    p["src_node"] = n
                p.setdefault("stores", []).append((n, src, part))
                flows_parts += [src, p["pid"]]
                links.append((n, p["name"], p["tc"], GP))
        p0, plast = posts[0], posts[-1]
        block_store = self._stand_node(p0["x"], p0["y"] + p0["dir"] * (ROBOT_OFF + SRC_OFF), plan["store"],
                                       size=plan.get("stand", 700.0))
        links.append((block_store, p0["name"], p0["tc"], G))
        ship = None
        if plan.get("ship"):
            ship = self._stand_node(plast["x"], plast["y"] + plast["dir"] * (ROBOT_OFF + SRC_OFF), plan["ship"],
                                    size=plan.get("stand", 700.0))
            links.append((plast["name"], ship, plast["tc"], G))

        # 3б. роботы технологических операций: клей, пайка, сварка, винты, контроль
        for i, p in enumerate(posts):
            if p["who"] != "process":
                continue
            kind = p["process"]
            if kind == "oven":
                self.progress(f"{p['pid']}: печь над лентой")
                self._decor(DECOR["oven"], p)
                continue
            self.progress(f"{p['pid']}: робот — {PROCESS_RU.get(kind, kind)}")
            pr = self._process_robot(p, plan, i)
            p["robot"], p["tc"] = pr["robot"], pr["tc"]
            if p.get("scrap"):
                d = p["dir"]
                p["reject_pid"] = p["pid"].split(" П")[0] + f" брак после П{p['pid'].split(' П')[1].split()[0]}"
                p["reject"] = self._stand_node(p["x"], p["y"] + d * REJECT_OFF, p["reject_pid"],
                                               size=plan.get("stand", 700.0), color=(0.85, 0.1, 0.1))
                links.append((p["name"], p["reject"], p["tc"], G))

        # 4. операторы: склады у постов и бригады по рядам
        crews: dict[str, list] = {}
        for p in posts:
            if p["who"] != "operator":
                continue
            d = p["dir"]
            if p.get("src"):
                # склад — дальше от ленты, оператор берёт со стороны ленты
                n = self._stand_node(p["x"] + 1300.0, p["y"] + d * 2200.0, p["src"], op_dy=-d * 900.0)
                p["src_node"] = n
                flows_parts += [p["src"], p["pid"]]
            crews.setdefault("A" if abs(p["y"] - ya) < 1.0 else "B", []).append(p)
        for key, plist in crews.items():
            d = plist[0]["dir"]
            spots = [(q["x"] - 600.0 * k, q["y"] + d * 1600.0)
                     for q in plist for k in range(q.get("crew", 1))]
            cx = sum(q["x"] for q in plist) / len(plist)
            self.progress(f"операторы ряда {key}: {len(spots)} чел.")
            tc = self._people(f"Операторы ряда {key}", cx, plist[0]["y"] + d * 3500.0, spots)
            for q in plist:
                q["worker"] = tc
                if q.get("src_node"):
                    links.append((q["src_node"], q["name"], tc, GP))

        # 5. участок подсборки поршней — внутри буквы П, у роботов П2 и П3.
        # У каждого поста подсборки своя ячейка: оператор, три склада деталей
        # полукругом в метре от него и свой ТК. Общие склады на два поста
        # сводили двух-четырёх людей в одну рабочую точку — им некуда встать.
        # Отчёт по прогону показал: узкое место — сборщики поршней (заняты на
        # 85–92 %, на поршень три ходки). Поэтому у каждого робота по CELLS
        # ячеек: компактные подставки 0,4 м, склады в 0,8 м от места сборщика.
        sub = plan.get("sub")
        cells = []
        sub_posts = [p for p in posts if p.get("sub")]
        if sub and sub_posts:
            self.progress(f"участок подсборки: {sub['title']}")
            dy = sub_posts[0]["dir"]
            ys = sub_posts[0]["y"] + dy * (ROBOT_OFF + SRC_OFF)
            offsets = [0.0] if spec.piston_cells_per_robot <= 1 else [-CELL_DX, CELL_DX]
            letters = iter("АБВГДЕЖЗИК")
            for n_post, rpost in enumerate(sub_posts):
                for dx in offsets:
                    tag = "П" + next(letters)
                    sx = rpost["x"] + dx
                    side = -1.0 if dx < 0 or (dx == 0 and n_post == 0) else 1.0
                    st_pid = f"{tag} {sub['post_name']}"
                    st = self._stand_node(sx, ys, st_pid, op_dy=dy * 700.0, size=400.0)
                    shelves = []
                    for k, part in zip((-1, 0, 1, -2, 2), sub["parts"]):
                        pid = f"{tag} склад: {part}"
                        shelves.append((self._stand_node(sx + k * 600.0, ys + dy * 1500.0, pid,
                                                         op_dy=-dy * 800.0, size=400.0), pid, part))
                    crew = self._people(f"Сборщик {tag}", sx, ys + dy * 3000.0,
                                        [(sx + side * 1100.0, ys + dy * 700.0)])
                    for node, _, _ in shelves:
                        links.append((node, st, crew, sub["parts_group"]))
                    links.append((st, rpost["name"], rpost["tc"], sub["group"]))
                    cells.append({"tag": tag, "st": st, "pid": st_pid, "shelves": shelves, "crew": crew})

        # 6. процедуры: склады, посты, подсборка, отгрузка
        self.progress("пишу процедуры постов")
        code = ["E = pc().ProductTypeManager.findProductType(_b(%r))\n" % plan["asm"],
                "gE = group_by_name(_b(%r))\n" % G]
        if cells:
            code.append("PA = pc().ProductTypeManager.findProductType(_b(%r))\n" % sub["asm"])
        code.append("source_routine(comp(%r), %r, E, [asm_find_step(E, _b(%r))], %f)\n"
                    % (block_store, plan["store"], plan["root_step"], spec.block_every_s))
        for i, p in enumerate(posts):
            for node, src, part in p.get("stores", []):
                code.append("source_routine(comp(%r), %r, pc().ProductTypeManager.findProductType(_b(%r)))\n"
                            % (node, src, part))
            if p["who"] == "process":
                robot = "comp(%r)" % p["robot"] if p.get("robot") else "None"
                bead = ("pc().ProductTypeManager.findProductType(_b(%r))" % p["bead"]) if p.get("bead") else "None"
                code.append("process_routine(comp(%r), %r, gE, robot=%s, bead_type=%s, bead_pos=%r, "
                            "work_s=%f, scrap=%f, stream=%d)\n"
                            % (p["name"], p["pid"], robot if p["process"] != "oven" else "None", bead,
                               p.get("bead_pos"), float(p.get("work_s") or 0.0), float(p.get("scrap") or 0.0),
                               i + 1))
                if p.get("reject"):
                    code.append("sink_routine(comp(%r), %r)\n" % (p["reject"], p["reject_pid"]))
                continue
            worker = "comp(%r)" % p["worker"] if p.get("worker") else "None"
            code.append("post_routine(comp(%r), %r, gE, E, %r, worker=%s, work_s=%f, delay_s=%f)\n"
                        % (p["name"], p["pid"], p.get("steps", []), worker,
                           float(p.get("work_s", 0)), float(p.get("delay_s", 2.0 if p["who"] == "robot" else 0.0))))
        for cell in cells:
            for node, pid, part in cell["shelves"]:
                code.append("source_routine(comp(%r), %r, pc().ProductTypeManager.findProductType(_b(%r)))\n"
                            % (node, pid, part))
            code.append("subassembly_routine(comp(%r), %r, PA, comp(%r), %f)\n"
                        % (cell["st"], cell["pid"], cell["crew"], float(sub.get("work_s", 8.0))))
        if ship:
            code.append("sink_routine(comp(%r), %r)\n" % (ship, plan["ship"]))
        self.run("".join(code) + "result = 1")

        # 7. маршруты и связи. Пост контроля сам назначает следующий шаг:
        # +1 — изолятор брака сразу за ним в маршруте, +2 — следующий пост
        self.progress("маршруты и транспортные связи")
        main_flow = [plan["store"]]
        for p in posts:
            main_flow.append(p["pid"])
            if p.get("reject_pid"):
                main_flow.append(p["reject_pid"])
        if ship:
            main_flow.append(plan["ship"])
        flows = [(main_flow, G), (flows_parts, GP)]
        if cells:
            sub_ids = [c["pid"] for c in cells]
            flows.append(([[pid for c in cells for _, pid, _ in c["shelves"]], sub_ids], sub["parts_group"]))
            flows.append(([sub_ids, [p["pid"] for p in sub_posts]], sub["group"]))
        res = self.run("result = [%s]" % ", ".join("set_flow(%r, _b(%r))" % (f, g) for f, g in flows if f))
        missing = sum((r.get("missing", []) for r in res), [])
        if missing:
            report["предупреждения"].append("нет процессов: " + ", ".join(missing))
        for a, b in zip(posts, posts[1:]):
            links.append((a["name"], b["name"], "ConveyorTransport", G))
        code = []
        for src, dst, impl, grp in links:
            impl_code = repr(impl) if impl == "ConveyorTransport" else "comp(%r)" % impl
            code.append("link(comp(%r), comp(%r), %s, %r)\n" % (src, dst, impl_code, grp))
        self.run("".join(code) + "result = len(pc().TransportSystem.Links)")
        # зоны прохода бригад — когда связи уже есть: зона берёт точки, куда бригада ходит
        if self.crews:
            self.run("result = [crew_area(comp(n), %r) for n in %r]" % (A_URI["pathway"], self.crews))

        # 8. итог
        if spec.hall:
            self._overview()
        self.run("app.Simulation.SimSpeed = %f\nresult = 1" % max(0.1, float(spec.sim_speed)))
        procs = [p for p in posts if p["who"] == "process" and p["process"] != "oven"]
        report.update({
            "цех_м": [spec.hall_x_m, spec.hall_y_m] if spec.hall else None,
            "площадь_м2": round(spec.hall_x_m * spec.hall_y_m) if spec.hall else None,
            "постов_на_линии": len(posts),
            "постов_подсборки": len(cells),
            "роботов": sum(1 for p in posts if p["who"] == "robot") + len(procs),
            "операторов": sum(p.get("crew", 1) for p in posts if p["who"] == "operator") + len(cells),
            "посты": [p["pid"] for p in posts],
            "длина_ленты_м": round((conveyor_mm + plan.get("post_len", 800.0) * len(posts)) / 1000.0, 1),
            "компонентов_поставлено": self.count,
            "строилось_с": round(time.time() - t0),
        })
        ops = [p for p in posts if p["who"] == "process"]
        if ops:
            report["операции_роботов"] = {p["pid"]: PROCESS_RU.get(p["process"], p["process"]) +
                                          (f", брак {p['scrap']:g} %" if p.get("scrap") else "")
                                          for p in ops}
        if not spec.hall:
            report.pop("цех_м"); report.pop("площадь_м2")
        # для строителя завода: где кончается линия и что ей нужно извне
        self.layout = {"posts": posts, "last": (last, last_out), "flow": main_flow, "group": G,
                       "external": self.external, "store": block_store, "level": self.level}
        return report

    def _post_props_code(self, plan: dict | None = None) -> str:
        """Свойства поста: длина и ширина под изделие, скорость, место оператора — снаружи П."""
        plan = plan or {}
        extra = ""
        if plan.get("post_len"):
            extra += "set_prop(p, 'ConveyorLength', %f)\n" % plan["post_len"]
        if plan.get("conv_w"):
            extra += "set_prop(p, 'ConveyorWidth', %f)\n" % plan["conv_w"]
        return (extra + "set_prop(p, 'ConveyorSpeed', %f)\n"
                "set_prop(p, 'ResourceOffset', mat(0.0, %f, 0.0))\n"
                % (self.spec.speed, -OPERATOR_OFF))

    @staticmethod
    def _product_code() -> str:
        """Py2-код: группы, типы деталей, «Поршень» и «Двигатель V8».
        Ключи словарей — только через _u(): в Python 2.7 u'Д' и байтовая 'Д' —
        разные ключи."""
        nl = "\n"
        lines = ["fm = pc().FlowGroupManager" + nl, "G = {}" + nl,
                 "for gname in (u'Двигатель', u'Детали двигателя', u'Детали поршня', u'Поршни'):" + nl +
                 "    g = group_by_name(gname)" + nl +
                 "    if g is None:" + nl + "        g = fm.createGroup(_b(gname))" + nl +
                 "    G[_u(gname)] = g" + nl, "T = {}" + nl]
        for name, fname in PARTS.items():
            grp = "Детали поршня" if name in PISTON_PARTS else "Детали двигателя"
            lines.append("T[_u(%r)] = part_type(%r, G[_u(%r)], %r)" % (name, name, grp, _file_uri(fname)) + nl)
        for tname, grp, steps in (("Поршень", "Поршни", PISTON_STEPS), ("Двигатель V8", "Двигатель", ENGINE_STEPS)):
            lines.append("A = assembly_type(%r, G[_u(%r)])" % (tname, grp) + nl + "S = {}" + nl)
            for sname, parent, rel, slots in steps:
                parent_code = "None" if parent is None else "S[_u(%r)]" % parent
                lines.append("S[_u(%r)] = asm_step(A, %s, %r)" % (sname, parent_code, sname) + nl)
                if rel:
                    lines.append("S[_u(%r)].getProperty('RelativePosition').Value = wpr_mat(*%r)"
                                 % (sname, rel) + nl)
                for ptype, pos, order in slots:
                    default = "T[_u(%r)]" % ptype if ptype in PARTS else "None"
                    lines.append("asm_slot(S[_u(%r)], [T[_u(%r)]], %r, %d, %s)"
                                 % (sname, ptype, pos, order, default) + nl)
            lines.append("T[_u(%r)] = A" % tname + nl)
        lines.append("result = sorted(T.keys())")
        return "".join(lines)


ROBOT_PART_MM = 800.0   # деталь крупнее — ставит робот, мельче — оператор
ROBOT_MANY = 6          # столько одинаковых деталей в шаге и больше — тоже робот


def engine_plan() -> dict:
    """Двигатель V8: посты подобраны руками (затяжки, испытание, бригады)."""
    return {
        "title": "двигатель V8", "asm": "Двигатель V8", "root_step": "Блок",
        "group": "Двигатель", "parts_group": "Детали двигателя",
        "store": "Склад блоков", "ship": "Отгрузка двигателей",
        "posts": POSTS, "leg_a": LEG_A,
        "product_code": AssemblyLineBuilder._product_code(),
        "sub": {"title": "поршни", "asm": "Поршень", "post_name": "Сборка поршня",
                "parts": PISTON_PARTS, "group": "Поршни", "parts_group": "Детали поршня",
                "work_s": 8.0},
    }


def kit_plan(kit: dict, ship: str = "robot", straight: bool = False) -> dict:
    """План линии из набора изделия: шаг сборки — пост.

    ship="lift" — изделие не выгружается роботом на склад, а уходит лентой с
    последнего поста дальше (на лифт к другому этажу). straight — одна линия
    без разворота (этаж завода)."""
    title = kit["title"]
    names = kit.get("names", {})

    def ru(n: str) -> str:
        return names.get(n, n)

    short = kit.get("short") or title.split()[0]
    G, GP = title, f"Детали: {title}"
    subs = kit.get("subs", {})
    # узлы двух видов: собираются тут же в ячейках у робота (поршни двигателя) или
    # приходят готовыми со склада — с соседнего участка (ШПГ на коленвал)
    store_subs = [s for s in subs if subs[s].get("supply") == "store"]
    sub_name = next((s for s in subs if s not in store_subs), None)
    sub_title = ru(sub_name) if sub_name else ""
    sub_parts = []
    if sub_name:
        for st in subs[sub_name]["steps"]:
            for sl in st["slots"]:
                for t in sl["types"]:
                    if ru(t) not in sub_parts:
                        sub_parts.append(ru(t))

    all_steps = kit["steps"]
    # операции без деталей (затяжка, контроль…) — посты работы, не шаги сборки
    steps = [st for st in all_steps if not st.get("operation")]
    root = steps[0]
    root_part = ru(root["slots"][0]["types"][0]) if root["slots"] else ru(root["name"])
    # у заказчика в спецификации операция названа — берём её имя
    p0 = ru(root["name"]) if root.get("who") else f"Загрузка: {root_part}"
    posts = [dict(pid=f"{short} П0 {p0}", who="robot", side=-1)]
    robots_only = all(st.get("who") in (None, "robot") for st in all_steps) and \
        any(st.get("who") == "robot" for st in all_steps)
    i = 1
    for st in all_steps[all_steps.index(root) + 1:]:
        pid = f"{short} П{i} {ru(st['name'])}"
        if st.get("operation"):
            t_s = float(st.get("work_s") or 0.0)
            kind = st.get("process") or ""
            if kind and st.get("who") in (None, "robot"):
                # технологическая операция роботом (или печь): инструмент, проход
                # по шву или точкам, след операции на изделии, брак на контроле
                posts.append(dict(pid=pid, who="process", process=kind, side=-1, work_s=t_s,
                                  bead=ru(st["bead"]) if st.get("bead") else None,
                                  bead_pos=st.get("bead_pos"), path=st.get("path"),
                                  scrap=float(st.get("scrap") or 0.0)))
            elif st.get("who") == "robot":
                posts.append(dict(pid=pid, who="robot", side=-1, delay_s=t_s or 15.0))
            else:
                posts.append(dict(pid=pid, who="operator", side=-1, work_s=t_s or 15.0, crew=1))
            i += 1
            continue
        if not st["slots"]:
            continue
        # детали шага: одна или несколько разных (разъёмы ячеек и связи на одном посту)
        types: list[str] = []
        for sl in st["slots"]:
            if sl["types"] and sl["types"][0] not in types:
                types.append(sl["types"][0])
        t = types[0]
        n = len(st["slots"])
        # Кто ставит: прямо указано (спецификация заказчика) или подсказка в
        # имени шага (в каталоге бывают «Robotic_Assy» и «Manual_Assy»), иначе
        # крупная деталь или много одинаковых — робот.
        hint = st["name"].lower()
        if st.get("who"):
            by_robot = st["who"] == "robot"
        else:
            by_robot = ("robot" in hint or "робот" in hint) or (
                "manual" not in hint and "ручн" not in hint and
                (kit["parts"].get(t, {}).get("size", 0.0) > ROBOT_PART_MM or n >= ROBOT_MANY))
        if t == sub_name:
            posts.append(dict(pid=pid, who="robot", side=1, steps=[ru(st["name"])], sub=True))
        elif by_robot:
            posts.append(dict(pid=pid, who="robot", side=-1, steps=[ru(st["name"])],
                              src=f"{short} склад П{i}: {ru(t)}", part=ru(t),
                              more=[(f"{short} склад П{i}: {ru(x)}", ru(x)) for x in types[1:]],
                              sub_store=t in store_subs,
                              delay_s=float(st.get("work_s") or 3.0)))
        else:
            posts.append(dict(pid=pid, who="operator", side=-1, steps=[ru(st["name"])],
                              src=f"{short} склад П{i}: {ru(t)}", part=ru(t),
                              work_s=float(st.get("work_s") or (6.0 + 4.0 * n)), crew=1))
        i += 1
    has_qc = any(p.get("process") in ("inspect", "test") or "контрол" in p["pid"].lower() for p in posts)
    if not has_qc:
        if robots_only:
            posts.append(dict(pid=f"{short} П{i} Контроль качества", who="process", process="inspect",
                              side=-1, work_s=0.0, scrap=0.0))
        else:
            posts.append(dict(pid=f"{short} П{i} Контроль качества", who="operator", side=-1,
                              work_s=20, crew=1))
        i += 1
    if ship == "robot":
        posts.append(dict(pid=f"{short} П{i} Выгрузка", who="robot", side=-1))
    leg_a = len(posts) if straight or len(posts) <= 7 else (len(posts) + 1) // 2

    # Py2-код типов: группы, детали, подсборка, изделие
    nl = "\n"
    groups = [G, GP] + ([sub_title, f"Детали: {sub_title}"] if sub_name else [])
    code = ["fm = pc().FlowGroupManager" + nl, "G = {}" + nl, "T = {}" + nl]
    for g in groups:
        code.append("g = group_by_name(_b(%r))" % g + nl +
                    "if g is None:" + nl + "    g = fm.createGroup(_b(%r))" % g + nl +
                    "G[_u(%r)] = g" % g + nl)
    sub_part_set = set(sub_parts)
    for t, info in kit["parts"].items():
        grp = f"Детали: {sub_title}" if ru(t) in sub_part_set else GP
        uri = "file:///" + (info.get("path") or os.path.join(kit["folder"], info["file"])).replace("\\", "/")
        code.append("T[_u(%r)] = part_type(%r, G[_u(%r)], %r)" % (ru(t), ru(t), grp, uri) + nl)

    def asm_code(type_name: str, grp: str, st_list: list[dict]) -> None:
        # описание сборки — данными, а строит его hands27.define_assembly: она же
        # не трогает тип, уже описанный другим участком той же сцены (общий узел)
        data = [{"name": ru(st["name"]), "parent": None if st["parent"] is None else ru(st["parent"]),
                 "rel": st.get("rel"),
                 "slots": [{"types": [ru(t) for t in sl["types"]], "pos": sl["pos"],
                            "order": int(sl.get("order", 1))} for sl in st["slots"]]}
                for st in st_list]
        code.append("T[_u(%r)] = define_assembly(%r, G[_u(%r)], %r, T)" % (type_name, type_name, grp, data) + nl)

    if sub_name:
        asm_code(sub_title, sub_title, subs[sub_name]["steps"])
    for s in store_subs:
        # готовый узел едет как деталь — в группе деталей изделия
        asm_code(ru(s), GP, subs[s]["steps"])
    asm_code(title, G, steps)
    code.append("result = sorted(T.keys())")

    # длина и ширина поста — под изделие: корпус батареи 1090 × 830 мм на посту 0,8 м не уместится
    bb = kit.get("bbox")
    post_len, conv_w, stand = 800.0, None, 700.0
    if bb:
        lx, ly = bb[1][0] - bb[0][0], bb[1][1] - bb[0][1]
        post_len = max(800.0, round(lx + 300.0, -1))
        conv_w = max(600.0, round(ly + 170.0, -1)) if ly + 170.0 > 600.0 else None
        stand = max(700.0, round(max(lx, ly) + 100.0, -1))
    pitch = POST_PITCH if sub_name else max(3800.0, post_len + 3000.0)
    return {
        "title": title, "asm": title, "root_step": ru(root["name"]),
        "group": G, "parts_group": GP,
        "store": f"{short} склад: {root_part}", "ship": f"{short} отгрузка" if ship == "robot" else None,
        "posts": posts, "leg_a": leg_a, "product_code": "".join(code),
        # без участка подсборки посты можно ставить теснее: 4,5 м вместо 5,2
        "pitch": pitch, "post_len": post_len, "conv_w": conv_w, "stand": stand, "bbox": bb,
        "short": short,
        "sub": ({"title": sub_title, "asm": sub_title, "post_name": f"Сборка: {sub_title}",
                 "parts": sub_parts, "group": sub_title, "parts_group": f"Детали: {sub_title}",
                 "work_s": 8.0} if sub_name else None),
    }


def build(spec: AssemblySpec | None = None, progress: Callable[[str], None] | None = None) -> dict:
    return AssemblyLineBuilder(progress=progress).build_engine(spec or AssemblySpec())


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(build(AssemblySpec(**args), progress=lambda s: print("…", s, flush=True)),
                     ensure_ascii=False, indent=1))
