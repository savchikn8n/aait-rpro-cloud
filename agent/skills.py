# -*- coding: utf-8 -*-
"""
Базовые навыки агента из его описания — кодом, без выбора инструмента моделью.

Прогон 06.10 (17 живых фраз, qwen3:8b с 24 инструментами) дал 2 из 17:
«Запусти симуляцию» модель превращала в отчёт и настройку линии, «Поставь
длину конвейера 3000 мм» — в шесть минут отчётов, «Посмотри на экран» — в «я
не могу видеть». Инструменты были, модель не выбирала их. Поэтому навыки,
которые обещает описание агента, разбираются здесь по смыслу фразы и
выполняются кодом:

- состояние проекта: что открыто, сколько компонентов, симуляция, выделение;
- состав сцены; координаты, свойства и поведения компонента;
- найти компонент по имени и выделить (камера наводится на него);
- ошибки и предупреждения из панели вывода;
- симуляция: запуск, остановка, сброс, состояние, скорость;
- каталог: найти модель, добавить в сцену;
- снимок окна и ответ модели зрения;
- изменить свойство; сдвинуть, повернуть, удалить, переименовать компонент.

Фраза, которую код не узнал, уходит модели с инструментами, как раньше.
Ответы — в разметке панели (MarkdownLite): **жирный**, шаги, `код`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import catalog
import kits
import tools

# --- общее --------------------------------------------------------------------------


def _run(code: str) -> Any:
    """Python 2.7 внутри R-Pro с библиотекой «рук» (hands27)."""
    return kits._run(tools.client, code)


def _j(value: Any) -> str:
    """Значение для вставки в код Python 2.7: json.loads вернёт unicode."""
    return "json.loads(%s)" % json.dumps(json.dumps(value, ensure_ascii=False))


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е").strip()


def num(v: float, digits: int = 1) -> str:
    r = round(float(v), digits)
    if abs(r - round(r)) < 1e-9:
        return f"{int(round(r)):,}".replace(",", " ")
    return f"{r:,.{digits}f}".replace(",", " ").replace(".", ",")


def _m(mm: float) -> str:
    return f"{num(mm / 1000.0, 2)} м"


def _sim_at_zero() -> str | None:
    """Правки сцены — только на 0:00:00: иначе после «Сброса» они пропадут.
    Возвращает отметку, с которой пришлось сбросить, или None."""
    st = tools.client.simulation("status")
    t = st.get("time_sec") or 0
    if st.get("running") or t > 0:
        tools.client.simulation("reset")
        # после самоостановки пустой симуляции часы стоят на 0,001 с — это не прогон
        return (st.get("time") or "?") if (st.get("running") or t >= 1) else None
    return None


def _reset_note(at: str | None) -> str:
    return f"\n_Симуляция стояла на {at} — сбросил на 0:00:00: менять сцену можно только в исходном состоянии._" if at else ""


# --- что в сцене ----------------------------------------------------------------------

_INVENTORY = u'''
import json
out = []
for c in app.Components:
    try:
        types = set([b.Type for b in c.Behaviours])
    except Exception:
        types = set()
    props = set()
    try:
        for p in c.Properties:
            props.add(p.Name)
    except Exception:
        pass
    tags = []
    if "rSimRobotController" in types or "rRobotExecutor" in types:
        tags.append(u"робот")
    if "rOneWayPath" in types or "rTwoWayPath" in types or "ConveyorSpeed" in props or "ConveyorLength" in props:
        tags.append(u"конвейер")
    if "rComponentCreator" in types or "rProductCreator" in types:
        tags.append(u"подача")
    if "rSensor" in types or "rComponentPathSensor" in types or "rVolumeSensor" in types:
        tags.append(u"датчик")
    info = []
    for nm in ("BOMname", "BOMdescription", "Category"):
        try:
            v = c.getProperty(nm)
            if v is not None and v.Value:
                info.append(_u(v.Value))
        except Exception:
            pass
    procs = []
    if "rProcessExecutor" in types:
        # узел процесса называется «Узел процесса #5», а человек зовёт его по
        # процессу — «ОТК бутылок»
        try:
            for b in c.Behaviours:
                if b.Type == "rProcessExecutor":
                    for r in b.Program.Routines:
                        if r.Name != "Main" and _u(r.Name) != _u(c.Name):
                            procs.append(_u(r.Name))
        except Exception:
            pass
    m = c.PositionMatrix
    par = c.Parent
    pn = None
    try:
        if par is not None and par.Component is not None and par.Component is not c:
            pn = par.Component.Name
    except Exception:
        pn = None
    out.append({"name": c.Name, "tags": tags, "info": info, "procs": procs,
                "pos": [m.P.X, m.P.Y, m.P.Z], "rot": [m.WPR.X, m.WPR.Y, m.WPR.Z], "parent": pn})
result = out
'''


def inventory() -> list[dict]:
    return _run(_INVENTORY) or []


# Слова, которые не называют объект: «у него», «этот», «в сцене»…
_STOP = set("""у него его ее её их этот эта это эти того той тот те мне нам пожалуйста сейчас в на с со
к по из за и или а сцене сцену сцена планировке какой какая какие каков какова где что
стоит стоят находится находятся расположен расположена координаты координат положение
позиция свойства свойство параметры поведения поведение все всё весь всех мой моя у до
""".split())

_ORD = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-я0-9#/.\-]+", _norm(text)) if w not in _STOP]


def _stem(w: str) -> str:
    """Основа слова как в базе знаний: «ленту» и «лента» → «лент»."""
    if re.match(r"[а-я]", w):
        import kb
        return kb.tokens_stem(w)
    return w


# Что агент поставил в сцену последним — на «удали только что добавленное»,
# «сдвинь его». Имена, а не ссылки: компонент могли удалить руками.
_last_added: list[str] = []
_last_title = [""]   # как модель называлась в каталоге: «Замкнутый конвейер» — 34 компонента

# Слова, которыми на объект показывают, а не называют его.
_POINT = re.compile(r"^(только|что|последн\w*|недавн\w*|сейчас|добавленн\w*|поставленн\w*|вставленн\w*|"
                    r"нов\w*|выделенн\w*|выбранн\w*|отмеченн\w*|эт\w*|тот|та|то|те|объект\w*|компонент\w*|"
                    r"модел\w*|элемент\w*|штук\w*|его|ее|её|их|него|нее|неё|них)$")


def is_pointer(phrase: str) -> bool:
    """Во фразе нет названия — только «это», «его», «только что добавленный»…"""
    return all(_POINT.match(w) for w in re.findall(r"[a-zа-я0-9#]+", _norm(phrase)))


def _pointed(phrase: str, comps: list[dict]) -> list[dict] | None:
    """
    «только что добавленный объект», «это», «выделенное», «его» — компоненты,
    на которые показали; None — во фразе есть название, ищем по нему.

    Журнал 08.10: на «Нет, удали только что добавленный объект» агента не
    понял никто — ни разбор, ни модель (минута попыток скрыть его свойством).
    """
    if not is_pointer(phrase):
        return None
    names = {c["name"] for c in comps}
    selected = re.search(r"(выделенн|выбранн|отмеченн)", _norm(phrase))
    if not selected:
        last = [c for c in comps if c["name"] in _last_added]
        if last:
            return last
    try:
        picked = set(_run("result = [c.Name for c in app.SelectionManager.getSelection(VC_SELECTION_COMPONENT)]") or [])
    except Exception:
        picked = set()
    sel = [c for c in comps if c["name"] in picked & names]
    if sel:
        return sel
    if len(comps) == 1:
        return comps   # в сцене одна модель — о ней и речь
    return []


def resolve(phrase: str, comps: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Компоненты сцены по словам человека: «конвейер», «робота ABB», «второй
    конвейер», «IRB 4600», «Конвейер #2». Возвращает (лучшие, все компоненты).

    Сравнение по основам слов с именем, служебными сведениями (BOMname,
    категория) и видом («робот», «конвейер» — по поведениям, а не по имени:
    робот в сцене называется «IRB 4600-60/2.05»).

    «Это», «только что добавленный», «выделенное» — см. _pointed.
    """
    comps = inventory() if comps is None else comps
    if comps:
        shown = _pointed(phrase, comps)
        if shown is not None:
            return shown, comps
    words = _words(phrase)
    if not words or not comps:
        return [], comps
    nth = None
    m = re.search(r"#\s*(\d+)|\b(\d+)-?(й|ой|ый|ий)?\b", _norm(phrase))
    for w in words:
        for k, v in _ORD.items():
            if w.startswith(k):
                nth = v
    if m and m.group(1):
        nth = None   # «#2» — часть имени, сравним целиком
    scored = []
    for c in comps:
        info = " ".join(_norm(x) for x in c.get("info") or [])
        best_c = None
        # имя компонента и имена его процессов — как равные названия
        for label in [c["name"]] + list(c.get("procs") or []):
            name = _norm(label)
            name_words = re.findall(r"[a-zа-я0-9#/.\-]+", name)
            s = 0.0
            if _norm(phrase).strip(" ?.!") == name:
                s += 100
            for w in words:
                if w.isdigit() and ("#" + w) in name.replace(" ", ""):
                    s += 6
                    continue
                st = _stem(w)
                if any(_stem(nw).startswith(st) or (len(nw) >= 4 and st.startswith(_stem(nw))) for nw in name_words):
                    s += 3
                elif any(st.startswith(t[:5]) for t in c.get("tags") or []):
                    s += 2.5
                elif st in info:
                    s += 1
            if s > 0:
                # «длину конвейера» — это «Конвейер», а не «Спиральный конвейер»:
                # имя без лишних слов сверх названных — первым
                extra = [nw for nw in name_words
                         if not any(_stem(nw).startswith(_stem(w)) or _stem(w).startswith(_stem(nw)) for w in words)]
                if best_c is None or s - 0.5 * len(extra) > best_c[1]:
                    best_c = (s, s - 0.5 * len(extra))
        if best_c is not None:
            scored.append((best_c[0], best_c[1], c))
    if not scored:
        return [], comps
    if nth is not None:
        # «второй конвейер»: среди одинаково подходящих по словам — R-Pro
        # называет их «Конвейер», «Конвейер #2», … — берём «#2», иначе второй по порядку
        raw_best = max(s for s, _, _ in scored)
        same = [c for s, _, c in scored if s == raw_best]
        tagged = [c for c in same if re.search(r"#\s*%d$" % nth, c["name"])]
        if tagged:
            return tagged[:1], comps
        if nth == 1:
            plain = [c for c in same if not re.search(r"#\s*\d+$", c["name"])]
            if plain:
                return plain[:1], comps
        if len(same) >= nth:
            return [same[nth - 1]], comps
    best = max(adj for _, adj, _ in scored)
    top = [c for _, adj, c in scored if adj == best]
    return top, comps


