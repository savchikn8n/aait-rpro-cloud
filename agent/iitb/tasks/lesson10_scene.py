# Python 2.7 внутри R-Pro. Урок 10: собственный компонент — позиционер робота с подвижной кареткой.
# Шаги урока: геометрия → звено → свойство → тип движения и пределы → контроллер → мастер «Позиционер» →
# подключить робота и написать программу движения (внешняя ось).
import vcMatrix
import vcVector

RD2 = "https://download.r-pro.digital/v204/Components/R-Pro Digital/"
info = {}


def blk(feature, name, l, w, h, x=0.0, y=0.0, z=0.0, mat=None):
    b = feature.createFeature(VC_BLOCK, name)
    b.getProperty("Length").Value = l
    b.getProperty("Width").Value = w
    b.getProperty("Height").Value = h
    m = vcMatrix.new()
    m.translateAbs(x, y, z)
    b.PositionMatrix = m
    return b


comp = app.createComponent()
comp.Name = _b(u"Позиционер")
# --- 1. геометрия: основание из трёх параллелепипедов (плита и две направляющие) -----------------
rf = comp.RootFeature
base = blk(rf, u"Основание", "1500", "500", "50", 0, 0, 0)
rail1 = blk(base, u"Направляющая 1", "1500", "60", "20", 0, -150, 50)
rail2 = blk(base, u"Направляющая 2", "1500", "60", "20", 0, 150, 50)
# --- 2. свойство-параметр «ДлинаКаретки» (real) -------------------------------------------------
lp = comp.createProperty(VC_REAL, "CarriageLength")
lp.Value = 300.0
for a, v in (("MinValue", 200.0), ("MaxValue", 500.0)):
    try:
        setattr(lp, a, v)
    except Exception:
        pass
info["свойство"] = [str(lp.Name), lp.Value]
# --- 3. звено «Каретка» с собственной геометрией, длина = значение свойства --------------------
car = comp.createNode(VC_NODE, "Carriage")
cf = car.RootFeature
c_blk = blk(cf, u"Каретка", "CarriageLength", "400", "30", 0, 0, 70)
# --- 4. тип движения: поступательное по +X, пределы от 0 до (1500 − длина каретки) ------------
car.JointType = VC_JOINTTYPE_TRANSLATIONAL
dof = car.Dof
dof.AxisType = VC_JOINTAXIS_PLUS_X
dof.Name = "J1"
dof.MinLimit = "0"
dof.MaxLimit = "1500 - CarriageLength"
# --- 5. контроллер: сервоконтроллер управляет осью J1 ------------------------------------------
servo = comp.createBehaviour(VC_SERVOCONTROLLER, "ServoController")
dof.Controller = servo
servo.FlangeNode = car
# --- 6. «Мастер → Позиционер → Позиционер робота» (то же, что делает PositionerWizard.py) ----------
frame = car.RootFeature.createFeature(VC_FRAME, "MountFrame")
geo = car.Geometry
top = geo.BoundCenter
top.Z = top.Z + geo.BoundDiagonal.Z
m = vcMatrix.new()
m.P = top
frame.PositionMatrix = m
frame.rebuild()
iface = car.createBehaviour(VC_ONETOONEINTERFACE, "MountInterface")
section = iface.createSection("Section")
field = section.createField(VC_HIERARCHYFIELD, "Pnp")
section.Frame = frame
field.Parent = True
field.Node = car
field.Frame = frame
field = section.createField(VC_JOINTEXPORTFIELD, "ExportJoint")
field.Controller = servo
field.Export = True
info["компонент"] = _u(comp.Name)
info["звенья"] = [str(x.Name) for x in comp.Children]
info["J1"] = [str(dof.Name), str(dof.MinLimit), str(dof.MaxLimit)]
result = info
