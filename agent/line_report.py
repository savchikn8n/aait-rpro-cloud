# -*- coding: utf-8 -*-
"""
Отчёт по прогону: сколько выпущено, кто загружен, где узкое место.

Работает с любой сценой, где процессы, люди и роботы ведут статистику: с
линиями механообработки, двухэтажным цехом, сборочной линией. Цифры берутся
из статистики компонентов R-Pro (hands27.line_stats), выводы — здесь.

Узкое место — ресурс или процесс с наибольшей занятостью. Его подтверждают
посты перед ним: они «в блоке» (ждут, когда следующий освободится), а посты
после него простаивают. Совет зависит от того, кто узкое место: человек,
робот или процесс (станок, пост).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from rpro_client import RProClient

_HANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hands27.py")

BUSY_BOTTLENECK = 75.0   # занят больше — кандидат в узкое место
BLOCKED_HIGH = 50.0      # в блоке больше — ждёт следующего
BUSY_LOW = 50.0          # если даже самый загруженный занят меньше — дело не в нём


def _run(client: RProClient, code: str) -> Any:
    with open(_HANDS, encoding="utf-8") as f:
        lib = f.read()
    r = client.exec_python(lib + "\n" + code)
    if r.get("stderr"):
        raise RuntimeError(r["stderr"])
    return r.get("result")


def _patient(fn, *args, tries: int = 6, **kwargs):
    """Вызов моста, который переживает занятость R-Pro. На тяжёлой сцене
    (две линии, ×20) прогон съедает главный поток, и мост минуту не отвечает —
    это не ошибка, а повод подождать и спросить снова."""
    from rpro_client import BridgeError
    for k in range(tries):
        try:
            return fn(*args, **kwargs)
        except BridgeError as exc:
            if "не ответила" not in str(exc) or k == tries - 1:
                raise
            time.sleep(5.0)


def simulate(client: RProClient, run_s: float, speed: float = 20.0, from_start: bool = True,
             timeout_s: float = 1800.0) -> float:
    """Прогнать симуляцию на run_s секунд модельного времени с ускорением speed.
    from_start — сначала сбросить, чтобы статистика была за весь прогон."""
    if from_start:
        _patient(client.simulation, "reset")
        time.sleep(1.0)
    old = _patient(_run, client, "result = app.Simulation.SimSpeed")
    _patient(_run, client, "app.Simulation.SimSpeed = %f\nresult = 1" % max(1.0, float(speed)))
    _patient(client.messages, clear=True)
    t0 = float(_patient(client.simulation, "status").get("time_sec") or 0.0)
    _patient(client.simulation, "run_until", until=t0 + run_s)
    started = time.time()
    while time.time() - started < timeout_s:
        if not _patient(client.simulation, "status", tries=30).get("running"):
            break
        time.sleep(3.0)
    _patient(_run, client, "app.Simulation.SimSpeed = %f\nresult = 1" % float(old or 1.0))
    return float(_patient(client.simulation, "status").get("time_sec") or 0.0)


def _label(r: dict) -> str:
    """Подпись в отчёте: робот (и AGV) — по роботу, человек — по бригаде."""
    if r.get("вид") == "робот":
        return r.get("робот") or r["имя"]
    return r.get("бригада") or r["имя"]


_REJECT = re.compile(r"^(?P<short>.+?) брак после П(?P<n>\d+)$")
_POST = re.compile(r"^(?P<short>\S+) П(?P<n>\d+) ")


def rejects_of(procs: list[dict]) -> dict[str, tuple[int, int]]:
    """Изолятор брака → (сколько списано, сколько проверено на его посту контроля)."""
    out = {}
    for r in procs:
        if "брак" not in r:
            continue
        m = _REJECT.match(r["имя"])
        qc = None
        if m:
            qc = next((q for q in procs if q["имя"].startswith(f"{m['short']} П{m['n']} ")), None)
        out[r["имя"]] = (r["брак"], (qc or {}).get("прошло") or 0)
    return out


def sections(procs: list[dict]) -> dict[str, int]:
    """Участок (префикс постов «МБ», «BMS», «ТБ») → годных с его последнего поста.
    У этажа, который отдаёт узел на лифт, последний пост — контроль: из прошедших
    вычитается его брак."""
    last: dict[str, tuple[int, dict]] = {}
    for r in procs:
        m = _POST.match(r["имя"])
        if m and r.get("прошло") is not None and "брак" not in r:
            n = int(m["n"])
            if m["short"] not in last or n > last[m["short"]][0]:
                last[m["short"]] = (n, r)
    rej = {r["имя"]: r["брак"] for r in procs if "брак" in r}
    return {k: r["прошло"] - rej.get(f"{k} брак после П{n}", 0) for k, (n, r) in last.items()}


def _n(v: float) -> str:
    r = round(float(v), 1)
    return str(int(r)) if r == int(r) else str(r).replace(".", ",")


def summary_text(rep: dict, goals: dict | None = None) -> str:
    """Итог отчёта человеческим текстом — его агент отдаёт как есть.

    Модель 8B пересказывала отчёт «6 батарей в час при цели 12» как «узких мест
    нет, производительность оптимальна». Цифры и вывод теперь пишет код."""
    if rep.get("ошибка"):
        return f"{rep['ошибка']}. {rep.get('что_можно', '')}".strip()
    out = []
    steady = rep.get("после_разгона") or {}
    t = rep.get("модельное_время_мин", 0)
    rate = steady.get("в_час", rep.get("в_час", 0))
    shipped = rep.get("выпущено", 0)
    sink = ", ".join(rep.get("склады_отгрузки", [])) or "отгрузку"
    line = f"За {_n(t)} мин модельного времени на {sink} вышло {shipped} шт."
    if steady:
        line += f" После разгона — {_n(rate)} в час" + (f" (такт {steady['такт_с']} с)." if steady.get("такт_с") else ".")
    else:
        line += f" Это {_n(rep.get('в_час', 0))} в час."
    out.append(line)
    sec = steady.get("участки_в_час") or {}
    if sec:
        out.append("По участкам в час: " + ", ".join(f"{k} — {_n(v)}" for k, v in sec.items()) + ".")
    for title, g in (goals or rep.get("цель_заказчика") or {}).items():
        ok = "выполняется" if g.get("выполняется") else "НЕ выполняется"
        out.append(f"Цель заказчика «{title}»: нужно {_n(g['нужно_в_час'])} в час, есть {_n(g['есть_в_час'])} — "
                   f"{ok} ({'+' if g.get('запас_%', 0) >= 0 else ''}{g.get('запас_%', 0)} %).")
    b = rep.get("узкое_место") or {}
    if b.get("кто") and b["кто"] != "явного нет":
        out.append(f"Узкое место: {b['кто']} (занят {b.get('занят', '?')}). Совет: {b.get('совет', '')}.")
    elif b:
        out.append(f"Явного узкого места нет: {b.get('совет', '')}.")
    rej = rep.get("брак") or {}
    if rej:
        out.append("Брак: " + "; ".join(f"{k} — {v}" for k, v in rej.items()) + ".")
    if rep.get("ошибок_в_выводе"):
        out.append(f"В выводе R-Pro {rep['ошибок_в_выводе']} строк ошибок — стоит посмотреть.")
    return "\n".join(out)


def analyse(stats: dict, errors: int = 0) -> dict:
    t = max(float(stats.get("время_с") or 0.0), 1.0)
    rows = stats.get("строки", [])
    procs = [r for r in rows if r.get("вид") == "процесс"]
    people = [r for r in rows if r.get("вид") == "человек"]
    robots = [r for r in rows if r.get("вид") == "робот"]

    def load(r: dict) -> float:
        if r["вид"] == "процесс":
            return float(r.get("работа") or 0.0)
        return round(100.0 - float(r.get("простой") or 0.0), 1)

    shipped = sum(r.get("выпуск", 0) for r in procs)
    out: dict[str, Any] = {
        "модельное_время_мин": round(t / 60.0, 1),
        "выпущено": shipped,
        "в_час": round(shipped * 3600.0 / t, 1),
        "ошибок_в_выводе": errors,
    }
    sinks = [r for r in procs if "выпуск" in r]
    out["склады_отгрузки"] = [r["имя"] for r in sinks]
    if len(sinks) > 1:
        # несколько линий в сцене — выпуск каждой отдельно, общий такт не считаем
        out["выпуск_по_линиям"] = {r["имя"]: f"{r['выпуск']} шт., {round(r['выпуск'] * 3600.0 / t, 1)} в час"
                                   for r in sinks}
    elif shipped:
        out["такт_с_в_среднем"] = round(t / shipped)

    # бригады людей: средняя занятость по ТК человека
    crews: dict[str, list[float]] = {}
    for h in people:
        crews.setdefault(h.get("бригада") or h["имя"], []).append(load(h))
    out["люди"] = {k: f"{round(sum(v) / len(v))} % ({len(v)} чел.)" for k, v in crews.items()}
    out["роботы"] = {(r.get("робот") or r["имя"]): f"{round(load(r))} %" for r in robots}
    posts = [r for r in procs if r.get("учёт") and r.get("работа") is not None
             and r.get("блок") is not None and "выпуск" not in r]
    out["процессы"] = {r["имя"]: f"работа {round(r['работа'])} %, блок {round(r['блок'])} %, "
                                 f"простой {round(r['простой'])} %" for r in posts}

    # люди — по бригадам (средняя занятость), иначе одна бригада заняла бы
    # весь список «самых загруженных»
    crew_rows = [({"вид": "человек", "бригада": k, "имя": k}, sum(v) / len(v)) for k, v in crews.items()]
    candidates = [(b, r) for r, b in crew_rows] + [(load(r), r) for r in robots + posts]
    candidates.sort(key=lambda x: -x[0])
    blocked = [r["имя"] for r in posts if (r.get("блок") or 0) >= BLOCKED_HIGH]
    # Посты «в блоке» — значит, тормозит кто-то после них, даже если его
    # загрузка ниже порога: тогда узкое место — самый загруженный.
    if candidates and blocked and candidates[0][0] < BUSY_LOW:
        # все заняты мало, а первые посты стоят «в блоке»: изделие дольше
        # едет между постами, чем на них работают
        out["узкое_место"] = {
            "кто": "перемещение изделия между постами", "вид": "транспорт",
            "занят": f"самый загруженный — {round(candidates[0][0])} %",
            "совет": "сблизить посты, ускорить ленту или поставить буфер (накопитель) "
                     "перед медленными постами; добавлять людей и роботов бесполезно",
            "подтверждение": "в блоке: " + ", ".join(blocked[:5])}
    elif candidates and (candidates[0][0] >= BUSY_BOTTLENECK or blocked):
        busy, r = candidates[0]
        who = r["вид"]
        name = _label(r)
        advice = {
            "человек": "добавить оператора (лучше со своей ячейкой и складом, чтобы люди не "
                       "мешали друг другу) или сократить ходки: детали ближе, комплектом",
            "робот": "поставить второго робота на этот участок или поднять скорость робота",
            "процесс": "сократить время операции или поставить такой же пост параллельно",
        }[who]
        out["узкое_место"] = {"кто": name, "вид": who, "занят": f"{round(busy)} %", "совет": advice}
        if blocked:
            out["узкое_место"]["подтверждение"] = (
                "посты перед ним большую часть времени стоят и ждут, пока примут их изделие: "
                + ", ".join(blocked[:5]) + " — значит, линию тормозит именно это место")
    else:
        out["узкое_место"] = {"кто": "явного нет",
                              "совет": "все загружены меньше чем на 75 % — темп задаёт подача; "
                                       "можно подавать чаще"}
    idle_crews = [f"{k}: {len(v)} чел., заняты на {round(sum(v) / len(v))} %"
                  for k, v in crews.items() if len(v) >= 2 and sum(v) / len(v) < 25.0]
    if idle_crews:
        out["недогружены"] = {"бригады": idle_crews,
                              "совет": "здесь людей больше, чем нужно — можно снять часть "
                                       "и перевести на узкое место"}
    # брак: изоляторы после постов контроля; доля — от проверенных на этом посту
    rejects = rejects_of(procs)
    if rejects:
        out["брак"] = {}
        for name, (n, checked) in rejects.items():
            pct = f" ({round(100.0 * n / checked, 1)} % проверенных)" if checked else ""
            out["брак"][name] = f"{n} шт.{pct}"
    sec = sections(procs)
    if len(sec) > 1:
        # несколько участков (этажи завода, связанные участки): выпуск каждого —
        # годные с последнего поста участка
        out["участки"] = {k: f"{n} шт., {round(n * 3600.0 / t, 1)} в час" for k, n in sec.items()}
    kind_word = {"человек": "люди", "робот": "робот", "процесс": "пост"}
    out["самые_загруженные"] = [f"{kind_word[r['вид']]} «{_label(r)}»: "
                                f"{round(b)} %" for b, r in candidates[:5]]
    return out


def report(client: RProClient | None = None, run_s: float = 0.0, speed: float = 20.0) -> dict:
    """run_s > 0 — сначала прогнать столько модельных секунд с нуля; иначе —
    отчёт по уже сделанному прогону."""
    client = client or RProClient()
    steady = None
    if run_s > 0:
        # Разгон: первые минуты линия только заполняется, и средний выпуск за
        # весь прогон занижен. Треть прогона (не больше 30 минут: трём этажам завода
        # нужно до получаса, чтобы заполниться) — разгон,
        # выпуск в установившемся режиме — по разнице счётчиков после него.
        warm = min(run_s / 3.0, 1800.0)
        simulate(client, warm, speed)
        s1 = _patient(_run, client, "result = line_stats()")
        simulate(client, run_s - warm, speed, from_start=False)
        steady = s1
    stats = _patient(_run, client, "result = line_stats()")
    if float(stats.get("время_с") or 0.0) < 1.0:
        return {"ошибка": "симуляция ещё не запускалась — нечего считать",
                "что_можно": "прогнать линию: minutes = 20–30"}
    if float(stats["время_с"]) < 120.0:
        # по нескольким секундам выводы бессмысленны: «выпуск 0, люди на 100 %»
        return {"ошибка": f"прогон слишком короткий ({stats['время_с']:.0f} с модельного времени) — "
                          "выводы делать рано",
                "что_можно": "отчёт с прогоном: minutes = 20–30 (идёт ускоренно, 1–2 минуты)"}
    msgs = client.messages(tail=500)
    out = analyse(stats, int(msgs.get("total_lines") or 0))
    if steady is not None:
        def shipped(s: dict) -> dict:
            return {r["имя"]: r.get("выпуск", 0) for r in s.get("строки", []) if "выпуск" in r}
        a, b = shipped(steady), shipped(stats)
        dt = float(stats["время_с"]) - float(steady["время_с"])
        if dt > 0:
            n = sum(b.values()) - sum(a.values())
            out["после_разгона"] = {"минут": round(dt / 60.0, 1), "выпущено": n,
                                    "в_час": round(n * 3600.0 / dt, 1)}
            if n and len(b) == 1:
                out["после_разгона"]["такт_с"] = round(dt / n)
            if len(b) > 1:
                out["после_разгона"]["по_линиям_в_час"] = {
                    k: round((b[k] - a.get(k, 0)) * 3600.0 / dt, 1) for k in b}
            procs_of = lambda s: [r for r in s.get("строки", []) if r.get("вид") == "процесс"]
            sa, sb = sections(procs_of(steady)), sections(procs_of(stats))
            if len(sb) > 1:
                out["после_разгона"]["участки_в_час"] = {
                    k: round((sb[k] - sa.get(k, 0)) * 3600.0 / dt, 1) for k in sb}
    return out


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    run = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    print(json.dumps(report(run_s=run), ensure_ascii=False, indent=1))
