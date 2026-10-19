# -*- coding: utf-8 -*-
"""
Дописывает в конспекты уроков (lessons/Lxx.md) раздел «Как это делает агент (проверено в R-Pro 2.2.2)»:
короткий рабочий рецепт на Python 2.7 R-Pro (для rpro_exec) и ловушки, найденные при практике 14.10.
Раздел заменяется при повторном запуске. Потом: python iitb_to_kb.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = "## Как это делает агент (проверено в R-Pro 2.2.2)"

RECIPES: dict[int, str] = {
    5: """Видео: `app.Recorder = VC_RECORDER_VIDEO; app.RecordingFileName = "C:/путь/имя"` (БЕЗ расширения — программа допишет `.avi`), `app.Recording = True` сам запускает симуляцию; остановить `app.Recording = False` до её конца. mp4 делают ffmpeg-ом из avi.
Виды: `app.createView(u"Вид 1")` запоминает текущую камеру; аниматор камеры — компонент-элемент планировки `ViewAnimation`: `prog = item.Program; r = prog.MainRoutine; s = r.addStatement(VC_STATEMENT_VIEW); s.View = вид; s.Delay = секунды` и `VC_STATEMENT_DELAY`.
Не пишутся командами: изображение, 3D-PDF (`VC_RECORDER_PDF`), STL — только кнопками области «Экспорт».""",
    6: """Дашборд: `tab = app.Dashboard.createTab(...)`, `tab.clearLayout()`, `chart = tab.createChart(плитка, VC_CHARTTYPE_PIE|LINE|COLUMN|BAR, True)`, серия: `s = chart.addSeries(); s.Property = beh(компонент, "Statistics").getProperty("BusyPercentage")` (ещё `PartsExited`, `Utilization`), цвет `s.Colors = [vcVector...]`. Данные — `chart.DataRows`. Интервал выборки `app.Simulation.Statistics.SamplingInterval`.
Часовой прогон: `app.Simulation.SimSpeed = 20.0` и `run_for` на 3600 с. CSV/PDF с листа пишут из `DataRows` внешним кодом.""",
    7: """Ручные операции: «Процесс подачи» → «Ручная рабочая станция» → ... → «Процесс утилизации»; исполнитель транспортных связей — «ТК человека» (`Human Transport Controller`), люди подключаются `beh(tc, "Resources").connect(beh(человек, "PMResource"))`, места ожидания — `"Idle/ChargingLocations"`, инструмент (вилочная тележка) — `"Tools"`.
Зоны прохода («Pathway Area»): `set_prop(зона, "AreaLength", L)`, `"AreaWidth"`, подключить `beh(tc, "Pathways").connect(beh(зона, "Зона Прохода"))`, у ТК `UseGlobalArea = False` (иначе карта путей по всей сцене и модальное окно «продолжить расчёт?» — мост молчит).
Связь везёт на тележке: свойства связи `Tool` (выбор из StepValues) и `ToolName`.""",
    8: """Ячейка робота: робот на «Параметрической тумбе» (PnP по интерфейсу `Tool`/`EOAT_MountInterface` для захвата), конвейеры на `InInterface`/`OutInterface`, двигатель и датчик конвейера. Сигналы робота: `beh(робот, "Inputs").connect(102, beh(датчик, "SensorBooleanSignal"))`, `beh(робот, "Outputs").connect(105, beh(двигатель, "MotorSignal"))`. Инструмент называется `TOOL[1]`, базы `BASE_1`, `BASE_2`. Положение датчика вдоль ленты — свойство `ComponentPathSensor.Distance` (присвоение `PositionMatrix` игнорируется).""",
    9: """Программа робота: `ex = robot.findBehavioursByType(VC_ROBOTEXECUTOR)[0]; prog = ex.Program; r = prog.addRoutine(u"имя")`; операторы `PtpMotion`, `LinMotion` (позиция `Positions[0]`, углы `pos.setJoints([...])` — присваивания `JointValues` нет), `SetBin`/`WaitBin` (сигналы), `Call`, `Comment`, `While` (`While.Scope.addStatement`, `Condition="True"`). Захват — сигнал 1 по умолчанию «взять инструментом TOOL[1]». Цикл партии — `While` + счётчик. Видео — рекордер (см. урок 5).""",
    10: """Свой компонент: `comp = app.createComponent(); comp.Name = _b(u"Позиционер")`; геометрия `comp.RootFeature.createFeature(VC_BLOCK, "имя")` (Length/Width/Height — строки-выражения, можно `"CarriageLength"`); свойство `comp.createProperty(VC_REAL, "CarriageLength")`; звено `n = comp.createNode(VC_NODE, "Carriage")` (БЕЗ типа первым аргументом вернёт None!); `n.JointType = VC_JOINTTYPE_TRANSLATIONAL; n.Dof.AxisType = VC_JOINTAXIS_PLUS_X; n.Dof.Name = "J1"; n.Dof.MinLimit = "0"; n.Dof.MaxLimit = "1500 - CarriageLength"`; сервоконтроллер `servo = comp.createBehaviour(VC_SERVOCONTROLLER, "ServoController"); n.Dof.Controller = servo`. Мастер «Позиционер» = `VC_ONETOONEINTERFACE` «MountInterface» + `VC_HIERARCHYFIELD` + `VC_JOINTEXPORTFIELD` (см. PositionerWizard.py).
