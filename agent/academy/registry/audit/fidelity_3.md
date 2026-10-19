# Fidelity and usefulness audit, batch K=3

Truth = part 1 of each sample. Part 2 only used to locate where an error entered.

## python-api-in-visual-components-4-0

- **Unsupported**:
  - "application.selectionManager: setSelection (с добавлением), getSelection, очистка, событие": the speaker only says the selection manager can "set and get the selection", has "clear selection" and a "selection changed property". The camelCase identifiers are reconstructed from speech (guessed).
  - "старые getSelection и «текущее выделение» устарели" and then the same name `getSelection` as the new call: transcript says "get selection and current selection is deprecated from the VC application" (i.e. the VC application object methods), not the selection manager. As written the lesson lists one name as both deprecated and recommended.
  - "значки — чёрно-белый SVG строкой": transcript restricts this to ribbon icons ("these ribbon icons support only black and white ... raw SVG"); colored icons elsewhere "can be passed as URI". The lesson turns a ribbon-only limit into a general rule.
  - Step 7 "Пример: команда «свернуть геометрию активного узла»" is presented as a ready example; in the transcript it crashed in the demo ("and it crashed so that was a little bit bad").
- **Wrong**: none outright.
- **Missed** (valuable):
  - Snap: "this snap command needs to be Global so that the event stays alive" (the command object must be kept in a global variable, otherwise OnTarget never fires). Also snap on bound type: leave default / -1, or set to component to force picking a component; the result still contains target node and position.
  - The localization net command argument order: command name "set localization", language, context/scope, command name, then "text" / "tool tip" / "icon", then the value. The lesson has no usable recipe.
  - Context: `app.context` prints e.g. "VC author context"; the context has an ID property; active node/component/features exist only in the author (modeling) context; active node and component are single, active features is a tuple of (component, feature) pairs.
- **Terminology**:
  - Identifiers "OnTarget", "IsVisible", "selectionManager", "setSelection" are guessed from speech ("On Target set event", "is visible flag"). The real event name is probably longer (OnTargetSet?). The lesson does say "Имена из речи (сверьте со справкой)".
  - "Snap", "OnChanged" left English; "лента", "панель действий" fine.
- **Danger for the assistant**: No Python 3 syntax. But with no code at all, the assistant can only invent calls from these guessed names, and `getSelection` appearing as both deprecated and new invites a wrong call. Keywords for placing buttons (VC_TAB_HOME etc.) are not given, only "look in Essentials XML".
- **Scores**: fidelity 4, usefulness 2 (an outline of the agenda; no argument order, no code, no keyword names).
- **Verdict**: fix:
  1. Remove or clarify the duplicate getSelection (deprecated = on the application object).
  2. Qualify the SVG limit as "ribbon icons only".
  3. Add the "snap command must be global" pitfall and the net-command argument order from the transcript.
  4. Mark the merge-geometry example as a demo that crashed.
  5. Mark OnTarget/IsVisible as unverified names.

## programming-application-plugins-with-net-framework

- **Unsupported**:
  - "Библиотека классов": the transcript never says Class Library. It says "we have the solution with one project here and I will remove the default user control", which points to a WPF user-control library project. The digest invented "Create a Class Library project".
  - "Debug — Essentials.exe": transcript says "start external program ... point to the Visual Components Essentials executable"; the exact file name is guessed.
  - "ISelectionManager" (and `IApplication`, `UX.Ribbon`, `Create3D.Shared`): reconstructed from speech ("selection manager", "ux Ron", "create 3d. shared dll"). The digest claims "names are checked against the ZIP" but they were not.
  - Step 9 hard-codes `visual components.essentials.exe.config`: the transcript says "visual components. essentials. exit. config" (speech-to-text of ".exe.config").
- **Wrong**: none outright.
- **Missed** (valuable):
  - `EvaluateCanExecute()` must be called whenever the condition may change (here on SelectionChanged); without it the ribbon button never updates. The lesson says only "CanExecute по ISelectionManager".
  - Subscribe to component events in `OnActivate` and unsubscribe in `OnDeactivate` (DockableScreen); "at ComponentRemoving the component is still in the world".
  - The base-class constructor arguments of the ribbon command (ID, header, icon name, action, control type, get-icon-from-file) and the ID matching in tab / group / command; "it's quite easy to make typos here".
  - Why output path = installation folder: the DLL must be in the installation folder; working directory also must be the install folder.