def _one(phrase: str, verb: str) -> tuple[dict | None, str | None]:
    """Ровно один компонент по словам или вопрос-уточнение."""
    found, comps = resolve(phrase)
    if not comps:
        return None, "Сцена пустая — компонентов нет. Добавить модель из каталога: «добавь конвейер»."
    if not found and is_pointer(phrase):
        return None, ("Не понял, о каком компоненте речь: я ничего не добавлял в этом разговоре и в сцене ничего "
                      "не выделено. Выделите компонент мышью или назовите его.")
    if not found:
        names = ", ".join(f"«{c['name']}»" for c in comps[:8])
        return None, f"В сцене нет ничего похожего на «{phrase.strip()}». Есть: {names}{'…' if len(comps) > 8 else ''}."
    if len(found) > 1:
        names = "; ".join(f"«{c['name']}»" for c in found[:8])
        return None, f"Подходят несколько: {names}{'…' if len(found) > 8 else ''}. {verb[0].upper() + verb[1:]} — назовите по имени."
    return found[0], None


# --- состояние --------------------------------------------------------------------

def status_text() -> str:
    st = tools.client.status()
    sim = st.get("simulation") or {}
    uri = st.get("layout_uri") or ""
    # После вставки модели R-Pro отдаёт адрес её файла из каталога, а не
    # планировки: это не «открытый проект».
    if uri and (not uri.lower().startswith("file:") or "/components/" in uri.lower()
                or not uri.lower().endswith((".rpro", ".vcmx"))):
        uri = ""
    if uri:
        import urllib.parse
        path = urllib.parse.unquote(uri.replace("file:///", "")).replace("+", " ")
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        head = f"Открыта планировка **{name}**" + (" (есть несохранённые изменения)" if st.get("layout_modified") else "") + "."
        where = f"\n_Файл: {path}_"
    else:
        head = "Открыта новая планировка, ещё не сохранённая" + (" (есть изменения)" if st.get("layout_modified") else "") + "."
        where = ""
    n = st.get("component_count", 0)
    t = sim.get("time_sec", 0) or 0
    clock = f"{int(t // 3600)}:{int(t // 60 % 60):02d}:{int(t % 60):02d}"
    simtxt = ("идёт" if sim.get("running") else "стоит") + f" на отметке {clock}, скорость ×{num(sim.get('speed', 1))}"
    sel = st.get("selection") or []
    lines = [head, f"• Компонентов в сцене: **{n}**", f"• Симуляция: {simtxt}",
             "• Выделено: " + (", ".join(f"«{s}»" for s in sel[:5]) if sel else "ничего")]
    return "\n".join(lines) + where


def components_text() -> str:
    # Построенная линия или завод — рассказ о них (этажи, посты, роботы), а не
    # список из сотен «cell.stl» (intents.scene_text).
    try:
        lines = (_run("result = scene_summary()") or {}).get("линии")
    except Exception:
        lines = None
    if lines:
        import intents
        return intents.scene_text()
    comps = inventory()
    if not comps:
        return "Сцена пустая — компонентов нет."
    out = [f"**В сцене {len(comps)} компонент{_ending(len(comps))}**"]
    if len(comps) <= 25:
        for c in comps:
            kind = f" — {', '.join(c['tags'])}" if c.get("tags") else ""
            on = f", стоит на «{c['parent']}»" if c.get("parent") else ""
            x, y, z = c["pos"]
            out.append(f"• **{c['name']}**{kind}: X {_m(x)}, Y {_m(y)}, Z {_m(z)}{on}")
    else:
        kinds: dict[str, int] = {}
        for c in comps:
            base = re.sub(r"\s*#\d+$", "", c["name"])
            kinds[base] = kinds.get(base, 0) + 1
        for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:20]:
            out.append(f"• {k}" + (f" × {v}" if v > 1 else ""))
        if len(kinds) > 20:
            out.append(f"…и ещё {len(kinds) - 20} видов")
        out.append("Подробно о любом: «где стоит <имя>», «свойства <имя>».")
    return "\n".join(out)


