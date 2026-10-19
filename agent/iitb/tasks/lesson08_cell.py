# Python 2.7 внутри R-Pro. Уроки 8–9: ячейка «робот + два конвейера + датчик/двигатели + захват».
# Шаблон из PDF: подача → конвейер 1 (датчик на конце, двигатель) → робот на подставке → конвейер 2 (двигатель).
# Все размеры в мм, мир: робот в начале координат.
import vcMatrix
import vcVector

RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
U_PED = RD2 + "Robot Pedestals/alupedestal.rpro"            # «Параметрическая тумба робота» (подставка)
U_ROB = RD2 + "Robots/Universal articulated robot.rpro"      # «Шарнирный робот-манипулятор»
U_GRIP = RD2 + "Robot Tools/SingleCupVacuumGripper.rpro"     # «Вакуумный захват с одной чашкой»
U_CONV = RD2 + "Conveyors/Conveyor 4.01.rpro"
U_MOTOR = RD2 + "Conveyor Utilities/conveyor_motor.rpro"
U_SENS = RD2 + "Conveyor Utilities/conveyor_sensor.rpro"
U_FEED = RD2 + "PM Flow Components/Flow Feeder.rpro"
U_CAN = RD2 + "Products and Containers/Can.rpro"

info = {}


def nm(n, o, a, p):
    m = vcMatrix.new()
    m.N = vcVector.new(*n)
    m.O = vcVector.new(*o)
    m.A = vcVector.new(*a)
    m.P = vcVector.new(*p)
    return m


def down(x, y, z):
    """Инструмент смотрит вниз (ось Z инструмента = −Z мира), мировые координаты точки."""
    return nm((1, 0, 0), (0, -1, 0), (0, 0, -1), (x, y, z))


def build_cell():
    ped = load(U_PED)
    place(ped, 0.0, 0.0)
    rob = load(U_ROB)
    info["подставка_робот"] = snap(ped, "RobotInterface", rob, "RobotPositioner")
    grip = load(U_GRIP)
    info["захват"] = snap(rob, "Tool", grip, "EOAT_MountInterface")
    # конвейер 1 (жёлтый): вдоль +X, справа от робота по Y−; поток к роботу
    c1 = load(U_CONV)
    set_prop(c1, "ConveyorLength", 1500.0)
    set_prop(c1, "ConveyorWidth", 400.0)
    set_prop(c1, "ConveyorHeight", 600.0)
    place(c1, -1200.0, -700.0)
    # конвейер 2 (синий): вдоль +X, по Y+, начинается рядом с роботом, уносит партию дальше
    c2 = load(U_CONV)
    set_prop(c2, "ConveyorLength", 1500.0)
    set_prop(c2, "ConveyorWidth", 400.0)
    set_prop(c2, "ConveyorHeight", 600.0)
    place(c2, -200.0, 700.0)
    try:
        c1.getProperty("Materials::BeltMaterial").Value = app.findMaterial("yellow")
        c2.getProperty("Materials::BeltMaterial").Value = app.findMaterial("blue")
    except Exception:
        pass
    # подача банок в начало конвейера 1
    f = load(U_FEED)
    snap(c1, "InInterface", f, "OutInterface")
    # двигатели и датчик через интерфейс конвейера (PnP), датчик — на конце конвейера 1
    m1 = load(U_MOTOR)
    beh(c1, "SensorInterface").connect(beh(m1, "PathInterface"))
    m2 = load(U_MOTOR)
    beh(c2, "SensorInterface").connect(beh(m2, "PathInterface"))
    s1 = load(U_SENS)
    beh(c1, "SensorInterface").connect(beh(s1, "PathInterface"))
    return ped, rob, grip, c1, c2, f, m1, m2, s1


def prepare_robot(rob, grip, c1, c2, m1, m2, s1):
    """Ввод в эксплуатацию (урок 8): сигналы, TOOL_1, BASE_1, BASE_2."""
    ctrl = beh(rob, typ="rRobotExecutor").Controller
    res = {}
    # датчик — на конце конвейера 1, двигатель — ближе к началу (по оси конвейера)
    beh(s1, "ComponentPathSensor").getProperty("Distance").Value = 1430.0   # положение вдоль конвейера, мм
    beh(m1, "ComponentPathSensor").getProperty("Distance").Value = 300.0
    res["датчик_мир"] = m2l(s1.WorldPositionMatrix)
    # сигналы: датчик → вход робота 102; выход 105 → двигатель 1, выход 106 → двигатель 2
    inp, outp = beh(rob, "Inputs"), beh(rob, "Outputs")
    inp.connect(102, beh(s1, "SensorBooleanSignal"))
    outp.connect(105, beh(m1, "MotorSignal"))
    outp.connect(106, beh(m2, "MotorSignal"))
    # TOOL_1: центр вакуумной чашки (конец захвата, 60 мм от фланца по оси Z инструмента)
    t = ctrl.Tools[0]
    t.PositionMatrix = mat(0.0, 0.0, 60.0)
    res["TOOL_1"] = m2l(t.PositionMatrix)
    # BASE_1 — на конвейере 1 в точке остановки банки; BASE_2 — на конвейере 2 (начало площадки укладки)
    RW = rob.WorldPositionMatrix
    inv = vcMatrix.new(RW)
    inv.invert()
    for idx, (wx, wy, wz) in enumerate(((250.0, -700.0, 600.0), (300.0, 650.0, 600.0))):
        b = ctrl.Bases[idx]
        b.PositionMatrix = inv * nm((1, 0, 0), (0, 1, 0), (0, 0, 1), (wx, wy, wz))
        res[str(b.Name)] = m2l(b.PositionMatrix)
    return res, ctrl
