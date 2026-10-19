# Fidelity and usefulness audit, batch K=2

Truth = transcript (part 1). Part 2 (digest) is used only to say where an error entered.

## live-stream-a-simulation

- **Unsupported**:
  - Step 3 «Создайте учётную запись YouTube, подходящую для трансляций». Transcript: "for your YouTube account it must be verified in order to livestream". Nothing about creating an account (digest wrote "Create/verify").
  - Tip «Виртуальное время ... не зависит от ЦП». Transcript only says "I prefer to use virtual time". The CPU claim entered in the digest.
  - Step 5 «Установите OBS Studio». The speaker only opens an already installed OBS.
  - Pitfall «задержка может быть 30+ секунд». Transcript: "some latency or delay". The 30/60 s figures are the optional stream delay for Normal latency, not typical latency.
- **Wrong**:
  - Step 9 «OBS Studio: нажмите «Начать запись»» and step 12 «OBS: нажмите «Остановить запись»». Transcript: the button is "Start streaming" / "Stop streaming". He says explicitly "I'm not going to be recording from OBS studio, I'll just be streaming". Start recording is a different button. Error entered at stage 2 (the digest has "Start Streaming"). A novice following the lesson records a local file and nothing goes live.
  - Step 7 «добавьте сцену → Источники». Transcript: "you should have by default one scene but you don't have any sources", so only a source is added.
  - Step 4 «Начать трансляцию». Not wrong, but it is the "Stream now" option, not "schedule an event". The lesson does not say so.
- **Missed**:
  - Privacy setting Private / Unlisted / Public (he uses Private for testing).
  - OBS output settings: Full HD, audio disabled.
  - The stream appears on YouTube only after a delay. Check via "view on watch page". Do not stop in panic while YouTube still shows the old picture.
- **Terminology**:
  - «Базовую Информацию» (capitalised oddly).
  - Mixed «File > Настройки», «Service:», «Window Capture», «Stream Key». These are OBS/YouTube UI and may stay English, but the mix looks sloppy.
  - «Прямые трансляции» and «Поток» are guessed Russian for YouTube and OBS names.
  - R-Pro-side names «Элементы управления «Симуляция» → «Настройки»» are plausible but unverified.
- **Danger for the assistant**:
  - Steps 9 and 12 give the wrong button (see above).
  - Step 3 pushes a novice to create accounts, which is outside R-Pro.
  - Nothing warns that the stream key is secret.
  - Low relevance: the lesson is about YouTube/OBS, not R-Pro itself, and is probably unreachable from an industrial network.
- **Scores**: fidelity 2, usefulness 2
- **Verdict**: fix. Change steps 9 and 12 to «Начать/Остановить трансляцию (Start/Stop Streaming)». Step 3 becomes «аккаунт YouTube должен быть верифицирован». Remove «не зависит от ЦП». Step 7 becomes «сцена уже есть, добавьте источник Window Capture». Consider dropping the lesson if the knowledge base should hold only R-Pro-internal content.

## olp-basic-workflow-for-welding

- **Unsupported**:
  - Step 10 «Включайте обнаружение столкновений в настройках». Transcript: "please note that my collision detection is enabled. That's why you see visually when there is a collision in the 3D world". No "settings" and no instruction to enable it.
  - Step 9 «регулируйте с помощью кнопки touchup». Transcript: click P10, rotate the robot by hand until there is no collision, then Path Setup → touchup. The lesson makes touchup sound like the adjusting tool.
- **Wrong**:
  - Order: step 3 (check preset "arc") comes after step 2 (create path). Transcript: preset is selected first, then "go to create the path".
  - Pitfall «значительно улучшить... с 94% до 95%». Transcript: "we are 1% improved". Calling 94→95% significant is spin, not a warning.
  - Step 12 «решения процесса и пути поиска» is garbled. Transcript: buttons "to solve the process pass [path] and also to solve the search pass [path]".