def _ending(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return ""
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "а"
    return "ов"


def coords_text(phrase: str) -> str:
    found, comps = resolve(phrase)
    if not found:
        return _one(phrase, "о каком речь")[1] or "Не нашёл."
    out = []
    for c in found[:5]:
        x, y, z = c["pos"]
        rx, ry, rz = c["rot"]
        rot = f"; поворот вокруг Z {num(rz)}°" + (f", X {num(rx)}°, Y {num(ry)}°" if abs(rx) > 0.05 or abs(ry) > 0.05 else "")
        on = f" (стоит на «{c['parent']}», координаты мировые)" if c.get("parent") else ""
        out.append(f"**{c['name']}**: X {num(x, 0)} мм, Y {num(y, 0)} мм, Z {num(z, 0)} мм{rot}{on}")
    if len(found) > 5:
        out.append(f"…и ещё {len(found) - 5} таких.")
    tools.client.select([c["name"] for c in found[:5]])
    out.append("_Выделил в сцене. Поменять положение: «сдвинь <имя> на 500 мм по X» или панель «Свойства» → X, Y, Z._")
    return "\n".join(out)


# Служебные свойства, которые инженеру ничего не говорят
_HIDDEN_PROPS = re.compile(r"^(BOM|BOMname|BOMdescription|PDFExportLevel|BackfaceMode|SimulationLevel|"
                           r"Material|Visible|Category|SignalActions::|WorkSpace::)")


def props_text(phrase: str) -> str:
    c, err = _one(phrase, "о каком речь")
    if err:
        return err
    info = tools.client.component(c["name"])
    props = [p for p in info.get("properties", []) if not _HIDDEN_PROPS.match(str(p.get("name")))]
    out = [f"**Свойства «{c['name']}»** ({len(props)})"]
    for p in props[:40]:
        v = p.get("value")
        if isinstance(v, float):
            v = num(v, 2)
        elif isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)[:60]
        out.append(f"• `{p.get('name')}` = {v}")
    if len(props) > 40:
        out.append(f"…и ещё {len(props) - 40}. Все — в панели «Свойства».")
    out.append("_Изменить: «поставь <свойство> <имя> 3000» или «измени ConveyorSpeed у конвейера на 300»._")
    return "\n".join(out)


_BEH_RU = {
    "rOneWayPath": "конвейерный путь (в одну сторону)", "rTwoWayPath": "путь в обе стороны",
    "rPythonScript": "скрипт Python", "rSimInterface": "интерфейс для стыковки (PnP)",
    "rSimDynamicInterface": "интерфейс для подключения", "rSimRobotController": "контроллер робота",
    "rRobotExecutor": "исполнитель программы робота", "rKinArticulated2": "кинематика робота",
    "rActionContainer": "приём сигнальных действий", "rSimBoolSignalMap": "карта сигналов (входы/выходы)",
    "rSimStatistics": "статистика", "rComponentCreator": "генератор компонентов",
    "rProcessExecutor": "процесс (моделирование процессов)", "rTransportNode": "транспортный узел",
    "rComponentContainer": "контейнер компонентов", "rBooleanSignal": "логический сигнал",
    "rComponentPathSensor": "датчик на пути", "rVolumeSensor": "объёмный датчик",
    "rServoController": "сервоконтроллер", "rSimDynamicContainer": "контейнер",
}


def behaviours_text(phrase: str) -> str:
    c, err = _one(phrase, "о каком речь")
    if err:
        return err
    info = tools.client.component(c["name"], with_behaviours=True)
    behs = info.get("behaviours", [])
    out = [f"**Поведения «{c['name']}»** ({len(behs)})"]
    for b in behs:
        t = b.get("type", "")
        out.append(f"• {b.get('name')} — {_BEH_RU.get(t, t)}")
    out.append("_Поведения настраиваются на вкладке «Моделирование» → дерево компонента._")
    return "\n".join(out)


# --- найти и выделить -------------------------------------------------------------

def select_text(phrase: str) -> str | None:
    """Найти в сцене и выделить, навести камеру. None — в сцене не нашлось."""
    found, comps = resolve(phrase)
    if not found:
        return None
    names = [c["name"] for c in found[:20]]
    tools.client.select(names)
    c = found[0]
    x, y, z = c["pos"]
    try:
        _run("camera([%f, %f, %f], [%f, %f, %f])\nresult = 1" % (x, y, z + 500.0, x + 4000.0, y - 6000.0, z + 4000.0))
    except Exception:
        pass
    if len(found) == 1:
        return (f"Нашёл и выделил **{c['name']}** — X {_m(x)}, Y {_m(y)}, Z {_m(z)}. Камера — на нём.")
    lst = ", ".join(f"«{n}»" for n in names[:8])
    return f"Нашёл и выделил {len(found)}: {lst}{'…' if len(found) > 8 else ''}. Камера — на первом."


# --- ошибки ------------------------------------------------------------------------

_ERR = re.compile(r"(error|ошибк|exception|traceback|warning|предупрежд|не удалось|failed|unable|невозможно|"
                  r"не найден|systemerror|valueerror|typeerror)", re.IGNORECASE)


def errors_text() -> str:
    lines = tools.client.messages(tail=300).get("lines", [])
    bad = [ln for ln in lines if _ERR.search(ln or "")]
    if not bad:
        tail = [ln for ln in lines if ln.strip()][-3:]
        return ("**Ошибок и предупреждений в панели вывода нет.**"
                + ("\nПоследние строки:\n" + "\n".join(f"• {t[:200]}" for t in tail) if tail else ""))
    uniq: list[str] = []
    for ln in bad:
        ln = ln.strip()[:240]
        if ln not in uniq:
            uniq.append(ln)
    out = [f"**В панели вывода {len(bad)} строк с ошибками или предупреждениями**"
           + (f" (разных — {len(uniq)})" if len(uniq) != len(bad) else "") + ". Последние:"]
    out += [f"• {u}" for u in uniq[-8:]]
    out.append("_Разобрать конкретную: «что значит ошибка …» или /проблема <текст>._")
    return "\n".join(out)


# --- симуляция ---------------------------------------------------------------------

def sim_text(action: str, speed: float | None = None) -> str:
    if action == "speed" and speed:
        _run("app.Simulation.SimSpeed = %f\nresult = app.Simulation.SimSpeed" % float(speed))
        return f"Скорость симуляции — ×{num(speed)}."
    r = tools.client.simulation(action)
    t = r.get("time", "0:00:00")
    if action == "run":
        # R-Pro сама гасит симуляцию, если в сцене нечему работать (autoHalt):
        # «запущена» тогда было бы неправдой — проверяем через секунду.
        import time
        time.sleep(1.2)
        st = tools.client.simulation("status")
        if not st.get("running"):
            return (f"Симуляция запустилась и сразу остановилась на {st.get('time', t)}: в сцене нечему работать. "
                    "R-Pro сама останавливает симуляцию, когда нет ни подачи деталей, ни программы у робота, "
                    "ни другого активного поведения. Добавьте «Устройство подачи» на конвейер или постройте линию: "
                    "«построй линию из 2 станков».")
        return f"Симуляция идёт с отметки {t}. Остановить — «стоп», сбросить — «сбрось симуляцию»."
    if action == "halt":
        return f"Симуляция остановлена на отметке {t}."
    if action == "reset":
        return "Симуляция сброшена на 0:00:00 — сцена в исходном состоянии."
    st = tools.client.status().get("simulation") or {}
    return (f"Симуляция {'идёт' if r.get('running') else 'стоит'}, отметка {t}, скорость ×{num(st.get('speed', 1))}.")


# --- каталог -----------------------------------------------------------------------

def catalog_find_text(query: str) -> str:
    found = catalog.найти(query, 8)
    if not found:
        return f"В каталоге ничего не нашлось по «{query}». Попробуйте другое слово или марку."
    out = [f"**В каталоге по «{query}»:**"]
    for m in found:
        maker = f", {m['производитель']}" if m.get("производитель") else ""
        out.append(f"• **{m['имя']}** — {m['раздел']}{maker}")
    out.append(f"_Поставить в сцену: «добавь {found[0]['имя']}»._")
    return "\n".join(out)


