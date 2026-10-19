# Python 2.7 внутри R-Pro. Урок 15: паллетирование (TransportPatternIn + Attach + TransportOut).
import vcMatrix
import vcVector

RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
U_FEED = RD2 + "PM Flow Components/Flow Feeder.rpro"            # «Устройство подачи» (поддоны)
U_PFEED = RD2 + "PM Flow Components/Flow Process Feeder.rpro"   # «Процесс подачи» (банки)
U_NODE = RD2 + "PM Flow Components/Flow Node Process.rpro"      # «Узел процесса»
U_SINK = RD2 + "PM Flow Components/Flow Sink.rpro"
U_CONV = RD2 + "Conveyors/Conveyor 4.01.rpro"
U_PALLET = RD2 + "Products and Containers/EuroPallet_2.rpro"   # «Европоддон» 1200×800×144
U_CAN = RD2 + "Products and Containers/Can.rpro"                # банка Ø70×140

COUNT = (6.0, 4.0, 1.0)      # банок по X, Y, Z
STEP = (180.0, 150.0, 0.0)   # шаг, мм
PALLET_TOP = 144.0

info = {}
feeder = load(U_FEED)
place(feeder, 0.0, 0.0)
conv1 = load(U_CONV)
set_prop(conv1, "ConveyorLength", 3000.0)
snap(feeder, "OutInterface", conv1, "InInterface")
node = load(U_NODE)
info["узел_на_ленте"] = snap(conv1, "OutInterface", node, "InInterface")
pfeed = load(U_PFEED)
nm_ = frame_world(node, "InInterface")
place(pfeed, nm_.P.X + 300.0, nm_.P.Y - 1300.0)
conv2 = load(U_CONV)
set_prop(conv2, "ConveyorLength", 2500.0)
snap(node, "OutInterface", conv2, "InInterface")

pid_p = set_process_id(pfeed, u"Подача банок")
pid_n = set_process_id(node, u"Паллетирование")

# --- шаг 1 урока: типы деталей в группах процессов (Европоддон и Банка) ---------
fm = pc().FlowGroupManager
ptm = pc().ProductTypeManager
cr = beh(feeder, typ="rProductCreator")
cr.SingleFeed.getProperty("Interval").Value = 400.0   # поддоны редко: пока идёт укладка, следующий не нужен
r1 = new_line_group(feeder, u"Поддоны", u"Европоддон", U_PALLET)
g_pal = group_by_name(u"Поддоны")
g_can = fm.createGroup(_b(u"Банки"))
t_can = ptm.createProductType(_b(u"Банка"), g_can, False)
t_can.ComponentUri = _b(U_CAN)

# --- шаг 2: операции. «Процесс подачи» создаёт банку и отдаёт; узел паллетирует -------
source_routine(pfeed, pid_p, t_can)
r = clear_routine(node, pid_n)
stmt(r, "TransportIn", Mode=0, Source="From Container", ProductVariableName="Pallet",
     AcceptAllProductTypes=False, AcceptedFlowGroups=[g_pal])
pat = stmt(r, "TransportPatternIn", ProductVariableName="Can", AcceptAllProductTypes=False,
           AcceptedFlowGroups=[g_can])
# шаблон укладки: смещение (угол поддона, высота поддона), число и шаг (шаги 3–4 урока)
off = vcMatrix.new()
off.translateAbs(-STEP[0] * (COUNT[0] - 1) / 2.0, -STEP[1] * (COUNT[1] - 1) / 2.0, PALLET_TOP)
pat.getProperty("Offset").Value = off
pat.getProperty("PatternCount").Value = vcVector.new(*COUNT)
pat.getProperty("PatternStep").Value = vcVector.new(*STEP)
stmt(r, "AttachProduct", Parent="Pallet", Child="Can")          # шаг 5: Attach
stmt(r, "TransportOut", Destination="To Container", Container=beh(node, "ComponentContainer__HIDE__"),
     ProductVariableName="Pallet")   # шаг 6: поддон с банками уезжает на конвейер 2

# --- маршруты и транспортные связи -----------------------------------------------
f1 = set_flow([pid_n], g_pal)
f2 = set_flow([pid_p, pid_n], g_can)
link(pfeed, node, "InterpolatingTransport", g_can)
# перелёт банки быстрый: по 0,5 с на взятие и укладку (по умолчанию по 5 с)
lk = list(pc().TransportSystem.Links)[-1]
_lp = dict((str(p.Name), p) for p in lk.Properties)
info["свойства_связи"] = sorted(_lp.keys())
if "UseCustomParameters" in _lp:
    _lp["UseCustomParameters"].Value = True
for _n in ("PickTime", "PlaceTime"):
    if _n in _lp:
        _lp[_n].Value = 0.5
app.Simulation.setInitialState()
info["маршруты"] = [f1, f2]
info["связей"] = len(list(pc().TransportSystem.Links))
info["компонентов"] = len(app.Components)
result = info
