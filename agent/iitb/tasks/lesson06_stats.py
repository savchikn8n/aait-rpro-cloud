# Python 2.7 внутри R-Pro. Урок 6: лист статистики (Dashboard): шаблон листа 2×2, четыре графика.
import vcVector

dash = app.Dashboard
# убрать пробную вкладку, если осталась
for t in list(dash.Tabs):
    if t.Name in (u"Проба", u"Состояния и выпуск"):
        dash.deleteTab(t)
tab = dash.createTab(_b(u"Состояния и выпуск"), True)
# шаблон листа: «2-Столбец 2-Строка» — четыре плитки (индекс по списку Layouts)
want = None
for i, l in enumerate(tab.Layouts):
    if _u(str(l[0])).startswith(u"2-Столбец 2-Строка"):
        want = i
        break
if want is not None:
    tab.SelectedLayout = want
tab.clearLayout()

mill = app.findComponent(u"Параметрический вертикально-фрезерный станок")
conv2 = app.findComponent(u"Конвейер #2")
feeder = app.findComponent(u"Устройство подачи")
tc = app.findComponent(u"ТК робота")


def st(c):
    return c.findBehavioursByType(VC_STATISTICS)[0]


COL = {"Idle": (1.0, 0.85, 0.0), "Busy": (0.1, 0.7, 0.2), "Blocked": (0.85, 0.1, 0.1),
       "Setup": (0.0, 0.7, 0.8), "Failed": (0.6, 0.0, 0.0)}


def pie_states(tile, comp, title):
    ch = tab.createChart(tile, VC_CHARTTYPE_PIE, True)
    ch.Name = _b(title)
    ch.TitleVisibility = True
    ch.LegendVisibility = True
    s0 = st(comp)
    for state, ru in (("Idle", u"Ожидает"), ("Busy", u"Занят"), ("Blocked", u"Заблокирован")):
        s = ch.addSeries()
        s.Name = _b(ru)
        s.Property = s0.getProperty(state + "Percentage")
        s.Colors = [vcVector.new(*COL[state])]
    return ch


tiles = list(tab.Charts)
charts = []
# 1. диаграмма состояний станка (круговая, за всё время симуляции)
charts.append(pie_states(tiles[0], mill, u"Станок: состояния"))
# 2. выпуск: деталей, покинувших конвейер 2 (линия)
ch = tab.createChart(list(tab.Charts)[1], VC_CHARTTYPE_LINE, True)
ch.Name = _b(u"Выпуск: деталей прошло по конвейеру 2")
ch.TitleVisibility = True
ch.LegendVisibility = False
s = ch.addSeries()
s.Name = _b(u"-")
s.Components = [conv2]
s.Property = st(conv2).getProperty("PartsExited")
s.Colors = [vcVector.new(0.1, 0.4, 0.9)]
charts.append(ch)
# 3. загрузка (Utilization) станка и конвейеров — столбцы
ch = tab.createChart(list(tab.Charts)[2], VC_CHARTTYPE_COLUMN, True)
ch.Name = _b(u"Загрузка оборудования, %")
ch.TitleVisibility = True
ch.LegendVisibility = True
for comp, ru, color in ((mill, u"Станок", (0.1, 0.7, 0.2)), (conv2, u"Конвейер 2", (0.1, 0.4, 0.9))):
    s = ch.addSeries()
    s.Name = _b(ru)
    s.Property = st(comp).getProperty("Utilization")
    s.Colors = [vcVector.new(*color)]
charts.append(ch)
# 4. деталей в станке в среднем (PartsAverageCount) — столбец
ch = tab.createChart(list(tab.Charts)[3], VC_CHARTTYPE_BAR, True)
ch.Name = _b(u"Деталей в станке: среднее")
ch.TitleVisibility = True
ch.LegendVisibility = False
s = ch.addSeries()
s.Name = _b(u"-")
s.Property = st(mill).getProperty("PartsAverageCount")
s.Colors = [vcVector.new(0.8, 0.4, 0.0)]
charts.append(ch)

app.Simulation.Statistics.SamplingInterval = 60.0   # интервал обновления графиков: раз в минуту
result = {"вкладка": tab.Name, "шаблон": want, "графиков": len(charts),
          "названия": [_u(c.Name) for c in charts]}