def catalog_add_text(query: str, beside: bool = False) -> str:
    """beside — «ещё один … рядом»: не поверх прежнего, а рядом (line_join.place_beside)."""
    found = catalog.найти(query, 5)
    if not found:
        return f"В каталоге нет модели по «{query}». Посмотреть похожие: «найди в каталоге …»."
    r = tools.t_catalog_add(name=query)
    if r.get("error"):
        return f"Не получилось добавить: {r['error']}"
    name = r.get("добавлено")
    n = int(r.get("новых") or 1)
    out = [f"Добавил **{name}** ({r.get('раздел')}) в начало координат."]
    if n > 1:
        out[0] = f"Добавил **{name}** ({r.get('раздел')}): в сцене +{n} компонент{_ending(n)}."
    # выделим новое, чтобы человек сразу видел и мог двигать
    try:
        new = inventory()[-max(1, n):]
        _last_added[:] = [c["name"] for c in new]
        _last_title[0] = name
        if beside and len(inventory()) > len(new):
            import line_join
            how = line_join.place_beside(tools.client, _last_added)
            out[0] = out[0].replace(" в начало координат.", ".")
            out.append(f"Поставил рядом: {how}.")
        tools.client.select([c["name"] for c in new])
        if n > 1:
            out.append("Все они выделены в сцене. Убрать — «удали только что добавленное».")
        else:
            out.append(f"Выделил его в сцене как «{new[-1]['name']}». Подвинуть: «сдвинь его на 2 м по X».")
    except Exception:
        pass
    others = list(dict.fromkeys(m["имя"] for m in found[1:6] if m["имя"] != name))[:3]
    if others:
        out.append(f"_Не та модель? Похожие: {', '.join(others)}._")
    if r.get("симуляция"):
        out.append(f"_{r['симуляция']}._")
    return "\n".join(out)


# --- зрение ------------------------------------------------------------------------

def look_text(question: str) -> str:
    q = question.strip() or "Что видно в окне R-Pro?"
    r = tools.t_look(question=q + " Отвечай по-русски, коротко и только о том, что действительно видно.")
    return f"{r.get('observation', '').strip()}\n_Снимок окна: {r.get('screenshot_path')}_"


# --- правки ------------------------------------------------------------------------

# слово человека → свойства, которые оно может означать (по порядку предпочтения)
_PROP_WORDS = [
    (r"длин", ["ConveyorLength", "Length", "PathLength"]),
    (r"ширин", ["ConveyorWidth", "Width"]),
    (r"высот", ["ConveyorHeight", "Height", "UpperHeight"]),
    (r"скорост", ["ConveyorSpeed", "Speed", "MaxSpeed", "Velocity"]),
    (r"радиус", ["ConveyorRadius", "Radius", "SpiralRadius"]),
    (r"угол|угл", ["ConveyorAngle", "Angle"]),
    (r"интервал|как часто|период", ["CreationInterval", "Interval", "TimeInterval"]),
    (r"врем\w* обработ|время цикл|время операц", ["ProcessTime", "CycleTime"]),
    (r"имя|назван", ["Name"]),
    (r"видим", ["Visible"]),
]
_LENGTHY = re.compile(r"(Length|Width|Height|Radius|Elevation|Travel)$")


def _unit_value(prop: str, value: float, unit: str) -> float:
    unit = (unit or "").lower()
    if _LENGTHY.search(prop):
        return value * {"м": 1000.0, "см": 10.0, "мм": 1.0}.get(unit, 1.0)
    if prop.endswith("Speed"):
        return value * {"м/с": 1000.0, "мм/с": 1.0, "м/мин": 1000.0 / 60.0}.get(unit, 1.0)
    return value


def set_prop_text(obj: str, prop_word: str, raw_value: str, unit: str = "") -> str:
    c, err = _one(obj, "у какого менять")
    if err:
        return err
    info = tools.client.component(c["name"])
    have = {p["name"]: p for p in info.get("properties", [])}
    prop = None
    if prop_word in have:
        prop = prop_word
    else:
        for pat, cands in _PROP_WORDS:
            if re.search(pat, prop_word):
                prop = next((x for x in cands if x in have), None)
                if prop is None:
                    prop = next((n for n in have if any(x.lower() in n.lower() for x in cands)), None)
                break
        if prop is None:
            pw = prop_word.replace(" ", "").lower()
            prop = next((n for n in have if pw and pw in n.lower()), None)
    if prop is None:
        sample = ", ".join(f"`{n}`" for n in list(have)[10:22])
        return (f"У «{c['name']}» нет свойства «{prop_word}». Есть, например: {sample}. "
                f"Все — «свойства {c['name']}».")
    old = have[prop].get("value")
    at = _sim_at_zero()
    if isinstance(old, bool):
        value: Any = _norm(raw_value) in ("да", "true", "1", "вкл", "включить")
    elif isinstance(old, (int, float)):
        value = _unit_value(prop, float(raw_value.replace(",", ".")), unit)
        if isinstance(old, int) and not isinstance(old, bool):
            value = int(round(value))
    else:
        value = raw_value
    if isinstance(value, str):
        # строки с кириллицей мост передаёт юникодом, а сеттер R-Pro хочет UTF-8
        _run("c = comp(%s)\nc.getProperty(%s).Value = _b(%s)\napp.Simulation.setInitialState()\nresult = 1"
             % (_j(c["name"]), _j(prop), _j(value)))
        new = value
    else:
        new = tools.client.set_property(c["name"], prop, value).get("value")
    shown = num(new, 2) if isinstance(new, (int, float)) and not isinstance(new, bool) else new
    was = num(old, 2) if isinstance(old, (int, float)) and not isinstance(old, bool) else old
    return f"У **{c['name']}** `{prop}`: {was} → **{shown}**." + _reset_note(at)


_AXES = {"x": 0, "х": 0, "y": 1, "у": 1, "z": 2, "з": 2}
_DIRS = {"вправо": (0, 1), "влево": (0, -1), "вперед": (1, 1), "назад": (1, -1), "вверх": (2, 1), "вниз": (2, -1)}


def move_text(obj: str, amount: float, unit: str, axis: str = "", direction: str = "") -> str:
    c, err = _one(obj, "какой двигать")
    if err:
        return err
    mm = amount * {"м": 1000.0, "см": 10.0, "мм": 1.0}.get((unit or "мм").lower(), 1.0)
    if not unit and abs(amount) <= 20:
        mm = amount * 1000.0   # «на 2 по X» — метры, миллиметрами так мало не двигают
    vec = [0.0, 0.0, 0.0]
    if direction:
        i, sgn = _DIRS[direction]
        vec[i] = sgn * mm
    else:
        vec[_AXES.get((axis or "x").lower(), 0)] = mm
    at = _sim_at_zero()
    target = c["parent"] if c.get("parent") else c["name"]
    r = _run("c = comp(%s)\nm = vcMatrix.new(c.PositionMatrix)\nm.translateAbs(%f, %f, %f)\n"
             "c.PositionMatrix = m\napp.Simulation.setInitialState()\np = c.PositionMatrix.P\n"
             "result = [p.X, p.Y, p.Z]" % (_j(target), vec[0], vec[1], vec[2]))
    x, y, z = r
    via = f" (вместе с «{target}», на котором стоит)" if target != c["name"] else ""
    return (f"Сдвинул **{c['name']}**{via} на {num(mm, 0)} мм по {'XYZ'[[i for i, v in enumerate(vec) if v][0]]}: "
            f"теперь X {num(x, 0)}, Y {num(y, 0)}, Z {num(z, 0)} мм." + _reset_note(at))


