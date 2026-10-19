# -*- coding: utf-8 -*-
"""
Строитель производственных линий: из короткого описания — работающая линия в R-Pro.

Линия — змейка через цех: ряды вдоль оси X, развороты двумя поворотами.
В рядах стоят станции. Станция разрывает ленту: в конце участка деталь
снимает «С конвейера», робот несёт её в станок (или сразу дальше) и кладёт
через «К конвейеру» на следующий участок. В конце линии последний робот
отдаёт детали на выход.

Логика работы — моделирование процессов R-Pro, как в шаблонах программы:
готовые операции каталога, маршрут деталей по шагам (FlowTable2) и
транспортные связи с роботами-исполнителями. Всё это настраивается через
hands27.py, который выполняется внутри R-Pro.

Строим по элементу за вызов: пользователь видит, как линия растёт, а камера
ведёт голову стройки. Всё, что узнано про программу по дороге, записано в
hands27.py.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from rpro_client import BridgeError, RProClient

_HANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hands27.py")

RD = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
URI = {
    "feeder": RD + "PM Flow Components/Flow Feeder.rpro",
    "conveyor": RD + "Conveyors/Conveyor 4.01.rpro",
    "curve": RD + "Conveyors/Curve Conveyor 4.01.rpro",
    "pick": RD + "PM Flow Components/From Conveyor Process.rpro",
    "place": RD + "PM Flow Components/To Conveyor Process.rpro",
    "sink": RD + "PM Flow Components/Flow Sink.rpro",
    "tc": RD + "PM Transport Controllers/Robot Transport Controller.rpro",
    "spiral": RD + "Conveyors/spiral_conveyorv2.rpro",
    "ramp": RD + "Conveyors/VerticalOffset_conveyor_02_.rpro",
    "slab": RD + "Basic Shapes/BlockGeo.rpro",
    "pillar": RD + "Facilities - Interior/SquarePillar.rpro",
    "stairs": RD + "Facilities - Factory/Stairway v2.rpro",
}

# Роботы станций — все с досягаемостью ~2,05–2,1 м: геометрия станции
# (робот в 1,3 м от ленты, станок в 0,6 м за ним) рассчитана под неё.
_R = "https://download.r-pro.digital/v204/Components/"
ROBOTS = [
    ("ABB IRB 4600-60/2.05", _R + "ABB/Robots/IRB 4600-602.05.rpro"),
    ("KUKA KR 30 R2100", _R + "KUKA/Robots/Medium Payloads (30kg - 70kg)/Iontec-Series/KR_30_R2100.rpro"),
    ("FANUC M-710iC/50", _R + "Fanuc/Robots/M-710iC 50.rpro"),
    ("Yaskawa GP50", _R + "Yaskawa/Robots/GP50.rpro"),
]

# Оборудование станций: вид станции → станки каталога, по очереди.
# Отобраны прогоном всех 37 станков каталога: у этих процесс начинается с
# «Транспорт В (от предыдущего процесса)» и кончается «Транспорт Из (к
# следующему)», то есть станок принимает чужую деталь и отдаёт дальше.
# 3D-принтер, термопластавтоматы и EffiMat сами рождают детали — это
# источники, а не станции обработки: входящая деталь у них «теряет маршрут».
_C = "https://download.r-pro.digital/v204/Components/"
MACHINES = {
    "фрезерный": [
        ("Haas VF-1", _C + "Haas/Machines/VF-1.rpro"),
        ("Фрезерный станок с ЧПУ", RD + "Machines/MachineTending_Mill.rpro"),
        ("Hurco VM-1", _C + "Hurco/Machines/HURCO_VM1.rpro"),
        ("Feeler VMP-32A", _C + "Feeler/Machines/VPM-32A_V3.rpro"),
        ("Haas UMC-500", _C + "Haas/Machines/UMC-500.rpro"),
        ("Tongtai TVL-40", _C + "Tongtai/Machines/TONGTAI_TVL-40.rpro"),
    ],
    "токарный": [
        ("Haas ST-30", _C + "Haas/Machines/ST-30.rpro"),
        ("Токарный станок с ЧПУ", RD + "Machines/MachineTending_Lathe.rpro"),
        ("Goodway GA-2000", _C + "Goodway/Machines/GOODWAY_GA-2000.rpro"),
        # Colchester 3000L не берём: место загрузки глубоко внутри, робот не достаёт
        ("Feeler FTC-350", _C + "Feeler/Machines/FEELER_FTC350.rpro"),
    ],
    "контроль": [
        ("Mapvision Quality Gate", _C + "Mapvision/Machines/Quality Gate AD1 LSL.rpro"),
        ("Координатно-измерительная машина", RD + "Machines/CMM machine.rpro"),
    ],
    # Лазерную резку не берём: как и Colchester, робот не достаёт до места загрузки
    "пятиосевой": [("Пятиосевой станок", RD + "Machines/Parametric five-axis lathe.rpro")],
    "портальный": [("Портальный станок", RD + "Machines/Parametric gantry machine.rpro")],
    "сборка": [("Рабочая станция", RD + "Machines/MachineTending_GeneralProcessMachine.rpro")],
}

# Как человек называет станцию → вид; «перекладка» — робот без станка.
STATION_WORDS = {
    "фрез": "фрезерный", "токар": "токарный",
    "контрол": "контроль", "измер": "контроль", "качеств": "контроль", "инспек": "контроль",
    "пятиос": "пятиосевой", "портал": "портальный",
    "сборк": "сборка", "рабоч": "сборка", "монтаж": "сборка",
    "перекладк": "перекладка", "перенос": "перекладка",
    # общие слова — последними: «станок с роботом» не должен стать перекладкой
    "станок": "чередовать", "чпу": "чередовать", "обработ": "чередовать",
    "робот": "перекладка",
}

# Геометрия, мм. Проверено на живой программе: робот IRB 4600 (досягаемость
# 2,05 м) в 1300 мм от ленты достаёт и съём, и укладку, и станок.
GAP = 1800.0            # разрыв ленты на станции: съём → укладка
ROBOT_OFFSET = 1300.0   # робот сбоку от ленты
FRONT_GAP = 600.0       # от робота до места обслуживания станка
TURN_STRAIGHT = 5000.0  # прямой участок в развороте: ряды в 7 м друг от друга
MIN_SEG = 1500.0        # короче конвейер не ставим


def _station_kind(word: str, index: int) -> str:
    """Слово пользователя → вид станции (ключ MACHINES или «перекладка»)."""
    w = (word or "").lower()
    for key, kind in STATION_WORDS.items():
        if key in w:
            break
    else:
        kind = "чередовать"
    if kind == "чередовать":
        kind = ("фрезерный", "токарный")[index % 2]
    return kind


class _Rotation:
    """Выдаёт станки вида по очереди: шесть «фрезерных» — шесть разных моделей."""
    def __init__(self):
        self.used: dict[str, int] = {}

    def next(self, kind: str) -> tuple[str, str]:
        pool = MACHINES[kind]
        i = self.used.get(kind, 0)
        self.used[kind] = i + 1
        return pool[i % len(pool)]


@dataclass
class LineSpec:
    """Что строить. Всё необязательно — есть разумные умолчания."""
    length_m: float = 60.0              # общая длина ленты
    row_m: float = 24.0                 # длина ряда змейки
    stations: list[str] = field(default_factory=lambda: ["станок"] * 4)
    product: str = ""                   # вид детали: название модели из каталога
    interval_s: float = 20.0            # подача детали раз в N секунд
    process_s: float = 4.0              # время обработки в станке
    speed: float = 700.0                # скорость лент, мм/с
    sim_speed: float = 1.0              # множитель скорости симуляции (x2 — вдвое быстрее)
    robot: str = ""                     # марка роботов: abb, kuka, fanuc, yaskawa; пусто — вперемешку
    clear: bool = False                 # очистить сцену перед стройкой
    run_s: float = 0.0                  # сразу запустить симуляцию на N секунд
    pace_s: float = 0.08                # пауза между элементами — чтобы было видно рост

    @property
    def rows(self) -> int:
        return max(1, round(self.length_m / self.row_m))


class LineBuilder:
    def __init__(self, client: RProClient | None = None,
                 progress: Callable[[str], None] | None = None):
        self.client = client or RProClient()
        with open(_HANDS, encoding="utf-8") as f:
            self.lib = f.read()
        self.progress = progress or (lambda s: None)
        self.count = 0
        self.rotation = _Rotation()

    # --- связь с R-Pro --------------------------------------------------------

    def run(self, code: str) -> Any:
        r = self.client.exec_python(self.lib + "\n" + code)
        if r.get("stderr"):
            raise BridgeError(r["stderr"])
        return r.get("result")

    def step(self, code: str, camera: bool = True) -> Any:
        """Один элемент линии + камера на голову стройки."""
        res = self.run(code)
        self.count += 1
        if camera and isinstance(res, dict) and "at" in res:
            x, y, z = res["at"][:3]
            self.run("camera([%f, %f, 700.0], [%f, %f, 9000.0])" % (x, y, x - 9000, y - 12000))
        time.sleep(self._pace)
        return res

    # --- стройка -------------------------------------------------------------

    def build(self, spec: LineSpec) -> dict:
        t0 = time.time()
        self._pace = spec.pace_s
        self.spec = spec
        self.robots_used = 0
        report: dict[str, Any] = {"станции": [], "предупреждения": []}
        origin_y = self._prepare(spec)
        # Каждая линия — своё пространство имён процессов («Л2 Съём 1»), своя
        # группа деталей и свой тип детали. Иначе вторая линия с теми же
        # именами сливается с первой и переписывает её маршрут (так и было).
        self.line_no = int(self.run("result = len(feeders_in_scene())")) + 1
        self.prefix = f"Л{self.line_no} "
        self.group = f"Линия {self.line_no}"
        report["линия"] = self.line_no

        kinds = [_station_kind(w, i) for i, w in enumerate(spec.stations)]
        rows = spec.rows
        per_row = [0] * rows
        for i in range(len(kinds)):
            per_row[i * rows // max(len(kinds), 1)] += 1

        # 1. подача
        self.progress("ставлю подачу деталей")
        res = self.step(
            "f = load(%r)\nplace(f, 0.0, %f)\n"
            "cr = beh(f, typ='rProductCreator')\n"
            # Interval — не атрибут, а свойство RealDistribution: число, не строка
            "cr.SingleFeed.getProperty('Interval').Value = %f\n"
            "info = new_line_group(f, %r, %r, %r)\n"
            "result = {'name': f.Name, 'at': m2l(f.PositionMatrix), 'type': info['type']}"
            % (URI["feeder"], origin_y, float(spec.interval_s), self.group,
               f"Деталь Л{self.line_no}", self._product_uri(spec.product)))
        last, last_out = res["name"], "OutInterface"
        report["деталь"] = res.get("type")

        flow: list[str] = []
        links: list[tuple[str, str, str]] = []
        station_no = 0
        conveyor_mm = 0.0

        for r in range(rows):
            k = per_row[r]
            segs = self._segments(spec.row_m * 1000.0, k, shifted=r % 2 == 1)
            self.progress(f"ряд {r + 1} из {rows}: {k} станций")
            for j in range(k + 1):
                last, last_out = self._conveyor(last, last_out, segs[j], spec.speed)
                conveyor_mm += segs[j]
                if j < k:
                    station_no += 1
                    kind = kinds[station_no - 1]
                    self.progress(f"станция {station_no}: {kind}")
                    st = self._station(station_no, kind, last, last_out, spec)
                    report["станции"].append(st["описание"])
                    flow += st["flow"]
                    links += st["links"]
                    last, last_out = st["out"], "OutInterface"
            if r < rows - 1:
                turn = "Left" if r % 2 == 0 else "Right"
                last, last_out = self._curve(last, last_out, turn, spec.speed)
                last, last_out = self._conveyor(last, last_out, TURN_STRAIGHT, spec.speed)
                last, last_out = self._curve(last, last_out, turn, spec.speed)
                conveyor_mm += TURN_STRAIGHT + 2 * 1571

        # 2. финиш: робот снимает с конца линии и отдаёт на выход
        self.progress("ставлю финишного робота и выход")
        fin = self._finish(last, last_out)
        flow += fin["flow"]
        links += fin["links"]

        # 3. логика: маршрут и транспортные связи
        self.progress("задаю маршрут деталей и связи роботов")
        res = self.run("result = set_flow(%r, %r)" % (flow, self.group))
        if res.get("missing"):
            report["предупреждения"].append("нет процессов: " + ", ".join(res["missing"]))
        for src, dst, tc in links:
            self.run("link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (src, dst, tc, self.group))

        # 4. самопроверка: робот должен достать до каждого станка. Что не так —
        # чиним правкой на месте (сдвиг, замена модели), линию не пересобираем.
        self.progress("проверяю досягаемость на всех станциях")
        import line_doctor
        time.sleep(0.5)
        # в выводе могут быть ошибки прошлой сцены с теми же именами роботов
        self.client.messages(clear=True)
        fixes = line_doctor.LineDoctor(self.client).auto_fix()
        if fixes["исправлено"]:
            report["исправлено_при_проверке"] = [
                {"станция": f["станция"], "как": "замена" if "замена" in f else "сдвиг"}
                for f in fixes["исправлено"]]
        if fixes["проверка_после"]:
            report["предупреждения"] += [p.get("что", "") + " — станция " + str(p.get("станция"))
                                         for p in fixes["проверка_после"]]

        # 5. общий план
        overview = self._overview()
        report.update({
            "длина_ленты_м": round(conveyor_mm / 1000.0, 1),
            "рядов": rows,
            "роботов": station_no + 1,
            "станков": sum(1 for k in kinds if k != "перекладка"),
            "компонентов_поставлено": self.count,
            "маршрут": flow,
            "размер_цеха_м": overview,
            "строилось_с": round(time.time() - t0),
        })
        self.run("app.Simulation.SimSpeed = %f\nresult = 1" % max(0.1, float(spec.sim_speed)))
        if spec.run_s > 0:
            self.client.simulation("reset")
            time.sleep(1.0)
            report["симуляция"] = self.client.simulation("run_for", seconds=spec.run_s).get("note")
        return report

    # --- элементы ------------------------------------------------------------

    @staticmethod
    def _segments(row_mm: float, k: int, shifted: bool) -> list[float]:
        """Длины участков ряда между станциями. В нечётных рядах станции
        сдвинуты на полшага: оборудование соседних рядов не встаёт в столбец."""
        seg = max(MIN_SEG, (row_mm - k * GAP) / (k + 1))
        segs = [seg] * (k + 1)
        if shifted and k and seg / 2 >= MIN_SEG:
            segs[0], segs[-1] = seg * 1.5, seg * 0.5
        return segs

    def _prepare(self, spec: LineSpec) -> float:
        """Сброс симуляции, очистка или место рядом с тем, что уже стоит."""
        self.client.simulation("reset")
        time.sleep(1.0)
        if spec.clear:
            self.run("app.clearWorld()\nresult = 1")
            return 0.0
        # Не трогаем чужое: строим за северной границей сцены.
        top = self.run(
            "ys = [c.PositionMatrix.P.Y for c in app.Components]\n"
            "result = max(ys) if ys else None")
        return 0.0 if top is None else float(top) + 8000.0

    @staticmethod
    def _product_uri(product: str) -> str | None:
        """Модель каталога для вида детали; None — оставить заготовку подачи."""
        if not product:
            return None
        import catalog
        found = [m for m in catalog.найти(product, 5) if m["раздел"] == "Продукты и контейнеры"]
        return found[0]["адрес"] if found else None

    # Высота ленты height: 700 мм — первый этаж; на втором — 700 + высота
    # этажа, а сам конвейер стоит на полу на длинных ногах, как эстакада.

    def _conveyor(self, last: str, last_out: str, length: float, speed: float,
                  height: float = 700.0) -> tuple[str, str]:
        res = self.step(
            "a = comp(%r)\nc = load(%r)\n"
            "set_prop(c, 'ConveyorHeight', %f)\n%s"
            "set_prop(c, 'ConveyorLength', %f)\nset_prop(c, 'ConveyorSpeed', %f)\n"
            "snap(a, %r, c, 'InInterface')\n"
            "result = {'name': c.Name, 'at': m2l(frame_world(c, 'OutInterface'))}"
            % (last, URI["conveyor"], height, self._width_code(), length, speed, last_out))
        return res["name"], "OutInterface"

    def _width_code(self, var: str = "c") -> str:
        """Ширина ленты под изделие (корпус батареи — 830 мм поперёк)."""
        w = getattr(self, "conv_w", None)
        return "set_prop(%s, 'ConveyorWidth', %f)\n" % (var, w) if w else ""

    def _curve(self, last: str, last_out: str, direction: str, speed: float,
               height: float = 700.0) -> tuple[str, str]:
        res = self.step(
            "a = comp(%r)\nc = load(%r)\n"
            "set_prop(c, 'ConveyorHeight', %f)\n%s"
            "set_prop(c, 'Direction', %r)\nset_prop(c, 'ConveyorSpeed', %f)\n"
            "snap(a, %r, c, 'InInterface')\n"
            "result = {'name': c.Name, 'at': m2l(frame_world(c, 'OutInterface'))}"
            % (last, URI["curve"], height, self._width_code(), direction, speed, last_out))
        return res["name"], "OutInterface"

    def _spiral_up(self, last: str, last_out: str, rise: float, speed: float,
                   hand: str = "Right") -> tuple[str, str]:
        """Подъём на второй этаж спиральным конвейером: выход на rise выше входа,
        в том же направлении. Вниз спираль не годится: Elevation=Down кадры не
        перестраивает (это делает только кнопка Rebuild, а её из API не нажать)."""
        res = self.step(
            "a = comp(%r)\nc = load(%r)\n"
            "set_prop(c, 'HeightOffset', %f)\nset_prop(c, 'Spiral', %r)\n"
            "set_prop(c, 'ConveyorSpeed', %f)\n"
            "snap(a, %r, c, 'InInterface')\n"
            "result = {'name': c.Name, 'at': m2l(frame_world(c, 'OutInterface'))}"
            % (last, URI["spiral"], rise, hand, speed, last_out))
        return res["name"], "OutInterface"

    def _ramp_down(self, last: str, last_out: str, drop: float, run: float, speed: float,
                   top: float) -> tuple[str, str]:
        """Спуск наклонным конвейером: на run мм вперёд и drop мм вниз."""
        res = self.step(
            "a = comp(%r)\nc = load(%r)\n"
            "set_prop(c, 'ConveyorHeight', %f)\nset_prop(c, 'OffsetDirection', 'Down')\n"
            "set_prop(c, 'ConveyorHeightOffset', %f)\nset_prop(c, 'ConveyorLengthOffset', %f)\n"
            "set_prop(c, 'ConveyorSpeed', %f)\n"
            "snap(a, %r, c, 'InInterface')\n"
            "result = {'name': c.Name, 'at': m2l(frame_world(c, 'OutInterface'))}"
            % (last, URI["ramp"], top, drop, run, speed, last_out))
        return res["name"], "OutInterface"

    def _robot_uri(self) -> str:
        """Робот следующей станции: заданной марки или марки по очереди."""
        key = (self.spec.robot or "").lower()
        pool = [r for r in ROBOTS if key and key in r[0].lower()] or ROBOTS
        uri = pool[self.robots_used % len(pool)][1]
        self.robots_used += 1
        return uri

    def _robot_at(self, x: float, y: float, level: float, facing: float) -> dict:
        """ТК робота с роботом в точке (x, y) на этаже level, лицом в facing°."""
        return self.step(
            "tc = load(%r)\nplace(tc, %f, %f, %f, %f)\n"
            # по умолчанию робот ходит на половине скорости — на линии это тоскливо
            # AutoHoming: между заданиями робот уходит «Домой», а не стоит на последней точке
            "for nm, v in (('Speeds::Enabled', True), ('Speeds::JointSpeed', 1.0),"
            " ('Speeds::CartesianSpeed', 2000.0), ('Speeds::CartesianAcc', 4000.0),"
            " ('AutoHoming::Enabled', True), ('AutoHoming::Delay', 1.0)):\n"
            "    p = tc.getProperty(nm)\n"
            "    if p is not None: p.Value = v\n"
            "rb = load(%r)\nok = mount_robot(tc, rb)\n"
            "result = {'tc': tc.Name, 'robot': rb.Name, 'mounted': ok, 'at': [%f, %f, %f]}"
            % (URI["tc"], x, y, level, facing, self._robot_uri(), x, y, level))

    def _robot_near(self, ax: float, ay: float, side: int = 1, level: float = 0.0) -> dict:
        """Робот сбоку от точки ленты: side=+1 — со стороны +Y, −1 — со стороны −Y."""
        return self._robot_at(ax, ay + side * ROBOT_OFFSET, level, -90.0 * side)

    def _front_of(self, uri: str, rx: float, ry: float, pid: str, extra: str = "",
                  heading: float = 90.0, level: float = 0.0) -> dict:
        """Поставить оборудование лицом к роботу: его место обслуживания
        (кадр ResourceLocation) — в FRONT_GAP от робота по направлению heading
        (90° — дальше от ленты в сторону +Y)."""
        return self.step(
            "m = load(%r)\n"
            "face_to(m, 'ResourceLocation', %f, %f, %f, %f, %f)\n%s"
            "doors_wait_robot(m)\n"
            "pid = set_process_id(m, %r)\n"
            "result = {'name': m.Name, 'pid': pid, 'at': m2l(m.PositionMatrix)}"
            % (uri, rx, ry, FRONT_GAP, heading, level, extra, pid))

    def _node(self, kind: str, pid: str, height: float, code: str) -> dict:
        """Узел МП (съём/укладка/выход) на высоте ленты height."""
        return self.step(
            "n_ = load(%r)\n"
            "hp = n_.getProperty('ConveyorHeight')\n"
            "if hp is not None: hp.Value = %f\n" % (URI[kind], height) +
            code +
            "pid = set_process_id(n_, %r)\n" % pid +
            "result = {'name': n_.Name, 'at': m2l(frame_world(n_, %r))}"
            % ("InInterface" if kind == "pick" else "OutInterface"))

    def _station(self, n: int, kind: str, last: str, last_out: str, spec: LineSpec,
                 side: int = 1, level: float = 0.0, height: float = 700.0,
                 tag: str | None = None) -> dict:
        tag = tag or str(n)
        pick_id, place_id = f"{self.prefix}Съём {tag}", f"{self.prefix}Укладка {tag}"
        p = self._node("pick", pick_id, height,
                       "snap(comp(%r), %r, n_, 'InInterface')\n" % (last, last_out))
        q = self._node("place", place_id, height,
                       "put_frame_at(n_, 'OutInterface', ahead(frame_world(comp(%r), %r), %f))\n"
                       % (last, last_out, GAP))
        ax = (p["at"][0] + q["at"][0]) / 2.0
        ay = (p["at"][1] + q["at"][1]) / 2.0
        rb = self._robot_near(ax, ay, side, level)
        if kind == "перекладка":
            return {"flow": [pick_id, place_id], "links": [(p["name"], q["name"], rb["tc"])],
                    "out": q["name"], "описание": f"{tag}: робот-перекладчик"}
        title, uri = self.rotation.next(kind)
        mid = f"{self.prefix}{title} {tag}"
        m = self._front_of(uri, ax, ay + side * ROBOT_OFFSET, mid,
                           "pt = m.getProperty('ProcessTime')\n"
                           "if pt is not None: pt.Value = %f\n" % spec.process_s,
                           heading=90.0 * side, level=level)
        return {"flow": [pick_id, m["pid"], place_id],
                "links": [(p["name"], m["name"], rb["tc"]), (m["name"], q["name"], rb["tc"])],
                "out": q["name"], "описание": f"{tag}: {title}, робот {rb['robot']}"}

    def _finish(self, last: str, last_out: str, side: int = 1, prefix: str | None = None) -> dict:
        prefix = self.prefix if prefix is None else prefix
        p = self._node("pick", prefix + "Съём финиш", 700.0,
                       "snap(comp(%r), %r, n_, 'InInterface')\n" % (last, last_out))
        rb = self._robot_near(p["at"][0], p["at"][1], side)
        s = self._front_of(URI["sink"], p["at"][0], p["at"][1] + side * ROBOT_OFFSET,
                           prefix + "Выход", heading=90.0 * side)
        return {"flow": [prefix + "Съём финиш", s["pid"]], "links": [(p["name"], s["name"], rb["tc"])]}

    def _overview(self) -> list[float]:
        """Камера на всю линию. Возвращает размер занятой площади в метрах."""
        res = self.run(
            "xs = [c.PositionMatrix.P.X for c in app.Components]\n"
            "ys = [c.PositionMatrix.P.Y for c in app.Components]\n"
            "result = [min(xs), max(xs), min(ys), max(ys)]")
        x0, x1, y0, y1 = res
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        span = max(x1 - x0, y1 - y0, 5000.0)
        d = span * 0.85
        self.run("camera([%f, %f, 0.0], [%f, %f, %f])" % (cx, cy, cx - d * 0.35, cy - d * 1.05, d * 0.8))
        return [round((x1 - x0) / 1000.0, 1), round((y1 - y0) / 1000.0, 1)]


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    # Описание линии — JSON строкой или файлом (PowerShell портит кавычки в строке).
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg and os.path.isfile(arg):
        with open(arg, encoding="utf-8") as fh:
            arg = fh.read()
    spec = LineSpec(**json.loads(arg)) if arg else LineSpec(clear=True)
    rep = LineBuilder(progress=lambda s: print("  …", s, flush=True)).build(spec)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