Сохранить компонент: `comp.save(_b(u"file:///C:/путь/имя.rpro"))` — обычный путь молча ничего не пишет.""",
    11: """Сборка роутера. Тип-сборка: `part_type(...)` для 5 деталей + `define_assembly(имя, группа, шаги, типы)` (шаги: платформа — корень, остальные — гнёзда с `pos` и `order`).
ВАЖНО (R-Pro 2.2.2): схема «5 × TransportIn → GetAssembly → Construct» из видео зацикливает перенос в нулевое время (`CannotTransportAlreadyAtTarget`, часы стоят, окно EXCEPTION_ACCESS_VIOLATION) — НЕ использовать. Рабочая схема: склад платформы — `CreateProduct` с `AssemblySteps=[шаг платформы]` + `TransportOut`; склады остальных деталей — `CreateProduct` + `TransportOut`; пост (компонент с кадрами `ResourceLocation` и `Center`, например «Inline Process»; у «Manual Workstation v2» кадра Center нет) — `TransportIn Mode=0` (платформа, `ProductVariableName="Engine"`) → `GetAssembly` (`AssemblyDataSource=1`, `AssemblySteps=[...шаги 2–5]`, `ReturnVariableName="Order"`) → `TransportIn Mode=1` (`AssemblyVariableName="Engine"`, `AssemblyOrderVariableName="Order"`) → `Work` (человек, `Controller=beh(тк,"TC")`) → `TransportOut`. Детали носят люди «ТК человека»; два маршрута: сборка (платформа → пост → следующий этап) и детали (склады → пост). Присваивание `TransportOut.DestinationNode` вешает мост. Порядок свойств оператора важен: `AssemblySteps` после `ProductType`/`Assembly`.""",
    12: """Склад: «ТК крана-штабелера» + «Кран-штабелер — одиночный поддон» (`snap(тк, "CraneA", кран, "PMResource")`), «Складская полка» (Buffer) вдоль пути крана; места загрузки/выгрузки полки — свойства `FlowInResourceLocation`/`FlowOutResourceLocation` (в мир: `полка.PositionMatrix * свойство.Value`); узел «Создание поддонов» ставят у FlowIn, «Отгрузку» — за конвейером у FlowOut. Маршрут `[создание, процесс полки (routine(полка).Name), отгрузка]`, связи `link(создание, полка, тк_крана, группа)` и `link(полка, отгрузка, тк_крана, группа)`; исполнитель связей — кран.""",
    13: """Детектор столкновений: `det = app.Simulation.newCollisionDetector(); det.NodeListA = [(тумба, VC_NODELIST_INCLUDE, VC_NODELIST_TREE)]; det.NodeListB = [(конвейер, INCLUDE, TREE), ...]; det.Tolerance = 10.0; det.DisplayMinimumDistance = True; det.Active = True`; проверка `det.testAllCollisions()` → True/False, `det.HitCount`, `det.getHitNodeA(i)`/`getHitNodeB(i)`.
