# -*- coding: utf-8 -*-
"""
«Руки» агента: функции, которые выполняются ВНУТРИ R-Pro (Python 2.7).

Этот файл агент не импортирует: line_builder.py читает его текстом и
отправляет через мост вместе с кодом каждого шага. Поэтому здесь только
то, что понимает встроенный Python программы.

Что пришлось выяснить на живой программе:
- app.load() иногда бросает SystemError, хотя компонент загрузился
  (так ведёт себя «ТК робота»): новое ищем по разнице со сценой;
- компоненты МП (конвейеры, контроллеры) не дают себя переименовать —
  тоже SystemError. Имена даёт сама программа («Конвейер #7»), они
  уникальны, по ним и ведём учёт;
- стыковка interface.connect() не двигает компонент: сначала ставим его
  так, чтобы кадр его интерфейса лёг на кадр партнёра, потом соединяем —
  ровно это делает кнопка PnP;
- интерфейс робота у «ТК робота» лежит не в корне, а в узле Link1, так что
  поведения ищем во всех узлах;
- маршрут деталей хранится в FlowTable2 (шаги с группами процессов),
  старая FlowTable этой версией не читается;
- у объектов API нет __class__, а getattr(o, a, None) не ловит их
  исключения: отсюда _safe().
"""
import vcMatrix
import vcVector
from vcCommand import *


def _safe(o, a):
    """getattr без исключений. У объектов R-Pro неудачный getattr иногда не
    бросает исключение сразу, а оставляет его «висеть» до следующей операции,
    проверяющей ошибку. Пустой цикл — такая операция: зависшая ошибка всплывает
    здесь, внутри try, а не строкой ниже у вызывающего."""
    try:
        v = getattr(o, a)
        for _ in ():
            pass
        return v
    except Exception:
        return None


def _u(x):
    """Строки из агента приходят байтами (UTF-8), из программы — юникодом.
    Кириллицу между ними сравнивать только после приведения к юникоду."""
    return x.decode("utf-8") if type(x) is str else x


def _is_str(x):
    """Строка ли это. Никаких isinstance(): на объекте R-Pro он лезет в
    __class__, получает исключение — и даже пойманное, оно оставляет
    «висящую» ошибку, которая всплывает на СЛЕДУЮЩЕЙ операции с ложным
    номером строки. type() в __class__ не лезет."""
    return type(x) in (str, unicode)


def _b(x):
    """Для записи в свойства R-Pro: сеттеры принимают байтовую строку UTF-8,
    а юникод с кириллицей отвергают невнятной SystemError."""
    return _u(x).encode("utf-8")


# --- компоненты ---------------------------------------------------------------

def comp(name):
    c = app.findComponent(name)
    if c is None:
        raise ValueError(u"нет компонента «%s»" % name)
    return c


def load(uri, name=None):
    before = set(c.Name for c in app.Components)
    try:
        app.load(uri)
    except SystemError:
        pass
    new = [c for c in app.Components if c.Name not in before]
    if not new:
        raise ValueError(u"не загрузилось: %s" % uri)
    top = [c for c in new if _safe(_safe(c, "Parent"), "Name") in ("ROOT", None)] or new
    c = top[0]
    if name:
        rename(c, name)
    return c


def rename(c, name):
    try:
        c.Name = name
        return True
    except SystemError:
        return False


def set_prop(c, name, value):
    p = c.getProperty(name)
    if p is None:
        raise ValueError(u"у «%s» нет свойства %s" % (c.Name, name))
    p.Value = value
    return p.Value


# --- матрицы ------------------------------------------------------------------

def mat(x=0.0, y=0.0, z=0.0, rz=0.0):
    m = vcMatrix.new()
    m.translateAbs(x, y, z)
    m.rotateRelZ(rz)
    return m


def m2l(m):
    p = m.P
    return [round(p.X, 1), round(p.Y, 1), round(p.Z, 1), round(m.WPR.Z, 1)]


def l2m(l):
    return mat(l[0], l[1], l[2], l[3] if len(l) > 3 else 0.0)


def place(c, x, y, z=0.0, rz=0.0):
    c.PositionMatrix = mat(x, y, z, rz)
    return m2l(c.PositionMatrix)


# --- узлы, поведения, интерфейсы ---------------------------------------------

def nodes(n):
    yield n
    for ch in (_safe(n, "Children") or []):
        # дочерний компонент (робот на контроллере) — не наш узел: у него есть Uri
        if _safe(ch, "Uri") is None:
            for x in nodes(ch):
                yield x


def behaviours(c):
    for n in nodes(c):
        for b in (_safe(n, "Behaviours") or []):
            yield n, b


def beh(c, name=None, typ=None):
    for n, b in behaviours(c):
        if (name is None or b.Name == name) and (typ is None or b.Type == typ):
            return b
    raise ValueError(u"у «%s» нет поведения %s" % (c.Name, name or typ))


def find_feature(c, name):
    """Элемент (например, кадр ResourceLocation) по имени — во всех узлах."""
    def walk(f):
        for ch in (_safe(f, "Children") or []):
            if ch.Name == name:
                return ch
            got = walk(ch)
            if got is not None:
                return got
        return None
    for n in nodes(c):
        got = walk(_safe(n, "RootFeature"))
        if got is not None:
            return got
    return None


def face_to(c, frame_name, tx, ty, gap, heading=90.0, z=0.0):
    """Поставить c лицом к точке (tx, ty) — роботу.

    frame_name — обычно ResourceLocation: место, откуда обслуживают станок.
    Ось X этого кадра смотрит от обслуживающего на станок (у станков
    каталога кадр повёрнут на 90°, у Mapvision — на 0°, у Colchester он ещё
    и сдвинут вбок). Поэтому разворачиваем по повороту кадра, а не по
    направлению на него: ось X кадра должна смотреть в мире на heading
    (90° = +Y, от ленты к станку), а сам кадр — стоять в gap от робота."""
    import math
    place(c, 0, 0)
    f = find_feature(c, frame_name)
    h = math.radians(heading)
    ux, uy = math.cos(h), math.sin(h)
    if f is None:
        place(c, tx + ux * (gap + 800.0), ty + uy * (gap + 800.0), z, heading - 90.0)
        return m2l(c.PositionMatrix)
    m = f.NodePositionMatrix
    rz = heading - m.WPR.Z
    lx, ly = m.P.X, m.P.Y
    a = math.radians(rz)
    wx = lx * math.cos(a) - ly * math.sin(a)     # кадр после поворота станка
    wy = lx * math.sin(a) + ly * math.cos(a)
    # кадр должен встать в gap от робота по направлению heading
    place(c, tx + ux * gap - wx, ty + uy * gap - wy, z, rz)
    return m2l(c.PositionMatrix)


def frame_world(c, if_name, section=0):
    """Мировая матрица кадра интерфейса (компонент стоит в корне сцены)."""
    f = beh(c, if_name).Sections[section].Frame
    return c.PositionMatrix * f.NodePositionMatrix


def put_frame_at(c, if_name, target, section=0):
    """Поставить c так, чтобы кадр его интерфейса if_name совпал с target."""
    f = beh(c, if_name).Sections[section].Frame
    inv = vcMatrix.new(f.NodePositionMatrix)
    inv.invert()
    c.PositionMatrix = target * inv
    return m2l(c.PositionMatrix)


def snap(a, a_if, b, b_if):
    """PnP: поставить b кадром b_if на кадр a_if у a и состыковать."""
    put_frame_at(b, b_if, frame_world(a, a_if))
    ok = beh(a, a_if).connect(beh(b, b_if))
    return bool(ok)


def ahead(m, dist):
    """Матрица, сдвинутая вперёд по своей оси X на dist."""
    r = vcMatrix.new(m)
    r.translateRel(dist, 0.0, 0.0)
    return r


# --- роботы -------------------------------------------------------------------

def mount_robot(tc, robot):
    """Посадить робота на «ТК робота»: интерфейс RobotPnP ↔ RobotPositioner."""
    return bool(beh(tc, "RobotPnP").connect(beh(robot, "RobotPositioner")))


# --- моделирование процессов --------------------------------------------------

def pc():
    return app.Simulation.ProcessController


def routine(c):
    """Процедура процесса компонента (не Main)."""
    ex = beh(c, typ="rProcessExecutor")
    for r in ex.Program.Routines:
        if r.Name != "Main":
            return r
    raise ValueError(u"у «%s» нет процесса" % c.Name)


def doors_wait_robot(c, seconds=2.5):
    """Станок с дверями закрывает их только после того, как робот вышел.

    У Mapvision Quality Gate створки (MoveJoint) идут сразу за TransportIn:
    робот отпускает деталь — и дверь едет сквозь его руку (замер 08.10: рука
    в камере ещё 1,9 с, из них секунду ТК ждёт AutoHoming::Delay). У Haas пауза
    перед дверью уже есть — их не трогаем. Повторный вызов ничего не меняет."""
    try:
        r = routine(c)
    except Exception:
        return False
    types = [_u(str(s.Type)) for s in r.Statements]
    if u"TransportIn" not in types:
        return False
    i = types.index(u"TransportIn") + 1
    while i < len(types) and types[i] == u"SetStatisticsState":
        i += 1
    if i >= len(types) or types[i] != u"MoveJoint":
        return False
    d = r.addStatement("Delay", i)
    d.getProperty("Delay").Value = float(seconds)
    d.getProperty("Name").Value = _b(u"Робот выходит из камеры")
    return True


def set_process_id(c, pid):
    """Уникальное имя процесса: «Л1 Съём 3». Иначе все «С конвейера»
    сливаются в одну группу, и маршрут не различит станции.

    Атрибут Name у процедуры только для чтения, но у неё есть одноимённое
    СВОЙСТВО — его смена переименовывает только эту реализацию. (Раньше
    переименовывали группу целиком — и вторая линия с теми же именами
    сливалась с первой: 27 процессов на две линии.)
    """
    r = routine(c)
    if _u(r.Name) == _u(pid):
        return r.Name
    r.getProperty("Name").Value = _b(pid)
    return r.Name


def group_by_name(name):
    for g in pc().FlowGroupManager.Groups:
        if _u(g.Name) == _u(name):
            return g
    return None


def new_line_group(feeder, line_name, type_name, uri=None):
    """Своя группа деталей и свой тип детали для линии: иначе маршрут второй
    линии записывается поверх маршрута первой. Генератор подачи переводится
    на новый тип."""
    fm = pc().FlowGroupManager
    g = group_by_name(line_name)
    if g is None:
        g = fm.createGroup(_b(line_name))
    cr = beh(feeder, typ="rProductCreator")
    old = cr.SingleFeed.Part
    ptm = pc().ProductTypeManager
    t = ptm.findProductType(_b(type_name))
    if t is None:
        t = ptm.createProductType(_b(type_name), g, False)
    t.ComponentUri = _b(uri) if uri else old.ComponentUri
    cr.SingleFeed.Part = t
    return {"group": g.Name, "type": t.Name}


def flow_group():
    groups = pc().FlowGroupManager.Groups
    if not groups:
        raise ValueError(u"нет группы процессов: сначала поставьте устройство подачи")
    return groups[0]


def set_flow(pids, group=None):
    """Маршрут деталей группы: шаги по порядку, в каждом — один процесс или
    список процессов-альтернатив (деталь идёт в любой свободный из них).
    group — объект группы или её имя («Линия 2»)."""
    if _is_str(group):
        group = group_by_name(group)
    # «group or …» нельзя: проверка истинности объекта R-Pro бросает исключение
    g = group if group is not None else flow_group()
    ft = pc().FlowTable2
    seq = ft.getSequence(g)
    if seq is None:
        seq = ft.createSequence(g)
    seq.FlowSteps.clear()
    pm = pc().ProcessManager
    missing = []
    for i in range(len(pids)):
        alts = [pids[i]] if _is_str(pids[i]) else list(pids[i])
        found = []
        for a in alts:
            pg = pm.findProcessGroup(_u(a))
            if pg is None:
                missing.append(_u(a))
            else:
                found.append(pg)
        if not found:
            continue
        st = seq.FlowSteps.insert()
        for pg in found:
            st.Groups.insert(st.Groups.size(), pg)
    return {"steps": seq.FlowSteps.size(), "missing": missing}


def link(src, dst, implementer, group=None):
    """Транспортная связь src → dst. implementer — «ТК робота» (компонент)
    или имя системного контроллера (ConveyorTransport, InterpolatingTransport)."""
    ts = pc().TransportSystem
    if _is_str(implementer):
        impl = [x for x in ts.Controllers if _safe(x, "Name") == implementer][0]
    else:
        impl = beh(implementer, "TC")
    if _is_str(group):
        group = group_by_name(group)
    ts.createTransportLink(beh(src, typ="rTransportNode"), beh(dst, typ="rTransportNode"),
                           impl, group if group is not None else flow_group())
    return True


