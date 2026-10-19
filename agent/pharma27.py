# -*- coding: utf-8 -*-
# Фармлиния (тестовое TechSkills, Модуль A): приёмы поверх hands27.
# Выполняется ВНУТРИ R-Pro (Python 2.7) после текста hands27.py.
#
# Главный приём — гибрид: выданные машины (роторная разливочная, укупорочная)
# — «классические» компоненты с путями и своей логикой, а маршрут, ОТК, роботы,
# люди и склады — моделирование процессов (МП). Изделие МП проходит машину по
# ленте физически. Сквозь машину процессная связь «по конвейеру» не работает,
# поэтому узлы МП на ленте принимают изделие «из контейнера» (как «С конвейера»)
# и отпускают «в контейнер» выходного пути (как «К конвейеру»), без связи.

PH_RD = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
PH_A = "C:/Users/savchikav/Documents/R-Pro/techskills/A/"
PH_M = PH_A + "models/"
PH_URI = {
    "conv": PH_RD + "Conveyors/Conveyor 4.01.rpro",
    "curve": PH_RD + "Conveyors/Curve Conveyor 4.01.rpro",
    "feeder": PH_RD + "PM Flow Components/Flow Feeder.rpro",
    "inline": PH_RD + "PM Flow Components/Inline Process.rpro",
    "pick": PH_RD + "PM Flow Components/From Conveyor Process.rpro",
    "place": PH_RD + "PM Flow Components/To Conveyor Process.rpro",
    "node": PH_RD + "PM Flow Components/Flow Node Process.rpro",
    "slab": PH_RD + "Basic Shapes/BlockGeo.rpro",
    "tc": PH_RD + "PM Transport Controllers/Robot Transport Controller.rpro",
    "human_tc": PH_RD + "PM Transport Controllers/Human Transport Controller.rpro",
    "mobile_tc": PH_RD + "PM Transport Controllers/Mobile Robot Transport Controller.rpro",
    "vehicle_tc": PH_RD + "PM Transport Controllers/Vehicle Transport Controller.rpro",
    "agv": PH_RD + "PM Mobile Robots/Transport Bot.rpro",
    "forklift": PH_RD + "PM Resources/Forklift Resource.rpro",
    "man": PH_RD + "PM Resources/Human (R-Pro Operator Male).rpro",
    "woman": PH_RD + "PM Resources/Human (R-Pro Operator Female).rpro",
    "idle": PH_RD + "PM Resource Utilities/Idle Location.rpro",
    "pathway": PH_RD + "PM Resource Utilities/Pathway Area.rpro",
    "shelf": PH_RD + "PM Warehousing/Warehouse Advanced Shelf.rpro",
    "pallet": PH_RD + "Products and Containers/FinPallet.rpro",
    "carton": PH_RD + "Products and Containers/R-PRO_box.rpro",
    "wall": PH_RD + "Facilities - Factory/Wall.rpro",
    "fence": PH_RD + "Facilities - Factory/GenericFence v3.rpro",
    "safety": PH_RD + "Facilities - Factory/SafetyArea.rpro",
    "extinguisher": PH_RD + "Facilities - Factory/Extinguisher.rpro",
    "robot_fast": "https://download.r-pro.digital/v204/Components/ABB/Robots/IRB 1300-7_1400.rpro",
    "robot_small": "https://download.r-pro.digital/v204/Components/KUKA/Robots/Low Payloads (5kg - 22kg)/Archiv/KR CYBERTECH-1/KR20R1810_Cybertech.rpro",
    "filler": PH_A + "equip/Rotary filling machine.rpro",
    "capper": PH_A + "equip/Bottle capping machine.rpro",
    "tunnel": PH_A + "equip/Tablet blister packing machine.rpro",
}


def ph_file(path):
    return "file:///" + path


def ph_conv(prev, prev_if, length, speed=300.0, height=700.0, width=None):
    """Отрезок ленты, пристыкованный к prev."""
    c = load(PH_URI["conv"])
    set_prop(c, "ConveyorHeight", height)
    if width:
        set_prop(c, "ConveyorWidth", width)
    set_prop(c, "ConveyorLength", float(length))
    set_prop(c, "ConveyorSpeed", float(speed))
    snap(prev, prev_if, c, "InInterface")
    return c


def ph_curve(prev, prev_if, direction, speed=300.0, height=700.0):
    c = load(PH_URI["curve"])
    set_prop(c, "ConveyorHeight", height)
    set_prop(c, "Direction", direction)
    set_prop(c, "ConveyorSpeed", float(speed))
    snap(prev, prev_if, c, "InInterface")
    return c


def ph_release(r, c, var):
    """Отпустить изделие обратно на ленту: «в контейнер» выходного пути узла.
    Контейнер — ДО режима «To Container» (иначе свойство может повесить мост)."""
    s = r.addStatement("TransportOut")
    s.getProperty("ProductVariableName").Value = _b(var)
    s.getProperty("Container").Value = beh(c, "PathOut__HIDE__")
    s.getProperty("Destination").Value = "To Container"
    return s


