# -*- coding: utf-8 -*-
"""
Многоэтажный сборочный завод: на каждом этаже своя линия, узлы едут между
этажами на лифтах.

Заказчик описывает завод таблицей «Завод.csv» рядом со спецификациями:

    # Завод: тяговые батареи ЭлектроТяга
    # Высота этажа, м: 6
    Этаж;Изделие;Папка;Цель, шт/ч
    3;Плата BMS модуля;ЭлектроТяга — плата BMS;96
    2;Батарейный модуль 12S;ЭлектроТяга — батарейный модуль;96
    1;Тяговая батарея 17,8 кВт·ч;ЭлектроТяга — тяговая батарея;12

Кто кого кормит — из спецификаций: строка «узел: Плата BMS» у модуля значит,
что плата приезжает с этажа плат. Строитель:

1. принимает модели заказчика по каждой папке (customer_kit) — детали, цвета,
   операции роботов, места швов;
2. считает планировку: линии этажей — в одну линию вдоль X, у поставщика
   изделие уходит с последнего поста лентой на лифт, у потребителя лента от
   лифта приходит к посту, где узел ставится в изделие. Если пост дальше
   лифта — лента идёт прямо; если ближе — разворачивается и идёт вдоль линии
   назад. Этажи сдвинуты по Y так, чтобы лифт стоял ровно на ленте обоих;
3. строит этажи от поставщика к потребителю (тип узла должен принадлежать
   группе поставщика — тогда его маршрут продолжается на этаже ниже);
4. ставит лифты («Конвейер подъемный»: вход на отметке верхнего этажа,
   выход — нижнего), ленты доставки и склады-перевалки у постов;
5. продлевает маршрут узла: … → контроль → брак → склад у поста → пост;
6. перекрытия с проёмами под лифты, колонны по краям, вид на весь завод.

Приёмы и ловушки, на которых это стоит, — docs/11-mnogoetazhnyj-zavod.md.
"""

from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import customer_kit
from assembly_builder import ROBOT_OFF, SRC_OFF, AssemblyLineBuilder, AssemblySpec, kit_plan
from line_builder import RD, URI
from rpro_client import RProClient

LIFT_URI = RD + "Conveyors/VerticalShuttle_new.rpro"
EXIT_MM = 1500.0        # лента от последнего поста поставщика до лифта
LIFT_LEN = 1200.0       # длина площадки лифта вдоль ленты
SLAB_T = 300.0          # толщина перекрытия
MARGIN = 3900.0         # перекрытие шире линии: роботы и склады (2,8 м + подставка)
BUFFER_EVERY = 6000.0   # накопитель на ленте доставки через столько мм
STORE_LEN = 800.0       # длина перевалки («Операция на конвейере») на ленте доставки


@dataclass
class FactorySpec:
    customer: str = ""            # заказчик или папка с «Завод.csv»
    floor_h_m: float = 0.0        # высота этажа; 0 — из «Завод.csv» (по умолчанию 6 м)
    speed: float = 500.0          # скорость лент, мм/с
    sim_speed: float = 5.0
    clear: bool = False
    pace_s: float = 0.02


def find_factory(customer: str) -> tuple[str, dict] | None:
    """«Завод.csv» заказчика: в его папках (Документы\\Заказчики\\<заказчик> — …)."""
    root = customer_kit.CUSTOMERS
    if customer and os.path.isdir(customer):
        dirs = [customer]
    elif os.path.isdir(root):
        key = (customer or "").lower()
        dirs = [os.path.join(root, d) for d in sorted(os.listdir(root)) if key and key in d.lower()]
    else:
        dirs = []
    for d in dirs:
        for f in os.listdir(d):
            if f.lower().startswith("завод") and f.lower().endswith(".csv"):
                return os.path.join(d, f), read_factory(os.path.join(d, f))
    return None