- **Missed**:
  - Why PA/B: the robot is too close to the workpiece, and PA/B gives a 45° angle that "looks better".
  - What searches are: they compensate deviations between the real workpiece and the CAD model, and appear as search 2 and search 3 at the start and end of the weld (wire, nozzle, camera or laser pointer).
  - The check can run on the selected statement, a sequence or the whole program. Yellow spots on the result mean collisions. Collisions must be fixed before post-processing.
- **Terminology**:
  - «arc or arc welding» is mangled speech-to-text ("The preset arc or arc welding").
  - Untranslated: «Auxiliary», «Extras», «Check Path», «auto search», «touchup», «teach», «Check». The lesson claims UI names come from resource files, yet most are English. The R-Pro names are likely Russian.
  - «пути поиска» for "searches" is fine.
- **Danger for the assistant**:
  - English-only UI names may send the novice looking for non-existent buttons in the Russian UI.
  - Lesson is for 4.8.0. The Path Check panel and the solver buttons may not exist in an older R-Pro 4.x build. The lesson says only «скорее всего работает».
- **Scores**: fidelity 3, usefulness 3
- **Verdict**: fix. Swap steps 2 and 3. Remove «в настройках» and «значительно». Reword step 12 as «кнопки автоматического решения пути процесса и пути поиска (если решатели включены)». Add the three missed points. Replace English UI names with R-Pro names.

## add-a-background-plugin

- **Unsupported**:
  - Tip «Имя сборки должно начинаться с "UX." или "plugin."». Transcript: only "UX prefix" ("capital U capital X dot"). "plugin." is invented (digest).
  - Step 24 `block.Properties["length"].Value`. Transcript: "forget property [get property] I'll type the name length ... use its value property". It is a get-property call, not an indexer. Identifier guessed in the digest.
  - Step 2 name «example_001». Transcript: "example 001". The underscore is a guess.
  - Step 11 `MessageLevel.Warning`. Transcript: "that constant ... warning". Class name reconstructed.
- **Wrong**:
  - Step 6 «Visual Components.Create3D, Visual Components.UX.Shared». A namespace with a space does not compile. Transcript: "Visual Components dot create 3D", "dot ux dot shared". The real names are surely without a space (VisualComponents...). This is from my knowledge, not the transcript.
  - Step 5 «caliber.micro» vs step 6 «Caliburn.Micro». Inconsistent. The DLL names «create3D.shared, ux.shared» are the lowercased speech reconstruction.
  - Step 17 «engine.exe». Transcript: "Visual Components dot engine dot exe". Shortened, so the file name is mangled.
  - Step 33 uses the class `MyScene` without a step saying to rename Class1 to MyScene (transcript 16:58). The reader will not know where `MyScene` came from.
  - Step 23: no `IProperty<double> block_length =` declaration. The cast wording «приведите как» is unclear.
- **Missed**:
  - The success check: "hello world" appears in the Output panel. Test the property by typing 100, 1000, 500 in the component properties.
  - Minimum is Visual Components Essentials. The default block length/width/height is 100 mm.
  - On the constructor parameter the speaker adds `[Import]` as well as `[ImportingConstructor]` on the constructor.
- **Terminology**:
  - Guessed identifiers: `MessageLevel`, `Properties["length"]`, `FillWorld`, `SetSelection`, `CreateProperty(...)` signature.
  - Step 15 «Visual Components Premium 4.0» and step 17 «engine.exe» are product-specific paths. R-Pro is rebranded, so the folder and exe names are likely different.
- **Danger for the assistant**:
  - The code skeleton will not compile as given (namespace with a space, `Properties["length"]`, missing class rename).
  - The assistant may give Premium paths and the "UX." / "plugin." prefix as facts for R-Pro.
  - The lesson is heavy .NET work for a novice.
- **Scores**: fidelity 3, usefulness 3
- **Verdict**: fix.
  - Namespaces without spaces.
  - `GetProperty("length")` in place of the indexer.
  - Remove «plugin.».
  - Add a "rename class to MyScene" step.
  - Add a note that R-Pro install folder and exe name must be checked.
  - Add the success check.