def ph_qc(prev, prev_if, pid, ok_type, bad_type, prop="ProdID", bad_value="Defect", check_s=0.4,
          bad_expr=None, length=300.0):
    """ОТК на ленте («Операция на конвейере»): принять изделие с ленты, проверить
    пометку брака, перекрасить сменой типа (зелёная/красная модель) и решить:
    годное — дальше по ленте, брак — «следующему процессу» по маршруту брака
    (его уносит робот). bad_expr — своё условие брака (например, случайное)."""
    q = load(PH_URI["inline"])
    # узел вмещает одно изделие, и оно проезжает весь узел: при длине 1,5 м по
    # умолчанию ОТК пропускает ~800 шт./ч — короткий узел (длина, не скорость)
    if length:
        set_prop(q, "ConveyorLength", float(length))
    snap(prev, prev_if, q, "InInterface")
    ph_hide_icons(q)
    ph_qc_script(q, prop, bad_value)
    r = clear_routine(q, pid)
    st = stats(q)
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "TransportIn", Mode=0, Source="From Container", ProductVariableName="P", AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Enter")
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    if check_s > 0:
        stmt(r, "Delay", Delay=float(check_s))
    s = r.addStatement("IfElse")
    s.getProperty("Condition").Value = _b(bad_expr or "IsDefect")
    stmt(s.ThenScope, "ChangeProductType", ProductVariableName="P", NewType=bad_type)
    stmt(s.ThenScope, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Leave")
    stmt(s.ThenScope, "TransportOut", Destination="To Next Process", ProductVariableName="P")
    stmt(s.ElseScope, "ChangeProductType", ProductVariableName="P", NewType=ok_type)
    stmt(s.ElseScope, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Leave")
    ph_release(s.ElseScope, q, "P")
    return q


# Скрипт поста ОТК. Условие процедуры МП не читает свойства изделия (P.ProdID
# всегда «ложь»), а свойства поста читает. Поэтому пост сам смотрит на изделие,
# которое пришло в его контейнер: пометка машины (ProdID == "Defect") →
# IsDefect = True и красный цвет, иначе зелёный. Процедура ветвится по IsDefect.
PH_QC_SCRIPT = '''from vcScript import *
comp = getComponent()
app = getApplication()
cont = comp.findBehaviour("ComponentContainer__HIDE__")
flag = comp.getProperty("IsDefect")
PROP = comp.getProperty("QcProperty").Value
BAD = comp.getProperty("QcBadValue").Value

MAT_BAD = app.findMaterial("QC_bad")
MAT_OK = app.findMaterial("QC_ok")

def OnTransition(part, arriving):
  if not arriving:
    return
  p = part.getProperty(PROP)
  bad = p is not None and p.Value == BAD
  flag.Value = bad
  m = MAT_BAD if bad else MAT_OK
  if m is not None:
    part.Material = m

cont.OnTransition = OnTransition

def OnReset():
  flag.Value = False
'''


def ph_qc_script(q, prop="ProdID", bad_value="Defect"):
    material("QC_bad", [0.85, 0.1, 0.1])
    material("QC_ok", [0.1, 0.75, 0.2])
    for nm, typ, v in (("IsDefect", VC_BOOLEAN, False), ("QcProperty", VC_STRING, prop),
                       ("QcBadValue", VC_STRING, bad_value)):
        p = q.getProperty(nm)
        if p is None:
            p = q.createProperty(typ, nm)
        p.Value = v
    sc = q.findBehaviour("QcLogic")
    if sc is None:
        sc = q.createBehaviour(VC_SCRIPT, "QcLogic")
    sc.Script = PH_QC_SCRIPT
    return sc


PH_GATE_SCRIPT = '''from vcScript import *
comp = getComponent()
app = getApplication()
cr = comp.findBehaviour("ProductCreator")
SRC = comp.getProperty("GateNode").Value

def OnRun():
  node = app.findComponent(SRC)
  cont = node.findBehaviour("ComponentContainer__HIDE__")
  while True:
    cr.Enabled = cont.ComponentCount > 0
    delay(0.5)
'''


def ph_gate(feeder, node):
    """Подача работает, только пока в узле node лежит короб."""
    p = feeder.getProperty("GateNode")
    if p is None:
        p = feeder.createProperty(VC_STRING, "GateNode")
    p.Value = node.Name
    sc = feeder.findBehaviour("Gate")
    if sc is None:
        sc = feeder.createBehaviour(VC_SCRIPT, "Gate")
    sc.Script = PH_GATE_SCRIPT
    return sc


def ph_stand_node(x, y, pid, size=600.0, height=800.0, rz=0.0, rgb=None, title=None):
    """Узел процесса на подставке (склад, изолятор брака, место укладки)."""
    s = load(PH_URI["slab"])
    set_prop(s, "Length_X", size)
    set_prop(s, "Width_Y", size)
    set_prop(s, "Height_Z", height - 20.0)
    place(s, x, y, (height - 20.0) / 2.0, rz)
    if rgb:
        paint(s, title or pid, rgb)
    n = load(PH_URI["node"])
    set_prop(n, "ConveyorHeight", height)
    place(n, x, y, 0.0, rz)
    set_prop(n, "ShowGeo", False)
    set_prop(n, "ShowResourceLocation", False)
    set_process_id(n, pid)
    # пометка подставки: обстановка (dress27.dress_stands) заменит белый блок
    # столом той же высоты, ящиком брака или разметкой места на полу
    kind = "bin" if rgb else ("floor" if height <= 200.0 else "table")
    for nm_, typ_, v_ in (("StandOf", VC_STRING, n.Name), ("StandKind", VC_STRING, kind),
                          ("StandHeight", VC_REAL, float(height))):
        pp = s.getProperty(nm_)
        if pp is None:   # «a or b» с объектом R-Pro нельзя — SystemError
            pp = s.createProperty(typ_, nm_)
        pp.Value = v_
    return n


def ph_robot(x, y, facing, uri=None, name=None):
    """ТК робота с роботом, лицом в facing°. Возвращает (tc, robot).
    Скорости робота — по умолчанию из библиотеки: менять их задание запрещает."""
    tc = load(PH_URI["tc"])
    place(tc, x, y, 0.0, facing)
    p = tc.getProperty("AutoHoming::Enabled")
    if p is not None:
        p.Value = True
    rb = load(uri or PH_URI["robot_small"])
    mount_robot(tc, rb)
    if name:
        tc.Name = _b("ТК робота " + name)
        rb.Name = _b("Робот " + name)
    return tc, rb


def ph_sink(c, pid, delay_s=0.5, keep=False):
    """Приём изделия и списание (утилизация, отгрузка)."""
    r = clear_routine(c, pid)
    st = stats(c)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="P",
         AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Enter")
    if delay_s > 0:
        stmt(r, "Delay", Delay=float(delay_s))
    stmt(r, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Leave")
    stmt(r, "RemoveProduct", ProductVariableName="P")
    return r


def ph_group(name):
    g = group_by_name(name)
    if g is None:
        g = pc().FlowGroupManager.createGroup(_b(name))
    return g


# --- геометрия ---------------------------------------------------------------

import math as _ph_math


def ph_xy(c, if_name):
    m = frame_world(c, if_name)
    return (m.P.X, m.P.Y)


def ph_axes(c, a_if, b_if):
    """Центр между двумя кадрами компонента, направление a→b и нормаль влево."""
    ax, ay = ph_xy(c, a_if)
    bx, by = ph_xy(c, b_if)
    L = _ph_math.hypot(bx - ax, by - ay) or 1.0
    dx, dy = (bx - ax) / L, (by - ay) / L
    return ((ax + bx) / 2.0, (ay + by) / 2.0), (dx, dy), (-dy, dx)


def ph_face(x, y, tx, ty):
    return _ph_math.degrees(_ph_math.atan2(ty - y, tx - x))


def ph_at(p, d, n, along=0.0, side=0.0):
    return (p[0] + d[0] * along + n[0] * side, p[1] + d[1] * along + n[1] * side)


def ph_hide_icons(c):
    for nm in ("ShowResourceLocation", "ShowGeo"):
        p = c.getProperty(nm)
        if p is not None:
            p.Value = False


def ph_place_node(kind, x, y, heading, pid, height=700.0):
    """Узел «К конвейеру» — начало новой ленты: кадр выхода в (x, y), лента
    пойдёт в направлении heading°."""
    n = load(PH_URI[kind])
    ph_hide_icons(n)
    hp = n.getProperty("ConveyorHeight")
    if hp is not None:
        hp.Value = height
    put_frame_at(n, "OutInterface", mat(x, y, height, heading))
    set_process_id(n, pid)
    return n


def ph_res_offset(c, dy):
    """Где встаёт человек у узла на ленте: dy мм поперёк ленты в системе узла."""
    p = c.getProperty("ResourceOffset")
    if p is None:
        return False
    p.Value = mat(0.0, dy, 0.0, 90.0 if dy < 0 else -90.0)
    return True


def ph_pick_end(prev, prev_if, pid, height=700.0):
    """«С конвейера» в конце ленты. Значки узла скрыты: диск на месте подхода
    навигация людей считает препятствием («Unable to solve path»)."""
    n = load(PH_URI["pick"])
    ph_hide_icons(n)
    hp = n.getProperty("ConveyorHeight")
    if hp is not None:
        hp.Value = height
    snap(prev, prev_if, n, "InInterface")
    set_process_id(n, pid)
    return n


# --- изделия и сборки ----------------------------------------------------------

def ph_grid(nx, ny, px, py, z, nz=1, pz=0.0, limit=None):
    pos = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                if limit is not None and len(pos) >= limit:
                    return pos
                pos.append([(i - (nx - 1) / 2.0) * px, (j - (ny - 1) / 2.0) * py, z + k * pz, 0, 0, 0])
    return pos


class PhTypes(dict):
    """Словарь типов: ключи — юникод (define_assembly ищет по _u(имя))."""
    def __getitem__(self, k):
        return dict.__getitem__(self, _u(k))

    def __setitem__(self, k, v):
        dict.__setitem__(self, _u(k), v)


def ph_types():
    """Группы, типы изделий и сборки фармлинии. Возвращает словарь типов."""
    T = PhTypes()
    def pt(name, group, model):
        T[name] = part_type(name, ph_group(group), ph_file(PH_M + model + ".rpro"))
    pt("Короб пустых бутылок", "Коробы бутылок", "box_bottles_empty")
    pt("Бутылка", "Сироп", "bottle_base")
    pt("Бутылка годная", "Сироп", "bottle_ok")
    pt("Бутылка брак", "Брак сиропа", "bottle_bad")
    pt("Тара короба сиропа", "Короба сиропа", "carton_syrup")
    pt("Контейнер с таблетками", "Контейнеры", "pill_container")
    pt("Короб пустых блистеров", "Коробы блистеров", "box_blisters_empty")
    pt("Блистер", "Блистеры", "blister_base")
    pt("Блистер неполный", "Блистеры", "blister_defect")
    pt("Блистер годный", "Блистеры", "blister_ok")
    pt("Блистер брак", "Брак таблеток", "blister_bad")
    pt("Короб пустых упаковок", "Коробы упаковок", "box_packages_empty")
    pt("Упаковка", "Упаковки", "package")
    pt("Тара короба таблеток", "Короба таблеток", "carton_tabs")
    pt("Поддон", "Паллеты", "pallet")
    # короб сиропа: 36 бутылок 6×6 с шагом 66 мм
    T["Короб сиропа"] = define_assembly("Короб сиропа", ph_group("Короба сиропа"), [
        {"name": "Короб", "slots": [{"types": ["Тара короба сиропа"], "pos": [0, 0, 0, 0, 0, 0]}]},
        {"name": "Бутылки", "parent": "Короб",
         "slots": [{"types": ["Бутылка годная"], "pos": p} for p in ph_grid(6, 6, 66.0, 66.0, 5.0)]},
    ], T)
    # упаковка с таблетками: закрытая коробочка, внутри стопка из 5 блистеров (прикреплены)
    pt("Упаковка с таблетками", "Упаковки", "package_closed")
    # короб таблеток: 48 упаковок, слои по 10 (5 × 2), 205 мм — вдоль Y
    T["Короб таблеток"] = define_assembly("Короб таблеток", ph_group("Короба таблеток"), [
        {"name": "Короб", "slots": [{"types": ["Тара короба таблеток"], "pos": [0, 0, 0, 0, 0, 0]}]},
        {"name": "Упаковки", "parent": "Короб",
         "slots": [{"types": ["Упаковка с таблетками"], "pos": [p[0], p[1], p[2], 0, 0, 90]}
                   for p in ph_grid(5, 2, 76.0, 210.0, 5.0, nz=5, pz=32.0, limit=48)]},
    ], T)
    # паллета: низ — 6 коробов сиропа, верх — 6 коробов таблеток (3 × 2)
    T["Паллета"] = define_assembly("Паллета", ph_group("Паллеты"), [
        {"name": "Поддон", "slots": [{"types": ["Поддон"], "pos": [0, 0, 0, 0, 0, 0]}]},
        {"name": "Сироп", "parent": "Поддон",
         "slots": [{"types": ["Короб сиропа"], "pos": p, "order": 1} for p in ph_grid(3, 2, 400.0, 500.0, 143.0)]},
        {"name": "Таблетки", "parent": "Сироп",
         "slots": [{"types": ["Короб таблеток"], "pos": p, "order": 2} for p in ph_grid(3, 2, 400.0, 500.0, 278.0)]},
    ], T)
    # паллета сиропа: остаток коробов сиропа (коробов таблеток за смену меньше)
    T["Паллета сиропа"] = define_assembly("Паллета сиропа", ph_group("Паллеты"), [
        {"name": "Поддон", "slots": [{"types": ["Поддон"], "pos": [0, 0, 0, 0, 0, 0]}]},
        {"name": "Сироп низ", "parent": "Поддон",
         "slots": [{"types": ["Короб сиропа"], "pos": p, "order": 1} for p in ph_grid(3, 2, 400.0, 500.0, 143.0)]},
        {"name": "Сироп верх", "parent": "Сироп низ",
         "slots": [{"types": ["Короб сиропа"], "pos": p, "order": 2} for p in ph_grid(3, 2, 400.0, 500.0, 278.0)]},
    ], T)
    return T


# --- процедуры -----------------------------------------------------------------

def ph_counter(c, name, value=0):
    p = c.getProperty(name)
    if p is None:
        p = c.createProperty(VC_INTEGER, name)
    p.Value = value
    return p


def ph_unpack_routine(c, pid, item_type, count, out_container=None, pace_s=0.0):
    """Распаковка короба: принять короб, выдать count штук по одной и списать
    пустой короб. out_container — путь ленты (изделие ложится на ленту), иначе
    «следующему процессу» (забирает человек или робот)."""
    ph_counter(c, "Left", 0)
    r = clear_routine(c, pid)
    st = stats(c)
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Box",
         AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    stmt(r, "SetProperty", TargetProperty="Left", ValueExpression=str(count))
    w = r.addStatement("While")
    w.getProperty("Condition").Value = "Left > 0"
    sc = w.Scope
    stmt(sc, "CreateProduct", ProductType=item_type, ProductVariableName="P")
    stmt(sc, "SetStatisticsFlow", ProductVariableName="P", Statistics=st, FlowDirection="Leave")
    if out_container is not None:
        s = sc.addStatement("TransportOut")
        s.getProperty("ProductVariableName").Value = "P"
        s.getProperty("Container").Value = out_container
        s.getProperty("Destination").Value = "To Container"
    else:
        stmt(sc, "TransportOut", Destination="To Next Process", ProductVariableName="P")
    stmt(sc, "SetProperty", TargetProperty="Left", ValueExpression="Left - 1")
    if pace_s > 0:
        stmt(sc, "Delay", Delay=float(pace_s))
    stmt(r, "RemoveProduct", ProductVariableName="Box")
    return r


def ph_pack_routine(c, pid, asm, root, steps):
    """Пост укладки: создать тару (корневой шаг сборки), заказать изделия в гнёзда
    steps (их приносит робот), отдать заполненный короб/паллету дальше."""
    r = clear_routine(c, pid)
    st = stats(c)
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "CreateProduct", ProductType=asm, AssemblySteps=[asm_find_step(asm, root)],
         ProductVariableName="Box")
    stmt(r, "GetAssembly", AssemblyDataSource=1, Assembly=asm,
         AssemblySteps=[asm_find_step(asm, s) for s in steps], IncludeChildSteps=False,
         AssemblyVariableName="Box", ReturnVariableName="Order")
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    stmt(r, "TransportIn", Mode=1, Source="From Previous Process", AssemblyVariableName="Box",
         AssemblyOrderVariableName="Order", ProductVariableName="Parts", AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsState", State="Blocked", Statistics=st)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Box", Statistics=st, FlowDirection="Leave")
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="Box")
    return r


# --- участок сиропа (Линия 2) ----------------------------------------------------

def ph_line2(T, x0=22000.0, y0=10500.0, feed_len=4000.0, pace_s=2.6, pack_off=900.0):
    """Распаковка коробов → разлив → ОТК → укупорка → укладка 36 бутылок в короб.
    Буква П: подача на восток к разливочной машине, она разворачивает поток, и
    обратная ветка идёт на запад (поворотные конвейеры после машины встают —
    бутылки на втором повороте не едут). Возвращает имена узлов."""
    R = {}
    # Бутылки на ленту выдаёт «Устройство подачи» с тактом pace_s, а распаковка
    # держит короб 36 тактов и списывает пустой; скрипт включает подачу, только
    # пока на распаковке есть короб. Бутылки, созданные процессом (распаковкой),
    # после разливочной машины ОТК не принимает, а от «Устройства подачи» —
    # принимает; выкладка на входной путь поста вешает мост.
    f = load(PH_URI["feeder"])
    place(f, x0, y0, 0.0, 0.0)
    cr = beh(f, typ="rProductCreator")
    cr.SingleFeed.getProperty("Interval").Value = float(pace_s)
    cr.SingleFeed.Part = T["Бутылка"]
    f.Name = _b("Подача бутылок")
    R["feed"] = f.Name
    c0 = ph_conv(f, "OutInterface", feed_len, speed=200.0)
    u = ph_stand_node(x0 + 750.0, y0 + 900.0, "Распаковка бутылок", size=600.0, height=700.0)
    r = clear_routine(u, "Распаковка бутылок")
    st = stats(u)
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Box",
         AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    stmt(r, "Delay", Delay=36.0 * pace_s)
    stmt(r, "RemoveProduct", ProductVariableName="Box")
    ph_gate(f, u)
    R["unpack"] = u.Name
    buf = ph_stand_node(x0 + 600.0, y0 + 2000.0, "Буфер коробов бутылок", size=600.0, height=700.0)
    buffer_routine(buf, "Буфер коробов бутылок")
    R["buffer"] = buf.Name
    # разливочная машина: высота бутылки 112 мм, брак 5 %
    fill = load(PH_URI["filler"])
    snap(c0, "OutInterface", fill, "OneToOneInterface")
    set_prop(fill, "BottleHeight", 112.0)
    set_prop(fill, "Process::DefectRate", 0.05)
    R["filler"] = fill.Name
    # обратная ветка на запад
    c = ph_conv(fill, "OneToOneInterface_2", 1500.0, speed=200.0)
    qc = ph_qc(c, "OutInterface", "ОТК бутылок", T["Бутылка годная"], T["Бутылка брак"])
    R["qc"] = qc.Name
    c = ph_conv(qc, "OutInterface", 1500.0, speed=200.0)
    cap = load(PH_URI["capper"])
    snap(c, "OutInterface", cap, "InInterface")
    set_prop(cap, "BottleHeight", 112.0)
    set_prop(cap, "Process::DefectRate", 0.0)
    R["capper"] = cap.Name
    c = ph_conv(cap, "OutInterface", 6000.0, speed=200.0)
    pick = ph_pick_end(c, "OutInterface", "Съём бутылок")
    R["pick"] = pick.Name
    # робот брака у ОТК — с южной стороны (левой по ходу на запад; север занят подачей)
    p, d, n = ph_axes(qc, "InInterface", "OutInterface")
    rx, ry = ph_at(p, d, n, 0.0, 1200.0)
    tc, rb = ph_robot(rx, ry, ph_face(rx, ry, p[0], p[1]), name="брака сиропа")
    bx, by = ph_at(p, d, n, 1100.0, 1200.0)
    binn = ph_stand_node(bx, by, "Утилизация сиропа", size=600.0, height=700.0,
                         rgb=[0.8, 0.1, 0.1], title="Изолятор брака")
    ph_sink(binn, "Утилизация сиропа", delay_s=0.2)
    R["qc_tc"], R["bin"] = tc.Name, binn.Name
    _, d2, n2 = ph_axes(c, "InInterface", "OutInterface")
    R.update(ph_pack_cell(T, pick, d2, n2, "Короб сиропа", "Короб", ["Бутылки"], "Упаковка сиропа",
                          "Отправка коробов сиропа", "укладки сиропа", pack_off))
    return R


def ph_pack_cell(T, pick, d, n, asm, root, steps, pid, send_pid, robot_title, off=900.0, cells=2,
                 send_side=-1.0):
    """Укладка в тару двумя роботами: роботы по сторонам от съёма с ленты, у
    каждого свой пост с коробом; отправка коробов — прямо по ходу ленты, её
    достают оба. Быстрый робот (ABB IRB 1300, 1,4 м) вплотную: скорость роботов
    менять запрещено, поэтому темп — числом роботов и короткими перемещениями."""
    p = ph_xy(pick, "InInterface")
    out = {"posts": [], "tcs": []}
    sx, sy = ph_at(p, d, n, off, 0.0)
    # лента коробов уходит вбок от линии: send_side=-1 — в сторону -n, +1 — в сторону n
    send = ph_place_node("place", sx, sy, _ph_math.degrees(_ph_math.atan2(send_side * n[1], send_side * n[0])),
                         send_pid)
    out["send"] = send.Name
    for k in range(cells):
        side = -send_side if k == 0 else send_side
        rx, ry = ph_at(p, d, n, 0.0, side * off)
        tc, rb = ph_robot(rx, ry, ph_face(rx, ry, p[0], p[1]), uri=PH_URI["robot_fast"],
                          name="%s %d" % (robot_title, k + 1))
        bx, by = ph_at((rx, ry), d, n, 0.0, side * off)
        box = ph_stand_node(bx, by, "%s %d" % (pid, k + 1), size=700.0, height=600.0)
        ph_pack_routine(box, "%s %d" % (pid, k + 1), T[asm], root, steps)
        out["posts"].append(box.Name)
        out["tcs"].append(tc.Name)
    return out


# --- участок таблеток (Линия 1) --------------------------------------------------

def ph_blister_machine_routine(m, T, cycle_s=1.6, per_blister=10, defect=0.05, stream=7):
    """Станок упаковки таблеток в блистеры. Запасы — в свойствах станка:
    Tablets (таблетки) и Blisters (пустые блистеры). Таблеток меньше, чем на
    блистер, — станок останавливается и ждёт контейнер (5000 шт.); кончились
    блистеры — ждёт короб (48 шт.). Брак 5 %: блистер без части таблеток."""
    ph_counter(m, "Tablets", 0)
    ph_counter(m, "Blisters", 0)
    r = clear_routine(m, "Блистерная машина")
    st = stats(m)
    s = r.addStatement("IfElse")
    s.getProperty("Condition").Value = "Tablets < %d" % per_blister
    stmt(s.ThenScope, "Print", Message='"Нет таблеток: станок остановлен до подачи контейнера"')
    ti = stmt(s.ThenScope, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="C",
              AcceptAllProductTypes=False)
    ti.getProperty("AcceptedProductTypes").Value = [T["Контейнер с таблетками"]]
    stmt(s.ThenScope, "SetProperty", TargetProperty="Tablets", ValueExpression="Tablets + 5000")
    stmt(s.ThenScope, "RemoveProduct", ProductVariableName="C")
    s = r.addStatement("IfElse")
    s.getProperty("Condition").Value = "Blisters < 1"
    ti = stmt(s.ThenScope, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="E",
              AcceptAllProductTypes=False)
    ti.getProperty("AcceptedProductTypes").Value = [T["Короб пустых блистеров"]]
    stmt(s.ThenScope, "SetProperty", TargetProperty="Blisters", ValueExpression="Blisters + 48")
    stmt(s.ThenScope, "RemoveProduct", ProductVariableName="E")
    # состояния статистики у туннеля не задаём: «Idle» у него недопустимо и останавливает симуляцию
    stmt(r, "Delay", Delay=float(cycle_s))
    stmt(r, "SetProperty", TargetProperty="Tablets", ValueExpression="Tablets - %d" % per_blister)
    stmt(r, "SetProperty", TargetProperty="Blisters", ValueExpression="Blisters - 1")
    cont = beh(m, "Container__HIDE__")
    s = r.addStatement("IfElse")
    s.getProperty("Condition").Value = "uniform(%d, 0.0, 1.0) < %.3f" % (stream, defect)
    stmt(s.ThenScope, "CreateProduct", ProductType=T["Блистер неполный"], ProductVariableName="B", Container=cont)
    stmt(s.ElseScope, "CreateProduct", ProductType=T["Блистер"], ProductVariableName="B", Container=cont)
    stmt(r, "SetStatisticsFlow", ProductVariableName="B", Statistics=st, FlowDirection="Leave")
    so = r.addStatement("TransportOut")
    so.getProperty("ProductVariableName").Value = "B"
    so.getProperty("Container").Value = beh(m, "path2__HIDE__")
    so.getProperty("Destination").Value = "To Container"
    return r


def ph_fix_human(h):
    """Починка скрипта оператора: путь нулевой длины (оператор уже на месте)
    даёт пустой список отрезков, и int('') роняет скрипт — человек «умирает»,
    участок встаёт. Пустой путь заменяем прямым (как при «путь не найден»)."""
    sc = h.findBehaviour("ResourceScript")
    src = sc.Script
    old = "    if path_data:\n      path = travel_controller._create_path_from_schema(path_data, velocity)"
    new = "    if path_data and path_data[PathSchema.LINKS]:\n      path = travel_controller._create_path_from_schema(path_data, velocity)"
    for nl in ("\n", "\r\n"):
        o, n = old.replace("\n", nl), new.replace("\n", nl)
        if o in src:
            sc.Script = src.replace(o, n)
            return True
    return False


def ph_manual_routine(c, pid, T, worker, work_s):
    """Пост ручной сборки: человек приносит пустую упаковку и стопку из 5
    блистеров, вкладывает стопку (6 с на блистер = 30 с), упаковка закрыта."""
    r = clear_routine(c, pid)
    st = stats(c)
    res = frame(c, "ResourceLocation")
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    ti = stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Pk",
              AcceptAllProductTypes=False)
    ti.getProperty("AcceptedProductTypes").Value = [T["Упаковка"]]
    ti = stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="S",
              AcceptAllProductTypes=False)
    ti.getProperty("AcceptedProductTypes").Value = [T["Блистер годный"]]
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Pk", Statistics=st, FlowDirection="Enter")
    stmt(r, "Work", Controller=beh(worker, "TC"), TimeSource=0, ProcessTime=float(work_s),
         ProcessTimeExpression=str(work_s), ResourcePositionFrame=res)
    stmt(r, "AttachProduct", Parent="Pk", Child="S")
    stmt(r, "ChangeProductType", ProductVariableName="Pk", NewType=T["Упаковка с таблетками"], DeleteAttached=False)
    stmt(r, "SetStatisticsState", State="Blocked", Statistics=st)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Pk", Statistics=st, FlowDirection="Leave")
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="Pk")
    return r


