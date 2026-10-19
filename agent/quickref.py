# -*- coding: utf-8 -*-
"""
Быстрые справочные команды — кодом, без модели и без R-Pro.

Модель 8B отвечает на «как сделать…» по 50–100 секунд и нередко сочиняет:
кнопки, которых нет, код на Python 3, «ловушки», которых не было. Эти команды
отвечают за доли секунды тем, что лежит в базе знаний, и ничего не придумывают:

  /справка <вопрос>   — выдержки из справки R-Pro, справки по API и уроков Academy;
  /api <имя>          — класс или метод Python API: что это, свойства, методы;
  /термин <слово>     — английское название из уроков ↔ русская кнопка в R-Pro;
  /совет <тема>       — советы из уроков Academy (docs/12-lajfhaki-rpro.md);
  /проблема <что>     — проверенные ответы на частые неполадки (kb/faq.json).

Частые неполадки, описанные обычными словами («после сброса всё улетело в
ноль», «не найдена лицензия»), тоже отвечаются из faq.json — если вопрос
совпал с одним из шаблонов записи (faq_answer).

Данные: kb/chunks.jsonl и kb/academy_chunks.jsonl (kb.py), kb/api_index.json
(kb_build.py), kb/ui_terms.json и kb/tips.jsonl (quickref_build.py),
kb/faq.json (руками).
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

_SOURCE = {
    "help": "Справка R-Pro",
    "pyhelp": "Справка Python",
    "api": "Python API",
    "ui": "Лента",
    "commands": "Встроенные команды",
    "shortcuts": "Горячие клавиши",
    "academy": "Урок Academy (Visual Components — кнопки сверяйте с R-Pro)",
    "iitb": "Курс ИИТБ Skill Camp (родной курс по R-Pro)",
}

_cache: dict[str, object] = {}


def _load_json(name: str):
    if name not in _cache:
        path = os.path.join(KB_DIR, name)
        try:
            if name.endswith(".jsonl"):
                with open(path, encoding="utf-8") as f:
                    _cache[name] = [json.loads(line) for line in f if line.strip()]
            else:
                with open(path, encoding="utf-8") as f:
                    _cache[name] = json.load(f)
        except OSError:
            _cache[name] = None
    return _cache[name]


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _query_weights(query: str) -> dict[str, float]:
    """Основы слов запроса; термины из словаря бытовых слов — с меньшим весом."""
    w = {t: 0.6 for t in kb.tokens(" ".join(glossary.expand(query)))}
    w.update({t: 1.0 for t in kb.tokens(query)})
    return w


def _best_lines(text: str, weights: dict[str, float], limit: int = 420) -> str:
    """Самые подходящие к запросу строки фрагмента — в исходном порядке."""
    lines = [ln.strip() for ln in re.split(r"\n+|(?<=[.!?])\s+(?=[А-ЯA-Z0-9«])", text) if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith(("Урок:", "Ключевые слова", "## ")) and len(ln) > 3]
    if not lines:
        return ""
    scored = []
    for i, ln in enumerate(lines):
        toks = set(kb.tokens(ln))
        s = sum(w for t, w in weights.items() if t in toks)
        if s > 0:
            scored.append((s, i))
    if not scored:
        picked = [0, 1][:len(lines)]
    else:
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = sorted(i for _, i in scored[:3])
    out = ""
    for i in picked:
        piece = lines[i]
        # шаг инструкции без предыдущего шага понятнее, если взять и его
        if i > 0 and re.match(r"^\d+[.)]", piece) and i - 1 not in picked and len(out) < limit / 3:
            piece = lines[i - 1] + " " + piece
        if len(out) + len(piece) > limit:
            if not out:
                out = piece[:limit].rsplit(" ", 1)[0] + "…"
            break
        out = (out + " … " if out else "") + piece
    return out


# --- /справка ------------------------------------------------------------------------

def help_text(query: str) -> str:
    q = query.strip()
    if not q:
        return ("Напишите вопрос после команды, например: /справка как подключить сигналы робота.\n"
                "Целый раздел: /справка <название раздела> — его название видно в выдаче.")
    sources = None
    if q.lower().startswith(("курс ", "иитб ")):
        q = q.split(" ", 1)[1]
        sources = ["iitb"]
    elif q.lower().startswith(("уроки ", "урок ")):
        q = q.split(" ", 1)[1]
        sources = ["academy"]
    try:
        hits = kb.search(q, 5, sources)
    except OSError:
        return "База знаний не найдена (agent/kb/chunks.jsonl) — справка недоступна."
    if not hits:
        return f"В справке ничего не нашлось по «{q}». Попробуйте другими словами или /термин <слово>."
    # Запрос — название раздела: показать раздел целиком.
    if hits[0]["score"] >= 1000:
        h = hits[0]
        text = h["text"].strip()
        if len(text) > 1800:
            text = text[:1800].rsplit("\n", 1)[0] + "\n…"
        return f"📖 {h['title']} {h.get('part') or ''}\n[{_SOURCE.get(h['source'], h['source'])}]\n\n{text}"
    weights = _query_weights(q)
    top = hits[0]["score"]
    out = []
    # Проверенный нами ответ (kb/faq.json) важнее выдержек: справка и уроки
    # писались для Visual Components, а он — по опытам на R-Pro 2.2.2.
    known = faq_answer(q) if not sources else None
    if known:
        out.append("✔ " + known + "\n\nЕщё в справке:")
    else:
        out.append(f"Справка по «{q}» (без модели, выдержки):")
    shown = 0
    seen: set[str] = set()
    for h in hits:
        # слабые совпадения — шум: оставляем то, что не хуже трети лучшего
        if shown >= 3 or h["score"] < top / 3:
            break
        piece = _best_lines(h["text"], weights)
        # одна и та же страница справки лежит в нескольких разделах, а урок
        # разрезан на части — по одной выдержке на страницу
        if not piece or piece in seen or h["title"] in seen:
            continue
        seen.update((piece, h["title"]))
        shown += 1
        out.append(f"\n{shown}. {h['title']} — {_SOURCE.get(h['source'], h['source'])}\n   {piece}")
    # Лучший совет из уроков — только если в нём все слова запроса.
    own = set(kb.tokens(q))
    tips = _tips_ranked(q) if len(own) >= 1 and not known else []
    if tips and own <= set(kb.tokens(tips[0]["text"] + " " + tips[0]["section"])):
        out.append(f"\nСовет из уроков: {_tip_line(tips[0])}")
    section = hits[0]["title"].split(" / ")[-1]
    out.append(f"\nЦеликом: /справка {section}" + ("; ещё советы: /совет " + q if tips else ""))
    return "\n".join(out)


# --- /api ----------------------------------------------------------------------------

def _api_members() -> dict[str, list[tuple[str, str]]]:
    """Имя члена (в нижнем регистре) → [(класс, строка описания из справки API)]."""
    if "api_members" in _cache:
        return _cache["api_members"]   # type: ignore[return-value]
    members: dict[str, list[tuple[str, str]]] = {}
    # классы, которых нет в автодополнении (процессы, дашборд статистики…): kb_api_extra.py
    for cls, d in (_load_json("api_extra.json") or {}).items():
        for name, row in d.get("rows", {}).items():
            members.setdefault(name.lower(), []).append((cls, row))
    for c in _load_json("chunks.jsonl") or []:
        if c.get("source") != "api":
            continue
        cls = c["title"].split(" / ")[-1]
        for ln in c["text"].splitlines():
            m = re.match(r"-\s+(\w+)", ln)
            if m:
                members.setdefault(m.group(1).lower(), []).append((cls, ln[2:].strip()))
    _cache["api_members"] = members
    _cache.pop("chunks.jsonl", None)   # 2,7 МБ держать не нужно
    return members


def _api_note(name: str) -> str:
    notes = (_load_json("faq.json") or {}).get("api_notes", {})
    for k, v in notes.items():
        if k.lower() == name.lower():
            return f"\n⚠ В R-Pro: {v}"
    return ""


def api_text(query: str) -> str:
    q = query.strip().strip("().")
    index = _load_json("api_index.json")
    if index is None:
        return "Справочник API не найден (agent/kb/api_index.json)."
    extra = _load_json("api_extra.json") or {}
    if extra:
        index = {**{k: {"parents": v.get("parents", ""), "properties": v.get("properties", []),
                        "methods": v.get("methods", []), "events": v.get("events", [])}
                    for k, v in extra.items()}, **index}
    if not q:
        return ("Напишите имя класса или метода: /api vcSimulation, /api setInitialState, /api PositionMatrix.\n"
                f"Классов в справочнике: {len(index)}. Внутри R-Pro — Python 2.7.")
    if "." in q:   # vcSimulation.setInitialState → смотрим член, но в этом классе
        cls_hint, q = q.rsplit(".", 1)
    else:
        cls_hint = ""
    by_lower = {k.lower(): k for k in index}
    cls = by_lower.get(q.lower()) or by_lower.get("vc" + q.lower())
    if cls and not cls_hint:
        d = index[cls]
        out = [f"{cls}" + (f" (наследует {d['parents']})" if d.get("parents") else "") + " — Python API R-Pro (Python 2.7)"]
        for label, key in (("Свойства", "properties"), ("Методы", "methods"), ("События", "events")):
            if d.get(key):
                out.append(f"{label}: {', '.join(d[key])}")
        out.append(f"Подробно о члене: /api {cls}.<имя>; описание класса целиком: /справка {cls}")
        return "\n".join(out) + _api_note(cls)
    members = _api_members()
    found = members.get(q.lower(), [])
    if cls_hint:
        found = [f for f in found if f[0].lower() == cls_hint.lower()] or found
    if found:
        out = [f"{q} — встречается в {len(found)} класс{'е' if len(found) == 1 else 'ах'}:"]
        for c, line in found[:6]:
            line = re.sub(r"\s+", " ", line)[:300]
            out.append(f"• {c}.{line}")
        if len(found) > 6:
            out.append(f"…и ещё {len(found) - 6}: " + ", ".join(c for c, _ in found[6:16]))
        return "\n".join(out) + _api_note(q)
    # похожие имена
    ql = q.lower()
    similar = [k for k in index if ql in k.lower()][:8]
    similar += [n for n in members if ql in n and n not in (s.lower() for s in similar)][:10]
    if similar:
        return f"Точного «{q}» в API нет. Похожие: " + ", ".join(similar[:15])
    return f"В справочнике API нет «{q}». Проверьте написание: имена чувствительны к регистру (vcComponent, PositionMatrix)."


# --- /термин -------------------------------------------------------------------------

def term_text(query: str) -> str:
    q = _norm(query.strip().strip("«»\"'"))
    pairs = _load_json("ui_terms.json")
    if not q:
        return "Напишите слово: /термин Component Container, /термин сигнал, /термин хваталка."
    out = []
    if pairs:
        latin = bool(re.search(r"[a-z]", q))
        exact, starts, inside = [], [], []
        for en, ru in pairs:
            hay = [en.lower()] if latin else [_norm(r) for r in ru]
            if q in hay:
                exact.append((en, ru))
            elif any(h.startswith(q) for h in hay):
                starts.append((en, ru))
            elif any(q in h for h in hay):
                inside.append((en, ru))
        found = (exact + sorted(starts, key=lambda p: len(p[0])) + sorted(inside, key=lambda p: len(p[0])))[:8]
        for en, ru in found:
            out.append(f"• {en} → {' / '.join(ru)}")
    extra = [t for t in glossary.expand(q) if _norm(t) != q]
    head = f"«{query.strip()}» в интерфейсе R-Pro:" if out else ""
    text = "\n".join([head] + out) if out else f"В названиях интерфейса «{query.strip()}» не нашлось."
    if extra:
        text += "\nВ R-Pro это обычно называется: " + ", ".join(extra[:6]) + "."
    return text


# --- /совет --------------------------------------------------------------------------

def tips_text(query: str) -> str:
    tips = _load_json("tips.jsonl")
    if not tips:
        return "Советы не найдены (agent/kb/tips.jsonl) — соберите: python agent/quickref_build.py"
    q = query.strip()
    if not q:
        sections = Counter(t["section"] for t in tips if not t["section"].startswith("Приложение"))
        return ("Советы из уроков Academy по темам (напишите /совет <тема или вопрос>):\n"
                + "\n".join(f"• {s} — {n}" for s, n in sections.most_common()))
    ranked = _tips_ranked(q)
    if not ranked:
        return f"Советов по «{q}» нет. Список тем — /совет без слов."
    out = [f"Советы по «{q}» (из уроков Visual Components — проверяйте в R-Pro):"]
    out += [f"• {_tip_line(t)}" for t in ranked[:5]]
    return "\n".join(out)


def _tip_line(t: dict) -> str:
    doubtful = t.get("warn") or t["section"].startswith("Приложение")
    return ("⚠ " if doubtful and not t["text"].startswith("⚠") else "") + t["text"]


def _tips_ranked(q: str) -> list[dict]:
    """
    Советы по запросу: сначала те, где есть больше слов запроса, потом по весу.

    Чистый вес слов давал на «скорость конвейера» советы про скорость камеры
    и робота — «конвейер» в них не встречался. Поэтому отбрасываем советы,
    покрывающие меньше слов запроса, чем лучший.
    """
    tips = _load_json("tips.jsonl") or []
    if not tips:
        return []
    if "idf_tips" not in _cache:
        df: Counter = Counter()
        toks = []
        for t in tips:
            s = set(kb.tokens(t["text"] + " " + t["section"]))
            toks.append(s)
            df.update(s)
        n = len(tips)
        _cache["idf_tips"] = ({k: math.log(1 + n / v) for k, v in df.items()}, toks)
    idf, toks = _cache["idf_tips"]   # type: ignore[misc]
    weights = _query_weights(q)
    own = set(kb.tokens(q))
    scored = []
    for i, t in enumerate(tips):
        s = sum(w * idf.get(k, 0) for k, w in weights.items() if k in toks[i])
        if s > 0:
            if t["section"].startswith("Приложение"):
                s *= 0.5
            scored.append((len(own & toks[i]), s, i))
    if not scored:
        return []
    top_cov = max(c for c, _, _ in scored)
    scored = sorted((x for x in scored if x[0] == top_cov), key=lambda x: -x[1])
    best = scored[0][1]
    return [tips[i] for c, s, i in scored if s >= best / 2.5]


# --- /проблема и частые неполадки обычными словами ----------------------------------

def _faq_items() -> list[dict]:
    return (_load_json("faq.json") or {}).get("items", [])


def problem_text(query: str) -> str:
    items = _faq_items()
    if not items:
        return "Список частых неполадок не найден (agent/kb/faq.json)."
    q = query.strip()
    if not q:
        return ("Частые неполадки (напишите /проблема <что случилось>):\n"
                + "\n".join(f"• {it['title']}" for it in items))
    low = _norm(q)
    for it in items:
        if any(re.search(p, low) for p in it.get("patterns", [])):
            return f"**{it['title']}**\n{it['answer']}"
    weights = _query_weights(q)
    scored = []
    for it in items:
        title_t = set(kb.tokens(it["title"] + " " + it.get("keys", "")))
        body_t = set(kb.tokens(it["answer"]))
        s = sum(w * (2.0 if k in title_t else 1.0 if k in body_t else 0.0) for k, w in weights.items())
        if s > 0:
            scored.append((s, it["title"], it))
    if not scored:
        return ("Такой неполадки в списке нет. Опишите её агенту обычными словами или посмотрите "
                "/проблема — весь список.")
    scored.sort(key=lambda x: -x[0])
    it = scored[0][2]
    text = f"**{it['title']}**\n{it['answer']}"
    others = [t for s, t, _ in scored[1:3] if s >= scored[0][0] / 2]
    if others:
        text += "\n\nПохоже также: " + "; ".join(others)
    return text


# Просьба что-то сделать в сцене — работа модели с инструментами, а не справка:
# «поставь скорость всех конвейеров 300» совпадала с записью «Скорость конвейера».
_DO = re.compile(
    r"^(пожалуйста,?\s+)?(поставь|сделай|измени|установи|задай|добавь|построй|убери|удали|запусти|"
    r"перенеси|поменяй|увеличь|уменьши|ускорь|замедли|настрой|создай|почини|исправь|включи|выключи|"
    r"проверь|покажи|найди|давай|можешь|сможешь|переставь|сдвинь|подключи|соедини|оптимизир)")


def faq_item(text: str) -> dict | None:
    """Запись kb/faq.json, шаблон которой совпал с текстом, — в том числе для просьб."""
    low = _norm(text).strip()
    if low.startswith("/") or len(low) > 300:
        return None
    # Совпало несколько — берём запись с самым длинным совпадением: «погрузчик
    # пишет unable…» — про погрузчик, а не общая «Unable to solve path у людей»
    best, best_len = None, 0
    for it in _faq_items():
        for p in it.get("patterns", []):
            m = re.search(p, low)
            if m and len(m.group(0)) > best_len:
                best, best_len = it, len(m.group(0))
    return best


def faq_answer(text: str) -> str | None:
    """Готовый ответ на частую неполадку, описанную обычными словами, — или None."""
    if _DO.search(_norm(text).strip()):
        return None
    it = faq_item(text)
    return f"**{it['title']}**\n{it['answer']}" if it else None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, *rest = sys.argv[1:] or ["справка", "сигналы", "робота"]
    fn = {"справка": help_text, "api": api_text, "термин": term_text, "совет": tips_text,
          "проблема": problem_text}[cmd]
    print(fn(" ".join(rest)))