ЛОВУШКИ: робот и захват — ДОЧЕРНИЕ компоненты тумбы, на них самих список узлов ничего не находит — в группу A кладут компонент-родитель целиком (с деревом); объект детектора живёт, только пока на него есть ссылка (держать в `__builtin__`); свойств `FirstCollision`/`StopOnCollision` у объекта в 2.2.2 нет (галочки окна детектора). Если программа робота чистая, касаний не будет — это норма; для проверки поставьте препятствие (поддон) на путь захвата.""",
    14: """Двери станка по сигналу. Станок строят на каталожном «Узле процесса» (`Flow Node Process.rpro`): процесс компонента, созданного с нуля, не попадает в менеджер процессов и не запускается. Звенья: `d1 = comp.createNode(VC_NODE, "Link_1")`, `d1.JointType = VC_JOINTTYPE_TRANSLATIONAL`, `d1.Dof.AxisType = VC_JOINTAXIS_PLUS_X`, `d1.Dof.Name = "J1"`, пределы `"0"`/`"550"`, `d1.Dof.Controller = servo`; второе звено — `VC_JOINTTYPE_TRANSLATIONAL_FOLLOWER`, ось `MINUS_X`, `d2.Dof.Driver = d1.Dof`. Сигнал `sig = comp.createBehaviour(VC_BOOLEANSIGNAL, "DoorSignal")`.
Процесс (`r = clear_routine(comp)`): `TransportIn Mode=0` → `WaitSignal` (`Component=comp, Signal=sig, WaitTrigger=True`) → `MoveJoint` (`Controller=servo`, потом ОТДЕЛЬНО `Joint = servo.getJoint(0)`, `TargetValue=550`, `MotionTime=2`) → `WaitSignal(False)` → `MoveJoint(0)` → `TransportOut`. Станок ставят в поток «подача → станок → отгрузка» (`link(..., "InterpolatingTransport", группа)`).
ЛОВУШКИ: `Joint` присваивают ПОСЛЕ `Controller` (смена контроллера его сбрасывает); в `Joint` нельзя класть `Dof` — это вешает мост; значение сигнала шлют методом `сигнал.signal(True)` — присвоение `.Value` процесс не будит (в справке: «Setting this value does not trigger the OnSignal event unless you use the signal() method»); значение сигнала сбрасывается в исходное состояние при reset.""",
    15: """Паллетирование: «Устройство подачи» (поддоны) → конвейер → «Узел процесса» на ленте; «Процесс подачи» (банки) в ~1 м от узла. Группы `Поддоны`, `Банки` и типы (`createProductType`, `ComponentUri`). Узел: `TransportIn Source="From Container"` (поддон, `AcceptedFlowGroups=[g_pal]`) → `TransportPatternIn` (банки; `Offset` — матрица `translateAbs(-шаг*(n-1)/2, ..., высота поддона)`, `PatternCount = vcVector.new(6,4,1)`, `PatternStep = vcVector.new(180,150,0)`) → `AttachProduct(Parent="Pallet", Child="Can")` → `TransportOut Destination="To Container", Container=beh(узел, "ComponentContainer__HIDE__")`. Маршруты: поддон `[узел]`, банка `[подача, узел]`; связь `link(подача, узел, "InterpolatingTransport", g_банок)`, время связи `PickTime`/`PlaceTime` (с `UseCustomParameters=True`) — по умолчанию по 5 с на банку.""",
    16: """Депаллетизация: второй узел после конвейера: `TransportIn Source="From Container"` → `DetachProduct(ProductVariableName="Pallet", DetachedVariableName="Can", DetachMany=True, AcceptAllProductTypes=True)` → `TransportOut "To Next Process"` для банок (на «Процесс утилизации»/приёмку) → `TransportOut "To Container"` для пустого поддона. Банки переносит человек: «ТК человека» + «Human (Ivan)», зона прохода `crew_area(тк, AREA, 1500)`, связи `link(подача, узел1, тк, g)` и `link(узел2, приёмка, тк, g)` (старые связи-«перелёты» удалить `ts.deleteTransportLink(l)`).""",
}


def main() -> None:
    for n, body in RECIPES.items():
        p = HERE / "lessons" / f"L{n:02d}.md"
        if not p.exists():
            print("нет", p)
            continue
        s = p.read_text(encoding="utf-8")
        s = re.sub(r"\n+" + re.escape(MARK) + r".*?(?=\n## |\Z)", "", s, flags=re.S)
        add = f"\n\n{MARK}\n{body.strip()}\n"
        # перед «Ключевыми словами», если они есть: они завершают конспект
        m = re.search(r"\n## Ключевые слова", s)
        s = s[:m.start()] + add + s[m.start():] if m else s.rstrip() + add
        p.write_text(s, encoding="utf-8", newline="\n")
        print("урок", n, "—", len(body), "зн.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