- **Terminology**: The English type names are plausibly right but only partly verifiable. "Clipboard" group, "Home" tab are kept in English (not matched to the Russian UI names).
- **Danger for the assistant**:
  - Rule "в процесс загружаются только DLL с префиксом UX." is stated as fact for the 4.0 Premium used in the webinar. The repo's own plugin is named `addon/bin/Plugin.AiBridge.dll`, which suggests R-Pro loads plugins differently or under another prefix. Verify before the assistant tells anyone to rename assemblies.
  - Step 9 sends the user to edit a product config file in the installation folder; in R-Pro this file is most likely renamed and edits need admin rights.
  - The lesson does carry "API аддонов R-Pro не проверен", which is honest.
- **Scores**: fidelity 4, usefulness 2 (skeleton of 10 one-liners; not enough to build anything, and R-Pro applicability unconfirmed).
- **Verdict**: fix:
  1. Remove "Библиотека классов" (say "проект библиотеки; удалите стандартный UserControl").
  2. Mark Essentials exe name and `ISelectionManager`/`UX.Ribbon` as unverified.
  3. Add the EvaluateCanExecute step and the OnActivate/OnDeactivate subscribe pattern.
  4. Soften the UX. prefix claim for R-Pro (check against Plugin.AiBridge.dll).

## robot-programming-with-visual-components-essentials-4-0

- **Unsupported**:
  - "Установить бинарный выход" as a statement (Скрипты и API line): the transcript never names such a statement. The grasp is set as a property of the motion statement: "I go to my statement properties, change the output index to 1 and the value to true". A novice will look for a separate statement that does not exist in the talk.
  - Step 10 "PTP подход, LIN шов": the transcript is garbled here ("I've created a point-to-point motion but this I want to be in all pace so I touch up"); the PTP/LIN split is an inference of the digest.
  - Step 3 "линейное ... на её грани": transcript says linear statement on top of the box, plus an approach point above it that is moved before it by dragging and cloned.
- **Wrong**: none outright. "49–80 — внешний инструмент" is vague; transcript: "49 up to 80 will trace external tool" (trace, not the tool itself). "33–48 — инструмент" should say mount/unmount tool.
- **Missed** (valuable):
  - Where the action config lives: "Home tab, select the robot, Properties, Actions configuration" (list is slow to populate). The lesson lists the output numbers without saying where to configure them. Also grasp uses the TCP's detection box (50x50x50) and release looks 25 mm in gravity direction.
  - Reset before Play ("I always hit reset before playing"), otherwise the end pose becomes the new initial position. The digest had it as PITFALL, the lesson dropped it. Also the save path "Simulation settings, Save state" is shortened to "Сохранить состояние".
  - Shift+click on a new node moves the coordinate system with it (base/tool node change); piston icon next to the Tool/Base drop-down in the Jog panel. Also the loop needs an Assign-variable statement `count = count + 1` inside the While, otherwise `count < 3` never ends; and the sensor sequence (fire 100 true, wait for input 100 high, fire 100 false) is only hinted as "сигналы 100".
- **Terminology**: Mixed English and Russian UI names: "Jog", "Move", "Touch up", "Align", "Exchange robot", "Interfaces", "Play", "Snap" are English while the intro says UI names come from resource files; the R-Pro user sees Russian names. "PnP" is the digest's reading of "PMP tool".
- **Danger for the assistant**: No harmful advice. "Ctrl+A — скорость всем" is cryptic (it selects all motion points, then joint speed is changed in statement properties, e.g. 40%).
- **Scores**: fidelity 4, usefulness 3 (right topics for a robot novice, but compressed so far that several steps are not executable).
- **Verdict**: fix:
  1. Delete "Установить бинарный выход" (output index/value are statement properties).
  2. Add path "Дом → свойства робота → Конфигурация действий".
  3. Add "Reset перед Play" and "Shift+щелчок переносит систему координат".
  4. Add the count increment statement.
  5. Use Russian UI names for Jog/Move/Touch up.

## process-modeling-resources-manual

- **Unsupported**: none found; every property name matches the manual.
- **Wrong** (misleading):
  - "Ловушка: без инструмента симуляция останавливается; занятый инструмент держит задачу в очереди." Manual p.7: the error and pause occur when the *defined* tool is *not found* ("if the tool is not found"; tools must be connected through the Tools interface). A resource with no tool is legal ("No Tool" option). As written, it says having no tool stops the simulation.