def clear_links():
    ts = pc().TransportSystem
    for l in list(ts.Links):
        ts.deleteTransportLink(l)


# --- сборка изделия из деталей -------------------------------------------------
# Тип продукта «Сборка» — дерево шагов (блок → коленвал → поршни …). У шага
# шаблон с гнёздами: в гнезде позиция детали относительно сборки и какие
# типы деталей в него принимаются. На посту «Транспорт В» в режиме «сборка»
# заказывает детали в пустые гнёзда выбранных шагов, и робот или человек
# кладёт каждую ровно в её гнездо. Двигатель едет дальше уже собранным на шаг.

def wpr_mat(x=0.0, y=0.0, z=0.0, w=0.0, p=0.0, r=0.0):
    """Матрица из положения и углов W, P, R (как в свойствах R-Pro)."""
    m = vcMatrix.new()
    m.setWPR(w, p, r)
    m.translateAbs(x, y, z)
    return m


def part_type(name, group, uri):
    """Тип детали с видом из файла модели. Уже есть — обновить вид."""
    ptm = pc().ProductTypeManager
    t = ptm.findProductType(_b(name))
    if t is None:
        t = ptm.createProductType(_b(name), group, False)
    t.ComponentUri = _b(uri)
    return t


def assembly_type(name, group):
    """Тип продукта «Сборка» (третий аргумент createProductType — сборка ли)."""
    ptm = pc().ProductTypeManager
    t = ptm.findProductType(_b(name))
    if t is None:
        t = ptm.createProductType(_b(name), group, True)
    return t


def asm_pattern(step, name):
    """Шаблон гнёзд шага: у нового шага его нет, создаёт менеджер шаблонов."""
    p = _safe(step, "Pattern")
    if p is None:
        p = pc().AssemblyPatternManager.createPattern(_b(name))
        step.Pattern = p
    return step.Pattern


def asm_step(t, parent, name):
    """Шаг сборки под parent (None — корневой шаг типа)."""
    if parent is None:
        s = t.RootStep
    else:
        s = t.createStepTo(parent, len(parent.ChildSteps))
    s.Name = _b(name)
    asm_pattern(s, u"%s: %s" % (_u(t.Name), _u(name)))
    return s


def asm_slot(step, accepted, pos, order=1, default=None):
    """Гнездо шага: pos = [x, y, z, w, p, r] относительно сборки,
    accepted — список типов деталей, которые сюда кладут."""
    sl = step.Pattern.createSlot()
    sl.OrderIndex = order
    sl.Position = wpr_mat(*pos)
    it = sl.Item
    it.AcceptAllProductTypes = False
    it.AcceptedProductTypes = accepted
    if default is not None:
        it.DefaultProductType = default
    return sl


def define_assembly(type_name, group, steps, T):
    """Тип «Сборка» по описанию шагов: [{name, parent, rel, slots: [{types,
    pos, order}]}], T — типы деталей по имени. Если тип уже описан (узел общий
    для двух участков в одной сцене) — не трогаем: шаги задвоились бы, а
    шаблон гнёзд с тем же именем R-Pro создать не даст."""
    t = pc().ProductTypeManager.findProductType(_b(type_name))
    if t is not None and _safe(t, "IsAssembly") and len(t.RootStep.ChildSteps) > 0:
        return t
    A = assembly_type(type_name, group)
    S = {}
    for st in steps:
        parent = None if st.get("parent") is None else S[_u(st["parent"])]
        S[_u(st["name"])] = asm_step(A, parent, st["name"])
        rel = st.get("rel")
        if rel and any(abs(v) > 1e-6 for v in rel):
            S[_u(st["name"])].getProperty("RelativePosition").Value = wpr_mat(*rel)
        for sl in st["slots"]:
            acc = [T[_u(x)] for x in sl["types"]]
            asm_slot(S[_u(st["name"])], acc, sl["pos"], int(sl.get("order", 1)),
                     acc[0] if acc and not _safe(acc[0], "IsAssembly") else None)
    return A


def asm_find_step(t, name):
    def walk(s):
        if _u(s.Name) == _u(name):
            return s
        for ch in s.ChildSteps:
            got = walk(ch)
            if got is not None:
                return got
        return None
    return walk(t.RootStep)


def mat_list(m):
    """Матрица → [x, y, z, W, P, R] (обратно — wpr_mat)."""
    p, w = m.P, m.getWPR()
    return [round(p.X, 2), round(p.Y, 2), round(p.Z, 2), round(w.X, 2), round(w.Y, 2), round(w.Z, 2)]


def asm_tree(t):
    """Тип «Сборка» → список шагов в порядке обхода: имя, родитель, положение
    шага, гнёзда (позиция, порядок, какие типы принимает). Так набор изделия
    снимается с любой планировки, где сборка уже описана."""
    out = []

    def walk(s, parent):
        rel = s.getProperty("RelativePosition")
        slots = []
        pat = _safe(s, "Pattern")
        if pat is not None:
            for sl in pat.Slots:
                it = sl.Item
                acc = [_u(x.Name) for x in it.AcceptedProductTypes]
                dflt = _safe(it, "DefaultProductType")
                if not acc and dflt is not None:
                    acc = [_u(dflt.Name)]
                slots.append({"types": acc, "pos": mat_list(sl.Position), "order": sl.OrderIndex})
        out.append({"name": _u(s.Name), "parent": parent,
                    "rel": mat_list(rel.Value) if rel is not None else None, "slots": slots})
        for ch in s.ChildSteps:
            walk(ch, _u(s.Name))
    walk(t.RootStep, None)
    return out


def compose_slot(product, move, sub):
    """Место узла в изделии: product · move · sub⁻¹ (все — [x, y, z, W, P, R]).

    product — как CAD изделия ставится в его систему (сдвиг на ленту, поворот),
    move — где узел стоит в CAD изделия относительно своего CAD-положения
    (поворот вокруг начала CAD, затем сдвиг), sub — как CAD узла ставится в
    систему узла. Считаем матрицами самой R-Pro, чтобы не разойтись с её
    соглашением об углах W, P, R."""
    inv = wpr_mat(*sub)
    inv.invert()
    return mat_list(wpr_mat(*product) * wpr_mat(*move) * inv)


def import_part(cad_path, out_path, color=None, rgb=None):
    """Деталь заказчика из CAD-файла (STEP, STL, IGES, OBJ, glTF…) — моделью R-Pro.

    app.load импортирует файл как компонент; геометрия остаётся в координатах
    CAD (начало компонента — начало CAD). Возвращает центр и полугабарит в этих
    координатах — по ним строитель положения деталей в сборке и сам масштаб."""
    c = load(_b(cad_path))
    # Габарит — по контейнерам геометрии. Габарит компонента не годится: в
    # него входит кадр крепления в начале координат, а деталь, выгруженная из
    # сборки, лежит от начала за сотни миллиметров.
    lo, hi = [1e18] * 3, [-1e18] * 3

    def walk(f):
        for ch in (_safe(f, "Children") or []):
            geo = _safe(ch, "Geometry")
            bc = _safe(geo, "BoundCenter") if geo is not None else None
            bd = _safe(geo, "BoundDiagonal") if geo is not None else None
            if bc is not None and bd is not None:
                for a, (cv, dv) in enumerate(((bc.X, bd.X), (bc.Y, bd.Y), (bc.Z, bd.Z))):
                    lo[a] = min(lo[a], cv - abs(dv))
                    hi[a] = max(hi[a], cv + abs(dv))
            walk(ch)
    for n in nodes(c):
        walk(_safe(n, "RootFeature"))
    painted = paint(c, color, rgb) if color and rgb else False
    c.save(_b(u"file:///" + _u(out_path).replace(u"\\", u"/")))
    app.deleteComponent(c)
    if lo[0] > hi[0]:
        return {"center": [0.0, 0.0, 0.0], "half": [0.0, 0.0, 0.0], "painted": painted}
    return {"center": [(lo[a] + hi[a]) / 2.0 for a in range(3)],
            "half": [(hi[a] - lo[a]) / 2.0 for a in range(3)], "painted": painted}


def save_template(ptype, path):
    """Шаблон детали типа ptype — отдельной моделью в path. Шаблон грузится
    прямо по адресу типа («планировка.rpro#якорь»). Возвращает габарит, мм."""
    c = load(ptype.ComponentUri)
    d = _safe(c, "BoundDiagonal")
    size = round(2.0 * max(abs(d.X), abs(d.Y), abs(d.Z)), 1) if d is not None else 0.0
    c.save(_b(u"file:///" + _u(path).replace(u"\\", u"/")))
    app.deleteComponent(c)
    return size


# --- процедура процесса из операторов ------------------------------------------

def frame(c, name):
    f = find_feature(c, name)
    if f is None:
        raise ValueError(u"у «%s» нет кадра %s" % (c.Name, name))
    return f


_STMT_FIRST = ("Mode", "Source", "Destination", "AssemblyDataSource", "Assembly",
               "ProductType", "TimeSource", "Statistics")


def stmt(r, typ, **props):
    """Добавить оператор в конец процедуры и задать свойства по их
    внутренним именам (Source, Mode, AssemblySteps …). Строки — байтами
    UTF-8, остальное (объекты, списки, числа) — как есть.

    Порядок важен: смена типа продукта или режима сбрасывает зависимые
    свойства (у «Создать» список шагов сборки становится «все шаги»). А словарь
    в Python 2.7 порядок не хранит — поэтому ключевые свойства идут первыми."""
    s = r.addStatement(typ)
    keys = [k for k in _STMT_FIRST if k in props] + \
        [k for k in props if k not in _STMT_FIRST]
    for k in keys:
        v = props[k]
        p = s.getProperty(k)
        if p is None:
            raise ValueError(u"у оператора %s нет свойства %s" % (typ, k))
        p.Value = _b(v) if _is_str(v) else v
    return s


def clear_routine(c, pid=None):
    """Процедура процесса компонента — пустая, с новым именем процесса."""
    r = routine(c)
    r.clear()
    if pid is not None:
        set_process_id(c, pid)
    return r


def stats(c):
    return beh(c, typ="rSimStatistics")


def connect_people(tc, people=(), idle=(), tools=()):
    """ТК человека: подключить операторов, места ожидания и инструменты."""
    for h in people:
        beh(tc, "Resources").connect(beh(h, "PMResource"))
    for i in idle:
        beh(tc, "Idle/ChargingLocations").connect(beh(i, typ="rSimDynamicInterface"))
    for t in tools:
        beh(tc, "Tools").connect(beh(t, typ="rSimDynamicInterface"))
    return True


def crew_area(tc, uri, margin=1200.0):
    """Зона прохода бригады — по её участку.

    Без зоны ТК человека строит карту путей по всей сцене (UseGlobalArea).
    На двух цехах это минуты, и R-Pro на каждом пересчёте спрашивает модальным
    окном «продолжить расчёт?» — главный поток стоит, мост молчит. Зона по
    размеру участка (люди, места ожидания, точки, куда бригада носит и где
    работает, плюс запас) считается мгновенно."""
    pts = []
    for h in (_safe(beh(tc, "Resources"), "ConnectedComponents") or []):
        pts.append(h.PositionMatrix.P)
    for i in (_safe(beh(tc, "Idle/ChargingLocations"), "ConnectedComponents") or []):
        pts.append(i.PositionMatrix.P)
    comps = []
    for l in pc().TransportSystem.Links:
        impl = comp_of(l.Implementer)
        if impl is not None and impl.Name == tc.Name:
            comps += [comp_of(l.Source), comp_of(l.Destination)]
    for c in app.Components:
        try:
            r = routine(c)
        except Exception:
            continue
        for s in r.Statements:
            if _u(_safe(s, "Type") or u"") == u"Work":
                ctrl = _safe(s.getProperty("Controller"), "Value")
                owner = comp_of(ctrl) if ctrl is not None else None
                if owner is not None and owner.Name == tc.Name:
                    comps.append(c)
    for c in comps:
        if c is None:
            continue
        f = find_feature(c, "ResourceLocation")
        m = c.PositionMatrix * f.NodePositionMatrix if f is not None else c.PositionMatrix
        pts.append(m.P)
    if not pts:
        return None
    x0, x1 = min(p.X for p in pts) - margin, max(p.X for p in pts) + margin
    y0, y1 = min(p.Y for p in pts) - margin, max(p.Y for p in pts) + margin
    a = load(uri)
    place(a, (x0 + x1) / 2.0, (y0 + y1) / 2.0)
    set_prop(a, "AreaLength", x1 - x0)
    set_prop(a, "AreaWidth", y1 - y0)
    beh(tc, "Pathways").connect(beh(a, "Зона Прохода"))
    p = tc.getProperty("UseGlobalArea")
    if p is not None:
        p.Value = False
    return [round(x0), round(y0), round(x1), round(y1)]


