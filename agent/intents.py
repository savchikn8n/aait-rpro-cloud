# -*- coding: utf-8 -*-
"""
Команды агента и частые вопросы — кодом, до модели.

Модель 8B не держит простые вещи: на «запусти симуляцию на 3 минуты» делала
отчёт, на «что из себя представляет модель» рассказывала, как запускать
симуляцию, а отчёт «6 батарей в час при цели 12» пересказывала как «узких
мест нет». Поэтому:

- **команды** (`/оптимизация`, `/габариты`, `/сцена`, `/отчёт`, `/симуляция`,
  `/домой`, `/где`, `/помощь`) выполняет код и отвечает готовым текстом;
- **частые вопросы обычными словами** («какая площадь занята?», «сколько этажей
  и какой высоты?», «что построено?», «запусти симуляцию на 3 минуты», «где пост
  пайки?») узнаются по словам и идут в те же обработчики;
- **справочные команды** (`/справка`, `/api`, `/термин`, `/совет`, `/проблема`)
  и частые неполадки обычными словами отвечает quickref.py — без модели и R-Pro;
- всё остальное — модели с инструментами (chat._loop).

Ответы — с цифрами из сцены, площадь в м², высоты в метрах.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import kits
import tools
from rpro_client import BridgeError

# --- числа по-русски --------------------------------------------------------------


def num(v: float, digits: int = 1) -> str:
    """1513 → «1 513», 6.0 → «6», 0.3 → «0,3»."""
    if v is None:
        return "—"
    r = round(float(v), digits)
    if abs(r - round(r)) < 1e-9:
        s = f"{int(round(r)):,}".replace(",", " ")
    else:
        s = f"{r:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s


def m2(v: float) -> str:
    return f"{num(v, 0)} м²"


def m(v: float) -> str:
    return f"{num(v)} м"


def _floors_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "этаж"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "этажа"
    return "этажей"


# --- обработчики --------------------------------------------------------------------

def _run(code: str) -> Any:
    return kits._run(tools.client, code)


def dims_text(focus: str = "") -> str:
    """Площадь, этажи, высоты — из сцены."""
    d = _run("result = layout_dims()")
    floors = d.get("этажи") or []
    if not floors:
        return "В сцене нет построенного производства — мерить нечего."
    n = len(floors)
    lines = []
    area = d.get("площадь_под_оборудованием_м2", 0)
    if n == 1:
        f = floors[0]
        lines.append(f"Конструкция занимает {m2(f['площадь_м2'])}: {m(f['длина_м'])} × {m(f['ширина_м'])}.")
    else:
        lines.append(f"Под оборудованием {m2(area)} на {n} {_floors_word(n)}:")
        for f in floors:
            lines.append(f"• {f['этаж']}-й этаж (отметка {m(f['отметка_м'])}) — {m2(f['площадь_м2'])}, "
                         f"{m(f['длина_м'])} × {m(f['ширина_м'])};")
        if d.get("пятно_м2"):
            lines.append(f"Пятно здания {m(d['пятно_м'][0])} × {m(d['пятно_м'][1])} = {m2(d['пятно_м2'])}.")
    h = d.get("высота_этажа_м")
    if n > 1 and h:
        t = d.get("толщина_перекрытия_м") or 0.0
        if isinstance(h, list):
            hh = ", ".join(m(x) for x in h)
            lines.append(f"Высоты этажей: {hh}.")
        else:
            clear = f", чистая высота {m(h - t)}" if t else ""
            lines.append(f"{n} {_floors_word(n)} по {m(h)} от пола до пола (перекрытия {m(t)}{clear}); "
                         f"высота здания {m(d.get('высота_здания_м'))}, верх оборудования — "
                         f"{m(d.get('верх_оборудования_м'))}.")
    elif n == 1:
        lines.append(f"Один этаж, верх оборудования — {m(d.get('верх_оборудования_м'))}.")
    if focus == "этажи" and n > 1:
        # вопрос про этажи — сначала про этажи
        lines = lines[-1:] + lines[:-1]
    return "\n".join(lines)


_KIND = {"нанесен": "нанесение", "клей": "склейка", "герметик": "герметизация", "паст": "нанесение пасты",
         "пайк": "пайка", "свар": "сварка", "затяжк": "завинчивание", "контрол": "контроль",
         "испыт": "испытание"}


def scene_text() -> str:
    """Что построено: линии по этажам, операции роботов, лифты, роботы."""
    s = _run("result = scene_summary()")
    lines_ = s.get("линии") or {}
    if not lines_:
        st = tools.client.status()
        n = st.get("component_count", 0)
        return (f"В сцене {n} компонентов, сборочных или производственных линий в ней нет."
                if n else "Сцена пустая.")
    d = _run("result = layout_dims()")
    items = sorted(lines_.items(), key=lambda kv: -kv[1].get("отметка_м", 0.0))
    n_fl = len({v.get("отметка_м") for _, v in items})
    head = (f"Построен завод на {n_fl} {_floors_word(n_fl)}" if n_fl > 1 else "Построено производство") + \
           f": {len(items)} {'линия' if len(items) == 1 else 'линии' if len(items) < 5 else 'линий'}, " \
           f"{s.get('роботов', 0)} роботов" + (f", {s['лифтов']} лифта между этажами" if s.get("лифтов") else "") + "."
    out = [head]
    types = s.get("изделия_сборки") or []
    for short, v in items:
        title = next((t for t in types if t.endswith(f"({short})")), short)
        ops = v.get("операции_роботов") or []
        op_txt = f" Роботы работают инструментом: {', '.join(o.lower() for o in ops)}." if ops else ""
        brak = f" Брак уходит в изолятор ({v['постов_контроля_с_браком']} пост.)." if v.get(
            "постов_контроля_с_браком") else ""
        out.append(f"• Отметка {m(v['отметка_м'])} — {title}: {v['постов']} постов, от «{v['первый']}» "
                   f"до «{v['последний']}».{op_txt}{brak}")
    if d.get("площадь_под_оборудованием_м2"):
        out.append(f"Под оборудованием {m2(d['площадь_под_оборудованием_м2'])}"
                   + (f", пятно здания {m2(d['пятно_м2'])}" if d.get("пятно_м2") and n_fl > 1 else "") + ".")
    t = s.get("время_симуляции_с") or 0
    out.append("Симуляция стоит на 0:00:00." if not t else f"Симуляция на отметке {t // 60:.0f} мин.")
    return "\n".join(out)


def sim_text(minutes: float) -> str:
    """Запустить симуляцию на N минут модельного времени (идёт на глазах, сама остановится)."""
    sec = max(1.0, float(minutes) * 60.0)
    st = tools.client.simulation("status")
    if st.get("running"):
        tools.client.simulation("halt")
    r = tools.client.simulation("run_for", seconds=sec)
    speed = _run("result = app.Simulation.SimSpeed") or 1.0
    wall = sec / max(float(speed), 0.01)
    return (f"Запустил симуляцию на {num(minutes)} мин модельного времени: с {r.get('time', '0:00:00')} "
            f"до {r.get('stop_at', '?')}, скорость ×{num(speed)} — это около {num(wall / 60.0)} мин на часах. "
            "Остановится сама. Выпуск и узкое место покажет /отчёт.")


def report_text(minutes: float = 0.0) -> str:
    import line_report
    # через инструмент агента: он же сравнивает с целью заказчика
    rep = tools.t_line_report(minutes=max(0.0, min(float(minutes), 120.0)), speed=25.0)
    return line_report.summary_text(rep)


def home_text() -> str:
    r = _run("result = robots_home()")
    return (f"Роботы возвращаются «Домой» между заданиями: автовозврат у {r['контроллеров_с_возвратом']} "
            f"контроллеров, «Домой» добавлено в {r['подпрограмм_с_домой']} подпрограмм операций.")


def where_text(query: str) -> str:
    """Найти пост, робота, лифт по словам и показать камерой."""
    r = _run("result = locate(%r)" % query)
    if not r:
        return f"Не нашёл в сцене ничего похожего на «{query}»."
    out = []
    for x in r[:5]:
        out.append(f"• {x['что']} — отметка {m(x['отметка_м'])}, x {m(x['x_м'])}, y {m(x['y_м'])}"
                   + (f"; {x['кто']}" if x.get("кто") else ""))
    _run("m_ = l2m(%r)\ncamera([m_.P.X, m_.P.Y, m_.P.Z + 700.0], "
         "[m_.P.X + 5000.0, m_.P.Y - 7000.0, m_.P.Z + 5000.0])\nresult = 1" % (r[0]["где"],))
    return "Нашёл (камера — на первом):\n" + "\n".join(out)


def optimize_text(arg: str = "") -> str:
    import optimizer
    # «/оптимизация выделенную линию», «… выбранное», «… эту линию»
    sel = bool(re.search(r"(выделен|выбран|отмечен|\bэт[уаио]\b)", arg))
    return optimizer.run(tools.client, dry=("провер" in arg or "план" in arg), selected=sel)


# Один список на всё: из него собираются /помощь и подсказка команд в панели
# R-Pro (GET /commands у serve.py). (команда, аргументы, что делает, группа)
COMMANDS: list[tuple[str, str, str, str]] = [
    ("/справка", "<вопрос>", "короткий ответ по шагам: как сделать, что такое", "Справка"),
    ("/проблема", "<что случилось>", "проверенные ответы на частые неполадки", "Справка"),
    ("/термин", "<слово>", "английское название ↔ русская кнопка R-Pro", "Справка"),
    ("/api", "<имя>", "класс или метод Python API R-Pro", "Справка"),
    ("/совет", "<тема>", "советы из уроков Academy", "Справка"),
    ("/задание", "[A|B|C]", "конкурс TechSkills: задание модуля A, B или C", "Конкурс"),
    ("/критерии", "<A|B|C>", "чек-лист приёмки модуля и частые ошибки", "Конкурс"),
    ("/раскладка", "[Д Ш а б]", "коробки на паллете: сколько и как (по умолчанию 1200 800 100 90)", "Конкурс"),
    ("/расчёт", "[годных мин брак% такт]", "план выпуска: запуски, паллеты, контейнеры", "Конкурс"),
    ("/откат", "[N]", "вернуть сцену к последнему автосохранению (или к номеру N)", "Сцена"),
    ("/автосохранение", "", "список автосохранений перед правками агента", "Сцена"),
    ("/сохрани", "[название]", "сохранить копию сцены вручную, чтобы потом откатиться", "Сцена"),
    ("/состояние", "", "что открыто, сколько компонентов, симуляция, выделение", "Сцена"),
    ("/сцена", "", "состав сцены: компоненты или построенные линии", "Сцена"),
    ("/ошибки", "", "ошибки и предупреждения из панели вывода", "Сцена"),
    ("/каталог", "<что найти>", "поиск модели в каталоге R-Pro", "Сцена"),
    ("/снимок", "[вопрос]", "снимок окна и описание моделью зрения", "Сцена"),
    ("/габариты", "", "площадь под оборудованием (м²), этажи, высоты", "Сцена"),
    ("/где", "<что>", "найти пост, робота или лифт и показать камерой", "Сцена"),
    ("/симуляция", "<минуты>", "запустить симуляцию на N минут", "Сцена"),
    ("/отчёт", "[минуты]", "выпуск, брак, узкое место", "Сцена"),
    ("/оптимизация", "[выделенное | проверка]", "сжать линии и убрать лишнее: было → стало, м²", "Сцена"),
    ("/домой", "", "роботы возвращаются «Домой» между заданиями", "Сцена"),
    ("/очистить", "", "очистить сцену: удалить все компоненты (переспрошу)", "Сцена"),
    ("/сброс", "", "начать разговор заново", "Разговор"),
    ("/помощь", "", "список команд", "Разговор"),
]


def _help_text() -> str:
    out = []
    for group in ("Справка", "Конкурс", "Сцена", "Разговор"):
        out.append(f"**{group}**" + (" — сразу, без ожидания" if group == "Справка" else ""))
        for cmd, args, what, g in COMMANDS:
            if g == group:
                out.append(f"• `{cmd}{' ' + args if args else ''}` — {what}")
    out.append("Остальное — обычными словами: «как собрать конвейерную линию?», «построй линию из 3 станков».")
    return "\n".join(out)


HELP = _help_text()


# --- распознавание -------------------------------------------------------------------

_NUM = r"(\d+(?:[.,]\d+)?)"

# фразы про задания TechSkills — к модели с инструментами модулей
_TECHSKILLS = re.compile(r"(модул\w*\s+[abcвас]\b|тестов\w* задани|techskills|техскилс|vsm|yamazumi|ямадзуми|"
                         r"ямазуми|бережлив|lean|фарм|сироп|таблет|блистер|паллетиз|общ\w* пол|одном пол|"
                         r"все три модул|ячейк\w* kuka|цилиндр|оформ\w* (сцен|цех|планировк|завод|линию)|сделай\w* (сцену |цех )?живее)",
                         re.IGNORECASE)


def _minutes(text: str, default: float) -> float:
    m_ = re.search(_NUM + r"\s*(час|ч\b|мин|м\b|сек|с\b)?", text)
    if not m_:
        return default
    v = float(m_.group(1).replace(",", "."))
    unit = (m_.group(2) or "мин").lower()
    if unit.startswith("ч"):
        return v * 60.0
    if unit.startswith("с"):
        return v / 60.0
    return v


def reference_text(query: str) -> str:
    """
    /справка <вопрос> — прямой ответ на вопрос (answer.py): проверенное, карточка
    задачи, шаги со страницы справки, определение; иначе коротко моделью по
    справке; иначе честное «нет». /справка <раздел> — раздел; /справка уроки … —
    выдержки из уроков Academy.
    """
    import answer
    import kb
    import quickref
    q = query.strip()
    if not q:
        return ("Напишите вопрос после команды, например: **/справка как собрать конвейерную линию**.\n"
                "Ответ — по шагам, из справки R-Pro и проверенных на ней приёмов.")
    if q.lower().startswith(("уроки ", "урок ", "курс ", "иитб ")):
        return quickref.help_text(q)
    # точное название раздела («/справка Сохранение планировки») — сам раздел
    try:
        hits = kb.search(q, 1)
    except OSError:
        hits = []
    if hits and hits[0]["score"] >= 1000:
        page = answer.task_page(hits[0]["title"])
        return answer.render_task(page, q) if page else quickref.help_text(q)
    text, _ = answer.answer(q)
    return text or answer.not_found(q)


_REFERENCE = ("справк", "спр", "api", "апи", "термин", "перевод", "словарь", "совет", "лайфхак",
              "проблем", "неполад", "ошибк", "помощь", "help", "команды", "?")


def is_reference(text: str) -> bool:
    """Справочная команда — её ответ не нужен модели в истории разговора."""
    low = (text or "").strip().lower()
    if not low.startswith("/"):
        return False
    cmd = low[1:].partition(" ")[0]
    return cmd.startswith(_REFERENCE)


# Очистка сцены — только командой /очистить и только после «да» на вопрос
# «вы уверены?». Модели clear не достаётся вовсе (chat._loop вырезает его):
# 13.10 на вопрос о браке разливочной машины 8B вызвала проверку линии с
# clear=true. Когда задан вопрос — время, через 10 мин он «протухает».
_clear_asked = [0.0]
_CLEAR_YES = re.compile(r"^да\b[\s,.!]*(очищай|очисти|удаляй|уверен\w*|конечно)?[\s.!]*$")
_CLEAR_WISH = re.compile(r"(с нуля|с чистого листа|в пуст\w+ (сцен|цех|планировк)|очист\w* сцен\w*)")


def _clear_question() -> str:
    import skills
    n = len(skills.inventory())
    if not n:
        return "Сцена и так пустая — очищать нечего."
    import time
    _clear_asked[0] = time.time()
    return (f"Вы уверены, что хотите очистить сцену? Будут удалены все компоненты ({n}), "
            "отменить нельзя. Ответьте «да» — очищу; любой другой ответ — отмена.")


def _clear_answer(low: str) -> str | None:
    """Ответ на «вы уверены?»: «да» — очистка, другое — отмена (None — разбирать дальше)."""
    import time
    asked, _clear_asked[0] = _clear_asked[0], 0.0
    if not asked or time.time() - asked > 600:
        return None
    if _CLEAR_YES.match(low.strip()):
        import skills
        return skills.clear_text()
    if re.match(r"^(нет|не надо|не нужно|отмена|отмени|стоп|не очищай)\b", low.strip()):
        return "Хорошо, сцену не трогаю."
    return None


_course_asked: list = [0, 0.0]   # [номер урока, когда спросили «заменить сцену?»]


def _course_run(n: int) -> str:
    from iitb import course
    try:
        return course.run_text(n)
    except Exception as exc:  # noqa: BLE001
        return f"Задание урока {n} не выполнилось: {type(exc).__name__}: {str(exc)[-300:]}"


def _course_start(n: int) -> str:
    """Задание курса заменяет сцену: если в ней есть компоненты — сначала просим «да»."""
    from iitb import course
    if n not in course.LESSONS or course.LESSONS[n][2] in ("только интерфейс", "в работе"):
        return course.run_text(n)           # объяснение вместо запуска — сцену не трогает
    import skills
    import time
    try:
        count = len(skills.inventory())
    except Exception:  # noqa: BLE001 — R-Pro недоступна: пусть run_text скажет это сам
        count = 0
    if count:
        _course_asked[0], _course_asked[1] = n, time.time()
        return (f"Задание урока {n} («{course.LESSONS[n][0]}») заменит текущую сцену ({count} компонентов), "
                "отменить нельзя. Ответьте «да» — выполню; другой ответ — отмена.")
    return _course_run(n)


def handle(text: str, on_tool: Callable | None = None) -> str | None:
    """Ответ кодом или None — тогда спрашиваем модель."""
    t = (text or "").strip()
    low = t.lower().replace("ё", "е")

    def done(name: str, answer: str) -> str:
        if on_tool is not None:
            on_tool(name, {"текст": t}, answer[:2000])
        return answer

    if _clear_asked[0]:
        r = _clear_answer(low)
        if r is not None:
            return done("очистить", r)

    # Откат к автосохранению (snapshots.py): «откатись», «верни как было», /откат [N]
    if not low.startswith("/"):
        import snapshots
        if snapshots.ROLLBACK.match(low):
            return done("откат", snapshots.rollback_text(tools.client))

    # Курс ИИТБ: задание заменяет сцену — если в ней что-то есть, сначала спрашиваем «да»
    if _course_asked[0]:
        n_, asked = _course_asked
        _course_asked[0], _course_asked[1] = 0, 0.0
        import time as _t
        if _t.time() - asked < 600 and re.match(r"^да\b", low.strip()):
            return done("курс ИИТБ", _course_run(int(n_)))
        if _t.time() - asked < 600 and re.match(r"^(нет|не надо|отмена|отмени|стоп)\b", low.strip()):
            return done("курс ИИТБ", "Хорошо, задание не запускаю, сцену не трогаю.")

    # Тема курса ИИТБ, применяемая к сцене пользователя (видео, дашборд, детектор, ячейка), и вопросы «как …»
    # по темам уроков — не для быстрых обработчиков ниже («поставь … захват» → каталог, «покажи … » → где задаётся):
    # они их перехватывали. Идёт к модели с рецептом урока или в общий поиск (chat.py).
    if not low.startswith("/"):
        try:
            from iitb import course
            rec_ = course.recipe(low)
            if rec_ is not None and course.intent(t) is None:
                # просьба «поставь детектор / запиши видео / покажи статистику на дашборде» — к сцене пользователя:
                # проверенный код (course_skills.py); «как …» и прочее — к общему поиску и модели
                if rec_[0] in (5, 6, 13) and course._DO.search(low) and not course._HOW.search(low):
                    import course_skills
                    return done("курс ИИТБ", course_skills.run(rec_[0], t))
                return None
        except Exception:  # noqa: BLE001 — курс не должен ломать остальные ответы
            pass

    if low.startswith("/"):
        cmd, _, arg = low[1:].partition(" ")
        if cmd.startswith("откат") or cmd in ("undo", "rollback"):
            import snapshots
            n_ = re.search(r"\d+", arg)
            return done("откат", snapshots.rollback_text(tools.client, int(n_.group()) if n_ else None))
        if cmd.startswith("автосохр") or cmd in ("снимки", "версии"):
            import snapshots
            return done("автосохранение", snapshots.list_text())
        if cmd.startswith("сохран") or cmd in ("save", "чекпоинт"):
            import snapshots
            name_ = t[1:].partition(" ")[2].strip() or "вручную"
            e_ = snapshots.take(tools.client, name_)
            return done("автосохранение", f"Сцена сохранена: «{name_}» ({e_.get('components')} компонентов). Вернуться — «откатись» "
                        "или /откат." + (f"\n{e_['warning']}" if e_.get("warning") else ""))
        if cmd.startswith("очист") or cmd in ("clear", "очистка"):
            return done("очистить", _clear_question())
        if cmd in ("помощь", "help", "команды", "?"):
            return done("команда", HELP)
        if cmd.startswith("оптимиз"):
            return done("оптимизация", optimize_text(arg))
        if cmd.startswith("габарит") or cmd.startswith("площад") or cmd.startswith("этаж"):
            return done("габариты", dims_text())
        if cmd.startswith("сцен"):
            import skills
            return done("сцена", skills.components_text())
        if cmd.startswith("состоян") or cmd in ("статус", "status"):
            import skills
            return done("состояние", skills.status_text())
        if cmd.startswith("ошибк") and not t[1:].partition(" ")[2].strip():
            import skills
            return done("ошибки", skills.errors_text())
        if cmd.startswith("каталог"):
            import skills
            q = t[1:].partition(" ")[2].strip()
            return done("каталог", skills.catalog_find_text(q) if q else "Что найти? Например: /каталог робот KUKA 30 кг")
        if cmd.startswith("снимок") or cmd in ("скриншот", "look"):
            import skills
            return done("зрение", skills.look_text(t[1:].partition(" ")[2] or "Что видно в окне R-Pro?"))
        if cmd.startswith("симул"):
            return done("симуляция", sim_text(_minutes(arg, 3.0)))
        if cmd.startswith("отч"):
            return done("отчёт", report_text(_minutes(arg, 0.0) if arg else 0.0))
        if cmd.startswith("дом"):
            return done("домой", home_text())
        if cmd.startswith("где") or cmd.startswith("найд") or cmd.startswith("покаж"):
            return done("где", where_text(arg))
        # конкурсное задание TechSkills (contest.py): задание, критерии, паллет, расчёт — без модели и без R-Pro
        import contest
        raw_ = t[1:].partition(" ")[2].strip()
        ct = contest.handle(cmd, raw_)
        if ct is not None:
            return done("конкурс", ct)
        # справочные команды — без модели и без R-Pro (quickref.py); аргумент
        # берём из исходного текста: в именах API важен регистр
        import quickref
        raw = t[1:].partition(" ")[2].strip()
        if cmd.startswith("справк") or cmd in ("спр", "help-kb"):
            return done("справка", reference_text(raw))
        if cmd in ("api", "апи"):
            return done("api", quickref.api_text(raw))
        if cmd.startswith("термин") or cmd.startswith("перевод") or cmd == "словарь":
            return done("термин", quickref.term_text(raw))
        if cmd.startswith("совет") or cmd.startswith("лайфхак"):
            return done("совет", quickref.tips_text(raw))
        if cmd.startswith("проблем") or cmd.startswith("неполад") or cmd.startswith("ошибк"):
            return done("проблема", quickref.problem_text(raw))
        return None   # /сброс, /выход и прочее — у чата

    # «Построй с нуля…», «в пустой сцене…», «как очистить сцену?» — сам не
    # очищаю: подсказываю /очистить (если сцена не пустая — иначе строим)
    if _CLEAR_WISH.search(low):
        import skills
        hint = skills.clear_hint_text(building=not re.search(r"очист\w* сцен", low))
        if not hint.startswith("Сцена и так пустая") or re.search(r"очист\w* сцен", low):
            return done("очистить", hint)

    # Курс ИИТБ словами: «выполни задание урока 15», «сделай паллетирование из курса ИИТБ» — выполняет
    # код; «как делать урок 5?» — объясняет по конспекту, сцену не трогает
    try:
        from iitb import course
        it_ = course.intent(t)
    except Exception:  # noqa: BLE001 — курс не должен ломать остальные ответы
        it_ = None
    if it_ is not None:
        n_ = it_[1]
        if it_[0] == "explain":
            return done("курс ИИТБ", course.explain_text(n_))
        return done("курс ИИТБ", _course_start(n_))

    # Задания TechSkills — это инструменты модели (модули A, B, C, общее поле).
    # 12.10 «…оптимизируй её и подготовь VSM» перехватила команда «оптимизация»
    # (сжатие планировки) и удалила из сцены сборщиков как «лишнее».
    if _TECHSKILLS.search(low):
        import skills
        # «где у блистерной машины задаётся брак?» — вопрос о компоненте сцены,
        # а не просьба выполнить модуль: слово «блистер» не должно уводить к модели
        if skills._WHERE_Q.search(low):
            r = skills.prop_where_text(t)
            if r is not None:
                return done("где задаётся", r)
        return None

    # Базовые навыки из описания агента (skills.py): состояние, состав сцены,
    # свойства, найти и выделить, ошибки, симуляция, каталог, снимок, правки.
    # Раньше их выбирала модель — и в прогоне 06.10 справилась с 2 из 17.
    import skills
    try:
        r = skills.run(t, on_tool)
    except BridgeError:
        raise
    except Exception as exc:  # noqa: BLE001 — честно, а не молча к модели
        r = f"Не получилось: {str(exc)[:400]}"
    if r is not None:
        return r

    # обычные слова
    if re.search(r"площад", low) and not re.search(r"(сократ|уменьш|сожм|оптимиз)", low):
        return done("габариты", dims_text())
    if re.search(r"(сколько|какие|какой|какая|каков).{0,20}этаж|этаж\w*.{0,30}высот|высот\w*.{0,30}(этаж|здани|цех)"
                 r"|габарит|размер\w* (здани|цеха|завода|производства|конструкц)", low):
        return done("габариты", dims_text("этажи"))
    if re.search(r"(что|чем)\s+(сейчас\s+)?(построено|собрано|в сцене|стоит в сцене|из себя представляет"
                 r"|представляет|за модел|у нас (сейчас )?(построено|есть))", low) or \
            re.search(r"(опиши|расскажи (про|о)|покажи что) .{0,20}(сцен|модел|построен|завод|производств)", low):
        return done("сцена", scene_text())
    m_ = re.search(r"(запусти|прогони|включи|пусти)\w*\s+(симуляц\w*|модел\w*|прогон)?.{0,25}?"
                   r"(на|длительностью|в течение)\s+" + _NUM + r"\s*(час|ч\b|мин|сек|с\b)", low)
    if m_ and not re.search(r"отч[её]т|узк|выпуск|сколько выпус", low):
        return done("симуляция", sim_text(_minutes(low[m_.start(4):], 3.0)))
    if re.search(r"(оптимизир|оптимизац|сократи площад|сожми|ужми|убери лишн)", low):
        return done("оптимизация", optimize_text("проверка" if "?" in low else ""))
    m_ = re.search(r"^(где|покажи|найди)\s+(.+)", low)
    if m_ and not re.search(r"(кнопк|меню|настройк|свойств|в программе|в r-pro)", low):
        return done("где", where_text(m_.group(2).strip(" ?.!")))
    import quickref
    # «как по-русски Component Container?», «как в R-Pro называется Feeder?» — словарь
    m_ = re.search(r"(как (это )?по-русски|как (в r-pro |в программе )?называется|перевод\w*)\s+[«\"']?"
                   r"([a-z][a-z0-9 \-]{1,48}?)[»\"']?\s*\??$", low)
    if m_:
        return done("термин", quickref.term_text(m_.group(4)))
    # частые неполадки обычными словами — проверенный ответ из kb/faq.json
    known = quickref.faq_answer(t)
    if known is not None:
        return done("проблема", known)
    return None