## linear-and-angular-damping

- **Unsupported**:
  - «Названия свойств: `linear_damping`, `angular_damping` (подчеркивание)» and `solver_position_iterations`, `solver_velocity_iterations`. Transcript: "notice there's no space here in the script but here in the GUI there is a space". It says nothing about underscores or exact spelling. Guessed in the digest.
  - `get_application()`, `app.components`, `c.get_behavior('physics entity')` are snake_case reconstructions of "get application", "app dot components", "c dot get behavior". The VC Python API normally uses camelCase (getApplication, getBehavior). Verify before the assistant emits code.
  - «Отрицательное значение (например, −1) отключает свойство» is placed in the solver context. Transcript uses −1 only for damping.
  - Solver defaults 4 and 1 are stated as fact. Transcript: "when this is 0 its default value is 4 if I remember correctly".
  - Tip «прозрачные материалы показывают повторяющееся напряжение» is garbled. Transcript: swept volume is iterative, so more movement gives a deeper colour.
- **Wrong**:
  - Step 1 «#В Физике» has a stray «#». Transcript: "in physics".
  - Step 5 «значением 1 ... подходящим для большинства случаев». This is the speaker's claim for a single picked-up object. The same video shows a stack toppling at 7 and 3, so 1 is not enough for stacks. The lesson does not say so.
- **Missed**:
  - The practical result: halve the values from the recommended 1000/400 until the stack fails. The stack stays up at 250/100, 125/50, 30/12, 15/6, and topples at 7/3. Default values and zero damping let the stack fall apart.
  - Solver alternative with numbers: position 40 and velocity 10 is stable, 20 and 5 is not. With damping 20/5 plus solvers 20/5 it is stable.
  - The real script is absent: list comprehension over app components filtering by "cylinder" in the name, `len(...)` check giving 8, a loop that gets the behavior by name and sets the properties.
- **Terminology**:
  - «Линейное Затухание / Угловое Затухание» is a guess. Check the R-Pro name (демпфирование?).
  - «Physics Entity», «spring force, damping, limits», «solver iterations» are left in English.
  - «Свойства компонента» is a panel, not a tab.
- **Danger for the assistant**:
  - The guessed Python names will produce a failing script.
  - Damping properties are described as new "in 4.1". If R-Pro is older than 4.1 they do not exist (version risk).
  - The "1 is enough for most cases" advice would give an unstable stack.
- **Scores**: fidelity 3, usefulness 3
- **Verdict**: fix.
  - Remove «#» from step 1.
  - Replace the property names with names verified in the R-Pro API, or mark them as unverified.
  - Add the halving rule with the 7/3 failure and the 40/10 vs 20/5 solver results.
  - Qualify step 5 as applying to a single free-hanging object.

## denso-robot-connectivity-plugin

- **Unsupported**:
  - Задача «к реальным или виртуальным контроллерам». The whole demo uses the controller's simulation mode in WINCAPS 3. A real controller is never shown.
  - Задача «перед развёртыванием» is not stated.
  - Pitfall «иначе симуляция запустит программу дважды». Transcript: "After this, the robot program in Visual Components is no longer executed". The "twice" rationale is invented (digest).
  - Pitfall «закрытие разрывает связь RC8» is an inference. Transcript: "Minimize, but don't close it".
- **Wrong**:
  - Step 20 «Включить режим симуляции для LPH060». It is WINCAPS' simulation mode button, not R-Pro. Ambiguous as written.
  - Step 7 drops "folder RC9 family VL". Step 12 drops "find the file path for the project file".
  - Step 3 says «выбрать робота» once, but the program is downloaded for both robots.
- **Missed**:
  - Precondition: all motion statements use a base at the robot origin and a tool with no offset. Without this the post-processed coordinates will not match.
  - Prerequisites: WINCAPS 3 (simulation mode) and ORiN2 (b-CAP listener) are installed separately.
  - Expected result: the controller drives the robot to the first point and stands by waiting for an input signal.