# Шаблоны процедур. Имена переменных процесса: Engine — изделие на посту,
# Order — заказ на сборку (какие гнёзда заполнить), P — созданная деталь.

def post_routine(c, pid, group, asm=None, steps=(), worker=None, work_s=0.0, delay_s=0.0):
    """Пост сборочной линии («Операция на конвейере»): принять изделие с
    конвейера, заказать детали в гнёзда шагов steps (их принесут робот или
    человек), поработать (worker — ТК человека) и отдать изделие дальше."""
    r = clear_routine(c, pid)
    st, res, ctr = stats(c), frame(c, "ResourceLocation"), frame(c, "Center")
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Engine",
         AcceptAllProductTypes=False, AcceptedFlowGroups=[group],
         ProductPositionFrame=ctr, ResourcePositionFrame=res)
    # учёт изделий: «Транспорт» по ленте счётчики статистики не трогает
    stmt(r, "SetStatisticsFlow", ProductVariableName="Engine", Statistics=st, FlowDirection="Enter")
    if steps:
        stmt(r, "GetAssembly", AssemblyDataSource=1, Assembly=asm,
             AssemblySteps=[asm_find_step(asm, s) for s in steps], IncludeChildSteps=False,
             AssemblyVariableName="Engine", ReturnVariableName="Order")
        stmt(r, "TransportIn", Mode=1, Source="From Previous Process", AssemblyVariableName="Engine",
             AssemblyOrderVariableName="Order", ProductVariableName="Parts", AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    if worker is not None and work_s > 0:
        stmt(r, "Work", Controller=beh(worker, "TC"), TimeSource=0, ProcessTime=float(work_s),
             ProcessTimeExpression=str(work_s), ResourcePositionFrame=res, WorkPositionFrame=ctr)
    if delay_s > 0:
        stmt(r, "Delay", Delay=float(delay_s))
    stmt(r, "SetStatisticsState", State="Blocked", Statistics=st)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Engine", Statistics=st, FlowDirection="Leave")
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="Engine",
         ResourcePositionFrame=res)
    return r.Name


def source_routine(c, pid, ptype, asm_steps=None, delay_s=0.0):
    """Склад деталей («Узел процесса»): создать деталь (или начало сборки —
    asm_steps) и ждать, пока её заберут. Следующую — когда эту унесли."""
    r = clear_routine(c, pid)
    kw = {"ProductType": ptype, "ProductVariableName": "P"}
    if asm_steps:
        kw["AssemblySteps"] = asm_steps
    stmt(r, "CreateProduct", **kw)
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="P")
    if delay_s > 0:
        stmt(r, "Delay", Delay=float(delay_s))
    return r.Name


def subassembly_routine(c, pid, asm, worker, work_s):
    """Пост подсборки: собрать новый экземпляр сборки asm из деталей (их
    приносит worker), поработать и отдать готовый узел дальше."""
    r = clear_routine(c, pid)
    st = stats(c)
    steps = []

    def walk(s):
        steps.append(s)
        for ch in s.ChildSteps:
            walk(ch)
    walk(asm.RootStep)
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "GetAssembly", AssemblyDataSource=1, Assembly=asm, AssemblySteps=steps,
         IncludeChildSteps=False, AssemblyVariableName="", ReturnVariableName="Order")
    stmt(r, "TransportIn", Mode=1, Source="From Previous Process", AssemblyVariableName="",
         AssemblyOrderVariableName="Order", ProductVariableName="Sub", AcceptAllProductTypes=True)
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    stmt(r, "Work", Controller=beh(worker, "TC"), TimeSource=0, ProcessTime=float(work_s),
         ProcessTimeExpression=str(work_s), ResourcePositionFrame=frame(c, "ResourceLocation"))
    stmt(r, "SetStatisticsState", State="Blocked", Statistics=st)
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="Sub")
    return r.Name


def buffer_routine(c, pid):
    """Перевалка: принять изделие и отдать дальше по маршруту (склад отгрузки
    одного участка, который теперь кормит другой участок)."""
    r = clear_routine(c, pid)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="P",
         AcceptAllProductTypes=True)
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="P")
    return r.Name


def sink_routine(c, pid, delay_s=3.0):
    """Отгрузка: принять готовое изделие, подержать и списать."""
    r = clear_routine(c, pid)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Done",
         AcceptAllProductTypes=True)
    stmt(r, "Delay", Delay=float(delay_s))
    stmt(r, "RemoveProduct", ProductVariableName="Done")
    return r.Name


# --- технологические операции роботом: клей, пайка, сварка, винты, контроль ----
# Робот не носит деталь, а работает инструментом над изделием на посту:
# проходит шов, встаёт в точки пайки или сварки, сканирует камерой. Проход —
# подпрограмма робота (линейные движения в мировых координатах), пост
# запускает её оператором «Выполнить процедуру робота». То, что операция
# оставляет на изделии (клеевой валик, паяные соединения, швы, болты), — деталь
# заказчика: пост создаёт её на месте и прикрепляет к изделию, дальше она едет
# вместе с ним.

def robot_exec(robot):
    return robot.findBehavioursByType(VC_ROBOTEXECUTOR)[0]


def mount_tool(robot, uri):
    """Инструмент на фланец робота. Возвращает имя инструмента контроллера
    (TCP), который добавился при монтаже, или None, если не встал.
    Монтируются горелки (сварка, пайка, дозатор) и отвёртка; пистолеты-
    герметики и камера Eyes к фланцу не подходят (canConnect False)."""
    ctrl = robot_exec(robot).Controller
    fi = ctrl.FlangeNode.findBehaviour("Tool")
    t = load(uri)
    ti = None
    for b in t.findBehavioursByType(VC_ONETOONEINTERFACE):
        if fi.canConnect(b):
            ti = b
            break
    if ti is None:
        app.deleteComponent(t)
        return None
    before = set(_u(x.Name) for x in ctrl.Tools)
    fi.connect(ti, False)
    new = [x for x in ctrl.Tools if _u(x.Name) not in before]
    return _u(new[0].Name) if new else None


def post_center(post):
    """Мировая матрица кадра Center поста — там стоит изделие."""
    return post.PositionMatrix * frame(post, "Center").NodePositionMatrix


def robot_path(robot, name, post, strokes, tool=None, speed=200.0, dwell=0.0, lift=80.0, park=None):
    """Подпрограмма робота name: проход по штрихам над изделием на посту.

    strokes — список штрихов, штрих — точки [x, y, z] в системе изделия
    (кадр Center поста). Штрих из одной точки — «точка» (пайка, сварка, болт):
    опуститься, подождать dwell, подняться. Иначе — шов: опуститься в первую
    точку и пройти остальные со скоростью speed. Инструмент смотрит вниз."""
    ex = robot_exec(robot)
    ctrl, prog = ex.Controller, ex.Program
    # «a or b» на объектах R-Pro нельзя: проверка истинности бросает исключение
    r = prog.findRoutine(_b(name))
    if r is None:
        r = prog.addRoutine(_b(name))
    for s in r.Statements[:]:
        r.deleteStatement(s)
    tl = None
    for t in ctrl.Tools:
        if tool and _u(t.Name) == _u(tool):
            tl = t
    if tl is None:
        tl = ctrl.Tools[0]
    cm = post_center(post)

    def target(x, y, z):
        m = vcMatrix.new(cm)
        m.translateRel(float(x), float(y), float(z))
        m.rotateRelY(180.0)
        return m

    def move(kind, m, v=None):
        s = r.addStatement(kind)
        s.Base = ctrl.Bases[0]
        s.Tool = tl
        s.Positions[0].PositionInWorld = m
        if v is not None:
            p = s.getProperty("MaxSpeed")
            if p is not None:
                p.Value = float(v)
        return s

    n = 0
    for k, st in enumerate(strokes):
        x, y, z = st[0]
        if k == 0:
            move("PtpMotion", target(x, y, z + lift))
        else:
            move("LinMotion", target(x, y, z + lift), 1500.0)
        move("LinMotion", target(x, y, z), speed)
        for (x, y, z) in st[1:]:
            move("LinMotion", target(x, y, z), speed)
        if dwell > 0:
            d = r.addStatement("Delay")
            d.getProperty("Delay").Value = float(dwell)
        x, y, z = st[-1]
        move("LinMotion", target(x, y, z + lift), 1500.0)
        n += len(st)
    # между изделиями — «Домой», а не зависнуть над лентой на последней точке
    try:
        r.addStatement("Home")
    except Exception:
        if park is not None:
            move("PtpMotion", target(park[0], park[1], park[2]))
    return {"routine": _u(r.Name), "points": n, "moves": len(r.Statements)}


def robots_home(delay=1.0):
    """Все роботы сцены возвращаются «Домой» между заданиями: у «ТК робота» —
    автовозврат (AutoHoming), у роботов-технологов — «Домой» в конце их
    подпрограмм. Без этого робот стоит на последней точке до следующего цикла."""
    tcs, routines_ = 0, 0
    for c in app.Components:
        p = c.getProperty("AutoHoming::Enabled")
        if p is not None:
            p.Value = True
            d = c.getProperty("AutoHoming::Delay")
            if d is not None:
                d.Value = float(delay)
            tcs += 1
        for ex in c.findBehavioursByType(VC_ROBOTEXECUTOR):
            for r in ex.Program.Routines:
                if _u(r.Name) != u"Process" or not r.Statements:
                    continue
                last = r.Statements[len(r.Statements) - 1]
                if _u(_safe(last, "Type") or u"") != u"Home":
                    try:
                        r.addStatement("Home")
                        routines_ += 1
                    except Exception:
                        pass
    return {u"контроллеров_с_возвратом": tcs, u"подпрограмм_с_домой": routines_}


def process_routine(c, pid, group, robot=None, routine_name="Process", bead_type=None, bead_pos=None,
                    work_s=0.0, scrap=0.0, stream=1):
    """Пост технологической операции: принять изделие, робот проходит свою
    подпрограмму (шов, точки, сканирование), на изделии появляется то, что
    операция оставляет (bead_type в месте bead_pos относительно изделия), и
    изделие едет дальше.

    scrap > 0 — пост контроля: с вероятностью scrap % изделие уходит в брак.
    Маршрут изделия: [… контроль, брак, следующий …] — пост сам назначает
    следующий шаг: +1 (брак) или +2 (дальше). Случайное число — из своего
    потока: uniform без потока в условии всегда одно и то же."""
    r = clear_routine(c, pid)
    st, res, ctr = stats(c), frame(c, "ResourceLocation"), frame(c, "Center")
    stmt(r, "SetStatisticsState", State="Idle", Statistics=st)
    stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="Engine",
         AcceptAllProductTypes=False, AcceptedFlowGroups=[group],
         ProductPositionFrame=ctr, ResourcePositionFrame=res)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Engine", Statistics=st, FlowDirection="Enter")
    stmt(r, "SetStatisticsState", State="Busy", Statistics=st)
    if robot is not None:
        s = r.addStatement("RunRobotRoutine")
        s.getProperty("Component").Value = robot
        s.getProperty("RoutineName").Value = _b(u'"%s"' % _u(routine_name))
    if bead_type is not None:
        # шов создаётся в своём контейнере поста: в контейнере самого поста
        # (ёмкость 1, там изделие) «Создать» ждал бы места вечно
        bc = c.findBehaviour("Beads")
        if bc is None:
            bc = c.createBehaviour(VC_COMPONENTCONTAINER, "Beads")
        f = find_feature(c, "BeadFrame")
        if f is None:
            f = c.RootFeature.createFeature(VC_FRAME, "BeadFrame")
        f.PositionMatrix = ctr.NodePositionMatrix * wpr_mat(*(bead_pos or [0.0] * 6))
        stmt(r, "CreateProduct", ProductType=bead_type, ProductVariableName="Bd", Container=bc,
             ProductPositionFrame=f)
        stmt(r, "AttachProduct", Parent="Engine", Child="Bd")
    if work_s > 0:
        stmt(r, "Delay", Delay=float(work_s))
    if scrap > 0:
        stmt(r, "GetFlowStep", FlowStepSource=2, ProductVariableName="Engine", ReturnVariableName="FlowInfo")
        s = r.addStatement("IfElse")
        s.getProperty("Condition").Value = _b("uniform(%d, 0.0, 1.0) < %.4f" % (int(stream), scrap / 100.0))
        for scope, off in ((s.ThenScope, "1"), (s.ElseScope, "2")):
            stmt(scope, "FindFlowStep", Mode=1, SourceFlowInfoVariableName="FlowInfo",
                 TargetFlowInfoVariableName="FlowInfo", ReturnStepOffset=off)
        stmt(r, "SetNextFlowStep", FlowInfoVariableName="FlowInfo", ProductVariableName="Engine")
    stmt(r, "SetStatisticsState", State="Blocked", Statistics=st)
    stmt(r, "SetStatisticsFlow", ProductVariableName="Engine", Statistics=st, FlowDirection="Leave")
    stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="Engine",
         ResourcePositionFrame=res)
    return r.Name


