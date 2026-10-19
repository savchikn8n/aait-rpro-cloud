# Python 2.7 внутри R-Pro. Урок 12: склад — ТК крана-штабелера, кран, складская полка, процессы наполнения и отгрузки.
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
U_TC = RD2 + "PM Transport Controllers/Stacker Crane Transport Controller.rpro"   # «ТК крана-штабелера»
U_CRANE = RD2 + "PM Resources/Single Pallet Stacker Crane.rpro"                     # «Кран-штабелер — одиночный поддон»
U_SHELF = RD2 + "PM Warehousing/Warehouse Advanced Shelf.rpro"                        # «Складская полка» (Buffer)
U_NODE = RD2 + "PM Flow Components/Flow Node Process.rpro"                            # «Узел процесса»
U_SINK = RD2 + "PM Flow Components/Flow Sink.rpro"
U_CONV = RD2 + "Conveyors/Conveyor 4.01.rpro"
U_PALLET = RD2 + "Products and Containers/EuroPallet_2.rpro"
info = {}

# 1. транспортный контроллер крана (путь крана) и кран: PnP к интерфейсу «Кран А»
tc = load(U_TC)
place(tc, 0.0, 0.0)
crane = load(U_CRANE)
info["кран_на_пути"] = snap(tc, "CraneA", crane, "PMResource")
# 2. складская полка вдоль пути крана
shelf = load(U_SHELF)
place(shelf, 0.0, 0.0)
info["полка_мм"] = [round(v) for v in _world_box(shelf)]
# места загрузки/выгрузки полки (FlowIn / FlowOut) — туда ставим узлы процесса
fin = shelf.PositionMatrix * shelf.getProperty("FlowInResourceLocation").Value
fout = shelf.PositionMatrix * shelf.getProperty("FlowOutResourceLocation").Value
info["flow_in"] = m2l(fin)
info["flow_out"] = m2l(fout)

# 3. узлы: «Создание» (создаёт поддон и отправляет в буфер) и «Отгрузка» на конвейере у выхода склада
node_in = load(U_NODE)
place(node_in, fin.P.X, fin.P.Y - 1500.0)
conv = load(U_CONV)
set_prop(conv, "ConveyorLength", 3000.0)
place(conv, fout.P.X, fout.P.Y + 1500.0, 0.0, 0.0)
node_out = load(U_NODE)
place(node_out, fout.P.X + 3200.0, fout.P.Y + 1500.0)
pid_in = set_process_id(node_in, u"Создание поддонов")
pid_sh = _u(routine(shelf).Name)
pid_out = set_process_id(node_out, u"Отгрузка")

# 4. деталь (шаг «Детали»): поддон в группе «Склад»
fm = pc().FlowGroupManager
ptm = pc().ProductTypeManager
g = fm.createGroup(_b(u"Склад"))
t = ptm.createProductType(_b(u"Поддон"), g, False)
t.ComponentUri = _b(U_PALLET)
# 5. логика: создание → в буфер полки (параллельно до 10), выдача → удаление
source_routine(node_in, pid_in, t, delay_s=20.0)
sink_routine(node_out, pid_out, 3.0)
# 6. маршрут и транспортные связи: исполнитель — кран (ТК крана-штабелера)
fl = set_flow([pid_in, pid_sh, pid_out], g)
link(node_in, shelf, tc, g)
link(shelf, node_out, tc, g)
info["маршрут"] = fl
info["связей"] = len(list(pc().TransportSystem.Links))
app.Simulation.setInitialState()
info["компонентов"] = len(app.Components)
result = info