def ph_line1(T, xm=38000.0, ym=29000.0, stations=7, st_y=26000.0, st_x0=20000.0, st_dx=2200.0,
             work_s=30.0):
    """Блистерная машина (поток на запад) → ОТК → съём блистеров → ручная сборка
    упаковок (5 блистеров, 6 с на блистер) → лента упаковок → укладка 48 в короб."""
    R = {}
    m = load(PH_URI["tunnel"])
    place(m, xm, ym, 0.0, 180.0)
    set_process_id(m, "Блистерная машина")
    ph_blister_machine_routine(m, T)
    m.Name = _b("Блистерная машина")
    R["machine"] = m.Name
    mp = ph_xy(m, "In")
    b1 = ph_stand_node(mp[0] - 300.0, ym - 1600.0, "Буфер контейнеров", size=600.0, height=500.0)
    buffer_routine(b1, "Буфер контейнеров")
    b2 = ph_stand_node(mp[0] - 1300.0, ym - 1600.0, "Буфер коробов блистеров", size=600.0, height=700.0)
    buffer_routine(b2, "Буфер коробов блистеров")
    R["buf_cont"], R["buf_blist"] = b1.Name, b2.Name
    c = ph_conv(m, "Out", 1000.0, speed=200.0)
    qc = ph_qc(c, "OutInterface", "ОТК блистеров", T["Блистер годный"], T["Блистер брак"])
    R["qc"] = qc.Name
    # лента блистеров тянется на запад за ручной участок: стопки собираются у его
    # западного края, и люди не ходят к ленте между постами
    qx = ph_xy(qc, "OutInterface")[0]
    c = ph_conv(qc, "OutInterface", max(2500.0, qx - (st_x0 - 2500.0)), speed=200.0)
    pick = ph_pick_end(c, "OutInterface", "Съём блистеров")
    R["pick"] = pick.Name
    # робот брака — с северной стороны (юг — ручной участок)
    p, d, n = ph_axes(qc, "InInterface", "OutInterface")
    rx, ry = ph_at(p, d, n, 0.0, -1200.0)
    tc, rb = ph_robot(rx, ry, ph_face(rx, ry, p[0], p[1]), name="брака таблеток")
    bx, by = ph_at(p, d, n, 1100.0, -1200.0)
    binn = ph_stand_node(bx, by, "Утилизация блистеров", size=600.0, height=700.0,
                         rgb=[0.8, 0.1, 0.1], title="Изолятор брака")
    ph_sink(binn, "Утилизация блистеров", delay_s=0.2)
    R["qc_tc"], R["bin"] = tc.Name, binn.Name
    # Ручная сборка. У каждого поста свой оператор со своим ТК, а рядом со столом —
    # свой лоток стопок (слева) и свой лоток упаковок (справа). Раздачу по лоткам и
    # уборку готовой упаковки на ленту делает системный транспорт, так что у
    # людей нет общих точек. Иначе: у одной точки двое — «Unable to solve path»;
    # шаг «любой пост» с общим источником выбирает связь по группе, и оператор 1
    # несёт упаковку на пост 2.
    posts, htcs, stacks, trays = [], [], [], []
    for k in range(stations):
        x = st_x0 + st_dx * k
        s = ph_stand_node(x, st_y, "Сборка упаковок %d" % (k + 1), size=700.0, height=800.0)
        set_prop(s, "ResourceOffset", mat(0.0, -1200.0, 0.0, 90.0))
        stk = ph_stand_node(x - 650.0, st_y, "Стопка блистеров %d" % (k + 1), size=450.0, height=800.0)
        set_prop(stk, "ResourceOffset", mat(0.0, -1200.0, 0.0, 90.0))
        r = clear_routine(stk, "Стопка блистеров %d" % (k + 1))
        stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="S",
             AcceptAllProductTypes=True)
        for j in range(4):
            stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="B",
                 AcceptAllProductTypes=True)
            stmt(r, "AttachProduct", Parent="S", Child="B")
        stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="S")
        tr = ph_stand_node(x + 650.0, st_y, "Лоток упаковок %d" % (k + 1), size=450.0, height=800.0)
        set_prop(tr, "ResourceOffset", mat(0.0, -1200.0, 0.0, 90.0))
        buffer_routine(tr, "Лоток упаковок %d" % (k + 1))
        htc = load(PH_URI["human_tc"])
        place(htc, x, st_y - 4300.0)
        for nm, v in (("LinkDefaults::PickTime", 2.0), ("LinkDefaults::PlaceTime", 2.0), ("UseGlobalArea", False)):
            pp = htc.getProperty(nm)
            if pp is not None:
                pp.Value = v
        htc.Name = _b("ТК человека %d" % (k + 1))
        ph_manual_routine(s, "Сборка упаковок %d" % (k + 1), T, htc, float(work_s))
        h = load(PH_URI["man" if k % 2 == 0 else "woman"])
        place(h, x + 500.0, st_y - 3200.0, 0.0, 90.0)
        ph_fix_human(h)
        i_ = load(PH_URI["idle"])
        place(i_, x, st_y - 3200.0, 0.0, 90.0)
        connect_people(htc, [h], [i_])
        posts.append(s.Name)
        htcs.append(htc.Name)
        stacks.append(stk.Name)
        trays.append(tr.Name)
    R["human_tcs"], R["stations"], R["stacks"], R["trays"] = htcs, posts, stacks, trays
    # распаковка коробов пустых упаковок — у восточного края ручного участка
    ux = st_x0 + st_dx * stations + 800.0
    up = ph_stand_node(ux, st_y, "Распаковка упаковок", size=700.0, height=800.0)
    set_prop(up, "ResourceOffset", mat(0.0, -1200.0, 0.0, 90.0))
    ph_unpack_routine(up, "Распаковка упаковок", T["Упаковка"], 48, None, 0.0)
    b3 = ph_stand_node(ux + 1300.0, st_y - 1200.0, "Буфер коробов упаковок", size=600.0, height=700.0)
    buffer_routine(b3, "Буфер коробов упаковок")
    R["unpack"], R["buf_pack"] = up.Name, b3.Name
    # лента упаковок на запад: укладка готовых упаковок к западу от постов
    lx, ly = st_x0 - 2000.0, st_y - 2000.0
    lay = ph_place_node("place", lx, ly, 180.0, "Укладка упаковок")
    ph_res_offset(lay, -1200.0)
    R["lay"] = lay.Name
    c = ph_conv(lay, "OutInterface", 3000.0, speed=200.0)
    pk = ph_pick_end(c, "OutInterface", "Съём упаковок")
    R["pick_pack"] = pk.Name
    _, d2, n2 = ph_axes(c, "InInterface", "OutInterface")
    cell = ph_pack_cell(T, pk, d2, n2, "Короб таблеток", "Короб", ["Упаковки"], "Укладка в короб таблеток",
                        "Отправка коробов таблеток", "укладки таблеток", 900.0, cells=1, send_side=1.0)
    R["pack_posts"], R["pack_tcs"], R["send"] = cell["posts"], cell["tcs"], cell["send"]
    c = ph_conv(comp(cell["send"]), "OutInterface", 2500.0, speed=200.0)
    out = ph_pick_end(c, "OutInterface", "Приём коробов таблеток")
    R["out"] = out.Name
    return R


