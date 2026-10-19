# Python 2.7 внутри R-Pro. Урок 11: сборка роутера из 5 деталей на ручной рабочей станции.
# Детали Router_1..5.rpro записывает py3-часть (PARTS_DIR). Схема сборки — проверенная в 2.2.2 (assembly_builder):
# пост = GetAssembly (какие шаги нужны) + TransportIn в режиме «сборка» (деталь — в своё гнездо), человек носит детали.
# Вариант из видео «5 × TransportIn → GetAssembly → Construct» в 2.2.2 уводит перенос в бесконечный цикл в нулевое
# время (CannotTransportAlreadyAtTarget, часы стоят на 50 с) и замораживает симуляцию — не использовать.
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
U_NODE = RD2 + "PM Flow Components/Flow Node Process.rpro"        # «Узел процесса» — склад детали
U_MANUAL = RD2 + "PM Flow Components/Manual Workstation v2.rpro"   # «Ручная рабочая станция»
U_INLINE = RD2 + "PM Flow Components/Inline Process.rpro"       # пост с кадрами ResourceLocation и Center
U_HTC =RD2 + "PM Transport Controllers/Human Transport Controller.rpro"
U_HUMAN = RD2 + "PM Resources/Human (Ivan).rpro"
U_AREA = RD2 + "PM Resource Utilities/Pathway Area.rpro"
NAMES = [u"Платформа", u"Плата", u"Крышка", u"WAN-порт", u"Антенна"]
info = {}

# 1. планировка: склады деталей (5 узлов), станция сборки, следующий этап, ТК человека и двое людей
mw1 = load(U_INLINE)
set_prop(mw1, "ConveyorLength", 800.0)
place(mw1, 4000.0, 0.0)
mw2 = load(U_MANUAL)
place(mw2, 8000.0, 0.0)
pid_asm = set_process_id(mw1, u"Сборка роутера")
pid_next = set_process_id(mw2, u"Следующий этап")
stores = []
pids = []
for k in range(5):
    nd = load(U_NODE)
    place(nd, 1800.0 + k * 1000.0, 2500.0)
    pids.append(set_process_id(nd, u"Склад: " + NAMES[k]))
    stores.append(nd)
htc = load(U_HTC)
place(htc, 6000.0, -3500.0)
people = []
for k in range(2):
    h = load(U_HUMAN)
    place(h, 5500.0 + k * 1000.0, -5000.0)
    people.append(h)
connect_people(htc, people)

# 2. вкладка «Детали»: группа «Детали роутера» (5 типов с видом из файлов) и группа «Роутер» с типом-сборкой из 5 шагов
fm = pc().FlowGroupManager
g_parts = fm.createGroup(_b(u"Детали роутера"))
g_asm = fm.createGroup(_b(u"Роутер"))
T = {}
for k in range(5):
    T[NAMES[k]] = part_type(NAMES[k], g_parts, "file:///" + PARTS_DIR + "/Router_%d.rpro" % (k + 1))
steps = []
zs = [0.0, 20.0, 26.0, 26.0, 26.0]
xs = [0.0, 0.0, 0.0, 70.0, -60.0]
for k in range(5):
    steps.append({"name": NAMES[k], "parent": None if k == 0 else NAMES[0], "rel": None,
                  "slots": [{"types": [NAMES[k]], "pos": [xs[k], 0.0, zs[k], 0.0, 0.0, 0.0], "order": k + 1}]})
A = define_assembly(u"Роутер", g_asm, steps, T)
info["шагов_сборки"] = [_u(A.RootStep.Name)] + [_u(s.Name) for s in A.RootStep.ChildSteps]

# 3. склады: платформа создаётся сразу как начало сборки (шаг «Платформа»), остальные — отдельными деталями
source_routine(stores[0], pids[0], A, [asm_find_step(A, _b(NAMES[0]))], 40.0)
for k in range(1, 5):
    source_routine(stores[k], pids[k], T[NAMES[k]])

# 4. пост сборки: принять платформу, заказать детали шагов 2–5, поработать 6 с (человек), отдать дальше
post_routine(mw1, pid_asm, g_asm, A, NAMES[1:], worker=htc, work_s=6.0)
sink_routine(mw2, pid_next, 3.0)

# 5. маршруты и связи (исполнитель — ТК человека)
f1 = set_flow([pids[0], pid_asm, pid_next], g_asm)       # сборка: платформа → пост → следующий этап
f2 = set_flow([list(pids[1:]), pid_asm], g_parts)        # детали: из любого склада → на пост
link(stores[0], mw1, htc, g_asm)
for k in range(1, 5):
    link(stores[k], mw1, htc, g_parts)
link(mw1, mw2, htc, g_asm)
crew_area(htc, U_AREA, 1500.0)
app.Simulation.setInitialState()
info["маршруты"] = [f1, f2]
info["связей"] = len(list(pc().TransportSystem.Links))
info["компонентов"] = len(app.Components)
result = info
