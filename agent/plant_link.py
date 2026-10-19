# -*- coding: utf-8 -*-
"""
Связать два участка в одной сцене: готовые узлы одного (ШПГ) едут на другой
(КШМ) на мобильных роботах, а не берутся со склада «из ниоткуда».

До связки: участок-поставщик сдаёт изделие на склад отгрузки, где оно
списывается; участок-потребитель берёт этот узел со своих складов, где он
создаётся. После связки:

- склад отгрузки поставщика и склады узла у потребителя — перевалки
  (принять → отдать дальше);
- маршрут изделия поставщика продолжается: … → отгрузка → [склады у постов
  потребителя] → [посты потребителя];
- отгрузка → склады: мобильные роботы (ТК мобильного робота + RB-Kairos, своя
  зона прохода — без неё карта путей строится по всей сцене и R-Pro без конца
  спрашивает окном); склад → пост: роботы постов потребителя, как и были.

Поставщик должен быть построен в сцене раньше потребителя: тогда тип узла
принадлежит группе поставщика, и его маршрут — маршрут поставщика.
"""

from __future__ import annotations

from typing import Any

import kits
from rpro_client import RProClient

RD = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
AGV_TC = RD + "PM Transport Controllers/Mobile Robot Transport Controller.rpro"
AGV = "https://download.r-pro.digital/v204/Components/Robotnik/PM Mobile Robots/RB-Kairos.rpro"
IDLE = RD + "PM Resource Utilities/Idle Location.rpro"
PATHWAY = RD + "PM Resource Utilities/Pathway Area.rpro"

FIND = r"""
owner = dict((_u(k), c) for k, c in process_owner().items())   # ключи — юникодом (_u)
sup_ship = %r
title = %r
cons = %r
ship = owner.get(_u(sup_ship))
stores = dict((_u(k), c) for k, c in owner.items()
              if _u(k).startswith(_u(cons) + u' склад') and _u(k).endswith(_u(title)))
posts = {}
for l in pc().TransportSystem.Links:
    s, d, impl = comp_of(l.Source), comp_of(l.Destination), comp_of(l.Implementer)
    for pid, c in stores.items():
        if s is not None and s.Name == c.Name and d is not None:
            posts[pid] = [_u(d.Name), _u(routine(d).Name), _u(impl.Name) if impl is not None else None]
t = pc().ProductTypeManager.findProductType(_b(title))
linked = ship is not None and u'RemoveProduct' not in [_u(_safe(s_, 'Type') or u'') for s_ in routine(ship).Statements]
result = {'ship': _u(ship.Name) if ship is not None else None, 'linked': linked,
          'ship_xy': [ship.PositionMatrix.P.X, ship.PositionMatrix.P.Y] if ship is not None else None,
          'stores': dict((pid, [_u(c.Name), c.PositionMatrix.P.X, c.PositionMatrix.P.Y]) for pid, c in stores.items()),
          'posts': posts,
          'type_group': _u(t.FlowGroup.Name) if t is not None else None,
          'flow': [_u(x) for x in flow_ids(group_by_name(_b(title)))] if group_by_name(_b(title)) is not None else []}
"""