# --- цвета деталей ----------------------------------------------------------------
# STL приходит без материалов — все детали одного серого цвета. Цвет берётся
# из спецификации заказчика (колонка «Цвет») и ставится модели детали.

def material(name, rgb):
    """Материал программы с этим именем; нет — создаём с цветом rgb (0..1)."""
    try:
        m = app.findMaterial(_b(name))
    except Exception:
        m = None
    if m is not None:
        return m
    m = None
    for args in ((_b(name),), ()):
        try:
            m = app.createMaterial(*args)     # без имени возвращает None
        except Exception:
            m = None
        if m is not None:
            break
    if m is None:
        return None
    try:
        m.Name = _b(name)
    except Exception:
        pass
    col = vcVector.new(rgb[0], rgb[1], rgb[2])
    for a in ("Diffuse", "Ambient"):
        try:
            setattr(m, a, col)
        except Exception:
            pass
    try:
        app.addMaterial(m)
    except Exception:
        pass
    return m


def paint(c, name, rgb):
    """Покрасить компонент целиком (материал компонента наследуют все узлы)."""
    m = material(name, rgb)
    if m is None:
        return False
    c.Material = m
    return True


# --- диагностика и правка готовой линии --------------------------------------
# Линию не храним у себя: восстанавливаем из данных программы — маршрута
# (FlowTable2) и транспортных связей. Так правка работает и для линии,
# сохранённой вчера, и для собранной руками.

def comp_of(obj):
    """Компонент, которому принадлежит поведение/узел/узел транспорта."""
    c = _safe(obj, "Component")
    if c is not None:
        return c
    n = obj
    for _ in range(20):
        n = _safe(n, "Parent")
        if n is None:
            return None
        if _safe(n, "Uri") is not None:
            return n
    return None


def process_owner():
    """Имя процесса → компонент, который его выполняет."""
    out = {}
    for c in app.Components:
        try:
            out[routine(c).Name] = c
        except Exception:
            pass
    return out


def _stat_value(st, name):
    p = st.getProperty(name)
    if p is None:
        return None
    v = _safe(p, "Value")
    return None if v is None else round(float(v), 1)


def line_stats():
    """Загрузка всего, что работает в сцене, с начала прогона.

    Процессы (посты, станки, склады): доля простоя / работы / блокировки — по
    состояниям, которые пишет сам процесс (у наших постов — «Состояние
    статистики»). Люди и роботы: занятость = 100 − простой. У склада отгрузки —
    сколько изделий ушло."""
    # бригада человека — ТК, а подпись бригады — посты, куда этот ТК возит
    serves = {}
    for l in pc().TransportSystem.Links:
        impl, dst = comp_of(l.Implementer), comp_of(l.Destination)
        if impl is not None and dst is not None:
            try:
                serves.setdefault(impl.Name, set()).add(_u(routine(dst).Name))
            except Exception:
                pass
    # и посты, где люди этого ТК работают («Работа» с этим контроллером)
    for c in app.Components:
        try:
            r = routine(c)
        except Exception:
            continue
        for s in r.Statements:
            if _u(_safe(s, "Type") or u"") == u"Work":
                ctrl = _safe(s.getProperty("Controller"), "Value")
                owner = comp_of(ctrl) if ctrl is not None else None
                if owner is not None:
                    serves.setdefault(owner.Name, set()).add(_u(r.Name))
    crew_of = {}
    for c in app.Components:
        for n, b in behaviours(c):
            if b.Name == "Resources" and b.Type == "rSimDynamicInterface":
                posts = sorted(serves.get(c.Name, set()))
                label = u", ".join(posts[:3]) if posts else _u(c.Name)
                for h in (_safe(b, "ConnectedComponents") or []):
                    crew_of[h.Name] = label
    out = []
    for c in app.Components:
        st, kind, ex, pnp = None, None, None, False
        for n, b in behaviours(c):
            if b.Type == "rSimStatistics" and st is None:
                st = b
            elif b.Type == "rProcessExecutor":
                ex = b
            elif b.Name == "RobotPnP":
                pnp = True
            elif b.Name == "PMResource" and b.Type == "rSimDynamicInterface":
                kind = kind or u"человек"
            elif b.Name == "RobotInterface":
                # ресурс МП с роботизированной частью — мобильный робот (AGV), не человек
                kind = u"AGV"
        if st is None:
            continue
        row = {"имя": _u(c.Name), "простой": _stat_value(st, "StateIdlePercentage")}
        if ex is not None:
            try:
                r = routine(c)
            except Exception:
                continue
            row["вид"] = u"процесс"
            row["имя"] = _u(r.Name)
            row["работа"] = _stat_value(st, "StateBusyPercentage")
            row["блок"] = _stat_value(st, "StateBlockedPercentage")
            kinds = [_u(_safe(s, "Type") or u"") for s in r.Statements]
            # без «Состояния статистики» процесс всё время числится «в работе»
            # (склады деталей) — такие в загрузку не берём
            row["учёт"] = u"SetStatisticsState" in kinds
            if row["учёт"]:
                # сколько изделий пришло на пост (у контроля — вместе с браком, у
                # последнего поста этажа — выпуск участка). Вход, а не выход: выход
                # роботом статистика считает сама, и с «Процессом» он удваивается
                row["прошло"] = int(_stat_value(st, "PartsEntered") or 0)
            if u"RemoveProduct" in kinds or _safe(c.getProperty("BOMname"), "Value") in ("Flow Sink",):
                # изолятор брака списывает изделия так же, как отгрузка, — но это не выпуск
                key = u"брак" if u"брак" in _u(r.Name).lower() else u"выпуск"
                row[key] = int(_stat_value(st, "PartsExited") or 0)
        elif kind is not None:
            row["вид"] = kind
            row["бригада"] = _u(crew_of.get(c.Name, u""))
            if kind == u"AGV":
                row["вид"] = u"робот"
                row["робот"] = u"AGV " + _u(c.Name)
        elif pnp:
            row["вид"] = u"робот"
            rb = robot_on(c)
            row["робот"] = _u(rb.Name) if rb is not None else u""
        else:
            continue
        if row["простой"] is None:
            continue
        out.append(row)
    return {"время_с": round(app.Simulation.SimTime, 1), "строки": out}


def scene_summary():
    """Что построено — для ответа человеку, а не перечень компонентов.

    Линии — по именам процессов «<кратко> П<N> <операция>»: сколько постов, на
    какой отметке, что делают роботы (подпрограмма на посту — технологическая
    операция), есть ли изолятор брака. Плюс лифты, роботы, изделия. Изделия в
    работе (детали на лентах) в счёт оборудования не идут."""
    import re
    lines = {}
    for c in app.Components:
        try:
            r = routine(c)
        except Exception:
            continue
        nm = _u(r.Name)
        m = re.match(u"^(\\S+) П(\\d+) (.+)$", nm)
        if m:
            ln = lines.setdefault(m.group(1), {"посты": {}, "z": [], "брак": 0, "операции": []})
            ln["посты"][int(m.group(2))] = m.group(3)
            ln["z"].append(c.PositionMatrix.P.Z)
            kinds = [_u(_safe(s, "Type") or u"") for s in r.Statements]
            if u"RunRobotRoutine" in kinds:
                ln["операции"].append(m.group(3))
        elif u"брак после" in nm:
            ln = lines.setdefault(nm.split(u" ")[0], {"посты": {}, "z": [], "брак": 0, "операции": []})
            ln["брак"] += 1
    out_lines = {}
    for k, ln in sorted(lines.items(), key=lambda kv: -max(kv[1]["z"] or [0.0])):
        if not ln["посты"]:
            continue
        posts = [ln["посты"][i] for i in sorted(ln["посты"])]
        z = round(max(ln["z"] or [0.0]) / 1000.0, 1)
        out_lines[k] = {u"отметка_м": z, u"постов": len(posts), u"первый": posts[0], u"последний": posts[-1],
                        u"операции_роботов": ln["операции"][:8], u"постов_контроля_с_браком": ln["брак"]}
    robots, lifts, types = 0, 0, []
    for c in app.Components:
        if _safe(c, "Parent") is not None and _u(_safe(c.Parent, "Name") or u"") not in (u"ROOT", u""):
            if c.findBehavioursByType(VC_ROBOTEXECUTOR):
                robots += 1        # робот на ТК — дочерний компонент контроллера
            continue
        if c.findBehavioursByType(VC_ROBOTEXECUTOR):
            robots += 1
        if u"VerticalShuttle" in _u(_safe(c, "Uri") or u"") or u"подъемн" in _u(c.Name).lower() \
                or u"Лифт" in _u(c.Name):
            lifts += 1
    for t in pc().ProductTypeManager.ProductTypes:
        if _safe(t, "IsAssembly"):
            types.append(_u(t.Name))
    return {u"линии": out_lines, u"роботов": robots, u"лифтов": lifts, u"изделия_сборки": types[:10],
            u"время_симуляции_с": round(app.Simulation.SimTime)}


def _is_block(c):
    """«Блок» (BlockGeo): перекрытие этажа или подставка склада."""
    return c.getProperty("Length_X") is not None and c.getProperty("Height_Z") is not None


def _is_slab(c):
    """Перекрытие или пол: тонкий «блок» (до 0,4 м). Подставка склада — 0,78 м.
    По площади различать нельзя: куски плиты вокруг проёма под лифт узкие."""
    if not _is_block(c):
        return False
    return c.getProperty("Height_Z").Value <= 400.0


def _is_pillar(c):
    n = _u(c.Name)
    return n.startswith(u"Столб") or u"Pillar" in _u(_safe(c, "Uri") or u"")


def _is_lift(c):
    # адрес загруженного компонента — «cid:…», поэтому по свойству, а не по Uri
    return c.getProperty("SideA_PortPlaces") is not None


def _olist(lst):
    """Список R-Pro (vcObservableList) не итерируется и не индексируется: .get(i)."""
    try:
        return [lst.get(i) for i in range(lst.size())]
    except Exception:
        try:
            return list(lst)
        except Exception:
            return []


