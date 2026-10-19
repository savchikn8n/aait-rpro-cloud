# -*- coding: utf-8 -*-
"""
Прямой ответ на вопрос «как сделать … в R-Pro» — кодом, без модели.

Раньше /справка отдавала три выдержки из страниц, где чаще всего встречались
слова вопроса. На «как собрать конвейерную линию?» это были операторы
«Транспорт Из», «Транспорт В» и «Создать» — слова совпали, смысл нет.
Пользователь ждёт ответа на свой вопрос, а не справочного шума.

Порядок:
1. **Карточка задачи** (kb/howto.json и проверенные записи kb/faq.json) —
   короткий ответ по шагам, собранный из справки, каталога и опытов на R-Pro.
2. **Страница задачи справки** («Задачи / …», «Начало работы / …») — их
   названия и есть задачи («Сохранение планировки», «Подключить сигналы»).
   Из страницы берутся только шаги инструкции.
3. Не нашлось уверенно — None: тогда отвечает модель (chat.py) по найденным
   фрагментам, но коротко.

Ответ — в разметке, которую рисует панель: **жирный**, нумерованные шаги,
«•» для пунктов, `код`, строка «> …» — совет.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

import glossary
import kb

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb")

# Разделы справки, где лежат инструкции «как сделать».
TASK_PREFIXES = ("Задачи / ", "Начало работы / ", "Пользовательский интерфейс / Панели / ")

# Глаголы вопроса → существительные в названиях задач справки.
# «Как повернуть компонент» ↔ «Перемещение и вращение компонентов».
VERB_NOUN = {
    "поверн": "вращ", "поворач": "вращ", "вращ": "вращ", "крути": "вращ",
    "передв": "перем", "подвин": "перем", "двига": "перем", "перета": "перем", "перене": "перем",
    "измер": "измер", "померя": "измер", "замер": "измер",
    "удали": "удал", "убрат": "удал", "стере": "удал",
    "скопи": "копир", "копир": "копир", "дубли": "клони", "клони": "клони", "размно": "паттер",
    "сохра": "сохра", "откры": "откры", "загру": "откры", "закры": "закры",
    "добав": "добав", "встав": "добав", "постав": "добав",
    "подклю": "подкл", "соеди": "соеди", "связа": "подкл",
    "запус": "запус", "запис": "запис", "сними": "запис", "экспо": "экспо", "выгру": "экспо",
    "импор": "импор", "сгруп": "групп", "объед": "групп",
    "обучи": "обуче", "научи": "обуче", "програ": "програ",
    "покра": "матер", "цвет": "матер", "матер": "матер",
    "выдел": "выбор", "выбра": "выбор", "выбер": "выбор",
    "выров": "вырав", "привя": "привя",
    "верну": "восст", "восст": "восст", "пропа": "восст",
}

_STOP_EXTRA = {kb._stem(w) for w in (
    "сделать", "сделат", "собрать", "создать", "делать", "программе", "r-pro", "rpro", "рпро",
    "мне", "нам", "пожалуйста", "подскажи", "скажи", "объясни", "можно", "нужно",
    # «компонент» не выбрасываем: без него «удалить компонент» = «удалить коллекцию»
    "сцена", "сцену", "сцене", "точно", "быстро", "правильно", "вообще")}


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _with_nouns(toks) -> list[str]:
    """Добавляет к основам глаголов основы существительных из названий задач."""
    out = list(toks)
    for t in toks:
        for verb, noun in VERB_NOUN.items():
            # основы — не длиннее STEM букв, ключи словаря бывают длиннее
            if t.startswith(verb[:kb.STEM]) and noun not in out:
                out.append(noun)
                break
    return out


def _same(a: str, b: str) -> bool:
    """Основы совпадают: «удал» ↔ «удале», «измер» ↔ «измер»."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long_.startswith(short)


def _qtokens(question: str) -> list[str]:
    return _with_nouns([t for t in kb.tokens(question) if t not in _STOP_EXTRA])


# --- 1. карточки --------------------------------------------------------------------

