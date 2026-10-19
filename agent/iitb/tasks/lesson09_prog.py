# Python 2.7 внутри R-Pro. Урок 9: программа робота «Перемещение продукции».
# Выполняется после lesson08_cell.py: ячейка, сигналы, TOOL_1, BASE_1/BASE_2 уже настроены.
ped, rob, grip, c1, c2, feeder, m1, m2, s1 = build_cell()
cal, ctrl = prepare_robot(rob, grip, c1, c2, m1, m2, s1)
cr = beh(feeder, typ="rProductCreator")
cr.SingleFeed.getProperty("Interval").Value = 6.0
new_line_group(feeder, u"Банки", u"Банка", U_CAN)

# высота банки — по умолчанию из свойства компонента «Параметрическая банка»
tmp = load(U_CAN)
CAN_H = float(tmp.getProperty("CanHeight").Value)
try:
    app.deleteComponent(tmp)
except Exception:
    tmp.delete()

ex = beh(rob, typ="rRobotExecutor")
prog = ex.Program
TOOL, B1, B2 = ctrl.Tools[0], ctrl.Bases[0], ctrl.Bases[1]
HOME_TCP = ctrl.FlangeNode.WorldPositionMatrix * TOOL.PositionMatrix      # робот сейчас в исходной позе
APP = 130.0
TOP = 600.0 + CAN_H                       # верх банки на ленте, мм


def routine_(name):
    r = prog.findRoutine(name)
    if r is None:
        r = prog.addRoutine(name)
    r.clear()
    return r


def comment(sc, text):
    s = sc.addStatement("Comment")
    s.getProperty("Comment").Value = _b(text)
    return s


def move(sc, kind, base, mat_world, speed=None):
    s = sc.addStatement(kind)
    s.Base = base
    s.Tool = TOOL
    s.Positions[0].PositionInWorld = mat_world
    if kind == "PtpMotion":
        p = s.getProperty("JointSpeed")
        if p is not None:
            p.Value = speed or 0.5
    else:
        p = s.getProperty("MaxSpeed")
        if p is not None:
            p.Value = speed or 500.0
    return s


def setout(sc, port, val):
    s = sc.addStatement("SetBin")
    s.getProperty("OutputPort").Value = port
    s.getProperty("OutputValue").Value = val
    return s


def waitin(sc, port, val):
    s = sc.addStatement("WaitBin")
    s.getProperty("InputPort").Value = port
    s.getProperty("InputValue").Value = val
    return s


def delay(sc, t):
    s = sc.addStatement("Delay")
    s.getProperty("Delay").Value = t
    return s


def call(sc, target):
    s = sc.addStatement("Call")
    s.getProperty("Routine").Value = target
    return s


def at(x, y, z):
    return down(x, y, z)


# --- подпрограммы -----------------------------------------------------------------
home = routine_("HOME")
comment(home, u"Исходная позиция робота")
s = home.addStatement("PtpMotion")
s.Base = ctrl.Bases[0]
s.Tool = TOOL
s.Positions[0].PositionInWorld = HOME_TCP
s.getProperty("JointSpeed").Value = 0.5

stop = routine_("STOP_PRODUCT")
comment(stop, u"Остановить конвейер 1: банка остаётся у датчика (сигнал 105 = выкл)")
setout(stop, 105, False)

start = routine_("START_CONVEYOR1")
comment(start, u"Включить конвейер 1 (сигнал 105 = вкл)")
setout(start, 105, True)

PICK_XY = (250.0, -700.0)
pick = routine_("PICK")
comment(pick, u"Взять банку: быстро PTP над банкой, вниз по прямой LIN, захват сигналом 1, вверх LIN")
move(pick, "PtpMotion", B1, at(PICK_XY[0], PICK_XY[1], TOP + APP))
move(pick, "LinMotion", B1, at(PICK_XY[0], PICK_XY[1], TOP))
setout(pick, 1, True)          # сигнал 1: «взять» инструментом TOOL_1 (настроен в свойствах робота)
delay(pick, 0.3)
move(pick, "LinMotion", B1, at(PICK_XY[0], PICK_XY[1], TOP + APP))

GRID = [(300.0, 590.0), (300.0, 710.0), (420.0, 590.0), (420.0, 710.0)]   # партия 2×2 на конвейере 2 (в BASE_2)
places = []
for k, (x, y) in enumerate(GRID):
    r = routine_("PLACE_%d" % (k + 1))
    comment(r, u"Положить банку %d партии на конвейер 2 (позиция в BASE_2)" % (k + 1))
    move(r, "PtpMotion", B2, at(x, y, TOP + APP))
    move(r, "LinMotion", B2, at(x, y, TOP + 4.0))
    setout(r, 1, False)        # сигнал 1 отрицательный: отпустить
    delay(r, 0.3)
    move(r, "LinMotion", B2, at(x, y, TOP + APP))
    places.append(r)

send = routine_("SEND_BATCH")
comment(send, u"Партия из 4 банок уложена: включить конвейер 2 на 6 с и увезти партию")
setout(send, 106, True)
delay(send, 6.0)
setout(send, 106, False)

# --- главная программа: цикл паллетизации --------------------------------------------------
main = prog.MainRoutine
main.clear()
comment(main, u"Урок 9: перенос партии из 4 банок с конвейера 1 на конвейер 2 в бесконечном цикле")
call(main, home)
setout(main, 106, False)
w = main.addStatement("While")
w.Condition = "True"
sc = w.Scope
for k in range(4):
    comment(sc, u"Банка %d из 4" % (k + 1))
    call(sc, start)
    waitin(sc, 102, True)      # датчик на конце конвейера 1 видит банку
    call(sc, stop)
    call(sc, pick)
    call(sc, places[k])
call(sc, send)

app.Simulation.setInitialState()
result = {"высота_банки": CAN_H, "подпрограммы": [prog.Routines[i].Name for i in range(len(prog.Routines))],
          "операторов_в_Main": len(main.Statements), "в_цикле": len(sc.Statements),
          "калибровка": cal}
