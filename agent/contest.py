# -*- coding: utf-8 -*-
"""Конкурс TechSkills 2026, «Цифровое производство»: модули A, B, C заранее в агенте.

Задание разобрано по модулям в agent/contest/*.md (требования, числа, критерии приёмки, ловушки).
Здесь — как это попадает к модели и пользователю, не раздувая контекст:

- note(messages) — по теме вопроса (манометр, OP50, Dobot, Yamazumi…) выбирает модуль и кладёт рядом
  с вопросом только нужные разделы: критерии приёмки всегда, плюс разделы, ближе всего к вопросу;
- brief / criteria / pallet / plan — команды /задание, /критерии, /раскладка, /расчёт без модели;
- kb_chunks() — те же разделы для базы знаний (kb/contest_chunks.jsonl, источник «contest»).
Модуль D (измерения) сознательно отсутствует: он ведётся отдельно.
"""

from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contest")
MODULES = {"A": "module_a.md", "B": "module_b.md", "C": "module_c.md"}
TITLES = {"A": "Модуль A — участок сборки манометра МП-63", "B": "Модуль B — ячейка переворота детали (Dobot CR10)",
          "C": "Модуль C — Lean Six Sigma и защита"}

_L = "AaАа"        # латинская и русская «A» (в задании и в речи встречаются обе)
_B = "BbВв"
_C = "CcСс"

TOPIC = {
    "A": re.compile(
        r"манометр|мп-?63|mp-?63|\bop ?(1[0-3]0|[2-9]0|100)\b|стеллаж|штабел|паллет|шильдик|этикетиров|"
        r"контейнер|коробк|\bz[1-7]\b|rp-?1000|тележк|испытан|отбраковк|накопител[ья] брак|"
        rf"модул[ьяеию]\s*[{_L}](?![а-яa-z])", re.I),
    "B": re.compile(
        r"dobot|cr10|cc16|переворот|перевернут|base5|tool4|постпроцессор|post ?process|\.lua|рктмп|рктп|"
        r"датчик присутствия|технологическ\w+ опор|реверсивн|"
        rf"модул[ьяеию]\s*[{_B}](?![а-яa-z])", re.I),
    "C": re.compile(
        r"lean|six ?sigma|sipoc|vsm|yamazumi|ямазуми|spaghetti|спагетти|\bppm\b|ishikawa|исикав|\boee\b|swimlane|"
        r"smed|\b5s\b|pfmea|контрольн\w+ карт|узк\w+ мест|презентаци|защит\w+|аналитическ\w+ записк|"
        rf"модул[ьяеию]\s*[{_C}](?![а-яa-z])", re.I),
}
GENERAL = re.compile(r"конкурс|чемпионат|techskills|техскиллс|конкурсн\w+ задани|баллы|критери\w+ приемк|"
                     r"критери\w+ приёмк|тестов\w+ задани", re.I)
# Вопрос про исключённую часть конкурса — честный отказ вместо догадок
OTHER = re.compile(r"polyworks|areatek|alpha ?arm|pmt-?kit|измерительн\w+ рук|модул[ьяеию]\s*[DdДд](?![а-яa-z])", re.I)

OTHER_ANSWER = ("Этот модуль конкурса делается отдельно, в агента он не заложен — я не стану подсказывать "
                "по нему наугад. Модули A, B, C — /задание A, /задание B, /задание C.")


@lru_cache(None)
def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


@lru_cache(None)
def sections(module: str) -> list[tuple[str, str]]:
    """[(заголовок раздела, текст раздела)] модуля A/B/C или общих сведений (ключ 'G')."""
    text = _read("general.md" if module == "G" else MODULES[module])
    parts = re.split(r"^## ", text, flags=re.M)
    out = [("Кратко", parts[0].strip())]
    for p in parts[1:]:
        head, _, body = p.partition("\n")
        out.append((head.strip(), body.strip()))
    return out


def modules_in(text: str) -> list[str]:
    return [m for m in "ABC" if TOPIC[m].search(text or "")]


def _norm(s: str) -> str:
    return (s or "").lower().replace("ё", "е")


def detect(messages: list[dict]) -> tuple[list[str], bool, bool]:
    """(модули, общий вопрос о конкурсе, вопрос про исключённый модуль).
    Смотрим последние три реплики пользователя: «а какой там такт?» тоже относится к теме."""
    users = [m.get("content") or "" for m in messages if m.get("role") == "user"][-3:]
    if not users:
        return [], False, False
    last = users[-1]
    other = bool(OTHER.search(last))
    mods = modules_in(_norm(last))
    if not mods:                      # уточнение без ключевых слов — берём тему предыдущих реплик
        for earlier in reversed(users[:-1]):
            mods = modules_in(_norm(earlier))
            if mods:
                break
    return mods, bool(GENERAL.search(_norm(last))), other


