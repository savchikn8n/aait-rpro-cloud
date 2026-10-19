# Python 2.7 внутри R-Pro. Урок 5: виды (редактор видов) и программа аниматора камеры.
# Ожидает в сцене компоненты урока 2–3: «Устройство подачи», «ТК робота», станок.


def _pos(name):
    c = app.findComponent(name)
    p = c.PositionMatrix.P
    return [p.X, p.Y, p.Z]


def _look(name, coi, eye, render=6):
    camera(coi, eye)
    if app.findView(name) is not None:
        app.deleteView(name)
    v = app.createView(name)
    try:
        v.ShadingRender = render
    except Exception:
        pass
    return name


feeder = _pos(u"Устройство подачи")
robot = _pos(u"ТК робота")
mill = _pos(u"Параметрический вертикально-фрезерный станок")

bs = [b for b in [_world_box(c) for c in app.Components] if b]
x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
x1, y1 = max(b[3] for b in bs), max(b[4] for b in bs)
cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
span = max(x1 - x0, (y1 - y0) * 1.3, 4000.0) * 1.15

names = []
# Вид 1 — вся планировка издалека
names.append(_look(u"Вид 1", [cx, cy, 0.0], [cx, cy - 0.55 * span, 0.95 * span]))
# Вид 2 — подача и первый конвейер
names.append(_look(u"Вид 2", [feeder[0] + 1500, feeder[1], 600.0], [feeder[0] - 1200, feeder[1] - 3500, 2200.0]))
# Вид 3 — робот крупно (берёт и кладёт заготовки)
names.append(_look(u"Вид 3", [robot[0], robot[1] - 700, 800.0], [robot[0] - 1800, robot[1] - 4200, 2400.0]))
# Вид 4 — станок: робот кладёт заготовку в станок
names.append(_look(u"Вид 4", [mill[0], mill[1], 900.0], [mill[0] - 2500, mill[1] - 3800, 2600.0]))
# Вид 5 — отъезд на общий план с другой стороны
names.append(_look(u"Вид 5", [cx, cy, 0.0], [cx + 0.4 * span, cy - 0.6 * span, 0.8 * span]))

# аниматор камеры: строка = вид + время, к которому он должен быть достигнут
item = app.findLayoutItem("ViewAnimation")
if not item:
    item = app.createLayoutItem("ViewAnimation")
routine = item.Program.MainRoutine
routine.clear()
program = []


def _view(name, t):
    s = routine.addStatement(VC_STATEMENT_VIEW)
    s.Delay = float(t)
    s.View = _b(name)
    program.append(("view", name, t))


def _wait(t):
    s = routine.addStatement(VC_STATEMENT_DELAY)
    s.Delay = float(t)
    program.append(("wait", t))


_view(u"Вид 1", 0)
_wait(10)       # стоим на общем плане до 10-й секунды
_view(u"Вид 2", 15)   # летим к подаче, к 25-й секунде там
_wait(5)
_view(u"Вид 3", 10)   # к роботу, к 40-й секунде
_wait(10)
_view(u"Вид 4", 10)   # к станку, к 60-й секунде
_wait(20)
_view(u"Вид 5", 15)   # отъезд, к 95-й секунде (1 мин 35 с)

result = {"виды": names, "программа": program, "всего_с": 10 + 15 + 5 + 10 + 10 + 10 + 20 + 15}