def rotate_text(obj: str, degrees: float, axis: str = "z") -> str:
    c, err = _one(obj, "какой поворачивать")
    if err:
        return err
    at = _sim_at_zero()
    ax = {"x": "X", "х": "X", "y": "Y", "у": "Y"}.get((axis or "z").lower(), "Z")
    r = _run("c = comp(%s)\nm = vcMatrix.new(c.PositionMatrix)\nm.rotateRel%s(%f)\nc.PositionMatrix = m\n"
             "app.Simulation.setInitialState()\nw = c.PositionMatrix.WPR\nresult = [w.X, w.Y, w.Z]"
             % (_j(c["name"]), ax, float(degrees)))
    return f"Повернул **{c['name']}** на {num(degrees)}° вокруг {ax}: теперь поворот по Z {num(r[2])}°." + _reset_note(at)


def delete_text(obj: str) -> str:
    found, comps = resolve(obj)
    if not found:
        return _one(obj, "какой удалить")[1] or "Не нашёл."
    # «удали только что добавленное»: шаблон планировки приносит десятки
    # компонентов — показали на все сразу, значит, и удалить все
    every = re.search(r"\b(все|всех|всё)\b", _norm(obj)) or is_pointer(obj)
    if len(found) > 1 and not every:
        names = "; ".join(f"«{c['name']}»" for c in found[:8])
        return f"Таких несколько: {names}. Удалить все — «удали все …», или назовите один по имени."
    at = _sim_at_zero()
    names = [c["name"] for c in found]
    _run("for n in %s:\n    c = app.findComponent(n)\n    if c is not None: c.delete()\n"
         "app.Simulation.setInitialState()\nresult = len(app.Components)" % _j(names))
    whole = bool(_last_added) and set(names) == set(_last_added) and len(names) > 1
    _last_added[:] = [n for n in _last_added if n not in names]
    if whole and _last_title[0]:
        # шаблон планировки целиком: 34 имени «Текст #6, Стрелка #4…» человеку не нужны
        return f"Удалил добавленный **{_last_title[0]}** — {len(names)} компонент{_ending(len(names))}." + _reset_note(at)
    lst = ", ".join(f"«{n}»" for n in names[:8])
    if len(names) > 8:
        lst += f" и ещё {len(names) - 8}"
    return f"Удалил {lst}." + _reset_note(at)


def clear_hint_text(building: bool = False) -> str:
    """
    «Очисти сцену» обычной фразой — подсказка команды /очистить, сама очистка
    только по ней и после «да» (intents.py). Фразу легко сказать мимоходом
    («начнём с нуля»), а удаление всех компонентов не отменить.
    """
    n = len(inventory())
    if not n:
        return "Сцена и так пустая." + (" Можно строить." if building else "")
    out = [f"В сцене {n} компонент{_ending(n)}. Очистить сцену — удалить их все — можно командой "
           "**/очистить**: я переспрошу и очищу только после вашего «да»."]
    if building:
        out.append("Если очищать не нужно, скажите «построй рядом …» — поставлю новое рядом с имеющимся.")
    return " ".join(out)


def clear_text() -> str:
    """Очистить сцену — только после /очистить и «да» (intents.py)."""
    n = len(inventory())
    if not n:
        return "Сцена и так пустая."
    _run("app.Simulation.reset()\napp.clearWorld()\nresult = len(app.Components)")
    _last_added[:] = []
    return f"Сцена очищена: удалил {n} компонент{_ending(n)}."


def rename_text(obj: str, new: str) -> str:
    c, err = _one(obj, "какой переименовать")
    if err:
        return err
    new = new.strip(" «»\"'.")
    _run("c = comp(%s)\nc.Name = _b(%s)\nresult = c.Name" % (_j(c["name"]), _j(new)))
    got = tools.client.find(new).get("found", 0)
    if not got:
        return (f"R-Pro не дала переименовать «{c['name']}» — у некоторых компонентов моделирования процессов "
                f"имя закреплено.")
    return f"Переименовал **{c['name']}** → **{new}**."


# --- где у компонента задаётся свойство или правило ----------------------------------
#
# 13.10: «А где я могу посмотреть, где у Роторной разливочной машины задаётся
# правило, связанное с дефектом выпускаемой продукции?» — модель 8B вызвала
# проверку линии с clear=true и спросила, очищать ли сцену. Ответ на такой
# вопрос — в самой сцене: компонент, его свойства с текущими значениями, вкладка
# панели «Свойства компонента» и строки скрипта, который это свойство применяет.

# Тема вопроса → регулярка по именам свойств и строкам скриптов (слова человека с
# именами R-Pro не совпадают: брак разливочной машины — Process::DefectRate).
_TOPICS: list[tuple[str, str, str]] = [
    (r"брак|дефект|отбрак|качеств|негодн|неполн", r"defect|reject|scrap|quality|fail(?!ure)|prodid", "брак"),
    (r"отказ|поломк|ремонт|mtbf|mttr|авари|простой|неисправн", r"mtbf|mttr|repair|failure|breakdown", "отказы и ремонт"),
    (r"скорост|темп|производительн|ppm|быстр|медлен", r"speed|\(ppm\)|velocity|productionrate", "скорость"),
    (r"врем|такт|цикл|длительн|задержк|пауз|интервал", r"time|cycle|delay|duration|interval|takt", "время"),
    (r"высот", r"height|elevation", "высота"),
    (r"длин", r"length", "длина"),
    (r"ширин", r"width", "ширина"),
    (r"радиус|диаметр", r"radius|diameter", "радиус"),
    (r"емкост|вместим|захват|сколько штук|за раз|вмеща", r"capacity|amount|count", "вместимость"),
    (r"запас|остат", r"stock|amount|inventory|buffer", "запас"),
    (r"направлен|поворот|угол|сторон", r"direction|angle|rotation", "направление"),
    (r"статистик|oee", r"statistics|oee", "статистика"),
]

# Что значит свойство — для частых; остальное показываем как есть
_MEANING = [
    (r"DefectRate$", "доля брака (0…1): с этой вероятностью каждое изделие помечается браком"),
    (r"ProductionRate\(PPM\)$", "производительность, изделий в минуту"),
    (r"MTBF\d*$", "среднее время между отказами (0 — отказов нет)"),
    (r"MTTR\d*$", "среднее время ремонта"),
    (r"RepairTask$", "задача ремонта для ресурса (пусто — без ремонтника)"),
    (r"Defects$", "сколько брака насчитано в прогоне"),
    (r"OEEQuality$", "доля годных в прогоне"),
    (r"PartsProduced$", "сколько изделий выпущено в прогоне"),
    (r"ConveyorSpeed$|^Speed$", "скорость, мм/с"),
    (r"Height$", "высота, мм"),
    (r"Length$", "длина, мм"),
]

_WHERE_Q = re.compile(
    r"(где|как|каким образом|в каком месте|откуда|как[а-я]{1,3}|покажи|посмотр|подскаж)\b.{0,90}?"
    r"(зада\w*|настра\w*|настро\w*|меня\w*|помен\w*|измен\w*|посмотр\w*|увид\w*|найти|указ\w*|хран\w*|"
    r"определ\w*|пропис\w*|устан\w*|регулир\w*|отвеча\w*|описан\w*|счита\w*|влия\w*)")
_GENERIC = re.compile(r"(правил|свойств|параметр|настройк|логик|значени)")
# Слова вопроса, а не названия компонента
_QNOISE = re.compile(
    r"^(где|как|каким|какой|какая|какое|какие|образом|месте|мож\w*|могу|посмотр\w*|увид\w*|найти|наход\w*|"
    r"зада\w*|настра\w*|настро\w*|меня\w*|помен\w*|измен\w*|указ\w*|хран\w*|определ\w*|пропис\w*|устан\w*|"
    r"регулир\w*|отвеча\w*|описан\w*|счита\w*|влия\w*|правил\w*|свойств\w*|параметр\w*|настройк\w*|логик\w*|"
    r"связ\w*|выпуск\w*|выпуска\w*|продукц\w*|издели\w*|котор\w*|значени\w*|это|ли|мне|я|можно|нужно|"
    r"чтобы|подскаж\w*|покажи|откуда|за|для|про|об|о|от|при|с|со|у|в|на|и|а|или|то|же)$")