def _load(name: str):
    try:
        with open(os.path.join(KB_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


_cards: list[dict] | None = None


def cards() -> list[dict]:
    global _cards
    if _cards is None:
        data = _load("howto.json") or {}
        _cards = list(data.get("cards", []))
    return _cards


def find_card(question: str) -> dict | None:
    """Первая карточка, шаблон которой совпал с вопросом."""
    low = _norm(question)
    for card in cards():
        if any(re.search(p, low) for p in card.get("patterns", [])):
            return card
    return None


def card_title(card: dict) -> str:
    return card.get("title") or card.get("page", "").split(" / ")[-1]


def render_card(card: dict, question: str = "") -> str:
    if card.get("page"):
        page = task_page(card["page"])
        if page is None:
            return ""
        return render_task(page, question)
    out = [f"**{card['title']}**"]
    if card.get("lead"):
        out.append(card["lead"])
    for i, step in enumerate(card.get("steps", []), 1):
        out.append(f"{i}. {step}")
    for tip in card.get("tips", []):
        out.append(f"> {tip}")
    if card.get("source"):
        out.append(f"_Источник: {card['source']}_")
    return "\n".join(out)


# --- 2. страницы задач справки --------------------------------------------------------

class _TaskIndex:
    def __init__(self) -> None:
        pages: dict[str, dict] = {}
        with open(kb.PATH, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                if c.get("source") != "help" or not c["title"].startswith(TASK_PREFIXES):
                    continue
                p = pages.setdefault(c["title"], {"title": c["title"], "text": ""})
                p["text"] += ("\n" if p["text"] else "") + c["text"]
        self.pages = list(pages.values())
        self.title_toks: list[set[str]] = []
        self.text_tf: list[Counter] = []
        df: Counter = Counter()
        for p in self.pages:
            name = p["title"].split(" / ")[-1]
            tt = set(_with_nouns(kb.tokens(name)))
            self.title_toks.append(tt)
            tf = Counter(kb.tokens(p["text"]))
            self.text_tf.append(tf)
            df.update(set(tf) | tt)
        n = len(self.pages)
        self.idf = {t: math.log(1 + n / d) for t, d in df.items()}

    def search(self, question: str) -> list[tuple[float, float, dict]]:
        """[(оценка, покрытие вопроса названием задачи, страница)], лучшие первыми."""
        q = list(dict.fromkeys(_qtokens(question)))
        extra = [t for t in kb.tokens(" ".join(glossary.expand(question))) if t not in q]
        # вес слова вопроса — его редкость в названиях и текстах задач
        qw = {t: self.idf.get(t, 2.0) for t in q}
        total = sum(qw.values()) or 1.0
        out = []
        for i, p in enumerate(self.pages):
            tt = self.title_toks[i]
            # совпадение с названием задачи — главное; текст страницы лишь уточняет
            title_hits = {t for t in q if any(_same(t, x) for x in tt)}
            cover = sum(qw[t] for t in title_hits) / total
            s = sum(3.0 * qw[t] for t in title_hits)
            tf = self.text_tf[i]
            s += sum(min(tf.get(t, 0), 3) * 0.3 * qw[t] for t in q)
            s += sum(min(tf.get(t, 0), 3) * 0.1 * self.idf.get(t, 1.0) for t in extra)
            # «Задачи» — инструкции; «Начало работы» — обзор той же темы
            if p["title"].startswith("Задачи / "):
                s *= 1.05
            if s > 0:
                out.append((s, cover, p))
        out.sort(key=lambda x: -x[0])
        return out


_tasks: _TaskIndex | None = None


def _index() -> _TaskIndex | None:
    global _tasks
    if _tasks is None:
        try:
            _tasks = _TaskIndex()
        except OSError:
            return None
    return _tasks


def task_page(title: str) -> dict | None:
    idx = _index()
    if idx is None:
        return None
    return next((dict(p, others=[]) for p in idx.pages if p["title"] == title), None)


def find_task(question: str) -> dict | None:
    """Страница задачи справки, если она уверенно отвечает на вопрос."""
    if _index() is None:
        return None
    ranked = _tasks.search(question)
    if not ranked:
        return None
    s, cover, page = ranked[0]
    # Уверенно — когда название задачи покрывает большую часть вопроса (по весу
    # слов). Близкие соседи с тем же покрытием — равноправные страницы той же
    # задачи («Запуск симуляции» в «Начале работы» и в «Задачах»): их называем
    # в конце ответа.
    if cover < 0.7 or s < 6.0:
        return None
    if len(ranked) > 1:
        s2, cover2, _ = ranked[1]
        if cover2 > cover + 0.01 or (s2 > s * 0.97 and cover2 < cover):
            return None
    others = [r[2]["title"] for r in ranked[1:4] if r[1] >= cover * 0.8 and r[0] >= s * 0.6]
    return dict(page, score=round(s, 1), cover=round(cover, 2), others=others[:2])


_STEP = re.compile(r"^\s*(\d+)\s*[.)]\s*(.+)")
_BULLET = re.compile(r"^\s*[·•]\s*(.+)")


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" .", ".").replace(" ,", ",")
    return s


def procedures(text: str) -> list[dict]:
    """
    Инструкции страницы справки: [{"head": заголовок, "steps": [...], "tips": [...]}].

    На одной странице их бывает несколько, и нумерация каждой начинается с 1:
    «Перемещение и вращение» — через поля XYZ и манипулятором, «Измерение» —
    сперва точность отображения, потом само измерение. Заголовок инструкции —
    абзац прямо перед её первым шагом («Манипулятор можно использовать…»,
    «Чтобы добавить соединение…:»). Инструкция из одних пунктов «·» тоже
    бывает — после строки «Чтобы …:».
    """
    lines = [_clean(ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("|")]
    procs: list[dict] = []
    cur: dict | None = None
    prev_para = ""
    for ln in lines:
        m = _STEP.match(ln)
        b = _BULLET.match(ln)
        if m:
            if m.group(1) == "1" or cur is None or cur.get("bullets_only"):
                cur = {"head": prev_para, "steps": [], "tips": []}
                procs.append(cur)
            cur["steps"].append(_clean(m.group(2)))
        elif b:
            if cur is not None and cur["steps"] and not cur.get("closed"):
                cur["steps"].append("• " + _clean(b.group(1)))
            elif prev_para.endswith(":") and prev_para.lower().startswith(("чтобы", "как ")):
                cur = {"head": prev_para, "steps": ["• " + _clean(b.group(1))], "tips": [],
                       "bullets_only": True}
                procs.append(cur)
                prev_para = ""
        else:
            if cur is not None and ln.startswith(("Подсказка", "Примечание")) and not cur.get("closed"):
                cur["tips"].append(ln)
            elif cur is not None:
                cur["closed"] = True
            prev_para = ln
    return procs


def _proc_score(proc: dict, q: set[str]) -> float:
    toks = set(kb.tokens(proc["head"] + " " + " ".join(proc["steps"])))
    return sum(1 for t in q if any(_same(t, x) for x in toks))


def _numbered(steps: list[str]) -> list[str]:
    out, n = [], 0
    for s in steps:
        if s.startswith("• "):
            out.append("   " + s)        # подпункт шага
        else:
            n += 1
            out.append(f"{n}. {s}")
    return out


def _is_heading(head: str) -> bool:
    """«Чтобы добавить соединение…:» — заголовок; «Если выбраны два…» — просто абзац."""
    return head.lower().startswith(("чтобы", "как ")) or head.endswith(":")


def _label(proc: dict) -> str:
    """Чем инструкция отличается: её заголовок или первое содержательное действие."""
    if proc["head"] and _is_heading(proc["head"]):
        return _first_sentences(proc["head"], 1).rstrip(":").split(", выполните")[0]
    # вводная фраза инструкции («Манипулятор можно использовать для…») — лучшая
    # подпись, если это не оговорка («Если выбраны два компонента…»)
    head1 = _first_sentences(proc["head"], 1) if proc["head"] else ""
    if head1 and not head1.startswith(("Если", "Примечание", "Подсказка")) and len(head1) <= 170:
        return head1.rstrip(":. ")
    steps = proc["steps"]
    for k, s in enumerate(steps):
        if s.startswith("• ") or re.match(r"(В трехмерном мире|В 3D-мире|В сцене) выбер", s):
            continue
        # «В панели Свойства Компонента, выполните одно из следующих действий:» —
        # само по себе ни о чём; суть в первом подпункте
        s = re.sub(r",?\s*(выполните|сделайте) (одно|одно или).*$", "", s).rstrip(":. ")
        if len(s) < 45 and k + 1 < len(steps) and steps[k + 1].startswith("• "):
            sub = steps[k + 1][2:].rstrip(".")
            s = f"{s}: {sub[0].lower() + sub[1:]}"
        return s
    return _first_sentences(proc["head"], 1).rstrip(":.")


def render_task(page: dict, question: str = "", limit_steps: int = 10) -> str:
    """Подходящая к вопросу инструкция со страницы справки — шагами, без воды."""
    name = page["title"].split(" / ")[-1]
    text = page["text"]
    procs = [p for p in procedures(text) if p["steps"]]
    paras = [_clean(ln) for ln in text.splitlines()
             if _clean(ln) and not _STEP.match(ln) and not _BULLET.match(ln) and not ln.strip().startswith("|")]
    lead = _first_sentences(paras[0], 1) if paras else ""
    out = [f"**{name}**"]
    if lead:
        out.append(lead)
    if procs:
        q = set(_qtokens(question))
        best = max(procs, key=lambda p: (_proc_score(p, q), -procs.index(p))) if q else procs[0]
        if best["head"] and _is_heading(best["head"]):
            out.append(f"_{_label(best)}:_")
        out += _numbered(best["steps"][:limit_steps])
        for tip in best["tips"][:1]:
            out.append("> " + re.sub(r"\.{2,}$", ".", tip.split(":", 1)[-1].strip()))
        labels: list[str] = []
        for p in procs:
            lab = _label(p)
            if p is not best and lab and lab != _label(best) and lab not in labels:
                labels.append(lab)
        if labels:
            out.append("Ещё на этой странице: " + "; ".join(labels[:2]) + ".")
    else:
        # инструкции нет — суть в двух-трёх фразах
        out[-1:] = [_first_sentences(" ".join(paras[:3]), 3)] if paras else out[-1:]
    out.append(f"_Источник: справка R-Pro, «{name}»_")
    others = [t.split(" / ")[-1] for t in page.get("others", [])]
    if others:
        out.append("Ещё по теме: " + "; ".join(f"/справка {o}" for o in others))
    return "\n".join(out)


def _first_sentences(text: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())[:n]
    # описание каталога обрезано по длине — недописанную фразу не показываем
    if len(parts) > 1 and not parts[-1].rstrip().endswith((".", "!", "?", ":")):
        parts = parts[:-1]
    return " ".join(parts)


# --- общий вход ----------------------------------------------------------------------

def direct(question: str) -> str | None:
    """Ответ без модели: карточка или уверенно найденная страница задачи."""
    card = find_card(question)
    if card is not None:
        text = render_card(card, question)
        if text:
            return text
    page = find_task(question)
    if page is not None:
        return render_task(page, question)
    return None


def candidates(question: str, limit: int = 14) -> list[dict]:
    """
    Разделы, из которых модель выберет ответ: карточки и страницы задач,
    близкие к вопросу по словам. Список короткий — модели 8B так проще не
    промахнуться, а запрос короче.
    """
    out: list[dict] = []
    seen: set[str] = set()
    q = set(_qtokens(question))
    for card in cards():
        if card.get("title"):   # карточки с шагами — всегда в списке, их мало
            out.append({"kind": "card", "card": card, "name": card["title"]})
            seen.add(card["title"])
    idx = _index()
    if idx is not None:
        for s, cover, p in idx.search(question)[:limit * 2]:
            name = p["title"].split(" / ")[-1]
            if p["title"] in seen or name in seen:
                continue
            seen.update((p["title"], name))
            # раздел — чтобы «Удаление Коллекции» не путалось с удалением компонента
            where = p["title"].split(" / ")[-2] if " / " in p["title"] else ""
            out.append({"kind": "page", "page": dict(p, others=[]),
                        "name": f"{name} ({where})" if where else name})
            if len(out) >= limit + len([c for c in out if c["kind"] == "card"]):
                break
    return out


_PICK_SYSTEM = (
    "Ты подбираешь раздел справки программы R-Pro под вопрос пользователя. "
    "Тебе дан пронумерованный список разделов. Ответь ОДНИМ числом — номером раздела, "
    "который прямо отвечает на вопрос. Если ни один не отвечает — ответь 0. "
    "Не пиши ничего, кроме числа.")


def pick_with_model(question: str, timeout: float = 60.0) -> dict | None:
    """
    Модель выбирает номер раздела; сам ответ берётся из раздела дословно.

    Модель здесь только понимает вопрос — она не пишет текст ответа и не может
    ничего присочинить: худшее, что она сделает, — выберет не тот раздел.
    """
    import llm
    cands = candidates(question)
    if not cands:
        return None
    listing = "\n".join(f"{i}. {c['name']}" for i, c in enumerate(cands, 1))
    messages = [{"role": "system", "content": _PICK_SYSTEM},
                {"role": "user", "content": f"Вопрос: {question.strip()}\n\nРазделы:\n{listing}\n\nНомер:"}]
    try:
        reply = llm.chat(messages, timeout=timeout).get("content", "")
    except Exception:
        return None
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    m = re.search(r"\d+", reply)
    if not m:
        return None
    n = int(m.group(0))
    if not 1 <= n <= len(cands):
        return None
    return cands[n - 1]


_DEFINE = re.compile(
    r"^\s*(что такое|что значит|что означает|что делает|что за|зачем нужн\w*|для чего нужн\w*|"
    r"для чего|объясни,? что такое|расскажи,? что такое)\s+(.+?)\s*\??\s*$")


def _catalog_def(term: str) -> tuple[str, str] | None:
    """(имя модели, первые фразы описания) из каталога R-Pro."""
    try:
        import catalog
        items = catalog.загрузить()
    except Exception:
        return None
    def bare(s: str) -> str:
        return re.sub(r"[\"«»']", "", _norm(s)).strip()
    t = bare(term)
    exact = [i for i in items if bare(i["имя"]) == t]
    near = exact or [i for i in items if t and t in bare(i["имя"]) and len(i["имя"]) <= len(t) + 12]
    for i in near:
        desc = (i.get("описание") or "").split("###")[0].strip()
        if desc:
            return i["имя"], _first_sentences(re.sub(r"\s+", " ", desc), 2)
    return None


def _help_def(term: str) -> tuple[str, str] | None:
    """(раздел, первые фразы) — страница справки, название которой и есть термин."""
    want = [t for t in kb.tokens(term)]
    if not want:
        return None
    best = None
    with open(kb.PATH, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c.get("source") != "help" or c.get("part", "") not in ("", "1/2", "1/3", "1/4", "1/5", "1/6"):
                continue
            name = c["title"].split(" / ")[-1]
            nt = kb.tokens(name)
            if nt and all(any(_same(w, x) for x in nt) for w in want) and len(nt) <= len(want) + 1:
                if best is None or len(nt) < len(kb.tokens(best["title"].split(" / ")[-1])):
                    best = c
    if best is None:
        return None
    paras = [_clean(p) for p in best["text"].splitlines() if _clean(p) and not p.strip().startswith("|")]
    # первая строка часто повторяет заголовок — берём первый абзац-фразу
    body = next((p for p in paras if len(p) > 40), paras[0] if paras else "")
    return best["title"].split(" / ")[-1], _first_sentences(body, 2)


def define(question: str) -> str | None:
    """«Что такое ТК робота?» — определение из каталога или справки, две фразы."""
    m = _DEFINE.match(_norm(question))
    if not m:
        return None
    term = m.group(2)
    found = _catalog_def(term)
    where = "каталог R-Pro"
    if found is None:
        found = _help_def(term)
        where = "справка R-Pro"
    if found is None:
        return None
    name, text = found
    if _norm(text).startswith(_norm(name)):
        # «Генератор деталей позволяет…» — имя уже в начале фразы
        out = [f"**{name}**{text[len(name):]}"]
    else:
        out = [f"**{name}** — {text[0].lower() + text[1:] if text[:1].isupper() and not text[:2].isupper() else text}"]
    if where == "каталог R-Pro":
        out.append(f"_Источник: описание модели в каталоге R-Pro (найти: поиск «{name}» в каталоге)_")
    else:
        out.append(f"_Источник: справка R-Pro. Целиком: /справка {name}_")
    return "\n".join(out)


_BRIEF_SYSTEM = (
    "Ты — помощник по программе R-Pro (основана на Visual Components 4). Ответь на вопрос "
    "пользователя по фрагментам справки ниже.\n"
    "Правила:\n"
    "1. Первая строка — прямой ответ одной фразой.\n"
    "2. Дальше, если нужно, нумерованные шаги — не больше 6, коротко, с точными названиями "
    "вкладок и кнопок из фрагментов, выделяй их **жирным**.\n"
    "3. Только то, что есть во фрагментах. Ничего не додумывай. Без вступлений, выводов, "
    "пересказа фрагментов и советов «обратитесь к справке».\n"
    "4. Если во фрагментах нет ответа на этот вопрос — ответь ровно: НЕТ ОТВЕТА")


def brief(question: str, timeout: float = 90.0) -> str | None:
    """
    Короткий ответ модели строго по найденным фрагментам — когда нет ни карточки,
    ни страницы задачи. Без инструментов и истории разговора: модели 8B так
    проще держаться вопроса. «НЕТ ОТВЕТА» — честный отказ вместо выдумки.
    """
    import config
    import llm
    try:
        hits = [h for h in kb.search(question, 5) if h["score"] >= config.KB_PREFETCH_MIN_SCORE][:3]
    except OSError:
        return None
    if not hits:
        return None
    parts = [f"### {h['title'].split(' / ')[-1]}\n{h['text'][:1400]}" for h in hits]
    messages = [{"role": "system", "content": _BRIEF_SYSTEM},
                {"role": "user", "content": f"Вопрос: {question.strip()}\n\nФрагменты:\n\n" + "\n\n".join(parts)}]
    try:
        reply = llm.chat(messages, timeout=timeout).get("content", "")
    except Exception:
        return None
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip()
    if not reply or "НЕТ ОТВЕТА" in reply.upper():
        return None
    lines = [ln.rstrip() for ln in reply.splitlines() if ln.strip()]
    if len(lines) > 9:
        lines = lines[:9]
    names = "; ".join(f"«{h['title'].split(' / ')[-1]}»" for h in hits[:2])
    lines.append(f"_Кратко по справке ({names}); готового проверенного ответа пока нет — названия кнопок сверяйте._")
    return "\n".join(lines)


def not_found(question: str) -> str:
    """Честное «не знаю» в две строки и куда двигаться дальше — вместо выдумки."""
    near: list[str] = []
    idx = _index()
    if idx is not None:
        for s, cover, p in idx.search(question)[:3]:
            if cover > 0:
                near.append(p["title"].split(" / ")[-1])
    out = ["В справке R-Pro нет готовой инструкции на этот вопрос — выдумывать не буду."]
    if near:
        out.append("Ближе всего: " + "; ".join(f"/справка {n}" for n in near) + ".")
    out.append("Сформулируйте иначе или опишите, что нужно получить в сцене, — попробую сделать сам.")
    return "\n".join(out)


def answer(question: str, use_model: bool = True) -> tuple[str | None, str]:
    """
    Ответ на вопрос «как сделать…» / «что такое…»: (текст, откуда) или (None, причина).

    откуда: «проверено», «карточка», «определение», «справка», «выбор модели».
    """
    import quickref
    # Проверенное на R-Pro (kb/faq.json) — первым: оно точнее справки.
    known = quickref.faq_item(question)
    if known is not None:
        return f"**{known['title']}**\n{known['answer']}", "проверено"
    # Тема практического урока курса ИИТБ (сборка, склад, двери, паллетирование…): конспект урока и проверенный
    # на R-Pro рецепт точнее общей карточки справки («как настроить ожидание сигнала» — не «как подключить сигналы»)
    try:
        from iitb import course
        rec = course.recipe(question.lower().replace("ё", "е"))
        if rec is not None and rec[0] in (10, 11, 12, 13, 14, 15, 16):
            return (course.explain_text(rec[0]).rsplit("\n\n", 1)[0] +
                    "\n\n**Проверено в R-Pro 2.2.2**\n" + rec[1]), "курс"
    except Exception:  # noqa: BLE001 — курс не должен ломать ответы справки
        pass
    if _DEFINE.match(_norm(question)):
        text = define(question)
        if text:
            return text, "определение"
    card = find_card(question)
    if card is not None:
        text = render_card(card, question)
        if text:
            return text, "карточка"
    page = find_task(question)
    if page is not None:
        return render_task(page, question), "справка"
    if not use_model:
        return None, "нет уверенного раздела"
    text = brief(question)
    if text:
        return text, "кратко моделью"
    return None, "в справке нет ответа"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "как собрать конвейерную линию?"
    print(direct(q) or "(нет уверенного ответа — к модели)")