def _world_box(c):
    """Габарит компонента в мире: углы локального габарита через его матрицу."""
    bc, bd = _safe(c, "BoundCenter"), _safe(c, "BoundDiagonal")
    if bc is None or bd is None:
        return None
    m = c.WorldPositionMatrix if _safe(c, "WorldPositionMatrix") is not None else c.PositionMatrix
    xs, ys, zs = [], [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                v = vcVector.new(bc.X + sx * abs(bd.X), bc.Y + sy * abs(bd.Y), bc.Z + sz * abs(bd.Z))
                w = m * v
                xs.append(w.X)
                ys.append(w.Y)
                zs.append(w.Z)
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def layout_dims():
    """Габариты построенного: этажи (отметки, высота этажа, перекрытия), площадь
    под оборудованием по этажам и пятно здания. Конструкции здания (плиты,
    колонны) в «оборудование» не входят, изделия на лентах — тоже."""
    import re
    levels = []
    for c in app.Components:
        try:
            nm = _u(routine(c).Name)
        except Exception:
            continue
        if re.match(u"^\\S+ П\\d+ ", nm):
            levels.append(round(c.PositionMatrix.P.Z / 100.0) * 100.0)
    levels = sorted(set(levels)) or [0.0]
    slabs, floors_eq, building = [], {}, [1e18, 1e18, -1e18, -1e18]
    top = 0.0
    for c in app.Components:
        if _safe(c, "Parent") is not None and _u(_safe(c.Parent, "Name") or u"") not in (u"ROOT", u""):
            continue
        b = _world_box(c)
        if b is None:
            continue
        # «блок» — и перекрытие этажа, и подставка склада (0,7–1,2 м): различаем по площади
        if _is_slab(c):
            slabs.append([b, float(c.getProperty("Height_Z").Value)])
            continue
        if _is_pillar(c):
            continue
        z0 = c.PositionMatrix.P.Z
        lv = max([l for l in levels if l <= z0 + 150.0] or [levels[0]])
        f = floors_eq.setdefault(lv, [1e18, 1e18, -1e18, -1e18])
        floors_eq[lv] = [min(f[0], b[0]), min(f[1], b[1]), max(f[2], b[3]), max(f[3], b[4])]
        top = max(top, b[5])
        building = [min(building[0], b[0]), min(building[1], b[1]), max(building[2], b[3]),
                    max(building[3], b[4])]
    if slabs:
        # пятно здания — по перекрытиям и полу, а не по выступам оборудования
        building = [min(x[0][0] for x in slabs), min(x[0][1] for x in slabs),
                    max(x[0][3] for x in slabs), max(x[0][4] for x in slabs)]
    floors = []
    for i, lv in enumerate(levels):
        f = floors_eq.get(lv)
        if f is None:
            continue
        dx, dy = (f[2] - f[0]) / 1000.0, (f[3] - f[1]) / 1000.0
        floors.append({u"этаж": i + 1, u"отметка_м": round(lv / 1000.0, 2),
                       u"длина_м": round(dx, 1), u"ширина_м": round(dy, 1), u"площадь_м2": round(dx * dy)})
    heights = [round((b - a) / 1000.0, 2) for a, b in zip(levels, levels[1:])]
    thick = [t for _, t in slabs if t > 100.0]
    out = {u"этажей": len(floors), u"этажи": floors,
           u"высота_этажа_м": heights[0] if heights and len(set(heights)) == 1 else heights,
           u"толщина_перекрытия_м": round(max(thick) / 1000.0, 2) if thick else 0.0,
           u"верх_оборудования_м": round(top / 1000.0, 1),
           u"площадь_под_оборудованием_м2": sum(f[u"площадь_м2"] for f in floors)}
    if building[0] < building[2]:
        bx, by = (building[2] - building[0]) / 1000.0, (building[3] - building[1]) / 1000.0
        out[u"пятно_м"] = [round(bx, 1), round(by, 1)]
        out[u"пятно_м2"] = round(bx * by)
    if heights:
        out[u"высота_здания_м"] = round((levels[-1] + 1000.0 * heights[-1]) / 1000.0, 1)
    return out


def locate(query):
    """Найти в сцене по словам человека: посты (по названию операции), роботов
    (по посту, где они работают), лифты, склады, изоляторы брака. Слова
    сравниваются по началу (4 буквы): «пайки» находит «Пайка выводов»."""
    import re
    # основа слова — 4 буквы: «пайки» и «пайка», «сваривает» и «сварка»
    words = [w[:4] for w in re.findall(u"[a-zа-яё0-9]{3,}", _u(query).lower().replace(u"ё", u"е"))
             if w not in (u"пост", u"посты", u"поста", u"робот", u"робота", u"где", u"покажи", u"найди",
                          u"который", u"которые", u"которая", u"этот", u"тот")]
    want_robot = u"робот" in _u(query).lower()

    def score(text):
        t = _u(text).lower().replace(u"ё", u"е")
        toks = [x[:4] for x in re.findall(u"[a-zа-яё0-9]{3,}", t)]
        return sum(1 for w in words if any(x.startswith(w) or w.startswith(x) for x in toks))
    # кто работает на посту: ТК по связям, робот-технолог — по «Выполнить процедуру робота»
    serves = {}
    for l in pc().TransportSystem.Links:
        impl, dst = comp_of(l.Implementer), comp_of(l.Destination)
        if impl is not None and dst is not None:
            try:
                rb = robot_on(impl)
                serves.setdefault(_u(routine(dst).Name), []).append(
                    (impl, _u(rb.Name) if rb is not None else _u(impl.Name)))
            except Exception:
                pass
    hits = []
    for c in app.Components:
        try:
            nm = _u(routine(c).Name)
        except Exception:
            nm = None
        if nm:
            sc = score(nm)
            if sc == 0:
                continue
            who = [n for _, n in serves.get(nm, [])]
            for s in routine(c).Statements:
                if _u(_safe(s, "Type") or u"") == u"RunRobotRoutine":
                    comp_ = _safe(s.getProperty("Component"), "Value")
                    if comp_ is not None:
                        who.append(_u(comp_.Name) + u" (инструментом)")
            m = post_center(c) if find_feature(c, "Center") is not None else c.PositionMatrix
            kind = u"изолятор брака" if u"брак" in nm else (u"пост" if re.match(u"^\\S+ П\\d+ ", nm) else u"процесс")
            hits.append((sc + (0.5 if want_robot and who else 0.0), {
                u"что": u"%s «%s»" % (kind, nm), u"кто": (u"роботы: " + u", ".join(who)) if who else u"",
                u"отметка_м": round(c.PositionMatrix.P.Z / 1000.0, 1), u"x_м": round(m.P.X / 1000.0, 1),
                u"y_м": round(m.P.Y / 1000.0, 1), u"где": m2l(m)}))
        elif _is_lift(c):
            if any(w.startswith(u"лифт") or w.startswith(u"подъе") or w.startswith(u"этаж") for w in words):
                hits.append((1.0, {u"что": u"лифт «%s»" % _u(c.Name), u"кто": u"",
                                   u"отметка_м": round(c.PositionMatrix.P.Z / 1000.0, 1),
                                   u"x_м": round(c.PositionMatrix.P.X / 1000.0, 1),
                                   u"y_м": round(c.PositionMatrix.P.Y / 1000.0, 1),
                                   u"где": m2l(c.PositionMatrix)}))
    hits.sort(key=lambda h: -h[0])
    return [h for _, h in hits[:8]]


# --- оптимизация: убрать лишнее, сжать линии, ужать перекрытия ------------------------

def _top_components():
    """Статические компоненты сцены (без изделий на лентах и без роботов на ТК)."""
    out = []
    for c in app.Components:
        par = _safe(c, "Parent")
        if par is not None and _u(_safe(par, "Name") or u"") not in (u"ROOT", u""):
            continue
        out.append(c)
    return out


def _has_beh(c, name):
    """Есть ли поведение с таким именем в любом узле (beh() бросает, если нет)."""
    for n, b in behaviours(c):
        if _u(b.Name) == _u(name):
            return True
    return False


def _top_of(c):
    """Компонент верхнего уровня: робот на «ТК робота» — дочерний, двигать его
    надо вместе с контроллером, а не отдельно (сдвиг дочернего идёт в осях
    повёрнутого родителя — робот поста контроля улетал на 9 м вбок)."""
    for _ in range(10):
        par = _safe(c, "Parent")
        if par is None or _u(_safe(par, "Name") or u"") in (u"ROOT", u""):
            return c
        nxt = comp_of(par) if _safe(par, "Uri") is None else par
        if nxt is None or nxt.Name == c.Name:
            return c
        c = nxt
    return c


def _is_conveyor(c):
    return c.getProperty("ConveyorLength") is not None and _has_beh(c, "InInterface")


def _iface_connected(c, name):
    b = c.findBehaviour(name)
    if b is None:
        return False
    return bool(_safe(b, "ConnectedComponents"))


def _shift(c, dx):
    # translateAbs ПРИБАВЛЯЕТ сдвиг по мировым осям, а не ставит положение: с
    # (X + dx, Y, Z) компонент уезжал на свою же координату — «4-й этаж на 24 м»
    m = vcMatrix.new(c.PositionMatrix)
    m.translateAbs(dx, 0.0, 0.0)
    c.PositionMatrix = m


ROBOT_SWING = 800.0   # размах руки робота по ходу линии сверх его опоры, мм


def optimize_scene(apply=False, margin=1500.0, clearance=400.0, min_conv=600.0):
    """Что можно сократить в построенном и (apply) сократить:

    1. «сироты» — роботы без связей и без операций, склады и процессы вне
       маршрутов, ленты, не подключённые ни с одной стороны;
    2. шаг постов прямых линий «<кратко> П<N>»: лента между постами короче, пока
       оборудование соседних постов (роботы, склады, изоляторы брака, печь над
       лентой) не встанет вплотную с зазором clearance. Посты, к которым
       приходит лифт с другого этажа или от которых уходит лифт, — якоря: стоят,
       остальные подтягиваются к ним;
    3. перекрытия этажей — по новому пятну оборудования плюс margin, с проёмами
       под лифты; колонны — по краям, но не над оборудованием этажа ниже."""
    import re
    comps = _top_components()
    owner = {}
    for c in comps:
        try:
            owner[_u(routine(c).Name)] = c
        except Exception:
            pass
    links = []
    for l in pc().TransportSystem.Links:
        links.append((comp_of(l.Source), comp_of(l.Destination), comp_of(l.Implementer)))
    used = set()
    for s_, d_, i_ in links:
        for x in (s_, d_, i_):
            if x is not None:
                used.add(x.Name)
    flows = set()
    ft = pc().FlowTable2
    for g in _olist(pc().FlowGroupManager.Groups):
        seq = ft.getSequence(g)
        if seq is None:
            continue
        for st in _olist(seq.FlowSteps):
            for pg in _olist(st.Groups):
                flows.add(_u(_safe(pg, "Name") or u""))
    run_robots = set()
    for c in comps:
        try:
            r = routine(c)
        except Exception:
            continue
        for s in r.Statements:
            if _u(_safe(s, "Type") or u"") == u"RunRobotRoutine":
                v = _safe(s.getProperty("Component"), "Value")
                if v is not None:
                    run_robots.add(v.Name)
    # 1. сироты
    orphans = []
    for c in comps:
        nm = _u(c.Name)
        uri = _u(_safe(c, "Uri") or u"")
        if _has_beh(c, "RobotPnP"):
            if c.Name not in used:
                orphans.append(c)
            continue
        if c.findBehavioursByType(VC_ROBOTEXECUTOR):
            if c.Name not in run_robots and c.Name not in used:
                orphans.append(c)
            continue
        if nm in [_u(x.Name) for x in owner.values()] and c.Name not in used:
            pid = _u(routine(c).Name)
            if pid not in flows and u"Feeder" not in uri:
                orphans.append(c)
            continue
        if _is_conveyor(c) and not _is_lift(c):
            if not _iface_connected(c, "InInterface") and not _iface_connected(c, "OutInterface"):
                orphans.append(c)
    # стенды (подставки) под удаляемыми складами — тоже лишние
    stands = [c for c in comps if _is_block(c) and not _is_slab(c)]

    def stand_under(n):
        p = n.PositionMatrix.P
        for s in stands:
            q = s.PositionMatrix.P
            # узел склада стоит на отметке этажа, центр подставки — на 0,39 м выше
            if abs(q.X - p.X) < 60.0 and abs(q.Y - p.Y) < 60.0 and abs(q.Z - p.Z) < 1000.0:
                return s
        return None
    extra = []
    for o in orphans:
        s = stand_under(o)
        if s is not None:
            extra.append(s)
    orphans += extra

    # 2. линии: посты по порядку, оборудование каждого поста
    posts_by_line = {}
    for pid, c in owner.items():
        m = re.match(u"^(\\S+) П(\\d+) ", pid)
        if m:
            posts_by_line.setdefault(m.group(1), []).append((int(m.group(2)), c))
    def group_of(post):
        """Оборудование поста: ТК по связям, склады и изоляторы со стендами,
        роботы-технологи, то, что стоит над постом (печь, камера)."""
        g = {}
        for s_, d_, i_ in links:
            if s_ is None or d_ is None:
                continue
            if d_.Name == post.Name or s_.Name == post.Name:
                other = s_ if d_.Name == post.Name else d_
                if i_ is not None and i_.Name != post.Name and _safe(i_, "Name") and \
                        i_.getProperty("ConveyorLength") is None:
                    g[i_.Name] = i_
                if other is not None and not _is_conveyor(other) and other.Name not in owner_post_names:
                    g[other.Name] = other
                    st = stand_under(other)
                    if st is not None:
                        g[st.Name] = st
        try:
            for s in routine(post).Statements:
                if _u(_safe(s, "Type") or u"") == u"RunRobotRoutine":
                    v = _safe(s.getProperty("Component"), "Value")
                    if v is not None:
                        v = _top_of(v)
                        g[v.Name] = v
        except Exception:
            pass
        cm = post_center(post)
        L = (post.getProperty("ConveyorLength").Value if post.getProperty("ConveyorLength") is not None else 800.0)
        for c in comps:
            if c.Name in g or c.Name == post.Name or _is_conveyor(c) or c.Name in owner_post_names:
                continue
            q = c.PositionMatrix.P
            if abs(q.X - cm.P.X) < L / 2.0 and abs(q.Y - cm.P.Y) < 600.0 and abs(q.Z - post.PositionMatrix.P.Z) < 300.0:
                if not _is_block(c) and not _is_pillar(c):
                    g[c.Name] = c
        return list(g.values())

    owner_post_names = set(c.Name for lst in posts_by_line.values() for _, c in lst)
    plans = []
    total_saved = 0.0
    for short, lst in posts_by_line.items():
        lst.sort()
        posts = [c for _, c in lst]
        if len(posts) < 2:
            continue
        ys = [post_center(p).P.Y for p in posts]
        xs = [post_center(p).P.X for p in posts]
        if max(ys) - min(ys) > 100.0:
            continue          # линия с разворотом — шаг не трогаем
        direction = 1.0 if xs[-1] > xs[0] else -1.0
        groups = [group_of(p) for p in posts]
        # якоря: пост, чей склад — лента (узел едет с другого этажа), и пост, от
        # которого лента уходит на лифт
        anchors = set()
        for i, p in enumerate(posts):
            for s_, d_, i_ in links:
                if d_ is not None and s_ is not None and d_.Name == p.Name and _is_conveyor(s_) \
                        and s_.Name not in owner_post_names and i_ is not None and i_.getProperty("ConveyorLength") is None:
                    anchors.add(i)
            for s_, d_, i_ in links:
                if s_ is not None and d_ is not None and s_.Name == p.Name and \
                        abs(d_.PositionMatrix.P.Z - p.PositionMatrix.P.Z) > 1000.0:
                    anchors.add(i)
        if not anchors:
            anchors = set([0])
        # протяжённость оборудования поста вдоль линии
        ext = []
        for p, g in zip(posts, groups):
            lo, hi = 1e18, -1e18
            for c in [p] + g:
                b = _world_box(c)
                if b is None:
                    continue
                # робот — не только опора: рука ходит по сторонам, соседи не должны
                # задевать друг друга (иначе шаг ужимался до 1,6 м)
                swing = ROBOT_SWING if (c.findBehavioursByType(VC_ROBOTEXECUTOR) or _has_beh(c, "RobotPnP")) else 0.0
                lo, hi = min(lo, b[0] - swing), max(hi, b[3] + swing)
            ext.append((lo, hi))
        # лента между постами i и i+1 и сколько можно сократить
        convs, cuts = [], []
        for i in range(len(posts) - 1):
            a, b = posts[i], posts[i + 1]
            conv = None
            outb = a.findBehaviour("OutInterface")
            for cc in (_safe(outb, "ConnectedComponents") or []):
                if _is_conveyor(cc) and cc.Name not in owner_post_names:
                    conv = cc
            if conv is None:
                convs.append(None)
                cuts.append(0.0)
                continue
            Lc = conv.getProperty("ConveyorLength").Value
            if direction > 0:
                free = ext[i + 1][0] - ext[i][1] - clearance
            else:
                free = ext[i][0] - ext[i + 1][1] - clearance
            cut = max(0.0, min(Lc - min_conv, free))
            cut = float(int(cut / 50.0) * 50)
            convs.append(conv)
            cuts.append(cut)
        # сдвиг каждого поста: якоря стоят, остальные — к ближайшему якорю
        d = [None] * len(posts)
        for a in anchors:
            d[a] = 0.0
        order = sorted(anchors)
        # вправо от каждого якоря до следующего якоря
        for k, a in enumerate(order):
            stop = order[k + 1] if k + 1 < len(order) else len(posts)
            for i in range(a + 1, stop):
                d[i] = d[i - 1] - direction * cuts[i - 1]
            # если следующий якорь есть — между ними сжимать нельзя (оба стоят)
            if k + 1 < len(order):
                for i in range(a + 1, stop):
                    d[i] = 0.0
                for i in range(a, stop):
                    cuts[i] = 0.0
        first = order[0]
        for i in range(first - 1, -1, -1):
            d[i] = d[i + 1] + direction * cuts[i]
        saved = sum(cuts)
        if saved <= 0.0:
            continue
        total_saved += saved
        plans.append({u"линия": short, u"сжато_м": round(saved / 1000.0, 1),
                      u"длина_было_м": round(abs(xs[-1] - xs[0]) / 1000.0, 1),
                      u"длина_стало_м": round((abs(xs[-1] - xs[0]) - saved) / 1000.0, 1),
                      u"якоря": [lst[i][0] for i in sorted(anchors)]})
        if apply:
            moved = set()
            for i, (p, g) in enumerate(zip(posts, groups)):
                if not d[i]:
                    continue
                for c in [p] + g:
                    if c.Name in moved:
                        continue
                    moved.add(c.Name)
                    # подпрограмма робота хранится от его базы: едет вместе с ним сама
                    # (сдвиг точек вдобавок уводил их вдвое — «вне досягаемости»)
                    _shift(c, d[i])
            for i, conv in enumerate(convs):
                if conv is None or not cuts[i]:
                    continue
                # лента идёт от поста i: её начало — вслед за ним, длина — короче
                _shift(conv, d[i])
                conv.getProperty("ConveyorLength").Value = conv.getProperty("ConveyorLength").Value - cuts[i]
            # ленты за последним постом (на лифт) и перед первым — вслед за своим постом
    # имена — до удаления: у удалённого объекта .Name бросает «Объект больше не
    # существует» (журнал 08.10), а робот уходит вместе со своим ТК раньше, чем
    # до него дойдёт очередь в списке
    orphan_names = []
    for o in orphans:
        nm = _u(_safe(o, "Name") or u"")
        if nm and nm not in orphan_names:
            orphan_names.append(nm)
    removed = []
    if apply:
        for nm in orphan_names:
            o = app.findComponent(_b(nm))
            if o is None:
                continue
            try:
                o.delete()
                removed.append(nm)
            except Exception:
                pass
    return {u"сироты": orphan_names, u"линии": plans, u"удалено": removed,
            u"сжато_м": round(total_saved / 1000.0, 1)}


# --- связка двух линий: выход одной → робот → вход другой ---------------------------

def _out_of(c):
    """Что стоит за выходом компонента (OutInterface), или None."""
    b = c.findBehaviour("OutInterface")
    if b is None:
        return None
    for cc in (_safe(b, "ConnectedComponents") or []):
        if cc.Name != c.Name:
            return cc
    return None


def flow_names(group):
    """Шаги маршрута группы именами процессов: [«ProductFeeder», «AssemblyProcess1», …];
    шаг-альтернатива — списком. У объекта шага имени нет — узнаём сравнением
    с ProcessManager.findProcessGroup(имя)."""
    if _is_str(group):
        group = group_by_name(group)
    seq = pc().FlowTable2.getSequence(group)
    if seq is None:
        return []
    pm = pc().ProcessManager
    names = set()
    for c in app.Components:
        try:
            names.add(_u(routine(c).Name))
        except Exception:
            pass
    cands = [(n, pm.findProcessGroup(n)) for n in names]
    out = []
    for st in _olist(seq.FlowSteps):
        row = []
        for pg in _olist(st.Groups):
            row += [n for n, c in cands if c is not None and c == pg]
        out.append(row[0] if len(row) == 1 else row)
    return out


def process_comp(pid):
    for c in app.Components:
        try:
            if _u(routine(c).Name) == _u(pid):
                return c
        except Exception:
            pass
    return None


def line_ends(feeder):
    """Вход и выход линии с подачей feeder (шаблон «Замкнутый конвейер» и
    подобные): группа маршрута, шаги, первая лента; лента выхода — за
    последним шагом маршрута, до конца цепочки лент; что стоит на её конце
    («Раковина для продукта») или None."""
    cr = beh(feeder, typ="rProductCreator")
    g = cr.SingleFeed.Part.FlowGroup
    steps = flow_names(g)
    entry = _out_of(feeder)
    res = {u"подача": _u(feeder.Name), u"группа": _u(g.Name), u"шаги": steps,
           u"тип": _u(cr.SingleFeed.Part.Name), u"вход": None, u"выход": None, u"сток": None}
    if entry is not None and _is_conveyor(entry):
        res[u"вход"] = _u(entry.Name)
        res[u"вход_м"] = m2l(frame_world(entry, "InInterface"))
    if not steps:
        return res
    last = steps[-1] if _is_str(steps[-1]) else steps[-1][0]
    c = process_comp(last)
    c = _out_of(c) if c is not None else None
    end = None
    seen = set()
    while c is not None and _is_conveyor(c) and c.Name not in seen:
        seen.add(c.Name)
        end = c
        c = _out_of(c)
    if end is not None:
        res[u"выход"] = _u(end.Name)
        res[u"выход_м"] = m2l(frame_world(end, "OutInterface"))
        if c is None:
            # сток может стоять на конце ленты без стыковки интерфейсов
            p = frame_world(end, "OutInterface").P
            for x in _top_components():
                q = x.PositionMatrix.P
                if x.Name != end.Name and abs(q.X - p.X) < 120.0 and abs(q.Y - p.Y) < 120.0 and \
                        len(x.findBehavioursByType(VC_ROBOTEXECUTOR)) == 0 and not _is_conveyor(x):
                    c = x
        if c is not None:
            res[u"сток"] = _u(c.Name)
    return res


def change_type_on(c, type_name):
    """Деталь, прошедшая процесс c, становится типом type_name (и маршрутом его
    группы): оператор ChangeProductType перед выдачей.

    Так вторая линия принимает детали первой как свои: у её сборки гнёзда
    принимают только свой тип (коробка BottlesInBox_2 — только Can_2, опыт
    08.10), а связи её роботов — только для своей группы (SupportedGroup у
    связи только для чтения)."""
    t = pc().ProductTypeManager.findProductType(_b(type_name))
    if t is None:
        raise ValueError(u"нет типа детали %s" % _u(type_name))
    r = routine(c)
    types = [_u(str(s.Type)) for s in r.Statements]
    i = types.index(u"TransportOut") if u"TransportOut" in types else len(types)
    s = r.addStatement("ChangeProductType", i)
    s.getProperty("NewType").Value = t
    return True


# --- оптимизация линий строителя (line_builder): цепочка от подачи ------------------

def _xy_box(c, grow=0.0):
    b = _world_box(c)
    if b is None:
        return None
    return [b[0] - grow, b[1] - grow, b[3] + grow, b[4] + grow]


def _chain(feeder, links):
    """Линия от подачи по потоку: [(вид, [компоненты верхнего уровня])].

    Вид: feed — подача, conv — лента (прямая или поворот), station — пост
    (съём, станок, укладка, ТК с роботом), finish — съём и выход. Лента
    ведёт к следующему элементу через OutInterface, пост — по транспортным
    связям (съём → станок → укладка). Вернулись туда, где уже были, — это
    замкнутая петля: её ленты сдвигом не укоротишь, возвращаем None."""
    def out_of(c):
        b = c.findBehaviour("OutInterface")
        if b is None:
            return None
        for cc in (_safe(b, "ConnectedComponents") or []):
            if cc.Name != c.Name:
                return cc
        return None

    def moves_from(c):
        return [(d, i) for s, d, i in links if s is not None and d is not None and s.Name == c.Name]

    def with_children(tc):
        """ТК и всё, что на нём: робот, инструмент — для габарита поста."""
        out = [tc]
        for x in app.Components:
            if x.Name != tc.Name and _top_of(x).Name == tc.Name:
                out.append(x)
        return out

    items = [(u"feed", [feeder])]
    seen = set([feeder.Name])
    c = out_of(feeder)
    while c is not None and len(items) < 300:
        if c.Name in seen:
            return None
        seen.add(c.Name)
        if _is_conveyor(c):
            items.append((u"conv", [c]))
            c = out_of(c)
            continue
        mv = moves_from(c)
        if not mv:
            break
        grp = [c]
        d, tc = mv[0]
        if tc is not None:
            grp += with_children(_top_of(tc))
        nxt = out_of(d)
        if nxt is not None and _is_conveyor(nxt):
            # съём → укладка: робот-перекладчик
            grp.append(d)
            seen.add(d.Name)
            items.append((u"station", grp))
            c = nxt
            continue
        mv2 = moves_from(d)
        grp.append(d)
        seen.add(d.Name)
        if not mv2:
            items.append((u"finish", grp))   # съём → выход: конец линии
            break
        place, tc2 = mv2[0]
        if tc2 is not None and (tc is None or tc2.Name != tc.Name):
            grp += with_children(_top_of(tc2))
        grp.append(place)
        seen.add(place.Name)
        items.append((u"station", grp))
        c = out_of(place)
    return items


def _overlap(a, b, gap):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def _moved(b, off):
    return [b[0] + off[0], b[1] + off[1], b[2] + off[0], b[3] + off[1]]


def optimize_lines(apply=False, only=None, clearance=400.0, min_conv=1500.0):
    """Сжать линии строителя: прямая лента короче, всё ниже по потоку
    сдвигается вслед как одно целое — по направлению этой ленты, поэтому и
    после разворота змейка остаётся собранной. Перемычка разворота короче —
    ряды змейки ближе друг к другу. Насколько короче — пока сдвинутое не встанет вплотную
    (clearance) к оборудованию выше по потоку; роботы — с размахом руки.

    only — имена компонентов (выделение): сжимать только линии, где они есть.
    Петли («Замкнутый конвейер») и посты заводов («… П1 …») не трогаем."""
    import re
    links = []
    for l in pc().TransportSystem.Links:
        links.append((comp_of(l.Source), comp_of(l.Destination), comp_of(l.Implementer)))
    only = set(_u(x) for x in (only or []))
    out = []
    for feeder in feeders_in_scene():
        if _safe(feeder, "Parent") is not None and _u(_safe(feeder.Parent, "Name") or u"") not in (u"ROOT", u""):
            continue
        items = _chain(feeder, links)
        name = _u(feeder.Name)
        if items is None:
            out.append({u"подача": name, u"пропущено": u"замкнутая петля"})
            continue
        names = set(_u(c.Name) for _, g in items for c in g)
        if only:
            # выделен робот — его ТК в цепочке; выделено что-то внутри — тоже
            hit = False
            for nm in only:
                c = app.findComponent(_b(nm))
                if c is not None and (_u(c.Name) in names or _u(_top_of(c).Name) in names):
                    hit = True
            if not hit:
                continue
        factory = False
        for _, g in items:
            for c in g:
                try:
                    if re.match(u"^\\S+ П\\d+ ", _u(routine(c).Name)):
                        factory = True
                except Exception:
                    pass
        if factory or not [1 for kind, _ in items if kind in (u"station", u"finish")]:
            continue

        boxes = []
        for kind, g in items:
            bs = []
            for c in g:
                # «a or b» на объектах R-Pro нельзя — висящее исключение
                robot = len(c.findBehavioursByType(VC_ROBOTEXECUTOR)) > 0
                b = _xy_box(c, ROBOT_SWING if robot else 0.0)
                if b is not None:
                    bs.append(b)
            boxes.append(bs)
        def gname(j):
            """Пост — по станку («VF-1»), не по ТК или съёму."""
            g = items[j][1]
            for c in g:
                if c.getProperty("ProcessTime") is not None:
                    return _u(c.Name)
            for c in g:
                if len(c.findBehavioursByType(VC_ROBOTEXECUTOR)) > 0:
                    return _u(c.Name)
            return _u(g[0].Name)

        off = [(0.0, 0.0)] * len(items)
        cuts, stops = [], {}
        conv_before = 0.0
        straight = {}
        for k, (kind, g) in enumerate(items):
            if kind != u"conv":
                continue
            conv = g[0]
            L = float(conv.getProperty("ConveyorLength").Value)
            conv_before += L
            if k == 0 or k + 1 >= len(items):
                continue
            a, b = frame_world(conv, "InInterface").P, frame_world(conv, "OutInterface").P
            dx, dy = b.X - a.X, b.Y - a.Y
            n = (dx * dx + dy * dy) ** 0.5
            if n < 1.0 or abs(n - L) > 50.0:
                continue        # не прямая
            straight[k] = (L, dx / n, dy / n)
        # перемычки разворота (между двумя поворотами) — вторым проходом: сблизь
        # ряды змейки раньше, и обратный ряд уже не сдвинется вдоль (упрётся
        # в оборудование первого ряда)
        def is_bridge(k):
            return k - 1 not in straight and k + 1 not in straight and                 items[k - 1][0] == u"conv" and items[k + 1][0] == u"conv"
        order = [k for k in sorted(straight) if not is_bridge(k)] + [k for k in sorted(straight) if is_bridge(k)]
        for k in order:
            L, ux, uy = straight[k]

            def collides(cut):
                for j in range(k + 1, len(items)):
                    oj = (off[j][0] - ux * cut, off[j][1] - uy * cut)
                    for bj in boxes[j]:
                        mj = _moved(bj, oj)
                        for i in range(0, k):
                            for bi in boxes[i]:
                                mi = _moved(bi, off[i])
                                if _overlap(mj, mi, clearance) and                                         not _overlap(_moved(bj, off[j]), mi, clearance):
                                    return (j, i)
                return None

            lo, hi = 0, int((L - min_conv) / 50.0)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if collides(mid * 50.0):
                    hi = mid - 1
                else:
                    lo = mid
            cut = lo * 50.0
            if lo < int((L - min_conv) / 50.0):
                why = collides((lo + 1) * 50.0)
                if why:
                    stops[_u(items[k][1][0].Name)] = u"%s упёрся бы в %s" % (gname(why[0]), gname(why[1]))
            if cut <= 0.0:
                continue
            for j in range(k + 1, len(items)):
                off[j] = (off[j][0] - ux * cut, off[j][1] - uy * cut)
            cuts.append((k, cut))
            # сама лента короче: начало стоит, конец ближе (иначе следующий пост
            # «упирался» в её прежний конец)
            b = boxes[k][0]
            boxes[k][0] = [b[0] + (cut * -ux if ux < -0.5 else 0.0), b[1] + (cut * -uy if uy < -0.5 else 0.0),
                           b[2] - (cut * ux if ux > 0.5 else 0.0), b[3] - (cut * uy if uy > 0.5 else 0.0)]

        def area(offs):
            x0 = y0 = 1e18
            x1 = y1 = -1e18
            for bs, o in zip(boxes, offs):
                for b in bs:
                    m = _moved(b, o)
                    x0, y0, x1, y1 = min(x0, m[0]), min(y0, m[1]), max(x1, m[2]), max(y1, m[3])
            return (x1 - x0) / 1000.0, (y1 - y0) / 1000.0
        w0, h0 = area([(0.0, 0.0)] * len(items))
        w1, h1 = area(off)
        saved = sum(c for _, c in cuts)
        rec = {u"подача": name, u"лент_м_было": round(conv_before / 1000.0, 1),
               u"лент_м_стало": round((conv_before - saved) / 1000.0, 1),
               u"пятно_было": [round(w0, 1), round(h0, 1)], u"пятно_стало": [round(w1, 1), round(h1, 1)],
               u"укорочено_лент": len(cuts), u"сжато_м": round(saved / 1000.0, 1),
               u"ленты": [[_u(items[k][1][0].Name), round(c / 1000.0, 2)] for k, c in cuts],
               u"упоры": stops}
        if apply and cuts:
            moved = set()
            for j, (kind, g) in enumerate(items):
                o = off[j]
                if abs(o[0]) < 0.5 and abs(o[1]) < 0.5:
                    continue
                for c in g:
                    t = _top_of(c)
                    if _safe(t, "Parent") is not None and _u(_safe(t.Parent, "Name") or u"") not in (u"ROOT", u""):
                        continue
                    if t.Name in moved:
                        continue
                    moved.add(t.Name)
                    m = vcMatrix.new(t.PositionMatrix)
                    m.translateAbs(o[0], o[1], 0.0)
                    t.PositionMatrix = m
            for k, cut in cuts:
                p = items[k][1][0].getProperty("ConveyorLength")
                p.Value = p.Value - cut
        out.append(rec)
    if apply:
        app.Simulation.setInitialState()
    return out


def rebuild_slabs(margin=1500.0):
    """Перекрытия этажей по пятну оборудования + margin, с проёмами под лифты.
    Колонны переставляются по новым краям, но не над оборудованием этажа ниже.
    Пол первого этажа (тонкая плита) — по оборудованию первого этажа."""
    d = layout_dims()
    comps = _top_components()
    slabs, pillars = [], []
    for c in comps:
        b = _world_box(c)
        if b is None:
            continue
        if _is_slab(c):
            slabs.append((c, b))
        elif _is_pillar(c):
            pillars.append(c)
    if not slabs:
        return {u"перекрытий": 0}
    before = sum((b[3] - b[0]) * (b[4] - b[1]) for _, b in slabs) / 1e6
    levels = sorted(set(round(b[5] / 100.0) * 100.0 for _, b in slabs))
    lifts = [c for c in comps if _is_lift(c)]
    # пятна оборудования по этажам (как в layout_dims)
    fl_boxes = {}
    eq_levels = [round(f[u"отметка_м"] * 1000.0) for f in d.get(u"этажи", [])]
    for c in comps:
        if _is_slab(c) or _is_pillar(c):
            continue
        b = _world_box(c)
        if b is None:
            continue
        z0 = c.PositionMatrix.P.Z
        lv = max([l for l in eq_levels if l <= z0 + 150.0] or [0.0])
        f = fl_boxes.setdefault(lv, [1e18, 1e18, -1e18, -1e18])
        fl_boxes[lv] = [min(f[0], b[0]), min(f[1], b[1]), max(f[2], b[3]), max(f[3], b[4])]
    thick, old_rect = {}, {}
    for c, b in slabs:
        lv = round(b[5] / 100.0) * 100.0
        t = c.getProperty("Height_Z")
        thick[lv] = float(t.Value) if t is not None else b[5] - b[2]
        r = old_rect.get(lv, [1e18, 1e18, -1e18, -1e18])
        old_rect[lv] = [min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[3]), max(r[3], b[4])]
        c.delete()
    for p in pillars:
        p.delete()
    made, after = 0, 0.0
    for lv in levels:
        f = fl_boxes.get(min(fl_boxes.keys(), key=lambda k: abs(k - lv))) if fl_boxes else None
        if f is None:
            continue
        x0, y0, x1, y1 = f[0] - margin, f[1] - margin, f[2] + margin, f[3] + margin
        # плита не больше прежней: оптимизация не должна раздувать перекрытие
        r = old_rect.get(lv)
        if r is not None:
            x0, y0, x1, y1 = max(x0, r[0]), max(y0, r[1]), min(x1, r[2]), min(y1, r[3])
        t = thick.get(lv, 300.0)
        holes = []
        for L in lifts:
            b = _world_box(L)
            if b is not None and b[2] < lv - 10.0 < b[5]:
                holes.append((b[0] - 300.0, b[3] + 300.0, b[1] - 300.0, b[4] + 300.0))
        rects = [(x0, x1, y0, y1)]
        for hx0, hx1, hy0, hy1 in holes:
            nxt = []
            for a0, a1, b0, b1 in rects:
                if hx1 <= a0 or hx0 >= a1 or hy1 <= b0 or hy0 >= b1:
                    nxt.append((a0, a1, b0, b1))
                    continue
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
        for a0, a1, b0, b1 in rects:
            s = load("https://download.r-pro.digital/v204/Components/R-Pro Digital/Basic Shapes/BlockGeo.rpro")
            set_prop(s, "Length_X", a1 - a0)
            set_prop(s, "Width_Y", b1 - b0)
            set_prop(s, "Height_Z", t)
            place(s, (a0 + a1) / 2.0, (b0 + b1) / 2.0, lv - t / 2.0)
            made += 1
            after += (a1 - a0) * (b1 - b0) / 1e6
        if t > 100.0:
            busy = [v for k, v in fl_boxes.items() if k < lv]
            nx = max(2, int((x1 - x0) / 9000.0) + 1)
            for i in range(nx):
                x = x0 + 300.0 + i * (x1 - x0 - 600.0) / (nx - 1)
                for yy in (y0 + 300.0, y1 - 300.0):
                    if any(bx[0] - 500.0 <= x <= bx[2] + 500.0 and bx[1] - 500.0 <= yy <= bx[3] + 500.0
                           for bx in busy):
                        continue
                    p_ = load("https://download.r-pro.digital/v204/Components/R-Pro Digital/Facilities - Interior/SquarePillar.rpro")
                    set_prop(p_, "Height", lv - t)
                    set_prop(p_, "Width", 400.0)
                    set_prop(p_, "Length", 400.0)
                    place(p_, x, yy, 0.0)
    return {u"перекрытий": made, u"плит_было_м2": round(before), u"плит_стало_м2": round(after)}


