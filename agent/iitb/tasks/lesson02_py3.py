# -*- coding: utf-8 -*-
"""
Урок 2 ИИТБ: «Создание планировки».

Каталог → компоненты → зона моделирования → PnP-подключение интерфейсов → сохранить.
Планировка из PDF урока: устройство подачи → конвейер → «С конвейера» | робот Kuka на
транспортном контроллере и параметрический вертикально-фрезерный станок | «К конвейеру» → конвейер.
Приёмы (snap = PnP, mount_robot) — из hands27, элементы линии — из LineBuilder.
"""

from __future__ import annotations

import line_builder as lbm
from line_builder import LineBuilder, LineSpec, URI

MILL = lbm.RD + "Machines/Parametric vertical mill.rpro"
KUKA = "https://download.r-pro.digital/v204/Components/KUKA/Robots/Palletizers (40kg - 1300kg)/KR40_PA.rpro"
KUKA_FALLBACK = lbm.ROBOTS[1][1]  # KR 30 R2100, досягаемость ~2,1 м


def build_layout(client, progress=print) -> dict:
    """Строит планировку урока 2; возвращает имена компонентов для урока 3."""
    lb = LineBuilder(client, progress=progress)
    lb.spec = LineSpec(robot="kuka")
    lb.prefix = ""
    lb.group = "Группа процессов #1"
    lb._pace = 0.05
    # 1. подача деталей
    f = lb.step("f = load(%r)\nplace(f, 0.0, 0.0)\n"
                "cr = beh(f, typ='rProductCreator')\n"
                "cr.SingleFeed.getProperty('Interval').Value = 20.0\n"
                "result = {'name': f.Name, 'at': m2l(f.PositionMatrix)}" % URI["feeder"])
    last, out = f["name"], "OutInterface"
    # 2. конвейер 1
    last, out = lb._conveyor(last, out, 3000.0, 700.0)
    # 3. «С конвейера» (съём) и «К конвейеру» (укладка) — разрыв ленты 1,8 м
    p = lb._node("pick", "С конвейера", 700.0, "snap(comp(%r), %r, n_, 'InInterface')\n" % (last, out))
    q = lb._node("place", "К конвейеру", 700.0,
                 "put_frame_at(n_, 'OutInterface', ahead(frame_world(comp(%r), %r), %f))\n"
                 % (last, out, lbm.GAP))
    ax = (p["at"][0] + q["at"][0]) / 2.0
    ay = (p["at"][1] + q["at"][1]) / 2.0
    # 4. транспортный контроллер робота + робот Kuka
    tc = lb.step(
        "tc = load(%r)\nplace(tc, %f, %f, 0.0, -90.0)\n"
        "rb = load(%r)\nok = mount_robot(tc, rb)\n"
        "result = {'tc': tc.Name, 'robot': rb.Name, 'mounted': ok, 'at': [%f, %f, 0.0]}"
        % (URI["tc"], ax, ay + lbm.ROBOT_OFFSET, KUKA, ax, ay + lbm.ROBOT_OFFSET))
    if not tc["mounted"]:
        client.exec_python("app.deleteComponent(app.findComponent(%r))" % tc["robot"])
        tc = lb.step(
            "rb = load(%r)\nok = mount_robot(comp(%r), rb)\n"
            "result = {'tc': %r, 'robot': rb.Name, 'mounted': ok, 'at': [%f, %f, 0.0]}"
            % (KUKA_FALLBACK, tc["tc"], tc["tc"], ax, ay + lbm.ROBOT_OFFSET))
    # 5. станок лицом к роботу (место обслуживания ResourceLocation)
    m = lb._front_of(MILL, ax, ay + lbm.ROBOT_OFFSET, "Фрезерный станок",
                     "pt = m.getProperty('ProcessTime')\nif pt is not None: pt.Value = 4.0\n")
    # 6. конвейер 2 после «К конвейеру»
    last2, out2 = lb._conveyor(q["name"], "OutInterface", 3000.0, 700.0)
    return {"feeder": f["name"], "pick": p["name"], "place": q["name"], "tc": tc["tc"],
            "robot": tc["robot"], "machine": m["name"], "machine_pid": m["pid"],
            "conveyor_end": last2, "mounted": tc["mounted"], "lb": lb}


def run(client) -> dict:
    res = build_layout(client)
    lb = res.pop("lb")
    lb._overview()
    res["компонентов"] = client.status()["component_count"]
    return res
