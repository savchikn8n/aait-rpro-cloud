# -*- coding: utf-8 -*-
"""
Диалог с ИИ-агентом R-Pro в терминале.

Запуск:  python chat.py
Команды: /выход, /сброс, /состояние, /снимок, /модель <имя>, /помощь
"""

from __future__ import annotations

import json
import os
import re
import sys

import config
import kb
import llm
import tools
from rpro_client import BridgeError

RESET, BOLD, DIM, CYAN, YELLOW, GREEN, RED = (
    "\033[0m", "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[32m", "\033[31m")


def prepare_console() -> None:
    """Русский текст и цвета в консоли Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")  # включает разбор ANSI-последовательностей в старой консоли


def _short(text: str, limit: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def ask(messages: list[dict], on_tool=None) -> str:
    """
    Прогоняет один запрос пользователя через модель с инструментами.

    on_tool — необязательный обработчик, которому сообщают о каждом вызове
    инструмента: имя, аргументы, результат. Через него окно чата внутри R-Pro
    показывает ход работы так же, как терминал.
    """
    # Команды (/оптимизация, /габариты…) и частые вопросы («какая площадь?»,
    # «что построено?», «запусти симуляцию на 3 минуты») — кодом, до модели:
    # 8B на них отвечала не то (intents.py).
    import intents
    _progress("разбираю просьбу…")
    try:
        прямой = intents.handle(_last_user_text(messages), on_tool)
    except BridgeError as exc:
        прямой = f"R-Pro не отвечает: {exc}"
    # Вопрос «как сделать … / что такое …» о работе в программе — прямой ответ
    # по справке и проверенным карточкам (answer.py), а не пересказ фрагментов
    # моделью с инструментами: та расползалась на полэкрана справочного шума.
    if прямой is None and _is_howto(_last_user_text(messages)):
        import answer
        _progress("ищу в справке…")
        текст, откуда = answer.answer(_last_user_text(messages))
        print(f"{DIM}  → ответ: {откуда}{RESET}")
        прямой = текст or answer.not_found(_last_user_text(messages))
        if on_tool is not None:
            on_tool("справка", {"откуда": откуда}, прямой[:2000])
    if прямой is not None:
        if intents.is_reference(_last_user_text(messages)):
            # Справочные выдержки (/справка, /api…) модели в истории не нужны:
            # они длинные и вытесняли бы из контекста 8B сам разговор.
            if messages and messages[-1].get("role") == "user":
                messages.pop()
        else:
            messages.append({"role": "assistant", "content": прямой})
        return прямой
    _compact(messages)
    _products_note(messages)
    справка = _reference_note(messages)
    if справка is not None:
        messages.insert(len(messages) - 1, справка)
        # Что подложено к ответу — видно в трассировке: плохую подсказку из уроков
        # Academy так можно отследить до конкретного урока.
        заголовки = [ln[4:] for ln in справка["content"].splitlines() if ln.startswith("### ")]
        print(f"{DIM}  → справка подложена: {'; '.join(заголовки)}{RESET}")
    try:
        return _humanize(_loop(messages, on_tool))
    finally:
        # Справка нужна на один вопрос: в истории она съедала бы контекст.
        if справка is not None and справка in messages:
            messages.remove(справка)


_PRODUCTS_MARK = "Изделия для сборочных линий:"


def _products_note(messages: list[dict]) -> None:
    """Дописать в системную подсказку, какие изделия умеем собирать: на вопрос
    «что умеешь собирать?» модель видит только читающие инструменты и описания
    стройки не знает. Список — из наборов в «Моих моделях»."""
    if not messages or messages[0].get("role") != "system":
        return
    if _PRODUCTS_MARK in (messages[0].get("content") or ""):
        return
    titles = ["двигатель V8"] + tools._kit_titles()
    messages[0] = {**messages[0], "content": messages[0]["content"] + "\n" + _PRODUCTS_MARK + " "
                   + ", ".join(titles) + ". Новое изделие — если его сборка описана в каталожной "
                   "планировке: rpro_assembly_kit снимает набор (с согласия пользователя: сцена очищается)."}


HISTORY_CHARS = 9000      # ~3 тысячи токенов на прошлые ходы при контексте 8 тысяч
OLD_TOOL_CHARS = 400      # ответ инструмента из прошлых ходов — до сути


def _compact(messages: list[dict]) -> None:
    """Сжать историю перед новым вопросом (на месте).

    Контекст модели — 8 тысяч токенов: подсказка, описания инструментов и
    длинная история не помещаются вместе, и первой вытесняется подсказка —
    модель забывает правила. Поэтому ответы инструментов из прошлых ходов
    ужимаются до начала (там главное: числа и итог), а если история всё
    равно длинная — самые старые ходы выбрасываются целиком, по реплике
    пользователя с её ответами."""
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    for i, m in enumerate(messages[:last_user]):
        if m.get("role") == "tool" and len(m.get("content") or "") > OLD_TOOL_CHARS:
            messages[i] = {**m, "content": m["content"][:OLD_TOOL_CHARS] + " …"}

    def size() -> int:
        return sum(len(m.get("content") or "") for m in messages[1:last_user])

    while size() > HISTORY_CHARS:
        # первый ход после системной подсказки: реплика пользователя и всё до следующей
        starts = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if len(starts) < 2:
            break
        del messages[starts[0]:starts[1]]
        last_user = max(i for i, m in enumerate(messages) if m.get("role") == "user")


def _reference_note(messages: list[dict]) -> dict | None:
    """
    Справка по теме вопроса, найденная заранее.

    Маленькая модель часто не догадывается заглянуть в справочник и отвечает
    по памяти: так она объявила, что «встроенной метрики загрузки нет», хотя
    на ленте есть кнопка «Статистика». Поэтому два самых подходящих фрагмента
    кладутся рядом с вопросом сами. Если поиск ничего внятного не нашёл
    («привет», «спасибо»), ничего не кладём.
    """
    if not config.KB_PREFETCH or not messages or messages[-1].get("role") != "user":
        return None
    вопрос = messages[-1].get("content") or ""
    # Конкурсное задание TechSkills (модули A, B, C): точные требования и критерии — по теме вопроса,
    # раньше общей справки и без ограничения «только вопросы как…»: просьбы тоже должны знать задание.
    try:
        import contest
        конкурс = contest.note(messages, budget=3000 if llm.provider() == "ollama" else config.CONTEST_NOTE_CHARS)
    except Exception:  # noqa: BLE001 — разбор задания не должен ломать обычный разговор
        конкурс = None
    if конкурс:
        return {"role": "system", "content": конкурс}
    # Проверенный на R-Pro факт (kb/faq.json) кладём и к просьбам: на «поставь
    # скорость конвейеров 300» модели нужно имя свойства ConveyorSpeed.
    import quickref
    проверено = quickref.faq_item(вопрос)
    # Справку — только к вопросам о работе в программе. «Сколько компонентов в
    # сцене» и «запусти симуляцию» решаются инструментами, а справка к ним лишь
    # сбивает: лексический поиск находит что-то про «Буфер».
    if not _HOWTO.search(вопрос):
        if проверено is None:
            # тема курса ИИТБ, применяемая к текущей сцене (видео, дашборд, детектор, ячейка): рецепт — к просьбе
            try:
                from iitb import course
                rec = course.recipe(вопрос.lower().replace("ё", "е"))
            except Exception:  # noqa: BLE001 — курс не должен ломать обычный разговор
                rec = None
            if rec is None:
                return None
            return {"role": "system", "content": (
                "Проверенный на R-Pro 2.2.2 рецепт по теме просьбы (код — для rpro_exec, Python 2.7; "
                "выполни его в текущей сцене пользователя, сцену не очищай):\n\n"
                f"### Курс ИИТБ, урок {rec[0]}\n{rec[1]}")}
        return {"role": "system", "content": (
            "Проверенный на R-Pro 2.2.2 факт по теме запроса — опирайся на него:\n\n"
            f"### {проверено['title']}\n{проверено['answer']}")}
    try:
        найдено = [f for f in kb.search(вопрос, 4)
                   if f["score"] >= config.KB_PREFETCH_MIN_SCORE
                   and not f["title"].startswith(_NOT_REFERENCE)][:2]
    except OSError:
        return None  # база не собрана — агент работает и без неё
    if проверено is not None:
        найдено = [{"title": проверено["title"], "text": проверено["answer"], "source": "faq"}] + найдено[:1]
    if not найдено:
        return None
    # Два урока подряд вытесняют справку (оценка A/B): после порога оставляем один.
    if len(найдено) == 2 and all(f["source"] == "academy" for f in найдено):
        найдено = найдено[:1]
    части = [f"### {f['title']}\n{f['text'][:config.KB_PREFETCH_CHARS]}" for f in найдено]
    уроки = ""
    if any(f["source"] == "academy" for f in найдено):
        # Уроки записаны для Visual Components, на котором основан R-Pro; аудит по
        # транскриптам нашёл в них неточные названия кнопок и имён API.
        уроки = ("Фрагменты «Уроки Academy» — приёмы из обучающих видео Visual Components "
                 "(R-Pro на нём основан): названия кнопок сверяй со справкой и лентой, а код "
                 "для rpro_exec пиши только на Python 2.7. ")
    return {"role": "system", "content": (
        "Фрагменты справки R-Pro, найденные по вопросу автоматически. Опирайся на них, "
        "если они по делу; чего в них нет — уточни через rpro_help, а не додумывай. "
        + уроки + "\n\n"
        + "\n\n".join(части))}


_HOWTO_STRICT = re.compile(
    r"^\s*(подскажи(те)?,?\s+|скажи(те)?,?\s+|объясни(те)?,?\s+|а\s+)?"
    r"(как|каким образом|где (найти|взять|наход)|что такое|что значит|что означает|что делает|"
    r"зачем нужн|для чего|можно ли)\b", re.IGNORECASE)

# Вопрос о текущей сцене — его решают инструменты, а не справка.
_ABOUT_SCENE = re.compile(
    r"(в сцене|на сцене|в планировке|сейчас|у нас|у меня|эт(от|а|о|и|ого|ой|у) |мо(й|я|ё|е|и) |"
    r"построен|собран\w* (линия|завод)|на линии|на заводе|сколько)", re.IGNORECASE)


def _is_howto(text: str) -> bool:
    """«Как сделать…», «что такое…» о работе в программе, а не о текущей сцене."""
    t = (text or "").strip()
    return bool(t) and not t.startswith("/") and bool(_HOWTO_STRICT.search(t)) \
        and not _ABOUT_SCENE.search(t)


_HOWTO = re.compile(
    r"^\s*(как|где|что так|что значит|что делает|что озна|зачем|для чего|можно ли|"
    r"какой|какая|какие|каким|какую|чем отлича|объясни|расскажи|подскажи|научи|покажи как)",
    re.IGNORECASE)

# Разделы, которые упоминают всё подряд и совпадают с любым вопросом.
_NOT_REFERENCE = ("Что нового", "Поддерживаемые CAD файлы")

# Внутренние имена инструментов → как о них сказать человеку.
# Ход работы для панели в R-Pro: пока агент думает, в пузыре с точками видно,
# что он делает сейчас («смотрю список компонентов…»). Строку читает
# serve.py по GET /progress; в переписке она не остаётся — её место занимает
# ответ (требование 08.10: служебные строки — временные, как размышление).
PROGRESS = {"text": ""}


def _progress(text: str) -> None:
    PROGRESS["text"] = text


_TOOL_WORDS = {
    "rpro_catalog_find": "поиск по каталогу", "rpro_catalog_add": "добавление из каталога",
    "rpro_help": "справка", "rpro_status": "состояние программы", "rpro_scene": "список компонентов",
    "rpro_find": "поиск в сцене", "rpro_component": "свойства компонента",
    "rpro_messages": "панель вывода", "rpro_simulation": "управление симуляцией",
    "rpro_select": "выделение", "rpro_set_property": "изменение свойства",
    "rpro_look": "снимок окна", "rpro_exec": "выполнение кода",
    "rpro_build_line": "стройка линии", "rpro_build_plant": "стройка двухэтажного цеха",
    "rpro_build_assembly": "стройка сборочной линии", "rpro_line_check": "проверка линии",
    "rpro_line_fix": "починка линии", "rpro_line_report": "отчёт по прогону",
    "rpro_assembly_kit": "снятие набора изделия",
    "rpro_customer_kit": "приём моделей заказчика", "rpro_line_tune": "настройка линии",
    "rpro_link_lines": "связка участков", "rpro_build_factory": "стройка многоэтажного завода",
    "rpro_robot_cell": "ячейка переноса цилиндров",
    "rpro_lean_optimize": "модуль C: замер, оптимизация, VSM и Yamazumi",
    "rpro_pharma_plant": "модуль A: фармпроизводство и прогон",
    "rpro_techskills_field": "все три модуля на одном поле",
    "rpro_dress_scene": "оформление сцены",
}


def _humanize(answer: str) -> str:
    """Модель иногда пишет пользователю «используйте `rpro_help`» — переводим.

    Сначала целиком заменяем кусок кода в обратных кавычках, где упомянут
    инструмент (`rpro_simulation run`), потом — голые имена.
    """
    def word(m: re.Match) -> str:
        имя = re.search(r"rpro_[a-z_]+", m.group(0)).group(0)
        return _TOOL_WORDS.get(имя, имя)

    answer = re.sub(r"`[^`\n]*rpro_[a-z_]+[^`\n]*`", word, answer)
    return re.sub(r"rpro_[a-z_]+", word, answer)


def _is_question(messages: list[dict]) -> bool:
    """
    Последнее сообщение — вопрос «как/где/что», а не поручение.

    Правило «на вопрос не меняй сцену» в подсказке маленькая модель
    нарушала: на «как сделать, чтобы появлялись детали?» дважды поставила
    устройство подачи в сцену. Поэтому на вопрос она просто не получает
    инструментов, которые меняют сцену. Поручение внутри вопроса («как
    добавить конвейер? добавь его») снимает запрет.
    """
    for m in reversed(messages):
        if m.get("role") == "user":
            текст = m.get("content") or ""
            return bool(_HOWTO.search(текст)) and not _ORDER.search(текст)
    return False


_ORDER = re.compile(
    r"\b(добавь|поставь|запусти|останови|сбрось|верни|удали|сделай|создай|подключи|"
    r"соедини|передвинь|перемести|поверни|измени|поменяй|выполни|открой|собери|построй)\b",
    re.IGNORECASE)


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def _guard(name: str, args: dict, messages: list[dict]) -> str | None:
    """Отказ вместо вызова, если модель хочет то, чего пользователь не просил."""
    if name == "rpro_line_tune" and not _TUNE_OK.search(_last_user_text(messages)):
        # «прогони и скажи, что тормозит» — не просьба крутить линию: модель 8B
        # принималась менять время постов и подачу, пока не кончались шаги
        return json.dumps({"error": "Менять линию пользователь не просил. Ничего не меняй: "
                                    "назови узкое место и предложи правку словами — "
                                    "пользователь решит сам."}, ensure_ascii=False)
    if name == "rpro_exec" and _WIPE.search(str(args.get("code") or "")):
        return json.dumps({"error": "Полная очистка, пересборка или подмена сцены кодом запрещены. Работай с тем, что "
                                    "уже стоит: меняй или удаляй только то, что назвал пользователь, остальное не "
                                    "трогай. Нужна очистка — пользователь выполнит /очистить сам."}, ensure_ascii=False)
    return None


# Код, сносящий или подменяющий всю сцену: clearWorld, открытие другой планировки, цикл удаления всех компонентов.
_WIPE = re.compile(r"clearWorld|loadLayout|newLayout|app\.new\w*\(|"
                   r"for\s+\w+\s+in\s+(?:list\()?(?:app\.)?[Cc]omponents\b[\s\S]{0,250}\.delete\s*\(")

_TUNE_OK = re.compile(r"(что если|что будет|ускор|быстрее|медленн|оптимиз|улучш|сократ|уменьш|"
                      r"увелич|поменя|измени|настро|подкрут|поставь|сделай|поправ|исправ|разгруз)",
                      re.IGNORECASE)


# Слова про линии, цеха и производство: только тогда модели нужны строители,
# отчёт, настройка и починка линий.
_ABOUT_LINES = re.compile(
    r"(лини|цех|завод|участ|этаж|сборк|собер|собрат|станк|станок|станци|выпуск|узк\w* мест|отч[её]т|"
    r"производ|оптимиз|заказчик|agv|тележк|шпг|кшм|изделие|издели|двигател|брак|такт|загрузк|"
    r"что если|ускорь лент|чаще подав|почини|исправ|проверь лини|свяжи|связать|"
    r"ячейк|цилиндр|krl|пусконаладк|модул\w* b|модул\w* в|модул\w* a|модул\w* а|модул\w* c|модул\w* с|"
    r"фарм|сироп|таблет|блистер|паллет|lean|бережлив|vsm|yamazumi|ямадзуми|ямазуми|поле|techskills|техскилс|"
    r"тестов\w* задани|оформ|обстановк|живее|реалистичн)", re.IGNORECASE)

LEGACY_TECHSKILLS = {"rpro_pharma_plant", "rpro_robot_cell", "rpro_lean_optimize", "rpro_techskills_field"}

BASIC_TOOLS = {"rpro_status", "rpro_scene", "rpro_find", "rpro_component", "rpro_messages",
               "rpro_simulation", "rpro_select", "rpro_set_property", "rpro_look",
               "rpro_catalog_find", "rpro_catalog_add", "rpro_help", "rpro_exec"}


# Осмотр сцены и автосохранение (snapshots.py): правке всегда предшествует взгляд на сцену, а первой правке
# хода — копия сцены, к которой можно вернуться фразой «откатись».
LOOK_TOOLS = {"rpro_status", "rpro_scene", "rpro_find", "rpro_component", "rpro_messages", "rpro_look",
              "rpro_line_check", "rpro_line_report"}
SNAPSHOT_TOOLS = (set(tools._CHANGING) - {"rpro_simulation", "rpro_select"}) | {"rpro_dress_scene"}
_LOOK_MARK = '{"сначала_осмотр"'


def _look_first() -> str:
    """Осмотр сцены кодом: состояние, состав, последние сообщения — вместо отказа модели «сначала посмотри»."""
    parts: dict[str, str] = {}
    for key, tool, args, cap in (("состояние", "rpro_status", {}, 700), ("сцена", "rpro_scene", {"limit": 60}, 2600),
                                 ("сообщения_R-Pro", "rpro_messages", {}, 1000)):
        try:
            parts[key] = tools.run_tool(tool, args)[:cap]
        except Exception as exc:  # noqa: BLE001
            parts[key] = f"не удалось: {exc}"
    return json.dumps({
        "сначала_осмотр": True, **parts,
        "требование": "Это то, что сейчас в сцене пользователя. Определи, где именно затык, и доработай только это: "
                      "достройка, правка свойства, перестановка, связь. Не пересобирай сцену, не удаляй и не дублируй "
                      "то, что уже стоит. Теперь повтори нужный вызов."}, ensure_ascii=False)


def _autosave(name: str) -> list[str]:
    """Копия сцены перед первой правкой хода. Возвращает заметки для ответа пользователю."""
    try:
        import snapshots
        e = snapshots.take(tools.client, f"перед правкой — {_TOOL_WORDS.get(name, name)}")
        print(f"{DIM}  → автосохранение: {os.path.basename(e['path'])}{RESET}")
        notes = ["Перед правкой сохранил автосохранение сцены; не понравится результат — напишите «откатись»."]
        if e.get("warning"):
            notes.append(e["warning"])
        return notes
    except Exception as exc:  # noqa: BLE001 — сбой копии не должен блокировать работу, но молчать о нём нельзя
        print(f"{DIM}  → автосохранение не удалось: {exc}{RESET}")
        return ["Внимание: автосохранение перед правкой не удалось (" + type(exc).__name__ + ": " + str(exc)[:120] +
                ") — откат к состоянию до правки невозможен, сохраните проект сами."]


def _loop(messages: list[dict], on_tool=None) -> str:
    вопрос = _is_question(messages)
    доступные = tools.READ_ONLY_TOOLS if вопрос else tools.TOOLS
    # Строители прошлого теста TechSkills (фарма, KUKA, двигатель) заменяют сцену целиком. Задания этого
    # конкурса другие (манометр МП-63, Dobot CR10), поэтому по «сделай модуль A» агент не должен стирать
    # сцену пользователя фармфабрикой: инструменты скрыты, пока не включён RPRO_LEGACY_TECHSKILLS=1.
    if not config.LEGACY_TECHSKILLS_TOOLS:
        доступные = [t for t in доступные if t["function"]["name"] not in LEGACY_TECHSKILLS]
    # Просьба не про линии — только базовые инструменты (13 вместо 24). Со всеми
    # 24 модель 8B на «поставь длину конвейера 3000 мм» шесть минут гоняла
    # настройку и отчёт по линии, которой в сцене не было (прогон 06.10).
    if not _ABOUT_LINES.search(_last_user_text(messages)):
        доступные = [t for t in доступные if t["function"]["name"] in BASIC_TOOLS]
    сбои: list[str] = []
    отказано: set[str] = set()   # инструменты, в которых отказал _guard, — до конца хода
    был_прогон = False           # повторный отчёт в том же ходе не гоняет прогон заново
    отчёт_был = False            # в этом ходе делали отчёт — его итог и будет ответом
    осмотр_был = False           # в этом ходе уже смотрели сцену (иначе перед правкой — осмотр кодом)
    снимок_сделан = False        # автосохранение перед первой правкой хода — одно на ход
    предупреждения: list[str] = []
    for step in range(config.MAX_TOOL_STEPS):
        доступные = [t for t in доступные if t["function"]["name"] not in отказано]
        _progress("думаю…" if step == 0 else "обдумываю результат…")
        message = llm.chat(messages, tools=доступные)
        messages.append(message)

        calls = message.get("tool_calls") or []
        if not calls:
            ответ = message.get("content", "").strip()
            if tools.LAST_REPORT is not None and отчёт_был:
                # Отчёт пересказывает код: модель 8B говорила «узких мест нет,
                # производительность оптимальна» при 6 батареях в час против 12
                import line_report
                ответ = line_report.summary_text(tools.LAST_REPORT)
            return _honest(ответ, сбои, предупреждения)

        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            if name == "rpro_line_report" and (вопрос or был_прогон):
                # на вопрос и при повторе в том же ходе — отчёт по уже сделанному
                # прогону: модель 8B перезапускала прогон снова и снова
                args = {k: v for k, v in args.items() if k not in ("minutes", "run_s")}
            if name == "rpro_line_report" and (args.get("minutes") or args.get("run_s")):
                был_прогон = True
            if name == "rpro_line_report":
                отчёт_был = True
            print(f"{DIM}  → {name}({_short(json.dumps(args, ensure_ascii=False), 120)}){RESET}")
            # Сцену очищает только человек — командой /очистить с подтверждением
            # (intents.py). Модель 8B передавала clear сама: 13.10 на вопрос «где у
            # разливочной машины задаётся брак» вызвала проверку линии с clear=true
            # и спросила, очищать ли сцену. Аргумент вырезаем у всех инструментов.
            args.pop("clear", None)
            _progress(_TOOL_WORDS.get(name, "работаю с R-Pro") + "…")
            if name in LOOK_TOOLS:
                осмотр_был = True
            refused = _guard(name, args, messages)
            if not refused and name in SNAPSHOT_TOOLS:
                if not осмотр_был:
                    # «сначала посмотри, потом правь»: осмотр делает код, модель получает сцену и повторяет вызов
                    осмотр_был = True
                    refused = _look_first()
                elif not снимок_сделан:
                    снимок_сделан = True
                    предупреждения += _autosave(name)
            if refused and not refused.startswith(_LOOK_MARK):
                отказано.add(name)            # осмотр — не отказ: инструмент остаётся доступным
            output = refused or tools.run_tool(name, args)
            if (name in ("rpro_line_tune", "rpro_build_assembly", "rpro_build_line",
                         "rpro_build_plant", "rpro_link_lines", "rpro_build_factory") and not refused
                    and not _tool_error(output) and "уже_связаны" not in output[:40]):
                был_прогон = False   # линия действительно изменилась — нужен свежий прогон
            print(f"{DIM}    {_short(output)}{RESET}")
            err = _tool_error(output)
            if err:
                сбои.append(f"{_TOOL_WORDS.get(name, name)}: {err}")
            if on_tool is not None:
                on_tool(name, args, output)
            messages.append({"role": "tool", "name": name, "content": output})
            ячейка = _robot_cell_answer(name, output) or _techskills_answer(name, output)
            if ячейка:
                # Итог по ячейке пишет код и ход заканчивается: 8B (прогон 09.10)
                # вызвала стройку ячейки 8 раз подряд и в итоге выдала секунды за
                # миллиметры и несуществующее окно «Пусконаладка»
                messages.append({"role": "assistant", "content": ячейка})
                return _honest(ячейка, [], предупреждения)
            нет_набора = _no_kit_answer(name, output)
            if нет_набора:
                # 08.10, «линия сборки голых кузовов»: 8B на отказ думала ещё
                # полторы минуты и советовала «приём моделей заказчика» — словами
                # инструментов, не сказав, что можно сделать сейчас
                messages.append({"role": "assistant", "content": нет_набора})
                return нет_набора

    # Шаги кончились — пусть модель подведёт итог по тому, что уже сделано, без
    # инструментов: голое «прерываю» после десяти минут работы ничего не даёт
    messages.append({"role": "user", "content": "Шаги с инструментами кончились. Подведи итог "
                     "по уже полученным результатам: что сделано, какие числа, что не получилось."})
    try:
        final = llm.chat(messages, tools=None)
        messages.pop()   # служебную просьбу из истории убираем
        messages.append(final)
        return _honest((final.get("content") or "").strip(), сбои, предупреждения)
    except Exception:  # noqa: BLE001
        messages.pop()
        return _honest("Слишком много шагов с инструментами — прерываю. Уточните задачу.", сбои, предупреждения)


def _robot_cell_answer(name: str, output: str) -> str | None:
    """Итог по ячейке переноса цилиндров — из данных инструмента, без пересказа моделью."""
    if name != "rpro_robot_cell":
        return None
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "пусконаладка" not in data:
        return None
    p = data["пусконаладка"]
    hits = p["без_поворота"]["столкновения"]
    if isinstance(hits, dict) and hits:
        found = "; ".join(f"{k.replace(' x ', ' задевает ')} на {v[0]:.1f}–{v[1]:.1f} с цикла"
                          for k, v in hits.items())
    else:
        found = "нет"
    after = p.get("после_поворота") or {}
    after_hits = after.get("столкновения")
    nests = after.get("цилиндры_в_BASE14") or p["без_поворота"]["цилиндры_в_BASE14"]
    lines = [
        "Ячейка Модуля B собрана и проверена.",
        "• Ячейка: TOOL_DATA[12], BASE_DATA[13] и [14] по приложению, захват OUT[7] — сжать, "
        "OUT[8] — разжать (1 с), три цилиндра в стартовом ложементе.",
        f"• Программа: {', '.join(data.get('подпрограммы', []))}; PTP 15 %, LIN 0,1 м/с, "
        f"цикл {p['длительность_цикла_с']} с.",
        f"• Проверка на столкновения (шаг 20 мс), без поворота захвата: {found}.",
        f"• Повороты захвата при укладке без столкновений: {', '.join(f'+{d:g}°' for d in p['чистые_углы'])}; "
        f"выбран +{p['выбран_поворот_град']:g}°.",
        f"• После поворота: столкновений {'нет' if after_hits in (None, 'нет', {}) else after_hits}; "
        "цилиндры в гнёздах конечного ложемента (BASE_DATA[14], мм): "
        + ", ".join(f"({x:g}; {y:g})" for x, y in nests) + ".",
    ]
    files = data.get("файлы") or []
    if files:
        lines.append("• Файлы: " + "; ".join(files) + ".")
    if data.get("ошибка"):
        lines.append("Не получилось: " + data["ошибка"])
    return "\n".join(lines)


def _techskills_answer(name: str, output: str) -> str | None:
    """Итог по модулям A и C и по общему полю — из данных инструмента: числа и
    файлы пересказывает код, а не модель (см. _robot_cell_answer)."""
    if name not in ("rpro_lean_optimize", "rpro_pharma_plant", "rpro_techskills_field"):
        return None
    try:
        d = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict) or "error" in d or "ошибка" in d:
        return None
    files = lambda xs: "• Файлы: " + "; ".join(str(x) for x in xs) + "."  # noqa: E731
    if name == "rpro_lean_optimize" and "после" in d:
        b, a = d["до"], d["после"]
        lines = ["Модуль C (Lean Six Sigma) выполнен: модель сборки двигателя оптимизирована и проверена прогоном смены.",
                 f"• До: выпущено {b['выпущено']} двигателей при потребности 11, отгружено {b['отгружено']}, "
                 f"людей {b['людей']}, ошибок в выводе {b['ошибок']}.",
                 f"• После: выпущено {a['выпущено']}, отгружено {a['отгружено']} (по такту {d['такт_мин']} мин), "
                 f"людей {a['людей']}, ошибок {a['ошибок']}.",
                 "• Пять проблем: " + "; ".join(d.get("проблемы", [])) + ".",
                 files(d.get("файлы", []))]
        return "\n".join(lines)
    if name == "rpro_pharma_plant" and "итог" in d:
        t, c = d["итог"], d["расчёт"]
        k = 480.0 / max(d["прогон_мин"], 1)
        lines = [f"Модуль A: фармпроизводство построено ({d['компонентов']} компонентов) и прогнано {d['прогон_мин']} мин.",
                 f"• Сироп: разлито {t['бутылок_разлито']} бутылок, брак {t['брак_сиропа']} (в изолятор роботом), "
                 f"коробов по 36 — {t['коробов_сиропа']}" + (f" (за смену ≈ {round(t['коробов_сиропа'] * 36 * k)} бутылок при плане 10 000)" if k > 1 else "") + ".",
                 f"• Таблетки: блистеров {t['блистеров']}, брак {t['брак_блистеров']}, упаковок {t['упаковок']}, "
                 f"коробов по 48 — {t['коробов_таблеток']}" + (f" (за смену ≈ {round(t['упаковок'] * k)} при плане 3 000)" if k > 1 else "") + ".",
                 f"• Паллеты: смешанных (6+6) {t['паллет_смешанных']}, сиропа {t['паллет_сиропа']}, на складе ГП {t['паллет_на_складе']}.",
                 f"• Расчёт на смену: разлить {c['линия_2']['разлить_с_учётом_брака_5%']} бутылок, "
                 f"блистеров {c['линия_1']['блистеров_с_учётом_брака_5%']}, контейнеров {c['линия_1']['контейнеров_по_5000']}, "
                 f"постов ручной сборки {c['линия_1']['постов_ручной_сборки']}.",
                 files(d.get("файлы", []))]
        if d.get("ошибки_вывода"):
            lines.append("• В выводе есть предупреждения: " + "; ".join(m[0][:90] for m in d["ошибки_вывода"][:3]))
        return "\n".join(lines)
    if name == "rpro_techskills_field" and "проверка" in d:
        b = d.get("B", {}).get("пусконаладка", {})
        ch = d["проверка"]["счёт"]
        g = lambda key: (ch.get(key) or [0, 0])[0]  # noqa: E731
        lines = ["Все три модуля TechSkills собраны на одном поле и проверены совместным прогоном.",
                 f"• B: ячейка KUKA, повороты без столкновений {b.get('чистые_углы')}, выбран +{b.get('выбран_поворот_град')}°, KRL записан.",
                 "• C: оптимизированная сборка двигателя (канбан 11, отгрузка по такту, 4 оператора).",
                 f"• A: фармпроизводство ({d['A'].get('n')} компонентов в сцене после постройки).",
                 f"• Совместный прогон {d['проверка']['минут']} мин: коробов сиропа {g('Приём коробов сиропа')}, "
                 f"коробов таблеток {g('Приём коробов таблеток')}, двигателей на стеллаже {g('Стеллаж готовых двигателей')}.",
                 files(d.get("файлы", []))]
        if d["проверка"].get("ошибки"):
            lines.append("• Предупреждения в выводе: " + "; ".join(m[0][:90] for m in d["проверка"]["ошибки"][:3]))
        return "\n".join(lines)
    return None


def _no_kit_answer(name: str, output: str) -> str | None:
    """Сборочной линии для такого изделия нет — что можно вместо неё."""
    if name != "rpro_build_assembly":
        return None
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "умею_собирать" not in data:
        return None
    known = data.get("умею_собирать") or []
    what = (data.get("ошибка") or "").replace("Набора деталей для", "Деталей для сборки изделия").strip()
    return "\n".join([
        f"{what} Собрать его по шагам из деталей не смогу.",
        "Что могу сейчас:",
        "• линию постов с роботами без сборки изделия — «построй линию из 5 постов сборки и контроль качества»;",
        f"• сборочную линию для готового изделия: {', '.join(known[:8])}{'…' if len(known) > 8 else ''};",
        "• новое изделие — по моделям заказчика (CAD деталей и спецификация) или по каталожной планировке, "
        "где сборка уже описана.",
    ])


def _tool_error(output: str) -> str:
    """Текст ошибки инструмента или пустая строка."""
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(data, dict):
        text = str(data.get("error") or data.get("ошибка") or "")
        if "Traceback" in text:
            # человеку нужна суть — последняя строка, а не путь к bridge_command.py
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            text = lines[-1] if lines else text
        return text[:200]
    return ""


_ADMITS = re.compile(r"(не получил|не удал|ошибк|не смог|не вышло|не построен|не найден|нет модел)",
                     re.IGNORECASE)


def _honest(answer: str, сбои: list[str], заметки: list[str] | None = None) -> str:
    """Ответ + то, что сделал код сам (автосохранение, предупреждения), + честная приписка о сбоях."""
    answer = _honest_failures(answer, сбои)
    if заметки:
        answer += "\n\n" + "\n".join(dict.fromkeys(заметки))
    return answer


def _honest_failures(answer: str, сбои: list[str]) -> str:
    """Если инструмент вернул ошибку, а модель в ответе о ней молчит —
    приписать, что не получилось. Модель 8B отчитывалась об удачной части
    и умалчивала о сорвавшейся (правило в подсказке нарушала)."""
    if not сбои or _ADMITS.search(answer):
        return answer
    lines = "\n".join("— " + x for x in list(dict.fromkeys(сбои))[:4])   # одинаковые — один раз
    return f"{answer}\n\nНе всё получилось:\n{lines}"


def print_banner() -> None:
    print(f"{BOLD}ИИ-агент R-Pro{RESET}")
    print(f"{DIM}модель: {llm.model_name()} ({llm.provider()}) | зрение: {config.VISION_MODEL or 'выключено'}{RESET}")
    try:
        health = tools.client.health()
        print(f"{GREEN}мост: на связи{RESET} {DIM}(версия {health.get('bridge_version')}){RESET}")
    except BridgeError as exc:
        print(f"{RED}мост: нет связи{RESET} {DIM}({exc}){RESET}")
        print(f"{YELLOW}Запустите R-Pro с установленным мостом, иначе инструменты не сработают.{RESET}")
    print(f"{DIM}/помощь — список команд, /выход — закончить{RESET}\n")


HELP = """Команды:
  /помощь            — эта справка
  /состояние         — что сейчас открыто в R-Pro
  /снимок            — описать текущий 3D-вид моделью зрения
  /сброс             — очистить историю диалога
  /модель <имя>      — сменить модель на лету
  /выход             — выйти
