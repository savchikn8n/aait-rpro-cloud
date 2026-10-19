# Python 2.7 внутри R-Pro. Урок 10 (окончание): робот на позиционере + программа с движением внешней оси.
RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
rob = load(RD2 + "Robots/Universal articulated robot.rpro")
comp = app.findComponent(u"Позиционер")
info["робот_на_позиционере"] = snap(comp, "MountInterface", rob, "RobotPositioner")
info["робот_мир"] = m2l(rob.WorldPositionMatrix)

ex = beh(rob, typ="rRobotExecutor")
prog = ex.Program
main = prog.MainRoutine
main.clear()
s = main.addStatement("Comment")
s.getProperty("Comment").Value = _b(u"Урок 10: робот ездит вместе с кареткой позиционера (7-я ось = J1 позиционера)")


def ptp(a1, a2, a3, a4, a5, a6, ext, speed=0.5):
    s = main.addStatement("PtpMotion")
    s.Positions[0].setJoints([float(v) for v in (a1, a2, a3, a4, a5, a6, ext)])
    p = s.getProperty("JointSpeed")
    if p is not None:
        p.Value = speed
    return s


ptp(0, 0, 0, 0, 0, 0, 0)                       # первая точка — PTP, каретка в начале
ptp(0, -30, 60, 0, 60, 0, 0)                   # поза «взять»
ptp(40, -30, 60, 0, 60, 0, 600)                # каретка на середину, робот повернулся
ptp(80, -30, 60, 0, 60, 0, 1200)               # каретка до упора (1500 − длина каретки)
ptp(0, 0, 0, 0, 0, 0, 0)                       # домой
info["операторов"] = len(main.Statements)
app.Simulation.setInitialState()
result = info