def read_factory(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    meta, body = {}, []
    for line in text.splitlines():
        if line.startswith("#"):
            k, _, v = line[1:].partition(":")
            meta[k.strip().lower()] = v.strip()
        elif line.strip():
            body.append(line)
    floors = []
    for row in csv.DictReader(io.StringIO("\n".join(body)), delimiter=";"):
        get = lambda *names: next((v.strip() for k, v in row.items() if k and any(
            k.strip().lower().startswith(n) for n in names)), "")
        floors.append({"floor": int(customer_kit._num(get("этаж")) or 1), "title": get("изделие"),
                       "folder": get("папка"), "target": customer_kit._num(get("цель")) or 0.0})
    return {"meta": meta, "floors": floors, "name": meta.get("завод", "")}


def plan_layout(kit_of: dict[int, dict], floors: list[dict], R: float) -> dict:
    """Планировка завода без R-Pro: посты по X, сдвиги этажей по Y под лифты,
    где у потребителя хозяйство постов уходит на север (на юге — лента доставки)."""
    # кто кого кормит: узел со склада в наборе потребителя = изделие поставщика
    title_floor = {k["title"]: fl for fl, k in kit_of.items()}
    feeds: dict[int, tuple[int, str]] = {}      # поставщик → (потребитель, узел)
    for fl, k in kit_of.items():
        for s, v in k.get("subs", {}).items():
            if v.get("supply") == "store" and s in title_floor:
                feeds[title_floor[s]] = (fl, s)
    order = sorted(kit_of, key=lambda fl: -fl)   # сверху вниз: поставщик раньше
    plans = {fl: kit_plan(kit_of[fl], ship="lift" if fl in feeds else "robot", straight=True)
             for fl in order}

    # 2. планировка: X постов и сдвиги этажей по Y под лифты
    D = 2.0 * R + 600.0                          # разворот ленты: две кривые и вставка
    x0 = {fl: 0.0 for fl in order}
    y = {fl: 0.0 for fl in order}
    north: dict[int, tuple] = {}
    links_geo: dict[int, dict] = {}

    def post_x(fl, k):
        pl = plans[fl]
        return x0[fl] + pl["post_len"] / 2.0 + k * pl["pitch"]

    def geo(sup):
        con, part = feeds[sup]
        pc_, ps_ = plans[con], plans[sup]
        k_sub = next(i for i, p in enumerate(pc_["posts"]) if p.get("sub_store") and p.get("part") == part)
        x_lift = post_x(sup, len(ps_["posts"]) - 1) + ps_["post_len"] / 2.0 + EXIT_MM
        return con, part, k_sub, x_lift, post_x(con, k_sub)

    # по X — сверху вниз: если пост потребителя чуть дальше лифта, но ленте до
    # него не хватает места, линия потребителя сдвигается дальше
    for sup in sorted(feeds, key=lambda fl: -fl):
        con, part, k_sub, x_lift, x_st = geo(sup)
        if x_lift < x_st < x_lift + LIFT_LEN + 2500.0:
            x0[con] += x_lift + LIFT_LEN + 2500.0 - x_st
    # по Y — снизу вверх: y нижнего известен, поставщик встаёт так, чтобы его
    # лента вошла в лифт ровно над лентой доставки нижнего этажа
    for sup in sorted(feeds, key=lambda fl: feeds[fl][0]):
        con, part, k_sub, x_lift, x_st = geo(sup)
        y_store = y[con] - (ROBOT_OFF + SRC_OFF)
        if x_st > x_lift:
            # пост дальше лифта: лента от лифта прямо к складу у поста
            case, y_lift = "прямо", y_store
            north[con] = (x_lift, x_st)
        else:
            # пост ближе лифта: лента разворачивается и идёт вдоль линии назад
            case, y_lift = "с разворотом", y_store - D
            north[con] = (x_st, x_lift + LIFT_LEN + 2.0 * R + 600.0)
        y[sup] = y_lift
        links_geo[sup] = {"con": con, "part": part, "case": case, "x_lift": x_lift, "y_lift": y_lift,
                          "x_store": x_st, "y_store": y_store}

    return {"order": order, "plans": plans, "feeds": feeds, "title_floor": title_floor,
            "x0": x0, "y": y, "north": north, "links": links_geo, "D": D}


class FactoryBuilder(AssemblyLineBuilder):

    def build_factory(self, fs: FactorySpec) -> dict:
        t0 = time.time()
        found = find_factory(fs.customer)
        if found is None:
            raise ValueError(f"не нашёл «Завод.csv» у заказчика «{fs.customer}» в {customer_kit.CUSTOMERS}")
        path, fac = found
        base = os.path.dirname(path)
        root = os.path.dirname(base)
        H = (fs.floor_h_m or customer_kit._num(fac["meta"].get("высота этажа, м", "")) or 6.0) * 1000.0
        report: dict[str, Any] = {"завод": fac["name"] or fs.customer, "этажей": len(fac["floors"]),
                                  "высота_этажа_м": H / 1000.0, "этажи": {}, "лифты": [],
                                  "предупреждения": []}

        # 1. модели заказчика: детали, цвета, операции, места швов. Порядок — от
        # поставщика к потребителю: модуль ссылается на набор платы.
        floors = sorted(fac["floors"], key=lambda f: -f["floor"])
        kit_of: dict[int, dict] = {}
        for f in floors:
            folder = os.path.join(root, f["folder"]) if f["folder"] else ""
            if not os.path.isdir(folder):
                folder = customer_kit.find_folder(f["folder"] or f["title"]) or ""
            if not folder:
                raise ValueError(f"нет папки изделия «{f['title']}» ({f['folder']})")
            self.progress(f"принимаю модели: {f['title']}")
            kit_of[f["floor"]] = customer_kit.build_kit(self.client, folder)
        R = self._curve_radius()
        lay = plan_layout(kit_of, floors, R)
        order, plans, feeds, title_floor = lay["order"], lay["plans"], lay["feeds"], lay["title_floor"]
        x0, y, north, links_geo, D = lay["x0"], lay["y"], lay["north"], lay["links"], lay["D"]

        # 3. этажи: от поставщика к потребителю
        if fs.clear:
            self.client.simulation("reset")
            self.run("app.clearWorld()\nresult = 1")
        layouts: dict[int, dict] = {}
        for fl in order:
            k = kit_of[fl]
            target = next((f["target"] for f in floors if f["floor"] == fl), 0.0)
            spec = AssemblySpec(
                product=k["title"], block_every_s=3600.0 / target if target else 40.0, speed=fs.speed,
                sim_speed=fs.sim_speed, clear=False, pace_s=fs.pace_s, origin=(x0[fl], y[fl]),
                level=(fl - 1) * H, hall=False, straight=True, ship="lift" if fl in feeds else "robot",
                external=tuple(s for s, v in k.get("subs", {}).items() if v.get("supply") == "store"
                               and s in title_floor),
                north_x=north.get(fl))
            self.progress(f"этаж {fl}: {k['title']}")
            rep = self._build(spec, plans[fl])
            layouts[fl] = dict(self.layout, plan=plans[fl])
            report["этажи"][fl] = {"изделие": k["title"], "отметка_м": (fl - 1) * H / 1000.0,
                                   "постов": rep["постов_на_линии"], "роботов": rep["роботов"],
                                   "цель_в_час": target, **({"операции_роботов": rep["операции_роботов"]}
                                                            if rep.get("операции_роботов") else {})}
            report["предупреждения"] += rep.get("предупреждения", [])

        # 4. лифты и ленты доставки
        holes: dict[int, list] = {}
        for sup, g in links_geo.items():
            con = g["con"]
            self.progress(f"лифт: этаж {sup} → этаж {con}, {g['part']}")
            info = self._lift(layouts[sup], layouts[con], g, sup, con, fs.speed, R)
            report["лифты"].append(info["описание"])
            holes.setdefault(sup, []).append(info["hole"])   # лифт проходит перекрытие верхнего этажа

        # 5. перекрытия, колонны, вид
        self.progress("перекрытия этажей и колонны")
        for fl in order:
            lay = layouts[fl]
            xs = [p["x"] for p in lay["posts"]]
            x_a, x_b = min(xs) - 4000.0, max(xs) + 4000.0
            for sup, g in links_geo.items():
                if g["con"] == fl or sup == fl:
                    x_b = max(x_b, g["x_lift"] + LIFT_LEN + 2.0 * R + 2500.0)
                    x_a = min(x_a, g["x_store"] - 3000.0)
            y_a, y_b = y[fl] - MARGIN - (D if any(g["con"] == fl and g["case"] != "прямо"
                                                  for g in links_geo.values()) else 0.0), y[fl] + MARGIN
            # колонны не должны встать в линию этажа ниже: её полоса и ленты доставки заняты
            busy = []
            for low in order:
                if low < fl:
                    lx = [p["x"] for p in layouts[low]["posts"]]
                    busy.append((min(lx) - 3000.0, max(lx) + 3000.0, y[low] - 4500.0, y[low] + 4500.0))
            for g in links_geo.values():
                if g["con"] < fl:
                    busy.append((min(g["x_store"], g["x_lift"]) - 3000.0, max(g["x_store"], g["x_lift"]) + 6000.0,
                                 g["y_lift"] - 2000.0, g["y_store"] + 2000.0))
            self._floor_slab(fl, x_a, x_b, y_a, y_b, (fl - 1) * H, holes.get(fl, []), ground=(fl == 1),
                             busy=busy)
        self.run("app.Simulation.SimSpeed = %f\nresult = 1" % fs.sim_speed)
        size = self._overview()
        report.update({"размер_м": size, "компонентов_поставлено": self.count,
                       "строилось_с": round(time.time() - t0),
                       "что_дальше": "Прогони завод отчётом (minutes = 60): выпуск батарей, брак, "
                                     "узкое место по этажам."})
        return report

    # --- лифт и лента доставки ---------------------------------------------------

    def _curve_radius(self) -> float:
        """Радиус кривой ленты: снять с модели (кривую ставим и убираем)."""
        r = self.run("c = load(%r)\nset_prop(c, 'Direction', 'Left')\n"
                     "a = frame_world(c, 'InInterface').P\nb = frame_world(c, 'OutInterface').P\n"
                     "res = max(abs(b.X - a.X), abs(b.Y - a.Y))\napp.deleteComponent(c)\nresult = res" % URI["curve"])
        return float(r or 1000.0)

    def _lift(self, ls: dict, lc: dict, g: dict, sup: int, con: int, speed: float, R: float) -> dict:
        """Лифт с этажа поставщика на этаж потребителя, лента доставки и склад
        у поста. Порты лифта перестраиваются только сменой длины площадки —
        кнопку «Обновить порты» из API не нажать."""
        last, last_out = ls["last"]
        dz = ls["level"] - lc["level"]
        width = ls["plan"].get("conv_w") or 600.0
        # с последнего поста — лента к лифту
        self.conv_w = ls["plan"].get("conv_w")
        c1, c1_out = self._conveyor(last, last_out, EXIT_MM, speed)
        # лифт и лента доставки везут изделие поставщика — ширина под него
        res = self.step(
            "a = comp(%r)\nfo = frame_world(a, %r)\ns = load(%r)\n"
            "set_prop(s, 'SideA_PortPlaces', '%d')\nset_prop(s, 'SideB_PortPlaces', '700')\n"
            "set_prop(s, 'ConveyorWidth', %f)\n"
            # скрипт лифта в конце перестройки портов смотрит на выделение и
            # падает на пустом (IndexError в reSelect) — выделяем лифт на это время
            "sm_ = app.SelectionManager\n"
            "try:\n    sm_.setSelection(s, True)\nexcept Exception:\n    pass\n"
            "set_prop(s, 'ConveyorLength', %f)\nset_prop(s, 'ConveyorLength', %f)\n"
            "try:\n    sm_.clear()\nexcept Exception:\n    pass\n"
            "for nm, v in (('Servo::ShuttleSpeed', 1500.0), ('ConveyorSpeed', %f)):\n"
            "    p_ = s.getProperty(nm)\n    if p_ is not None: p_.Value = v\n"
            "s.PositionMatrix = mat(fo.P.X, fo.P.Y, %f, 0.0)\n"
            "ok = beh(a, %r).connect(beh(s, 'SideA_ioPort0'))\n"
            "rename(s, %r)\n"
            "result = {'name': s.Name, 'ok': bool(ok), 'at': [fo.P.X + %f, fo.P.Y, %f]}"
            % (c1, c1_out, LIFT_URI, int(dz + 700.0), width, LIFT_LEN + 1.0, LIFT_LEN, speed,
               lc["level"], c1_out, f"Лифт: этаж {sup} → {con}", LIFT_LEN, lc["level"]))
        lift = res["name"]
        if not res["ok"]:
            self.progress("лифт не состыковался с лентой верхнего этажа")
        # первая лента на нижнем этаже — к порту B лифта
        res = self.step(
            "s = comp(%r)\nfb = frame_world(s, 'SideB_ioPort0')\nc = load(%r)\n%s"
            "set_prop(c, 'ConveyorLength', %f)\nset_prop(c, 'ConveyorSpeed', %f)\n"
            "put_frame_at(c, 'InInterface', mat(fb.P.X, fb.P.Y, fb.P.Z, 0.0))\n"
            "ok = beh(s, 'SideB_ioPort0').connect(beh(c, 'InInterface'))\n"
            "result = {'name': c.Name, 'ok': bool(ok), 'at': m2l(frame_world(c, 'OutInterface'))}"
            % (lift, URI["conveyor"], self._width_code(), 600.0, speed))
        last, out = res["name"], "OutInterface"
        if g["case"] != "прямо":
            # разворот: налево, вставка, налево — и вдоль линии назад
            last, out = self._curve(last, out, "Left", speed)
            last, out = self._conveyor(last, out, 600.0, speed)
            last, out = self._curve(last, out, "Left", speed)
        # до склада у поста: длина — по фактическому положению конца ленты.
        # Транспорт по ленте «на вытягивание»: пока склад не забрал узел,
        # следующий не трогается, и по 34 м ленты ехал один модуль за раз
        # (~95 с на модуль, 37 в час вместо 96). Накопители через каждые ~6 м
        # делят путь на короткие перегоны — узлы идут друг за другом.
        end = self.run("result = m2l(frame_world(comp(%r), %r))" % (last, out))
        store_len = STORE_LEN
        run = abs(g["x_store"] - end[0]) - store_len / 2.0
        ext = lc["external"][g["part"]]
        tag = ext["store_pid"].split(" склад")[0]
        buffers: list[tuple[str, str]] = []
        while run > BUFFER_EVERY + store_len:
            last, out = self._conveyor(last, out, BUFFER_EVERY - store_len, speed)
            pid = f"{tag} накопитель {len(buffers) + 1}: {g['part']}"
            buffers.append((self._inline(last, out, pid, speed), pid))
            last, out = buffers[-1][0], "OutInterface"
            run -= BUFFER_EVERY
        if run > 50.0:
            last, out = self._conveyor(last, out, run, speed)
        store = self._inline(last, out, ext["store_pid"], speed)
        res = {"at": self.run("result = m2l(post_center(comp(%r)))" % store)}
        # маршрут узла продолжается на этаж ниже: … контроль, брак, накопители,
        # склад у поста, пост; между ними — лента, со склада на пост — робот
        chain = [ls["last"][0]] + [n for n, _ in buffers] + [store]
        flow = ls["flow"] + [pid for _, pid in buffers] + [ext["store_pid"], ext["pid"]]
        code = ["res = set_flow(%r, _b(%r))\n" % (flow, ls["group"])]
        for a_, b_ in zip(chain, chain[1:]):
            code.append("link(comp(%r), comp(%r), 'ConveyorTransport', _b(%r))\n" % (a_, b_, ls["group"]))
        code.append("link(comp(%r), comp(%r), comp(%r), _b(%r))\nresult = res"
                    % (store, ext["post"], ext["tc"], ls["group"]))
        self.run("".join(code))
        dist = abs(res["at"][0] - g["x_lift"]) / 1000.0
        return {"описание": f"этаж {sup} → {con}: {g['part']}, лифт {dz / 1000.0:g} м, "
                            f"лента доставки {g['case']} ~{dist:.0f} м, накопителей {len(buffers)}",
                "накопителей": len(buffers),
                "hole": (g["x_lift"] - 600.0, g["x_lift"] + LIFT_LEN + 600.0,
                         g["y_lift"] - width / 2.0 - 600.0, g["y_lift"] + width / 2.0 + 600.0)}

    def _inline(self, last: str, out: str, pid: str, speed: float) -> str:
        """«Операция на конвейере» в конце ленты: принять узел и отдать дальше."""
        return self.step(
            # длина — до стыковки: по умолчанию 1,5 м, и пять накопителей уводили
            # склад у поста на 3,9 м от робота — он не дотягивался до узла
            "a = comp(%r)\np = load(%r)\nset_prop(p, 'ConveyorLength', %f)\n%s"
            "snap(a, %r, p, 'InInterface')\n"
            "set_prop(p, 'ConveyorSpeed', %f)\n"
            "set_process_id(p, %r)\nbuffer_routine(p, %r)\n"
            "result = {'name': p.Name, 'at': m2l(post_center(p))}"
            % (last, RD + "PM Flow Components/Inline Process.rpro", STORE_LEN,
               self._width_code("p"), out, speed, pid, pid))["name"]

    # --- здание ----------------------------------------------------------------------

    def _floor_slab(self, fl: int, x0: float, x1: float, y0: float, y1: float, z: float,
                    holes: list, ground: bool = False, busy: list | None = None) -> None:
        """Перекрытие этажа на отметке z (верх плиты — пол этажа) с проёмами под
        лифты, колонны по краям через ~9 м. Первый этаж — пол цеха."""
        t = 20.0 if ground else SLAB_T
        rects = [(x0, x1, y0, y1)]
        for hx0, hx1, hy0, hy1 in holes:
            nxt = []
            for a0, a1, b0, b1 in rects:
                if hx1 <= a0 or hx0 >= a1 or hy1 <= b0 or hy0 >= b1:
                    nxt.append((a0, a1, b0, b1))
                    continue
                # плита минус проём: до, после, ниже, выше
                if hx0 > a0:
                    nxt.append((a0, hx0, b0, b1))
                if hx1 < a1:
                    nxt.append((hx1, a1, b0, b1))
                cx0, cx1 = max(a0, hx0), min(a1, hx1)
                if hy0 > b0:
                    nxt.append((cx0, cx1, b0, hy0))
                if hy1 < b1:
                    nxt.append((cx0, cx1, hy1, b1))
            rects = nxt
        code = []
        for a0, a1, b0, b1 in rects:
            code.append("s = load(%r)\nset_prop(s, 'Length_X', %f)\nset_prop(s, 'Width_Y', %f)\n"
                        "set_prop(s, 'Height_Z', %f)\nplace(s, %f, %f, %f)\n"
                        % (URI["slab"], a1 - a0, b1 - b0, t, (a0 + a1) / 2.0, (b0 + b1) / 2.0, z - t / 2.0))
        if not ground:
            nx = max(2, int((x1 - x0) / 9000.0) + 1)
            for i in range(nx):
                x = x0 + 300.0 + i * (x1 - x0 - 600.0) / (nx - 1)
                for yy in (y0 + 300.0, y1 - 300.0):
                    if any(a0 <= x <= a1 and b0 <= yy <= b1 for a0, a1, b0, b1 in (busy or [])):
                        continue
                    code.append("p_ = load(%r)\nset_prop(p_, 'Height', %f)\nset_prop(p_, 'Width', 400.0)\n"
                                "set_prop(p_, 'Length', 400.0)\nplace(p_, %f, %f, 0.0)\n"
                                % (URI["pillar"], z - t, x, yy))
        self.run("".join(code) + "result = 1")


def build(spec: FactorySpec, progress: Callable[[str], None] | None = None,
          client: RProClient | None = None) -> dict:
    return FactoryBuilder(client=client, progress=progress).build_factory(spec)


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"customer": "ЭлектроТяга"}
    print(json.dumps(build(FactorySpec(**args), progress=lambda s: print("…", s, flush=True),
                           client=RProClient(timeout=600)), ensure_ascii=False, indent=1))