def _score(question: str, text: str) -> int:
    import kb
    q = set(kb.tokens(question))
    return sum(1 for t in kb.tokens(text) if t in q)


def pick_sections(module: str, question: str, budget: int) -> list[tuple[str, str]]:
    """Критерии приёмки всегда + разделы, ближайшие к вопросу, пока помещаются в budget."""
    secs = sections(module)
    chosen = [s for s in secs if s[0].startswith("Критерии приёмки")]
    used = sum(len(s[1]) for s in chosen)
    rest = sorted((s for s in secs if s not in chosen), key=lambda s: -_score(question, s[0] + " " + s[1]))
    for s in rest:
        if used + len(s[1]) > budget:
            continue
        if _score(question, s[0] + " " + s[1]) == 0 and chosen:
            break
        chosen.append(s)
        used += len(s[1])
    # короткие разделы (параметры, карта сигналов, раскладка) дёшевы — добираем их, пока есть место
    for s in sorted((s for s in secs if s not in chosen and 0 < len(s[1]) < 1500), key=lambda s: len(s[1])):
        if used + len(s[1]) <= budget:
            chosen.append(s)
            used += len(s[1])
    order = {s[0]: i for i, s in enumerate(secs)}
    return sorted(chosen, key=lambda s: order[s[0]])


