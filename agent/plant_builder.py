# -*- coding: utf-8 -*-
"""
Двухэтажный цех со связанными процессами.

    1-й этаж   линия A: подача → станция → спираль вверх
               линия B: подача → станция → спираль вверх
    2-й этаж   (перекрытие на опорах, лестница)
               A: станция → поворот к центру ─┐
                                              ├─ общий робот-хаб → общий контроль качества
               B: станция → поворот к центру ─┘          ↓
                                          общая лента → скат вниз
    1-й этаж   общая отгрузка: финишный робот → выход

Связанность — в моделировании процессов: у A и B свои группы деталей и
маршруты, но последние шаги у них ОБЩИЕ — один процесс контроля, одна
укладка, один финиш. Общий робот обслуживает оба потока, и транспортные
связи для общих шагов созданы для обеих групп.

Примитивы — из line_builder.LineBuilder; здесь только планировка.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from line_builder import URI, ROBOT_OFFSET, LineBuilder, LineSpec, _station_kind

FLOOR = 3000.0        # отметка второго этажа, мм
LINE_GAP = 10000.0    # расстояние между линиями A и B
SLAB = 200.0          # толщина перекрытия


@dataclass
class PlantSpec:
    product_a: str = ""                 # что едет по линии A (пусто — заготовка)
    product_b: str = "коробка"          # что едет по линии B
    ground_a: list[str] = field(default_factory=lambda: ["токарный"])
    ground_b: list[str] = field(default_factory=lambda: ["фрезерный"])
    upper_a: list[str] = field(default_factory=lambda: ["фрезерный"])
    upper_b: list[str] = field(default_factory=lambda: ["токарный"])
    shared: str = "контроль"            # общая станция второго этажа
    interval_s: float = 25.0
    process_s: float = 4.0
    speed: float = 700.0
    sim_speed: float = 3.0
    robot: str = ""
    clear: bool = False
    pace_s: float = 0.05


class PlantBuilder(LineBuilder):

    def build_plant(self, ps: PlantSpec) -> dict:
        t0 = time.time()
        # общие настройки берём у LineBuilder через его спецификацию
        self.spec = LineSpec(stations=[], interval_s=ps.interval_s, process_s=ps.process_s,
                             speed=ps.speed, robot=ps.robot, clear=ps.clear, pace_s=ps.pace_s)
        self._pace = ps.pace_s
        self.robots_used = 0
        y0 = self._prepare(self.spec)
        first = int(self.run("result = len(feeders_in_scene())")) + 1
        H, UH = FLOOR, FLOOR + 700.0
        # y0 — свободная полоса к северу от существующего; цех целиком севернее
        # (станции B торчат наружу ещё на ~4,5 м)
        yb = y0 + 5000.0
        ya = yb + LINE_GAP
        ym = (ya + yb) / 2.0
        report: dict[str, Any] = {"линии": [first, first + 1], "станции": [], "предупреждения": []}
        shared_prefix = f"Ц{first} "

        # --- две линии: первый этаж и подъём ------------------------------------
        streams = []
        for k, (yy, side, ground, upper, product, turn) in enumerate((
                (ya, +1, ps.ground_a, ps.upper_a, ps.product_a, "Right"),
                (yb, -1, ps.ground_b, ps.upper_b, ps.product_b, "Left"))):
            n = first + k
            self.prefix, self.group = f"Л{n} ", f"Линия {n}"
            letter = "AB"[k]
            self.progress(f"линия {letter}: подача и первый этаж")
            f = self.step(
                "f = load(%r)\nplace(f, 0.0, %f)\n"
                "beh(f, typ='rProductCreator').SingleFeed.getProperty('Interval').Value = %f\n"
                "info = new_line_group(f, %r, %r, %r)\n"
                "result = {'name': f.Name, 'at': m2l(f.PositionMatrix), 'type': info['type']}"
                % (URI["feeder"], yy, float(ps.interval_s), self.group, f"Деталь Л{n}",
                   self._product_uri(product)))
            last, out = f["name"], "OutInterface"
            flow, links = [], []
            for i, word in enumerate(ground, 1):
                last, out = self._conveyor(last, out, 3500.0, ps.speed)
                st = self._station(i, _station_kind(word, i), last, out, self.spec,
                                   side=side, tag=f"{i}")
                flow += st["flow"]; links += st["links"]
                report["станции"].append(f"{letter} этаж 1: " + st["описание"])
                last, out = st["out"], "OutInterface"
            last, out = self._conveyor(last, out, 2500.0, ps.speed)
            self.progress(f"линия {letter}: спираль на второй этаж")
            spiral_in_x = self.run("result = m2l(frame_world(comp(%r), %r))" % (last, out))[0]
            last, out = self._spiral_up(last, out, H, ps.speed)
            last, out = self._conveyor(last, out, 3500.0, ps.speed, height=UH)
            for i, word in enumerate(upper, len(ground) + 1):
                self.progress(f"линия {letter}: станция второго этажа")
                st = self._station(i, _station_kind(word, i), last, out, self.spec,
                                   side=side, level=H, height=UH, tag=f"{i}")
                flow += st["flow"]; links += st["links"]
                report["станции"].append(f"{letter} этаж 2: " + st["описание"])
                last, out = st["out"], "OutInterface"
                last, out = self._conveyor(last, out, 3000.0, ps.speed, height=UH)
            # поворот к центру цеха и подход к общему хабу
            last, out = self._curve(last, out, turn, ps.speed, height=UH)
            approach = LINE_GAP / 2.0 - 1000.0 - 1300.0
            last, out = self._conveyor(last, out, approach, ps.speed, height=UH)
            hub_pick = self._node("pick", f"{self.prefix}Съём хаб", UH,
                                  "snap(comp(%r), %r, n_, 'InInterface')\n" % (last, out))
            streams.append({"n": n, "group": self.group, "prefix": self.prefix, "flow": flow,
                            "links": links, "hub_pick": hub_pick, "spiral_x": spiral_in_x})

        # --- общий хаб второго этажа ---------------------------------------------
        self.progress("общий робот и контроль качества на втором этаже")
        xc = (streams[0]["hub_pick"]["at"][0] + streams[1]["hub_pick"]["at"][0]) / 2.0
        hub_robot = self._robot_at(xc + 1000.0, ym, H, 180.0)
        kind = _station_kind(ps.shared, 0)
        title, uri = self.rotation.next(kind if kind != "перекладка" else "контроль")
        machine = self._front_of(uri, xc + 1000.0, ym, f"{shared_prefix}{title} (общий)",
                                 "pt = m.getProperty('ProcessTime')\n"
                                 "if pt is not None: pt.Value = %f\n" % ps.process_s,
                                 heading=0.0, level=H)
        hub_place = self._node("place", f"{shared_prefix}Укладка хаб", UH,
                               "put_frame_at(n_, 'OutInterface', mat(%f, %f, %f, 180.0))\n"
                               % (xc - 150.0, ym, UH))
        report["станции"].append(f"общий хаб: {title}, робот {hub_robot['robot']}")

        # --- общая лента вниз и отгрузка ------------------------------------------
        self.progress("общая лента второго этажа и скат вниз")
        # перекрытие начинается за спиралями (их радиус ~1,75 м), иначе режет их
        slab_x0 = max(s["spiral_x"] for s in streams) + 2200.0
        last, out = self._conveyor(hub_place["name"], "OutInterface", xc - 150.0 - slab_x0,
                                   ps.speed, height=UH)
        last, out = self._ramp_down(last, out, H, 7500.0, ps.speed, top=UH)
        last, out = self._conveyor(last, out, 3000.0, ps.speed)
        self.progress("общая отгрузка")
        fin = self._finish(last, out, side=+1, prefix=shared_prefix)

        # --- перекрытие, опоры, лестница -----------------------------------------
        self.progress("перекрытие второго этажа, опоры и лестница")
        x1 = xc + 4500.0
        self._mezzanine(slab_x0, x1, yb - 4500.0, ya + 4500.0, H)

        # --- логика: две группы, общие шаги -----------------------------------------
        self.progress("маршруты двух потоков с общими шагами")
        shared_tail = [f"{shared_prefix}{title} (общий)", f"{shared_prefix}Укладка хаб"] + fin["flow"]
        for s in streams:
            full = s["flow"] + [s["prefix"] + "Съём хаб"] + shared_tail
            res = self.run("result = set_flow(%r, %r)" % (full, s["group"]))
            if res.get("missing"):
                report["предупреждения"].append(f"{s['group']}: нет процессов " + ", ".join(res["missing"]))
            hub = [(s["hub_pick"]["name"], machine["name"], hub_robot["tc"]),
                   (machine["name"], hub_place["name"], hub_robot["tc"])]
            for src, dst, tc in s["links"] + hub + fin["links"]:
                self.run("link(comp(%r), comp(%r), comp(%r), %r)\nresult = 1" % (src, dst, tc, s["group"]))

        # --- самопроверка и общий план --------------------------------------------
        self.progress("проверяю досягаемость на всех станциях")
        import line_doctor
        self.client.messages(clear=True)
        fixes = line_doctor.LineDoctor(self.client).auto_fix()
        if fixes["исправлено"]:
            report["исправлено_при_проверке"] = [f["станция"] for f in fixes["исправлено"]]
        report["предупреждения"] += [str(p) for p in fixes["проверка_после"]]
        self.run("app.Simulation.SimSpeed = %f\nresult = 1" % ps.sim_speed)
        report["размер_м"] = self._overview()
        report["компонентов"] = self.count
        report["строилось_с"] = round(time.time() - t0)
        return report

    def _mezzanine(self, x0: float, x1: float, y0: float, y1: float, h: float) -> None:
        """Перекрытие (блок) на отметке h, опоры по сетке ~6 м, лестница у края."""
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        self.step(
            "s = load(%r)\n"
            "set_prop(s, 'Length_X', %f)\nset_prop(s, 'Width_Y', %f)\nset_prop(s, 'Height_Z', %f)\n"
            "place(s, %f, %f, %f)\n"
            "result = {'name': s.Name, 'at': [%f, %f, %f]}"
            % (URI["slab"], x1 - x0, y1 - y0, SLAB, cx, cy, h - SLAB, cx, cy, h), camera=False)
        nx = max(2, int((x1 - x0) / 6000.0) + 1)
        ny = max(2, int((y1 - y0) / 6000.0) + 1)
        pts = [(x0 + 300 + i * (x1 - x0 - 600) / (nx - 1), y0 + 300 + j * (y1 - y0 - 600) / (ny - 1))
               for i in range(nx) for j in range(ny)]
        code = "res_ = []\n"
        for x, y in pts:
            code += ("p_ = load(%r)\nset_prop(p_, 'Height', %f)\nset_prop(p_, 'Width', 300.0)\n"
                     "set_prop(p_, 'Length', 300.0)\nplace(p_, %f, %f, 0.0)\nres_.append(p_.Name)\n"
                     % (URI["pillar"], h - SLAB, x, y))
        self.run(code + "result = res_")
        # лестница: верх — на краю перекрытия, подъём в сторону −Y
        self.run(
            "st_ = load(%r)\nset_prop(st_, 'HeightOffset', %f)\n"
            "fr = beh(st_, 'SnapTopInterface').Sections[0].Frame.NodePositionMatrix.P\n"
            "place(st_, %f, %f + abs(fr.Y), 0.0, 180.0)\nresult = st_.Name"
            % (URI["stairs"], h, x1 - 1500.0, y1))


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    rep = PlantBuilder(progress=lambda s: print("  …", s, flush=True)).build_plant(PlantSpec())
    print(json.dumps(rep, ensure_ascii=False, indent=1))