def tune_line(conveyor_speed=None, feed_every_s=None, post=None, work_s=None):
    """«Что если» правкой на месте, без пересборки.

    conveyor_speed — скорость всех лент и постов-конвейеров, мм/с;
    feed_every_s — как часто склад выдаёт базовую деталь (пауза после
    «Создать» сборки) и генераторы подачи линий механообработки;
    post + work_s — время операции на посту (часть имени процесса):
    «Работа» оператора или «Задержка» робота."""
    done = {}
    if conveyor_speed is not None:
        n = 0
        for c in app.Components:
            p = c.getProperty("ConveyorSpeed")
            if p is not None:
                p.Value = float(conveyor_speed)
                n += 1
        done[u"лент"] = n
    procs = []
    for c in app.Components:
        try:
            procs.append(routine(c))
        except Exception:
            pass
    if feed_every_s is not None:
        n = 0
        for r in procs:
            kinds = [_u(_safe(s, "Type") or u"") for s in r.Statements]
            if u"CreateProduct" in kinds and u"Delay" in kinds:
                for s in r.Statements:
                    if _u(_safe(s, "Type") or u"") == u"Delay":
                        s.getProperty("Delay").Value = float(feed_every_s)
                        n += 1
        for f in feeders_in_scene():
            cr = beh(f, typ="rProductCreator")
            cr.SingleFeed.getProperty("Interval").Value = float(feed_every_s)
            n += 1
        done[u"подач"] = n
    if post is not None and work_s is not None:
        hit = []
        for r in procs:
            if _u(post).lower() in _u(r.Name).lower():
                for s in r.Statements:
                    t = _u(_safe(s, "Type") or u"")
                    if t == u"Work":
                        s.getProperty("ProcessTime").Value = float(work_s)
                        s.getProperty("ProcessTimeExpression").Value = _b(str(work_s))
                        hit.append(_u(r.Name))
                    elif t == u"Delay":
                        s.getProperty("Delay").Value = float(work_s)
                        hit.append(_u(r.Name))
        done[u"посты"] = sorted(set(hit))
    return done


