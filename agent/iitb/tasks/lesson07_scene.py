# Python 2.7 внутри R-Pro. Урок 7: ручные операции — люди, зоны прохода, инструмент (вилочная тележка).
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
FEED = RD2 + "PM Flow Components/Flow Process Feeder.rpro"       # «Процесс подачи»
MANUAL = RD2 + "PM Flow Components/Manual Workstation v2.rpro"   # «Ручная рабочая станция»
SINK = RD2 + "PM Flow Components/Flow Sink.rpro"                 # «Процесс утилизации»
HUMAN_TC = RD2 + "PM Transport Controllers/Human Transport Controller.rpro"
IVAN = RD2 + "PM Resources/Human (Ivan).rpro"
MARIA = RD2 + "PM Resources/Human (Maria).rpro"
AREA = RD2 + "PM Resource Utilities/Pathway Area.rpro"            # «Зона прохода»
IDLE = RD2 + "PM Resource Utilities/Idle Location.rpro"           # «Местоположение ожидания»
JACK = RD2 + "PM Resource Utilities/PalletJack Resource Tool.rpro"  # «Вилочная тележка» (инструмент)

STEP = 3600.0
feeder = load(FEED);   place(feeder, 0, 0)
mw1 = load(MANUAL);    place(mw1, STEP, 0)
mw2 = load(MANUAL);    place(mw2, 2 * STEP, 0)
sink = load(SINK);     place(sink, 3 * STEP, 0)
pid_f = set_process_id(feeder, u"Подача")
pid_1 = set_process_id(mw1, u"Ручной процесс")
pid_2 = set_process_id(mw2, u"Ручной процесс 2")
pid_s = set_process_id(sink, u"Утилизация")

tc = load(HUMAN_TC);   place(tc, 1.5 * STEP, -4800)
people = []
for k, uri in enumerate((IVAN, MARIA, IVAN)):
    h = load(uri)
    place(h, (0.5 + k) * STEP * 1.0, -6200)
    people.append(h)
tool = load(JACK);     place(tool, -1500, -3000)
idle = []
for k in range(2):
    i = load(IDLE)
    place(i, 2.0 * STEP + k * 1500, -6800)
    idle.append(i)
connect_people(tc, people, idle, [tool])


def rl(c):
    """Точка ResourceLocation процесса в мире (куда подходит человек)."""
    f = find_feature(c, "ResourceLocation")
    m = c.PositionMatrix * f.NodePositionMatrix if f is not None else c.PositionMatrix
    return m.P


def zone(cx, cy, lx, ly):
    a = load(AREA)
    place(a, cx, cy)
    set_prop(a, "AreaLength", float(lx))
    set_prop(a, "AreaWidth", float(ly))
    beh(tc, "Pathways").connect(beh(a, "Зона Прохода"))
    return a


# зоны прохода: коридор вдоль станций + «отростки» к точкам, где человек работает
pts = [rl(c) for c in (feeder, mw1, mw2, sink)]
corr_y = -2600.0
x0, x1 = min(p.X for p in pts) - 1200, max(p.X for p in pts) + 1200
zones = [zone((x0 + x1) / 2.0, corr_y, x1 - x0, 1300.0)]
for p in pts:
    y_lo, y_hi = min(corr_y, p.Y), max(corr_y, p.Y)
    zones.append(zone(p.X, (y_lo + y_hi) / 2.0, 1300.0, (y_hi - y_lo) + 1300.0))
# коридор к людям и местам отдыха
zones.append(zone(1.5 * STEP, (corr_y - 6800) / 2.0 - 100, 1300.0, abs(-6800 - corr_y) + 1300.0))
zones.append(zone(1.5 * STEP, -6500.0, 2.0 * STEP + 3000.0, 1800.0))
tc.getProperty("UseGlobalArea").Value = False

# маршрут деталей и транспортные связи с исполнителем «ТК человека»
g = flow_group()
fl = set_flow([pid_f, pid_1, pid_2, pid_s], g)
link(feeder, mw1, tc, g)
link(mw1, mw2, tc, g)
link(mw2, sink, tc, g)
# первая связь везёт деталь на вилочной тележке: Tool = имя инструмента
lk = list(pc().TransportSystem.Links)[0]
tp = lk.getProperty("Tool")
steps = _safe(tp, "StepValues")
lk.getProperty("ToolName").Value = _b(tool.Name)
try:
    tp.Value = steps[1] if steps and len(steps) > 1 else tp.Value
except Exception:
    pass

result = {"группа": g.Name, "маршрут": fl, "связей": len(list(pc().TransportSystem.Links)),
          "Tool_варианты": [str(s) for s in (steps or [])], "Tool": str(tp.Value), "ToolName": tool.Name,
          "людей": len(people), "зон": len(zones), "компонентов": len(app.Components)}