- **Terminology**:
  - Left in English: «Translators», «Postprocess», «Executor», «unselect is enabled», «signal maps», «Degrees of freedom objects», «Arm View». Some of these are VC UI that should be Russian in R-Pro.
  - «Аддоны» and «сопоставление переменных» (variable pairing editor) are guessed.
  - Signal numbers 128–133 are correct.
  - «VLA 6022» is consistent (the transcript has 622/6022). «LPH060» is corrected from the transcript's "LBH060".
- **Danger for the assistant**:
  - Lesson is for version 5.0. The Connectivity add-on and the Denso RC8/RC9 connectors may not exist in R-Pro 4.x. The applicability line says «проверить», but 23 confident steps follow.
  - Needs external Denso software and licences, so it is niche.
- **Scores**: fidelity 4, usefulness 2
- **Verdict**: fix. Remove «реальным» and «перед развёртыванием». Reword the executor pitfall as «иначе роботом одновременно управляют и R-Pro, и контроллер» (marked as inference). Add the base/tool precondition and prerequisites. Translate UI names. Keep a hard version warning, or drop if the Connectivity add-on is absent in R-Pro.

## add-a-smart-collection

- **Unsupported**:
  - Tip «автоматически наследуют метаданные ... динамическими и самообновляющимися». Transcript: only "these items are coming from the metadata of components". "Self-updating" is not said.
  - Pitfall about «and» / «or». Transcript demonstrates both operators but states no such rule.
  - Step 7 quoted UI string «сгруппировать по типу» looks invented.
- **Wrong**:
  - Step 6 «Выбирайте элементы из появившегося списка». Transcript: "just find it from this list" refers to the manufacturer value in the filter drop-down, not to items. The digest misread it.
  - Tip «изменения вступают в силу сразу». Transcript: after editing he clicks save and then the grouping changes.
- **Missed**:
  - The key trick: the manufacturer metadata has two spellings, "Visual Components" and "Visual Components Oy". Add `or manufacturer is ...Oy` to catch both.
  - The default smart collections "models by type" and "models by manufacturer" show two grouping orders and are good starting points.
  - Group by source gives legacy library / public models / my models.
- **Terminology**:
  - «Каталог» for eCatalog is unverified.
  - Mixed «и» and «and»/«or» in the same procedure (step 5 mixes them).
  - «смарт-коллекция» may differ from the R-Pro UI name.
- **Danger for the assistant**: low. Step 6 could send a novice looking for a list of items to pick.
- **Scores**: fidelity 4, usefulness 3
- **Verdict**: fix. Rewrite step 6 as «выберите значение производителя из списка значений». Add the Oy tip and the "save to apply" note. Remove «самообновляющимися».

## create-a-3d-pdf-template

- **Unsupported**:
  - Step 5 «поле типа OK с именем «Model Name»». Transcript: "the model name which refers [to] the title you give the PDF". No field type is given. The digest copied the "OK" type from the 3D window.
  - Steps 6 and 7 field names «Play», «Stop», «Reset». Transcript: "controls for resetting or playing or stopping". Exact names are only visible on screen and are never spoken. Yet the same video warns that different names or types will not work.
  - Step 8 «текстовые поля» for component list/description. Types are not stated.
  - Step 3 «меню «Инструменты»» is not in the transcript.
  - Step 12 path «Documents\Visual Components\My Templates\PDFs». Transcript: "in your Visual Components documents in a folder called my templates PDFs". The path structure is reconstructed.
- **Wrong**:
  - Step 4 «поле типа OK» is a literal copy of "okay type button", which is garbled speech-to-text (probably a Button-type field). Unclear to a novice.
  - Step 8 «описания материалов» is an off reading of "component description ... mostly for your build materials".
- **Missed**:
  - The recording workflow in R-Pro: choose the template, give a title, start recording, choose a file name (overwrite), run the simulation, stop and save, then it opens in Acrobat.
  - The link button: double-click the field and in the action set Mouse Down → open web link. The demo URL was wrong and he fixed it.
  - The minimal "3D window only" template shows only the 3D world, with no component list or description. Test a template by re-recording and overwriting the old file.