def _topics(low: str) -> list[tuple[str, str, str]]:
    return [t for t in _TOPICS if re.search(t[0], low)]


def _object_words(low: str, topics: list) -> list[str]:
    out = []
    for w in _words(low):
        if _QNOISE.match(w) or any(re.match(r"\w*(" + t[0] + r")", w) for t in topics):
            continue
        out.append(w)
    return out


_PROP_WHERE = u'''
import re
c = comp(%s)
pat = re.compile(%s, re.I) if %s else None
props = []
for p in c.Properties:
    n = p.Name
    if "__HIDE__" in n:
        continue
    try:
        v = p.Value
    except Exception:
        v = None
    if isinstance(v, bool) or isinstance(v, (int, float)):
        pass
    elif hasattr(v, "Name"):
        v = _u(v.Name)
    else:
        v = _u(v) if v is not None else u""
    props.append({"name": _u(n), "value": v, "hit": bool(pat and pat.search(n))})
scripts = []
for b in c.Behaviours:
    try:
        src = b.Script
    except Exception:
        continue
    if not src or pat is None:
        continue
    hits = []
    for i, ln in enumerate(_u(src).split(chr(10))):
        s = ln.strip()
        if s and not s.startswith("#") and pat.search(s):
            hits.append([i + 1, s[:110]])
    if hits:
        scripts.append({"name": _u(b.Name), "type": b.Type, "lines": hits[:6]})
ru = re.compile(%s, re.I | re.U) if %s else None


def sv_(s, n):
    try:
        v = s.getProperty(n).Value
    except Exception:
        return None
    if hasattr(v, "Name"):
        return _u(v.Name)
    try:
        return _u(v)
    except Exception:
        return None


def desc_(s):
    bits = []
    for n in ("Condition", "TargetProperty", "ValueExpression", "ProductType", "Delay", "ProductVariableName"):
        v = sv_(s, n)
        if v not in (None, u""):
            bits.append(u"%%s=%%s" %% (n, v))
    return _u(str(s.Type)) + u"(" + u", ".join(bits) + u")"


def walk_(stmts, depth, out, parent):
    for s in stmts:
        out.append([depth, desc_(s), parent])
        me = len(out) - 1
        for sc, word in (("ThenScope", u"то"), ("ElseScope", u"иначе")):
            try:
                kids = getattr(s, sc).Statements
            except Exception:
                continue
            out.append([depth + 1, word + u":", me])
            walk_(kids, depth + 2, out, me)


procs = []
for b in c.Behaviours:
    if b.Type != "rProcessExecutor" or pat is None:
        continue
    try:
        routines = b.Program.Routines
    except Exception:
        continue
    for r in routines:
        flat = []
        try:
            walk_(r.Statements, 0, flat, -1)
        except Exception:
            continue
        keep = set()
        for i, (d, txt, par) in enumerate(flat):
            if pat.search(txt) or (ru is not None and ru.search(txt)):
                keep.add(i)
                while par >= 0:
                    keep.add(par)
                    par = flat[par][2]
        if keep:
            procs.append({"routine": _u(r.Name),
                          "lines": [[flat[i][0], flat[i][1][:120]] for i in sorted(keep)][:8]})
result = {"props": props, "scripts": scripts, "procs": procs}
'''


def _tab(name: str) -> str:
    """«Process::DefectRate» → вкладка «Process»; без группы — вкладка по умолчанию."""
    if "::" in name:
        return f"панель «Свойства компонента» → вкладка «{name.split('::')[0]}» → «{name.split('::', 1)[1]}»"
    return f"панель «Свойства компонента» → вкладка по умолчанию → «{name}»"


def _value(name: str, v: Any) -> str:
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, (int, float)):
        s = num(v, 3)
        if "," in s:
            s = s.rstrip("0").rstrip(",")
        if re.search(r"DefectRate$|OEE\w*$", name) and 0 <= float(v) <= 1:
            s += f" ({num(float(v) * 100, 1)} %)"
        return s
    if str(v).startswith("<vc"):
        return "положение (матрица) — задаётся в 3D-виде"
    return f"«{v}»" if v != "" else "пусто"


def prop_where_text(text: str) -> str | None:
    """Где у компонента сцены задаётся свойство (правило) — или None, если не про сцену."""
    low = _norm(text).rstrip(" ?!.")
    topics = _topics(low)
    if not topics and not _GENERIC.search(low):
        return None
    words = _object_words(low, topics)
    if not words:
        return None
    found, comps = resolve(" ".join(words))
    if not found:
        return None
    # компонент назван по имени, а не только видом («робот» — по поведениям):
    # иначе «как задать скорость робота?» без робота в сцене — это вопрос справки
    stems = [_stem(w) for w in words if len(w) > 2]
    named = [c for c in found if any(st in _norm(" ".join([c["name"]] + list(c.get("procs") or [])))
                                     for st in stems)]
    if not named:
        return None
    # «Шкаф: разливочная машина», «Камера: ОТК бутылок» — обстановка (dress27), не оборудование
    real = [c for c in named if ":" not in c["name"]]
    named = real or named
    c = named[0]
    pat = "|".join(t[1] for t in topics)
    ru = "|".join(t[0] for t in topics)
    r = _run(_PROP_WHERE % (_j(c["name"]), _j(pat), "True" if pat else "False", _j(ru), "True" if ru else "False"))
    tools.client.select([c["name"]])
    props = [p for p in r.get("props") or [] if not _HIDDEN_PROPS.match(p["name"]) and p["name"] != "Name"]
    тема = ", ".join(t[2] for t in topics) if topics else "свойства"
    head = f"**{тема[0].upper() + тема[1:]} у «{c['name']}»** — компонент выделен в 3D-виде."
    if len(named) > 1:
        head += f" Подходящих в сцене {len(named)}, показан первый; другой назовите по имени."
    out = [head]

    def line(p: dict) -> str:
        mean = next((d for pat_, d in _MEANING if re.search(pat_, p["name"])), "")
        if re.search(r"DefectRate$", p["name"]) and isinstance(p["value"], (int, float)) and p["value"] > 0.2:
            mean += ". **Это много** — обычно 0,01–0,05; проверьте, не опечатка ли"
        return (f"• `{p['name']}` = {_value(p['name'], p['value'])}" + (f" — {mean}" if mean else "")
                + f"\n  _где: {_tab(p['name'])}_")

    hits = [p for p in props if p["hit"]] if topics else props
    setting = [p for p in hits if not p["name"].startswith("Statistics::")]
    stats = [p for p in hits if p["name"].startswith("Statistics::")]
    if setting:
        out.append("**Задаётся свойствами:**")
        out += [line(p) for p in setting[:12]]
        if len(setting) > 12:
            out.append(f"…и ещё {len(setting) - 12} — в панели «Свойства компонента».")
    if stats:
        out.append("**Считается в прогоне** (статистика, задавать не нужно): " + "; ".join(
            f"`{p['name']}` = {_value(p['name'], p['value'])}" for p in stats[:6]))
    for s in r.get("scripts") or []:
        out.append(f"**Правило в скрипте «{s['name']}»** (Python Script) — строки, где оно применяется:")
        out += [f"  {n}: `{ln}`" for n, ln in s["lines"]]
        out.append("  _открыть: вкладка «Моделирование» → панель «Диаграмма компонента» → дерево узлов "
                   f"компонента → «{s['name']}», двойной щелчок — редактор скриптов._")
    for pr in r.get("procs") or []:
        out.append(f"**Правило в процессе «{pr['routine']}»** (операторы процедуры):")
        out += ["  " + "  " * d + f"`{txt}`" for d, txt in pr["lines"]]
        out.append("  _открыть: выделите компонент → вкладка «ПРОЦЕСС» → группа «Редактор» → «Операции», "
                   f"процедура «{pr['routine']}»._")
    if topics and not setting and not stats and not r.get("scripts") and not r.get("procs"):
        brief = ", ".join(f"`{p['name']}`" for p in props[:15])
        out.append(f"Свойств, скриптов и операторов процесса про «{тема}» у этого компонента нет. "
                   f"Его свойства: {brief}" + ("…" if len(props) > 15 else "") + ".")
    if setting:
        p = setting[0]
        ex = "0,05" if re.search(r"DefectRate$", p["name"]) else "<значение>"
        out.append(f"_Изменить: в панели «Свойства компонента» или мне: «поставь {p['name']} у "
                   f"«{c['name']}» {ex}». Новое значение действует со следующего прогона._")
    return "\n".join(out)