def note(messages: list[dict], budget: int = 9000) -> str | None:
    """Системная подсказка к вопросу по конкурсу или None."""
    mods, general, other = detect(messages)
    if other and not mods:
        return "Вопрос относится к части конкурса, которую агент не ведёт. " + OTHER_ANSWER
    if not mods and not general:
        return None
    question = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
    parts = []
    if general or len(mods) > 1 or not mods:
        parts.append("### Конкурс: общие сведения\n" + sections("G")[0][1] + "\n" + "\n".join(
            b for h, b in sections("G")[1:] if not h.startswith("Кратко")))
    per = max(2500, budget // max(len(mods), 1))
    for m in mods:
        body = "\n\n".join(f"#### {h}\n{b}" for h, b in pick_sections(m, question, per))
        parts.append(f"### {TITLES[m]}\n{body}")
    return ("Конкурсное задание TechSkills 2026 (разобрано заранее, это точные требования и числа — опирайся "
            "на них, не пересказывай по памяти и не выдумывай номера команды, координаты и значения, которых здесь нет; "
            "если в вопросе нужного нет — скажи, чего не хватает). Команды без модели: /задание, /критерии, "
            "/раскладка, /расчёт. Строители прошлого теста (rpro_pharma_plant, rpro_robot_cell, rpro_lean_optimize, "
            "rpro_techskills_field) к этим модулям не применяй.\n\n" + "\n\n".join(parts))


# --- команды без модели -------------------------------------------------------------------

def _module_arg(arg: str) -> str | None:
    a = _norm(arg).strip()
    for key, letters in (("A", "aа"), ("B", "bв"), ("C", "cс")):
        if re.fullmatch(rf"(модул[ьяе]\s*)?[{letters}]", a):
            return key
    return None


def overview() -> str:
    return ("Конкурс TechSkills 2026, «Цифровое производство», изделие — манометр МП-63.\n"
            "• Модуль A — участок сборки: склад с краном-штабелёром, 7 частей, испытание, шильдик, упаковка, паллеты. "
            "8 ч, 55 баллов, ≥ 520 годных за 480 мин (/задание A)\n"
            "• Модуль B — ячейка переворота детали, робот Dobot CR10, постпроцессор в .lua. 6 ч, 20 баллов (/задание B)\n"
            "• Модуль C — Lean Six Sigma по модели A и защита. 6 ч, 16 баллов (/задание C)\n"
            "Чек-лист приёмки — /критерии A|B|C; паллет — /раскладка; арифметика плана — /расчёт.")


def brief(arg: str = "") -> str:
    m = _module_arg(arg)
    if OTHER.search(arg or ""):
        return OTHER_ANSWER
    if m is None:
        return overview()
    secs = [s for s in sections(m) if not s[0].startswith(("Критерии", "Типичные"))]
    return f"{TITLES[m]}\n\n" + "\n\n".join(f"{h}\n{b}" if h != "Кратко" else b for h, b in secs) + \
        f"\n\nЧек-лист: /критерии {m}"


def criteria(arg: str = "") -> str:
    m = _module_arg(arg)
    if OTHER.search(arg or ""):
        return OTHER_ANSWER
    if m is None:
        return "Чьи критерии? /критерии A, /критерии B или /критерии C."
    crit = next(b for h, b in sections(m) if h.startswith("Критерии приёмки"))
    traps = next((b for h, b in sections(m) if h.startswith("Типичные")), "")
    return f"{TITLES[m]} — критерии приёмки\n\n{crit}\n\nЧастые ошибки\n{traps}"


def pallet_best(length: int = 1200, width: int = 800, a: int = 100, b: int = 90) -> dict:
    """Максимум коробок a×b на паллете length×width в один слой: простые сетки и гильотинный перебор."""
    simple = {}
    for (x, y, tag) in ((a, b, f"{a} вдоль {length}, {b} поперёк"), (b, a, f"{b} вдоль {length}, {a} поперёк")):
        nx, ny = length // x, width // y
        simple[tag] = (nx, ny, nx * ny)
    best_tag = max(simple, key=lambda k: simple[k][2])
    g = math.gcd(math.gcd(length, width), math.gcd(a, b)) or 1

    @lru_cache(None)
    def f(l: int, w: int) -> int:
        r = 0
        for x, y in ((a // g, b // g), (b // g, a // g)):
            if x <= l and y <= w:
                r = 1
        for i in range(1, l // 2 + 1):
            r = max(r, f(i, w) + f(l - i, w))
        for j in range(1, w // 2 + 1):
            r = max(r, f(l, j) + f(l, w - j))
        return r

    guillotine = f(length // g, width // g) if length // g * (width // g) <= 40000 else None
    n = simple[best_tag][2]
    return {"simple": simple, "best_simple": (best_tag, simple[best_tag]), "guillotine": guillotine,
            "area_bound": (length * width) // (a * b), "fill": n * a * b / (length * width)}


def pallet(arg: str = "") -> str:
    nums = [int(x) for x in re.findall(r"\d+", arg or "")]
    L, W, a, b = (nums + [1200, 800, 100, 90][len(nums):])[:4] if len(nums) in (0, 4) else (1200, 800, 100, 90)
    r = pallet_best(L, W, a, b)
    tag, (nx, ny, n) = r["best_simple"]
    lines = [f"Раскладка коробок {a}×{b} мм на паллете {L}×{W} мм, один слой (расчёт кодом):"]
    for k, (x, y, c) in r["simple"].items():
        lines.append(f"• сетка: {k}: {x} × {y} = {c} коробок")
    lines.append(f"• лучшая простая: {tag} — {nx} × {ny} = {n} коробок, заполнение {r['fill']*100:.1f} % площади")
    if r["guillotine"] is not None:
        lines.append(f"• перебор гильотинных раскладок (с поворотом коробок): {r['guillotine']}")
    lines.append(f"• верхний предел по площади: {r['area_bound']}")
    lines.append("Негильотинные схемы кодом не перебирались: если нужно больше, подтвердите геометрией и статистикой R-Pro. "
                 "Для отчёта: раскладка, число коробок в слое и заполнение — в комментарии к модели или в файле "
                 "«МодульA_№Команды_Раскладка».")
    return "\n".join(lines)


def plan(arg: str = "") -> str:
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", arg or "")]
    good, minutes, scrap, takt = (nums + [520, 480, 3, 40][len(nums):])[:4]
    t = minutes * 60
    starts = math.ceil(good / (1 - scrap / 100))
    cap = int(t // takt)
    return (f"План выпуска: {good:g} годных за {minutes:g} мин при браке {scrap:g} % (такт {takt:g} с).\n"
            f"• запустить в сборку не менее {starts} изделий ({good:g} ÷ {1 - scrap/100:.2f})\n"
            f"• время на изделие: {t/starts:.1f} с (с учётом брака); без запаса на брак — {t/good:.1f} с\n"
            f"• по такту {takt:g} с теоретически {cap} изделий за смену (≈ {int(cap*(1-scrap/100))} годных), запас {cap/starts*100-100:.0f} % "
            f"на простои и запуск\n"
            f"• контейнеров по 50 шт. на каждое из 7 наименований: {math.ceil(starts/50)}\n"
            f"• паллетов по 104 коробки: {good/104:.1f} → {math.ceil(good/104)}")


def handle(cmd: str, arg: str) -> str | None:
    """Команды intents.handle: /задание, /критерии, /раскладка, /расчёт."""
    if cmd.startswith("задан") or cmd in ("конкурс", "contest"):
        return brief(arg)
    if cmd.startswith("критер") or cmd in ("чеклист", "чек-лист"):
        return criteria(arg)
    if cmd.startswith("раскладк") or cmd.startswith("паллет"):
        return pallet(arg)
    if cmd.startswith("расчет") or cmd.startswith("расчёт") or cmd == "план":
        return plan(arg)
    return None


# --- база знаний -------------------------------------------------------------------------

def kb_chunks() -> list[dict]:
    out = []
    for m in ("G", "A", "B", "C"):
        title = "Конкурс TechSkills 2026 / " + ("Общие сведения" if m == "G" else TITLES[m])
        for h, body in sections(m):
            if not body:
                continue
            out.append({"source": "contest", "title": f"{title} / {h}", "part": "1/1",
                        "text": f"{title}\n## {h}\n{body}"})
    return out


if __name__ == "__main__":
    import sys
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb", "contest_chunks.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for c in kb_chunks():
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"записано {len(kb_chunks())} фрагментов → {path}")
