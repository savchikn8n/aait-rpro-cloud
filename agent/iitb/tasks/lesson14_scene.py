# Python 2.7 внутри R-Pro. Урок 14: ожидание сигнала — двери станка (WaitSignal + MoveJoint).
# Станок строим на «Узле процесса» из каталога: только такой компонент попадает в менеджер процессов R-Pro
# (у компонента, созданного с нуля, процесс в «Операциях» не появляется и не запускается). Процесс станка:
# принять изделие → ждать DoorSignal = True → двери открыть → ждать False → закрыть → отдать изделие дальше.
import vcMatrix
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
U_NODE = RD2 + "PM Flow Components/Flow Node Process.rpro"
U_PALLET = RD2 + "Products and Containers/EuroPallet_2.rpro"
info = {}

comp = load(U_NODE)
comp.Name = _b(u"Станок")
place(comp, 3000.0, 0.0)
rf = comp.RootFeature
def blk(f, name, l, w, h, x, y, z):
    b = f.createFeature(VC_BLOCK, name)
    b.getProperty("Length").Value = l; b.getProperty("Width").Value = w; b.getProperty("Height").Value = h
    m = vcMatrix.new(); m.translateAbs(x, y, z); b.PositionMatrix = m
    return b
blk(rf, u"Корпус", "1400", "1200", "1800", 0, 0, 0)
d1 = comp.createNode(VC_NODE, "Link_1")
blk(d1.RootFeature, u"Дверь 1", "550", "20", "1200", -300, -610, 300)
servo = comp.createBehaviour(VC_SERVOCONTROLLER, "ServoController")
d1.JointType = VC_JOINTTYPE_TRANSLATIONAL
d1.Dof.AxisType = VC_JOINTAXIS_PLUS_X
d1.Dof.Name = "J1"
d1.Dof.MinLimit = "0"; d1.Dof.MaxLimit = "550"; d1.Dof.Controller = servo
d2 = comp.createNode(VC_NODE, "Link_2")
blk(d2.RootFeature, u"Дверь 2", "550", "20", "1200", 300, -610, 300)
d2.JointType = VC_JOINTTYPE_TRANSLATIONAL_FOLLOWER
d2.Dof.AxisType = VC_JOINTAXIS_MINUS_X
d2.Dof.Driver = d1.Dof
sig = comp.createBehaviour(VC_BOOLEANSIGNAL, "DoorSignal")

# процесс станка
pid = set_process_id(comp, u"Двери станка")
r = clear_routine(comp)
def move(target, t):
    # порядок важен: смена контроллера сбрасывает соединение, поэтому Joint — отдельным шагом после Controller
    m = stmt(r, "MoveJoint", Controller=servo, TargetValue=target, MotionTime=t)
    m.getProperty("Joint").Value = servo.getJoint(0)   # vcJoint сервоконтроллера (Dof подставлять нельзя — вешает поток моста)
    return m
stmt(r, "TransportIn", Mode=0, Source="From Previous Process", ProductVariableName="P", AcceptAllProductTypes=True)
stmt(r, "WaitSignal", Component=comp, Signal=sig, WaitTrigger=True)     # DoorSignal = True → двери едут на 550 мм за 2 с
move(550.0, 2.0)
stmt(r, "WaitSignal", Component=comp, Signal=sig, WaitTrigger=False)    # DoorSignal = False → двери возвращаются в 0 за 2 с
move(0.0, 2.0)
stmt(r, "TransportOut", Destination="To Next Process", ProductVariableName="P")
info["операторов"] = [str(s.Type) for s in r.Statements]

# подача изделий до станка и отгрузка после него — чтобы процесс станка запускался потоком
fm = pc().FlowGroupManager
g = fm.createGroup(_b(u"Станок"))
t = part_type(u"Изделие", g, U_PALLET)
src = load(U_NODE)
place(src, 0.0, 0.0)
snk = load(U_NODE)
place(snk, 6000.0, 0.0)
pid_src = set_process_id(src, u"Подача изделий")
pid_snk = set_process_id(snk, u"Отгрузка изделий")
source_routine(src, pid_src, t)
sink_routine(snk, pid_snk, 1.0)
info["маршрут"] = set_flow([pid_src, pid, pid_snk], g)
link(src, comp, "InterpolatingTransport", g)
link(comp, snk, "InterpolatingTransport", g)
info["компонент"] = _u(comp.Name)
info["J1"] = [str(d1.Dof.Name), str(d1.Dof.MinLimit), str(d1.Dof.MaxLimit)]
app.Simulation.setInitialState()
result = info