# --- распознавание фразы -------------------------------------------------------------

_NUM = r"(-?\d+(?:[.,]\d+)?)"
_UNIT = r"(мм/с|м/с|м/мин|мм|см|м|%|с|сек\w*|градус\w*|°)?"
_BUILD = re.compile(r"(лини|цех|завод|участ|этаж|сборочн|станци|змейк|ячейк\w* с|производств)")
_HOW = re.compile(r"^\s*(как|каким образом|можно ли|зачем|для чего|что такое|что значит|почему)\b")


def _strip_obj(text: str) -> str:
    """Убрать из куска фразы служебные слова: остаётся название объекта."""
    t = re.sub(r"\b(у|у него|в сцене|на сцене|компонент\w*|модел\w*|пожалуйста|сейчас|его|её|ее|их)\b", " ", text)
    return re.sub(r"\s+", " ", t).strip(" ?.!,:")


# «Нет, удали…», «А теперь поставь…», «Пожалуйста, очисти…» — вводные слова в
# начале реплики. Из-за «Нет,» 08.10 просьба удалить ушла мимо разбора к модели.
_LEAD = re.compile(r"^(?:(?:нет|да|ну|а|и|так|тогда|лучше|теперь|сейчас|пожалуйста|давай|давайте|ладно|"
                   r"ок|окей|хорошо|слушай|еще|ещё|затем|потом)\b[\s,!.:;—\-]*)+", re.IGNORECASE)

# Где поставить: модель всё равно встаёт в начало координат, а слова места
# в запросе к каталогу только мешают («по центру» нашло «Модуль отслеживания»).
_PLACE = re.compile(r"\s+(?:по центру|в центр\w*|посередин\w*|в середин\w*|в начал\w* координат|в ноль|"
                    r"в сцену|на сцену|сюда|туда)\b.*$")

_CLEAR = re.compile(r"^(?:очисти|очистить|почисти|расчисти|сотри|удали|убери|снеси)\s+"
                    r"(?:всю\s+|все\s+|всё\s+)?(?:сцену|планировку|мир|все|всё)"
                    r"(?:\s+(?:из|со|с|в)\s+сцен\w*|\s+компоненты|\s+объекты|\s+модели)?"
                    r"(?:\s+(?:полностью|целиком|совсем|подчистую))?$")


# «… и соедини их в одну линию», «соедини их», «объедини обе петли»
_JOIN_TAIL = re.compile(r"\s*,?\s+(?:и|а потом|затем|потом)\s+(?:соедини|объедини|свяжи|состыкуй)\w*\b.*$")
_JOIN = re.compile(r"^(?:соедини|объедини|свяжи|состыкуй)\w*\s+(?:их|обе|оба|эти|петли|линии|конвейер\w*|"
                   r"замкнут\w*|.*\b(?:в одну|между собой|друг с другом))")
# «ещё один», «ещё одну», «второй» — и «рядом [с ним / с первым]»
_ANOTHER = re.compile(r"\b(?:ещ[её]\s+(?:один|одну|одно|одного)?|втор(?:ой|ую|ое))\b")
# «рядом со станком» — место у конкретного объекта, это не «рядом с прежним»
_BESIDE = re.compile(r"\s*\bрядом(?:\s+с\s+(?:ним|ней|первым|первой|прежним|предыдущим|этим|этой))?\b"
                     r"(?!\s+(?:с|со|у|возле|около)\b)")


def join_text() -> str:
    import line_join
    return line_join.join(tools.client, prefer_b=list(_last_added))