- **Missed** (valuable):
  - ReserveResource: the signal value selects the process; empty string `""` = the calling process, otherwise the process component name. Without this the Send Signal step cannot be filled in. Also a resource may be reserved for several processes, which is why ReleaseResource is mandatory.
  - Pathways must be connected to the Transport Controller; with no pathways and `UseGlobalArea` off, "the resources ignore the navigation and go straight through the obstacles"; an unconnected pathway gets a red outline and an Output warning.
  - `ResourcePickOffset/PlaceOffset` apply only if `UseCustomParameters` is enabled on the link; also `<tool name>_Work` and "with a tool, product type is ignored and Pick/Place animations are not used". Animations are not time-scaled and are cut at PickTime/PlaceTime/ProcessTime (digest had it; the lesson dropped it).
- **Terminology**: Property names left in English: correct for property IDs. "Wait Transport", "Send Signal" statement names in English (fine if the Russian UI keeps them; unverified).
- **Danger for the assistant**: Source is the 4.10 manual (April 2026). Several items (AllowIdling, ChargeUntilLimit, DynamicCostEvaluation, Pathway Capacity Group) are likely not in older 4.x builds; "скорее всего работает" for R-Pro overclaims. The assistant may recommend properties that the installed version lacks.
- **Scores**: fidelity 4, usefulness 4 (non-obvious, concrete property names for a topic where users are lost).
- **Verdict**: fix:
  1. Rewrite the tool pitfall ("если заданный инструмент не найден (не подключён через интерфейс Tools) — ошибка в Output и пауза").
  2. Add the `""` rule for ReserveResource.
  3. Add UseGlobalArea/pathway connection warning and UseCustomParameters.
  4. Add a note that the manual is for 4.10 and some properties may be missing.

## mqtt-client-tutorial

- **Unsupported**: none; all fields and expressions match the manual.
- **Wrong**:
  - Step 10 gives only the final expression `@Array(Payload.x, Payload.y - 5000, 0, 0, 0, Payload.theta)`. The manual first uses `@Array(Payload.x, Payload.y, 0, 0, 0, Payload.theta)` and only later modifies it to shift the robot 5 m in -Y (units are mm). Presented bare, the -5000 looks like a required part of position mapping.
- **Missed**:
  - Requirements: "Visual Components Professional or Premium 5.0 or newer" and a running broker; MQTT Client is "a new Connectivity feature in Visual Components 5.0". The lesson says "версия 5.0" but not that older versions lack it.
  - Which components are paired (SafetyScanner for OUT_WarningSignal, Analog Clock, Mobile Robot "for publishing" vs "for subscribing").
  - Update Mode Event-Based bypasses the rate limit.
- **Terminology**: "Симуляция на сервер" / "Сервер для симуляции" are invented translations of "Simulation to Server Pair" / "Server to Simulation Pair" ("Сервер для симуляции" reads wrong; the feature is not in the resource files, so no official Russian exists). Mixed with English "Test Connection", "Save", "Add Subscription". Tab "Подключения" for Connectivity is unverified.
- **Danger for the assistant**: R-Pro is a rebranded 4.x; this feature is 5.0+ and almost certainly absent. The lesson only says "проверить". The assistant would send a user to File → Options → Add-on → Connectivity, a menu that does not exist in 4.x.
- **Scores**: fidelity 4, usefulness 2 for R-Pro (if R-Pro really is 4.x then 1; accurate, but about a feature R-Pro does not have).
- **Verdict**: drop (unless R-Pro 5.x is confirmed). If kept, add a hard line "Только Visual Components 5.0 и новее; в R-Pro 4.x нет" and fix the two translations.

## waitsignal-statement

- **Unsupported**:
  - "Выделите части двери": the manual says "the parts shown on the image below" (image not available); "door" is inferred from DoorJoint. Minor.
  - "Ловушка: при заданном Timeout процесс продолжится по истечении времени, даже если условие не выполнено": the manual says only "wait for five seconds to get the correct value before continuing the execution"; the "continues even if not met" is a reasonable inference, not a quote.
- **Wrong**: none. "Timeout = 0" wording follows the manual's odd phrase and the usual meaning.
- **Missed**: nothing important. Could mention that the 550 value "has already been measured" (for another model measure the travel).
- **Terminology**: ok ("Извлечь звено" for Extract Link; "сервоконтроллер"; Explode, WaitTrigger, Condition, Timeout are property names).
- **Danger for the assistant**: none; 4.2 manual, no scripting.
- **Scores**: fidelity 5, usefulness 4 (clear and correct step-by-step; the WaitTrigger and Timeout semantics are the non-obvious part; slightly door-specific).
- **Verdict**: keep.