Всё остальное отправляется агенту как обычный запрос."""


def main() -> int:
    prepare_console()
    print_banner()
    base = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    messages = list(base)

    while True:
        try:
            line = input(f"{CYAN}вы ›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue

        if line in ("/выход", "/exit", "/quit"):
            return 0
        if line in ("/помощь", "/help"):
            print(HELP)
            continue
        if line in ("/сброс", "/reset"):
            messages = list(base)
            print(f"{DIM}история очищена{RESET}")
            continue
        if line.startswith("/модель"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                config.CHAT_MODEL = parts[1].strip()
                print(f"{DIM}модель: {config.CHAT_MODEL}{RESET}")
            continue
        if line in ("/состояние", "/status"):
            try:
                print(json.dumps(tools.client.status(), ensure_ascii=False, indent=2))
            except BridgeError as exc:
                print(f"{RED}{exc}{RESET}")
            continue
        if line in ("/снимок", "/look"):
            try:
                result = tools.t_look(question="Опиши, что сейчас показано в 3D-виде R-Pro.")
                print(result["observation"])
                print(f"{DIM}снимок: {result['screenshot_path']}{RESET}")
            except BridgeError as exc:
                print(f"{RED}{exc}{RESET}")
            continue

        messages.append({"role": "user", "content": line})
        try:
            answer = ask(messages)
        except Exception as exc:  # noqa: BLE001
            print(f"{RED}Ошибка: {exc}{RESET}")
            continue
        print(f"\n{BOLD}агент ›{RESET} {answer}\n")


if __name__ == "__main__":
    sys.exit(main())