- **Terminology**:
  - «поле типа OK» is unclear.
  - «Спецификация» in keywords vs "bill of materials".
  - The «VC_» prefix and the «Documents\Visual Components» folder are likely rebranded in R-Pro.
- **Danger for the assistant**:
  - Guessed field names and types are likely to give a template that silently does not populate.
  - The assistant may state the VC_ prefix and folder as certain for R-Pro.
  - The lesson requires paid Acrobat Pro.
- **Scores**: fidelity 3, usefulness 3
- **Verdict**: fix. Mark field names and types as "посмотреть в шаблоне, который идёт с R-Pro" instead of inventing them. Add the recording workflow and the link action. Replace «поле типа OK» with «кнопка (Button)». Flag the R-Pro folder name and prefix as needing verification.

## depalletizing-using-pm-detach-statement

- **Unsupported**:
  - Step 3 «Создайте новый ручной «ПРОЦЕСС»». Transcript: he "extends" the existing process from the previous tutorial and renames it "unloading". "Manual" is invented (digest).
  - Step 9/11 variable «запечатывание» (from "seals"). Transcript: "sales" and "seals" are speech-to-text noise for the variable of the cylinders. The items are cylinders, a sheet and a pallet. The Russian word is meaningless as a name.
  - Tip «удаляет все экземпляры типа». Transcript: "I want to detach many ... whatever is detached". No "all instances of a type".
  - Pitfall «Пустой поддон ... иначе остаётся в процессе». Transcript: "at the very last there is pallet that goes to the conveyor". No warning.
  - Step 5 "Исполнитель Процесса" is not named in the transcript.
- **Wrong**:
  - Tip «извлечь разные типы с разных мест». The second detach is from the same pallet.
  - Steps 18 and 19 are one action. Transcript: bring the unloading and the sink together "using this transport link".
  - Step 21 «Уменьшите количество паттерна». Transcript: change the pattern count in Transport Pattern In (where the cylinders are brought in) to 1 in X and 3 in Y. Where is not stated.
  - Cyrillic variable names (запечатывание, пластина) are not in the transcript.
- **Missed**:
  - Prerequisite: the lesson continues the previous palletizing tutorial (sheet + cylinders on a pallet). Without that layout the steps are not reproducible (sample-layout-final.zip is offered).
  - The 10-second delay between the sheet release and the pallet leaving, and reducing the simulation speed.
  - The human's pick-up point was changed from about 270 to about 600–700 so the human reaches the pallet.
- **Terminology**:
  - «оператор открепления», «открепление множество» (detach many), «Транспорт В / Транспорт Из» look like literal word-for-word translations. Check the R-Pro names.
  - «приёмник» for sink is fine.
  - `ProductIn` is plausible but not confirmed ("product in").
- **Danger for the assistant**:
  - Cyrillic variable names in process variables may break statements or Python code in Py2.7 R-Pro.
  - «ручной процесс» sends the novice to create the wrong object.
  - Detach Many and the Transport Controller are from version 4.8.0 and may be missing in older 4.x.
- **Scores**: fidelity 3, usefulness 2
- **Verdict**: fix. Say it continues the palletizing lesson. Use Latin variable names (cylinders, sheet). Remove «ручной», the "all instances" claim and the empty-pallet pitfall. Merge steps 18 and 19. Add the 10 s delay and the pick-up point note. Check the R-Pro statement names.

| slug | fidelity | usefulness | verdict |
|---|---|---|---|
| live-stream-a-simulation | 2 | 2 | fix |
| olp-basic-workflow-for-welding | 3 | 3 | fix |
| add-a-background-plugin | 3 | 3 | fix |
| linear-and-angular-damping | 3 | 3 | fix |
| denso-robot-connectivity-plugin | 4 | 2 | fix |
| add-a-smart-collection | 4 | 3 | fix |
| create-a-3d-pdf-template | 3 | 3 | fix |
| depalletizing-using-pm-detach-statement | 3 | 2 | fix |