## event-handlers

- **Unsupported**:
  - "Ловушка: heartbeat-время разное: 0.01 с здесь и 0.0015 с в «Control Servos»": nothing in this manual about 0.0015 or another lesson; cross-lesson content, not traceable here.
  - "(на 1 мм)": manual says "add 1 to the Z-axis value", units not stated.
  - "Raycast по умолчанию не видит геометрию звеньев": manual says "will most likely not detect" (not a certain default).
- **Wrong**: none.
- **Missed** (valuable):
  - Step 3 drops "connect the Boolean Signal to the Python Script"; without that connection the handler setup in the next steps does not work.
  - Boilerplate that makes the code run: `from vcScript import *`, `comp = getComponent()`, `servo = comp.findBehaviour("Servo")`, and the `print` is a Python 2 statement. The lesson only has fragments, so the assistant cannot produce a working script from the lesson text alone.
  - Event handlers work also when the simulation is not running (user edits a property); this is the first learning goal in the manual, the digest had it, and the lesson dropped it.
- **Terminology**: ok. Identifiers match the manual exactly (OnChanged, OnValueChange, OnHeartbeat, VC_CONTROLLER_*).
- **Danger for the assistant**: no Python 3 construct in the lesson. The manual's handler argument names `property` and `type` shadow builtins; harmless in 2.7 but the assistant should not "fix" them. Starting file EventHandlersStart.vcmx is not available to the user; the lesson says "Откройте EventHandlersStart.vcmx".
- **Scores**: fidelity 4, usefulness 4 (event-driven scripting is exactly where the assistant needs exact names).
- **Verdict**: fix:
  1. Remove the "0.0015 с в Control Servos" claim.
  2. Add "соедините Boolean-сигнал со скриптом".
  3. Add the 4-line boilerplate (`from vcScript import *`, `comp = getComponent()`, a Py2 `print` example).
  4. Add "обработчики работают и когда симуляция не запущена".
  5. Drop "на 1 мм".

## model-a-cartesian-robot

- **Unsupported**: none. Step 7 "точки звеньев в центры соединений" slightly over-states: the manual says that for a three-linear-axis robot the center of motion is not important; precision only matters for rotary joints.
- **Wrong**: none.
- **Missed**:
  - "Press Apply in the Move Origin panel to save the changed position" (step 10 drops Apply).
  - Appendix: hold Shift when dragging features into the new links to keep world location; keep mountplate and FlangeFrame at the end effector after changing the structure.
  - Features must be selected in the Modeling tab (turn green) before copying; the manual's tip that the model should be "fully green".
- **Terminology**: Mixed languages: "Move Origin", "Move Mode", "Selected", "Hierarchy", "Explode", "Group", "Interact", "Jog" in English but "Переместить рамку робота" and "Шаблоны компонентов" translated. Inconsistent, and the Russian R-Pro UI will show Russian names. "плита" for mountplate link is unclear. Identifiers (KinematicsIterativeJacobian, RobotController, FlangeFrame, RootFrame, L1_X_Trans) match the manual.
- **Danger for the assistant**: no harmful advice. Steps 2-3 depend on ExampleCartesianGeometry.step from the lesson's ZIP that the user will not have; the assistant should say "your own STEP model". Template 3-Axis Cartesian availability in R-Pro's catalog is unverified.
- **Scores**: fidelity 5, usefulness 4 (correct, non-trivial robot-modeling procedure with the Explode/Group/Shift-drag/Selected-mode tricks).
- **Verdict**: keep (optional: add Apply, Shift in appendix, and generalize the STEP file as "ваш STEP").

| slug | fidelity | usefulness | verdict |
|---|---|---|---|
| python-api-in-visual-components-4-0 | 4 | 2 | fix |
| programming-application-plugins-with-net-framework | 4 | 2 | fix |
| robot-programming-with-visual-components-essentials-4-0 | 4 | 3 | fix |
| process-modeling-resources-manual | 4 | 4 | fix |
| mqtt-client-tutorial | 4 | 2 | drop |
| waitsignal-statement | 5 | 4 | keep |
| event-handlers | 4 | 4 | fix |
| model-a-cartesian-robot | 5 | 4 | keep |
