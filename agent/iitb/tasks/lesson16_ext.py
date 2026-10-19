# Python 2.7 внутри R-Pro. Урок 16: депаллетизация — продолжение сцены урока 15 (lesson15_scene.py выполнен перед ним).
HUMAN_TC = RD2 + "PM Transport Controllers/Human Transport Controller.rpro"
IVAN = RD2 + "PM Resources/Human (Ivan).rpro"
AREA = RD2 + "PM Resource Utilities/Pathway Area.rpro"

# 1. клонируем конвейер и подключаем PnP: конвейер 2 → узел 2 («депаллетизация») → конвейер 3
node2 = load(U_NODE)
snap(conv2, "OutInterface", node2, "InInterface")
conv3 = load(U_CONV)
set_prop(conv3, "ConveyorLength", 2000.0)
snap(node2, "OutInterface", conv3, "InInterface")
# 2. место отгрузки банок: «Процесс утилизации» (приёмка) рядом с узлом 2
sink = load(U_SINK)
p2 = frame_world(node2, "InInterface").P
place(sink, p2.X + 300.0, p2.Y - 1300.0)
pid_2 = set_process_id(node2, u"Депаллетизация")
pid_s = set_process_id(sink, u"Приёмка банок")

# 3. логика узла 2: принять поддон → Detach («Открепить», «Отсоединить многие») → отправить банки и поддон
r2 = clear_routine(node2, pid_2)
stmt(r2, "TransportIn", Mode=0, Source="From Container", ProductVariableName="Pallet",
     AcceptAllProductTypes=False, AcceptedFlowGroups=[g_pal])
stmt(r2, "DetachProduct", ProductVariableName="Pallet", DetachedVariableName="Can", DetachMany=True,
     AcceptAllProductTypes=True)
stmt(r2, "TransportOut", Destination="To Next Process", ProductVariableName="Can")          # банки — на приёмку
stmt(r2, "TransportOut", Destination="To Container", Container=beh(node2, "ComponentContainer__HIDE__"),
     ProductVariableName="Pallet")                                                           # пустой поддон — на конвейер 3
sink_routine(sink, pid_s, 1.0)

# 4. маршруты: поддон — узел 1 → узел 2; банка — подача → узел 1 → узел 2 → приёмка
f1 = set_flow([pid_n, pid_2], g_pal)
f2 = set_flow([pid_p, pid_n, pid_2, pid_s], g_can)

# 5. человек: ТК человека + Иван, зоны прохода; исполнитель на связях подачи банок и разгрузки (шаг 3 урока)
tc = load(HUMAN_TC)
nx = frame_world(node2, "InInterface").P
place(tc, nx.X - 1500.0, nx.Y - 3600.0)
ivan = load(IVAN)
place(ivan, nx.X - 1500.0, nx.Y - 4800.0)
connect_people(tc, [ivan])
ts = pc().TransportSystem
for l in list(ts.Links):
    ts.deleteTransportLink(l)          # убираем прежнюю связь-«перелёт», ставим связи с человеком
link(pfeed, node, tc, g_can)
link(node2, sink, tc, g_can)
a = crew_area(tc, AREA, 1500.0)
info["зона_прохода"] = a
app.Simulation.setInitialState()
info["урок16"] = {"маршруты": [f1, f2], "связей": len(list(ts.Links)), "компонентов": len(app.Components)}
result = info