def link_lines(client: RProClient, supplier: str, consumer: str, agvs: int = 2) -> dict[str, Any]:
    sup, con = kits.find_kit(supplier), kits.find_kit(consumer)
    # Поставщика могут назвать заказчиком («МоторКомплект») или не так — тогда
    # он известен из потребителя: его узел со склада (ШПГ у КШМ)
    if con is not None and (sup is None or sup["title"] == con["title"]
                            or sup["title"] not in con.get("subs", {})):
        store_subs = [t for t, v in con.get("subs", {}).items() if v.get("supply") == "store"]
        if store_subs:
            sup = kits.find_kit(store_subs[0]) or sup
    if sup is None or con is None:
        return {"ошибка": f"нет набора «{supplier if sup is None else consumer}»"}
    s_short, c_short, title = sup.get("short") or sup["title"], con.get("short") or con["title"], sup["title"]
    client.simulation("reset")
    info = kits._run(client, FIND % (f"{s_short} отгрузка", title, c_short))
    if not info["ship"]:
        return {"ошибка": f"в сцене нет участка «{s_short}» (склад «{s_short} отгрузка»)"}
    if info.get("linked"):
        return {"уже_связаны": f"{s_short} → {c_short}",
                "что_дальше": "Связь уже есть — второй раз не связываю. Отчёт по прогону покажет выпуск."}
    if not info["stores"]:
        return {"ошибка": f"на участке «{c_short}» нет складов узла «{title}» — потребитель не построен?"}
    if info["type_group"] != title:
        return {"ошибка": f"узел «{title}» принадлежит группе «{info['type_group']}», а не поставщику: "
                          "постройте сначала участок поставщика, потом потребителя"}
    if any(p[1] is None for p in info["posts"].values()) or len(info["posts"]) != len(info["stores"]):
        return {"ошибка": "не нашёл постов потребителя за складами узла", "склады": list(info["stores"])}

    stores = info["stores"]          # pid → [имя, x, y]
    posts = info["posts"]            # pid склада → [имя поста, pid поста, ТК робота]
    flow = info["flow"]
    ship_pid = f"{s_short} отгрузка"
    if ship_pid in flow:
        flow = flow[:flow.index(ship_pid) + 1]
    flow = flow + [sorted(stores), sorted(p[1] for p in posts.values())]

    # мобильные роботы — между отгрузкой и складами
    sx, sy = info["ship_xy"]
    tx = sum(v[1] for v in stores.values()) / len(stores)
    ty = sum(v[2] for v in stores.values()) / len(stores)
    mx, my = (sx + tx) / 2.0, (sy + ty) / 2.0
    # Корпус контроллера — препятствие: посреди коридора он перегораживал AGV
    # подъезд («Unable to solve path»). Ставим его в стороне от коридора.
    side_x = min([sx] + [v[1] for v in stores.values()]) - 4000.0
    code = ["tc = load(%r)\nplace(tc, %f, %f)\n" % (AGV_TC, side_x, my), "rb = []\nidle = []\n"]
    for k in range(agvs):
        x = mx + (k - (agvs - 1) / 2.0) * 1800.0
        code.append("r_ = load(%r)\nplace(r_, %f, %f)\nrb.append(r_)\n"
                    "i_ = load(%r)\nplace(i_, %f, %f)\nidle.append(i_)\n"
                    % (AGV, x + 600.0, my, IDLE, x, my))
    code.append("connect_people(tc, rb, idle)\n"
                "p = tc.getProperty('UseGlobalArea')\nif p is not None: p.Value = False\n")
    # перевалки и маршрут. AGV подъезжает к складу со стороны коридора между
    # участками и в 1,2 м от него: по умолчанию точка — в 0,5 м, у самого края
    # подставки, и навигация считает её препятствием («Unable to solve path»)
    def approach(x: float, y: float) -> float:
        return 1200.0 if my > y else -1200.0
    code.append("buffer_routine(comp(%r), %r)\n" % (info["ship"], ship_pid))
    code.append("set_prop(comp(%r), 'ResourceOffset', mat(0.0, %f, 0.0, 90.0))\n"
                % (info["ship"], approach(sx, sy)))
    for pid, v in stores.items():
        code.append("buffer_routine(comp(%r), %r)\n" % (v[0], pid))
        code.append("set_prop(comp(%r), 'ResourceOffset', mat(0.0, %f, 0.0, 90.0))\n"
                    % (v[0], approach(v[1], v[2])))
    code.append("res = set_flow(%r, _b(%r))\n" % (flow, title))
    # связи: отгрузка → склады (AGV), склад → пост (робот поста) — в группе поставщика
    for pid, v in stores.items():
        post_name, _, robot_tc = posts[pid]
        code.append("link(comp(%r), comp(%r), tc, _b(%r))\n" % (info["ship"], v[0], title))
        code.append("link(comp(%r), comp(%r), comp(%r), _b(%r))\n" % (v[0], post_name, robot_tc, title))
    code.append("area = crew_area(tc, %r, 1500.0)\n" % PATHWAY)
    code.append("result = {'tc': tc.Name, 'agv': [r_.Name for r_ in rb], 'flow': res, 'area': area}")
    done = kits._run(client, "".join(code))
    return {"связаны": f"{s_short} → {c_short}", "мобильных_роботов": agvs,
            "склады_узла": sorted(stores), "маршрут_шагов": done["flow"]["steps"],
            "зона_проезда": done["area"],
            "что_дальше": "Отчёт по прогону покажет выпуск обоих участков и узкое место завода."}


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(link_lines(RProClient(timeout=300), sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