def feeders_in_scene():
    """Подачи деталей: по поведению-генератору, а не по адресу (в Uri
    загруженного компонента пробелы заменены на «+»)."""
    out = []
    for c in app.Components:
        for n, b in behaviours(c):
            if b.Type == "rProductCreator":
                out.append(c)
                break
    return out


def split_lines(y_from, prefix_new, prefix_old, group_new, type_new, uri_new=None,
                group_old=None, uri_old=None):
    """Ремонт: две линии с одинаковыми именами процессов слились в одну
    группу. Разводим ПРАВКОЙ: компоненты севернее y_from — новая линия.
    Каждой — свои имена процессов, у новой — своя группа, тип детали и
    связи. Маршруты строятся заново по связям каждой линии."""
    p = pc()
    ts = p.TransportSystem
    new_names = set(c.Name for c in app.Components if c.PositionMatrix.P.Y >= y_from)
    renamed = 0
    for c in app.Components:
        try:
            r = routine(c)
        except Exception:
            continue
        base = _split_pid(r.Name)
        pure = _u(r.Name)[len(base[0]):]
        pref = prefix_new if c.Name in new_names else prefix_old
        set_process_id(c, _u(pref) + pure)
        renamed += 1
    feeders = feeders_in_scene()
    f_new = [f for f in feeders if f.Name in new_names][0]
    f_old = [f for f in feeders if f.Name not in new_names][0]
    info_new = new_line_group(f_new, group_new, type_new, uri_new)
    g_old = beh(f_old, typ="rProductCreator").SingleFeed.Part.FlowGroup
    if group_old:
        g_old.Name = _b(group_old)
    if uri_old:
        beh(f_old, typ="rProductCreator").SingleFeed.Part.ComponentUri = _b(uri_old)
    # связи новой линии — заново, уже для её группы (SupportedGroup не меняется)
    g_new = group_by_name(group_new)
    moved = 0
    for l in list(ts.Links):
        s, d, impl = comp_of(l.Source), comp_of(l.Destination), comp_of(l.Implementer)
        if s is not None and s.Name in new_names:
            ts.deleteTransportLink(l)
            link(s, d, impl, g_new)
            moved += 1
    # маршруты по связям каждой линии
    flows = {}
    for g, names in ((g_old, None), (g_new, new_names)):
        flows[g.Name] = _flow_from_links(names, prefix_new if names else prefix_old)
        set_flow(flows[g.Name], g)
    return {"renamed": renamed, "links_moved": moved, "new": info_new,
            "flows": dict((k, len(v)) for k, v in flows.items())}