def ph_area(x0, y0, x1, y1, tcs, name=None):
    """Зона прохода на участок и подключение к ней транспортных контроллеров."""
    a = load(PH_URI["pathway"])
    place(a, (x0 + x1) / 2.0, (y0 + y1) / 2.0)
    set_prop(a, "AreaLength", float(x1 - x0))
    set_prop(a, "AreaWidth", float(y1 - y0))
    if name:
        a.Name = _b(name)
    for tc in tcs:
        beh(tc, "Pathways").connect(beh(a, "Зона Прохода"))
        p = tc.getProperty("UseGlobalArea")
        if p is not None:
            p.Value = False
    return a

def ph_link(src, dst, impl, group, pick=None, place=None, time_s=None):
    """Транспортная связь; pick/place — смещение места, где встаёт человек при
    взятии/укладке (вектор (x, y, z)): несколько людей у одной точки иначе
    мешают друг другу («Unable to solve path»). time_s — время системной
    переброски (InterpolatingTransport, по умолчанию 10 с)."""
    ts = pc().TransportSystem
    n0 = ts.Links.size() if hasattr(ts.Links, "size") else len(ts.Links)
    link(src, dst, impl, group)
    links = ts.Links
    l = links[len(links) - 1] if not hasattr(links, "get") else links.get(links.size() - 1)
    if pick is not None or place is not None:
        l.getProperty("UseCustomParameters").Value = True
        if pick is not None:
            l.getProperty("ResourcePickOffset").Value = vcVector.new(*pick)
        if place is not None:
            l.getProperty("ResourcePlaceOffset").Value = vcVector.new(*place)
    if time_s is not None:
        p = l.getProperty("TransportTime")
        if p is not None:
            p.Value = float(time_s)
    return l
