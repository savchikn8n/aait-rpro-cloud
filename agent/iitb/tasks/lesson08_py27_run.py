ped, rob, grip, c1, c2, feeder, m1, m2, s1 = build_cell()
cal, ctrl = prepare_robot(rob, grip, c1, c2, m1, m2, s1)
# банки на конвейер 1: тип «Банка», подача раз в 8 с
cr = beh(feeder, typ="rProductCreator")
cr.SingleFeed.getProperty("Interval").Value = 8.0
new_line_group(feeder, u"Банки", u"Банка", U_CAN)
app.Simulation.setInitialState()
info["калибровка"] = cal
info["компоненты"] = [c.Name for c in app.Components]
result = info