def _flow_from_links(names, prefix):
    """Маршрут линии по её транспортным связям: Съём k → [станок] → Укладка k …"""
    owner = process_owner()
    # линии различаются префиксом имён («Л1 », «Л2 »), names не нужен
    ids = sorted([pid for pid in owner if _u(pid).startswith(_u(prefix) + u"Съём ")],
                 key=lambda p: (u"финиш" in _u(p), int(_split_pid(p)[1]) if _split_pid(p)[1].isdigit() else 0))
    links = {}
    for l in pc().TransportSystem.Links:
        s, d = comp_of(l.Source), comp_of(l.Destination)
        if s is not None and d is not None:
            links[s.Name] = d.Name
    by_comp = dict((c.Name, pid) for pid, c in owner.items())
    flow = []
    for pid in ids:
        flow.append(pid)
        cur = owner[pid].Name
        for _ in range(3):
            nxt = links.get(cur)
            if nxt is None:
                break
            flow.append(by_comp[nxt])
            cur = nxt
            if u"Укладка" in _u(by_comp[nxt]) or u"Выход" in _u(by_comp[nxt]):
                break
    return flow


def flow_ids(group=None):
    g = group if group is not None else flow_group()
    seq = pc().FlowTable2.getSequence(g)
    if seq is None:
        return []
    ids = []
    for i in range(seq.FlowSteps.size()):
        st = seq.FlowSteps.get(i)
        for j in range(st.Groups.size()):
            ids.append(st.Groups.get(j).ProcessId)
    return ids


def robot_on(tc):
    for c in app.Components:
        par = _safe(c, "Parent")
        if par is not None and _safe(par, "Uri") is None and comp_of(par) is not None \
                and comp_of(par).Name == tc.Name and _safe(c, "Uri") and c is not tc:
            return c
    return None


def feature_world(c, name):
    """Мировая матрица элемента по имени.

    Мировые матрицы программа пересчитывает только на шаге симуляции: у
    станка, поставленного секунду назад, WorldPositionMatrix — ещё прежняя
    (у нового — единичная). Но матрицы его узлов согласованы с этой прежней.
    Поэтому берём положение узла ОТНОСИТЕЛЬНО компонента по прежним
    матрицам и умножаем на текущую позицию компонента — верно всегда."""
    def walk(f):
        for ch in (_safe(f, "Children") or []):
            if ch.Name == name:
                return ch
            got = walk(ch)
            if got is not None:
                return got
        return None
    inv = vcMatrix.new(c.WorldPositionMatrix)
    inv.invert()
    for n in nodes(c):
        f = walk(_safe(n, "RootFeature"))
        if f is not None:
            return c.PositionMatrix * inv * n.WorldPositionMatrix * f.NodePositionMatrix
    return None


def _dist(a, b):
    import math
    return math.sqrt((a.P.X - b.P.X) ** 2 + (a.P.Y - b.P.Y) ** 2 + (a.P.Z - b.P.Z) ** 2)


def _split_pid(pid):
    """«Л2 Съём 5» → ('Л2 ', '5'); «Съём 5» → ('', '5')."""
    pid = _u(pid)
    prefix = u""
    if pid.startswith(u"Л") and u" " in pid and pid.split(u" ", 1)[0][1:].isdigit():
        prefix, pid = pid.split(u" ", 1)
        prefix += u" "
    return prefix, pid.replace(u"Съём ", u"", 1)


def line_stations():
    """Станции всех линий сцены: съём, станок, укладка, контроллер, робот и
    расстояния от плеча робота (основание +500 мм) до точек, куда он тянется.
    Номер станции — «5», а если линий несколько — «2.5» (линия 2, станция 5)."""
    owner = process_owner()
    links = {}
    for l in pc().TransportSystem.Links:
        s, d = comp_of(l.Source), comp_of(l.Destination)
        impl = comp_of(l.Implementer)
        if s is not None and d is not None:
            links[s.Name] = (d.Name, impl.Name if impl is not None else None)
    groups = [g for g in pc().FlowGroupManager.Groups if flow_ids(g)]
    out = []
    for g in groups:
        out += _stations_of(g, owner, links, multi=len(groups) > 1)
    return out


def _stations_of(g, owner, links, multi):
    ids = flow_ids(g)
    out = []
    for i, pid in enumerate(ids):
        if u"Съём" not in _u(pid):
            continue
        pick = owner.get(pid)
        if pick is None or pick.Name not in links:
            continue
        dst, tc_name = links[pick.Name]
        prefix, k = _split_pid(pid)
        line_no = prefix.strip()[1:] if prefix else u""
        st = {"n": (line_no + u"." + k) if (multi and line_no) else k, "k": k, "prefix": prefix,
              "group": g.Name, "pick": pick.Name, "tc": tc_name,
              "machine": None, "machine_pid": None, "place": None}
        nxt = ids[i + 1] if i + 1 < len(ids) else None
        if nxt and u"Укладка" not in _u(nxt) and nxt in owner and owner[nxt].Name == dst:
            st["machine"], st["machine_pid"] = dst, nxt
            nn = ids[i + 2] if i + 2 < len(ids) else None
            st["place"] = owner[nn].Name if nn in owner else None
        else:
            st["place"] = dst
        tc = app.findComponent(tc_name) if tc_name else None
        rb = robot_on(tc) if tc is not None else None
        st["robot"] = rb.Name if rb is not None else None
        if rb is not None:
            base = vcMatrix.new(rb.WorldPositionMatrix)
            base.translateRel(0.0, 0.0, 500.0)
            reach = {}
            for key, nm, fr in (("pick", st["pick"], "MainFrame"), ("machine", st["machine"], "ProductLocation"),
                                ("place", st["place"], "MainFrame")):
                if nm:
                    w = feature_world(app.findComponent(nm), fr)
                    if w is not None:
                        reach[key] = int(_dist(base, w))
            st["reach_mm"] = reach
        out.append(st)
    return out


def move_machine(machine, tc, mm):
    """Сдвинуть станок к роботу (mm > 0) или от него (mm < 0) по горизонтали."""
    import math
    m, t = comp(machine), comp(tc)
    dx = t.PositionMatrix.P.X - m.PositionMatrix.P.X
    dy = t.PositionMatrix.P.Y - m.PositionMatrix.P.Y
    d = math.hypot(dx, dy) or 1.0
    p = m.PositionMatrix
    # translateAbs прибавляет смещение, а не ставит позицию: собираем матрицу заново
    m.PositionMatrix = mat(p.P.X + dx / d * mm, p.P.Y + dy / d * mm, p.P.Z, p.WPR.Z)
    return m2l(m.PositionMatrix)


def replace_machine(st, uri, title, gap=600.0):
    """Заменить станок станции другой моделью, не трогая остальную линию:
    старый — удалить вместе с его связями, новый — поставить лицом к роботу,
    вписать в маршрут на место старого и связать с тем же роботом."""
    old = comp(st["machine"])
    tc = comp(st["tc"])
    ts = pc().TransportSystem
    for l in list(ts.Links):
        if old.Name in (_safe(comp_of(l.Source), "Name"), _safe(comp_of(l.Destination), "Name")):
            ts.deleteTransportLink(l)
    g = group_by_name(st["group"])
    ids = flow_ids(g)
    import math
    # сторона, где стоял старый станок: новый ставим туда же
    heading = math.degrees(math.atan2(old.PositionMatrix.P.Y - tc.PositionMatrix.P.Y,
                                      old.PositionMatrix.P.X - tc.PositionMatrix.P.X))
    app.deleteComponent(old)
    new = load(uri)
    face_to(new, "ResourceLocation", tc.PositionMatrix.P.X, tc.PositionMatrix.P.Y, gap, heading)
    pid = set_process_id(new, u"%s%s %s" % (_u(st.get("prefix") or u""), _u(title), _u(st["k"])))
    old_pid = _u(st["machine_pid"])
    set_flow([pid if _u(x) == old_pid else x for x in ids], g)
    link(comp(st["pick"]), new, tc, g)
    link(new, comp(st["place"]), tc, g)
    return {"machine": new.Name, "pid": pid, "at": m2l(new.PositionMatrix)}


def swap_robot(tc_name, uri):
    """Заменить робота на контроллере станции. Связи с процессом держит
    контроллер, а не робот, поэтому маршрут и транспорт не трогаются."""
    tc = comp(tc_name)
    old = robot_on(tc)
    if old is not None:
        app.deleteComponent(old)
    rb = load(uri)
    ok = mount_robot(tc, rb)
    return {"robot": rb.Name, "mounted": ok}


# --- камера -------------------------------------------------------------------

def camera(coi, eye):
    cam = app.findCamera()
    cam.Coi = vcVector.new(coi[0], coi[1], coi[2])
    cam.Eye = vcVector.new(eye[0], eye[1], eye[2])
    return True