def handle(text: str) -> tuple[str, str] | None:
    """(навык, ответ) или None — не узнали, пусть решает модель."""
    t = _LEAD.sub("", (text or "").strip())
    low = _norm(t).rstrip(" ?!.")
    if not low or low.startswith("/"):
        return None
    # «где/как у <компонента сцены> задаётся <свойство, правило>» — раньше «как…»:
    # ответ в самой сцене, а не в справке (журнал 13.10, разливочная машина)
    if _WHERE_Q.search(low):
        r = prop_where_text(t)
        if r is not None:
            return "где задаётся", r
    if _HOW.match(low):
        return None

    if _CLEAR.match(low):
        return "очистить", clear_hint_text()

    # симуляция
    if re.search(r"симуляц|моделировани|прогон", low) and not _BUILD.search(low):
        if re.search(r"\b(на|в течение|длительностью)\s+\d", low):
            return None   # «запусти на 3 минуты» — уже есть в intents
        m = re.search(r"скорост\w*.{0,20}?(?:x|х|×)?\s*" + _NUM, low)
        if m:
            return "симуляция", sim_text("speed", float(m.group(1).replace(",", ".")))
        m = re.search(r"(ускорь|замедли)\w*.{0,25}?(?:в\s+)?" + _NUM + r"\s*раз", low)
        if m:
            k = float(m.group(2).replace(",", "."))
            return "симуляция", sim_text("speed", k if m.group(1) == "ускорь" else 1.0 / max(k, 0.01))
        if re.search(r"(сбрось|сбросить|обнули|верни в начало|на начало|в исходное|reset)", low):
            return "симуляция", sim_text("reset")
        if re.search(r"(останови|остановить|стоп|пауз|приостанов|выключи|прекрати|halt)", low):
            return "симуляция", sim_text("halt")
        if re.search(r"(запусти|запустить|включи|пусти|старт|начни|продолжи|поехали|run)", low):
            return "симуляция", sim_text("run")
        if re.search(r"(идет ли|запущена ли|работает ли|состояни|на какой отметк|сколько времени|статус)", low):
            return "симуляция", sim_text("status")
    if re.fullmatch(r"(стоп|пауза|старт|пуск|сброс)", low):
        return "симуляция", sim_text({"стоп": "halt", "пауза": "halt", "старт": "run", "пуск": "run",
                                      "сброс": "reset"}[low])

    # состояние проекта
    if re.search(r"(что|какой|какая|какое)\b.{0,25}\b(открыт|загружен)|"
                 r"какой (проект|файл|планировк)|состояни\w* (программ|r-pro|рпро|проекта|сцены)|"
                 r"^(статус|состояние)$|что с программой", low):
        return "состояние", status_text()

    # снимок и зрение
    if re.search(r"(посмотри|глянь|взгляни)\b.{0,30}(экран|окн|вид|сцен|картин)|что (видно|видишь|на экране|изображено)|"
                 r"сделай (снимок|скриншот)|скриншот|опиши (что видно|экран|картинку|вид)", low):
        return "зрение", look_text(t)

    # ошибки
    if re.search(r"(ошибк|предупрежден|warning|error|панел\w* вывода|что пишет программа|что в выводе)", low) \
            and not re.search(r"(что значит|почему|как исправ|что делать)", low):
        return "ошибки", errors_text()

    # каталог: найти
    m = re.search(r"(?:найди|поищи|покажи|подбери|есть ли|какие есть)\s+(?:в каталоге|в библиотеке)\s+(.+)|"
                  r"(?:в каталоге|в библиотеке)\s+(?:есть\s+|найди\s+|поищи\s+)?(.+)", low)
    if m:
        q = _strip_obj(m.group(1) or m.group(2) or "")
        if q:
            return "каталог", catalog_find_text(q)

    # переименовать
    m = re.search(r"переименуй\s+(.+?)\s+(?:в|на)\s+[«\"']?(.+?)[»\"']?$", t, re.IGNORECASE)
    if m:
        return "переименовать", rename_text(m.group(1), m.group(2))

    # удалить
    m = re.match(r"^(?:удали|убери|удалить|сотри)\s+(?:из сцены\s+)?(.+)$", low)
    if m and not _BUILD.search(low) and not re.search(r"(лишн|всё лишнее|сцену)", low):
        return "удалить", delete_text(_strip_obj(m.group(1)))

    # сдвинуть
    m = re.match(r"^(?:сдвинь|передвинь|перемести|подвинь|отодвинь|смести)\s+(.+?)\s+на\s+" + _NUM +
                 r"\s*(мм|см|м)?\b\s*(?:по\s+(?:оси\s+)?([xyzхуз])|(вправо|влево|вперед|назад|вверх|вниз))?", low)
    if m:
        return "сдвинуть", move_text(_strip_obj(m.group(1)), float(m.group(2).replace(",", ".")),
                                     m.group(3) or "", m.group(4) or "", m.group(5) or "")

    # повернуть
    m = re.match(r"^(?:поверни|разверни|крутани)\s+(.+?)\s+на\s+" + _NUM +
                 r"\s*(?:градус\w*|°)?\s*(?:вокруг\s+(?:оси\s+)?([xyzхуз]))?", low)
    if m:
        return "повернуть", rotate_text(_strip_obj(m.group(1)), float(m.group(2).replace(",", ".")), m.group(3) or "z")

    # изменить свойство: «поставь длину конвейера 3000 мм», «измени ConveyorSpeed у конвейера на 300»
    m = re.match(r"^(?:поставь|установи|задай|измени|поменяй|сделай|выставь)\s+(.+?)\s+(?:на\s+|=\s*|в\s+)?"
                 + _NUM + r"\s*" + _UNIT + r"$", low)
    if m and not _BUILD.search(low):
        body, val, unit = m.group(1), m.group(2), m.group(3) or ""
        # латинское имя свойства — ВерблюжийРегистр или «Группа::Имя», не «ABB IRB 4600»
        raw_prop = re.search(r"\b([A-Z][a-z]+[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)?|[A-Za-z]+::[A-Za-z0-9_]+)\b", t)
        word = None
        for pat, _ in _PROP_WORDS:
            mm_ = re.search(r"\b\w*(" + pat + r")\w*", body)
            if mm_:
                word = mm_.group(0)
                break
        if raw_prop:
            word = raw_prop.group(1)
            body = body.replace(raw_prop.group(1).lower(), " ")
        if word:
            # единица словом и до числа: «метра 4», «на 4 метра»
            if not unit:
                for pat, u in ((r"\bсантиметр", "см"), (r"\bмиллиметр", "мм"), (r"\bметр", "м")):
                    if re.search(pat, body):
                        unit = u
                        break
            obj = re.sub(re.escape(word.lower()), " ", body)
            obj = re.sub(r"\b(метр\w*|сантиметр\w*|миллиметр\w*|мм|см|м|до|около|примерно)\b|[,;]", " ", obj)
            obj = _strip_obj(obj)
            return "свойство", set_prop_text(obj or body, word, val, unit)

    # каталог: добавить — «добавь конвейер», «поставь робота ABB IRB 4600»;
    # «ещё один … рядом [и соедини их]» — рядом с прежним и связкой (журнал 08.10:
    # модель на эту фразу построила свою отдельную линию со станками)
    m = re.match(r"^(?:добавь|поставь|вставь|размести|загрузи|положи|притащи)\s+(?:в сцену\s+|на сцену\s+)?(.+)$", low)
    if m:
        body, join = m.group(1), False
        jm = _JOIN_TAIL.search(body)
        if jm:
            body, join = body[:jm.start()], True
        beside = join or bool(_BESIDE.search(body)) or bool(_ANOTHER.search(body))
        body = _BESIDE.sub(" ", _ANOTHER.sub(" ", body))
        if not _BUILD.search(body) and not re.search(r"\d+\s*(мм|см|м|мм/с)\b|\b(к|рядом|возле|между|на линию|к станку)\b", body):
            added = catalog_add_text(_strip_obj(_PLACE.sub("", body)), beside=beside)
            if join and added.startswith("Добавил"):
                return "соединить", added + "\n\n" + join_text()
            return "каталог", added

    # соединить: «соедини их», «объедини петли в одну линию»
    if _JOIN.match(low) and not _BUILD.search(re.sub(r"в одну линию|линии|линию", " ", low)):
        return "соединить", join_text()

    # состав сцены
    if re.search(r"(какие|что за|список|перечисли|покажи все|сколько)\s+(\w+\s+)?(компонент|модел|объект|оборудован)|"
                 r"состав сцены|что (есть|стоит|лежит|находится) (в|на) сцен|что в сцене|что на сцене", low):
        return "сцена", components_text()

    # поведения / свойства / координаты компонента
    m = re.search(r"поведени\w*\s+(?:у\s+|в\s+)?(.+)$", low) or re.search(r"^(.+?)\s+поведени", low)
    if m and not re.search(r"\bкак\b", low):
        obj = _strip_obj(m.group(1) or "")
        if obj:
            return "поведения", behaviours_text(obj)
    m = re.search(r"(?:свойства|параметры|настройки)\s+(?:у\s+|в\s+)?(.+)$", low) or \
        re.search(r"^(.+?)\s+(?:свойства|параметры)", low)
    # «какие» содержит «как» — только целое слово
    if m and not re.search(r"(\bкак\b|где найти|изменить)", low):
        obj = _strip_obj(m.group(1) or "")
        if obj:
            return "свойства", props_text(obj)
    m = re.search(r"(?:где\s+(?:стоит|стоят|находится|находятся|расположен\w*)|координат\w*|положени\w*|позици\w*)"
                  r"\s+(?:у\s+)?(.+)$", low)
    if m:
        obj = _strip_obj(re.split(r"[?.!]", m.group(1))[0])
        obj = re.sub(r"\b(какие|какой|у него|его)\b.*$", "", obj).strip()
        if obj:
            return "координаты", coords_text(obj)

    # найти и выделить
    m = re.match(r"^(?:найди|выдели|покажи|подсвети|отметь)\s+(?:мне\s+)?(.+?)(?:\s+и\s+(?:выдели|покажи|подсвети)\w*.*)?$", low)
    if m and not re.search(r"(кнопк|меню|вкладк|настройк|в программе|в r-pro|в каталоге|как )", low):
        obj = _strip_obj(m.group(1))
        if obj:
            r = select_text(obj)
            if r:
                return "найти", r
            # в сцене нет — посты линии (intents.where_text) или каталог
            return None
    return None


def run(text: str, on_tool: Callable | None = None) -> str | None:
    hit = handle(text)
    if hit is None:
        return None
    name, answer = hit
    if on_tool is not None:
        on_tool(name, {"текст": text}, answer[:2000])
    return answer
