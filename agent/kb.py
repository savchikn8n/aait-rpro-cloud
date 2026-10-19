# -*- coding: utf-8 -*-
"""
Поиск по базе знаний о R-Pro (kb/chunks.jsonl, собирается kb_build.py).

Обычный BM25 без внешних библиотек. Русские слова приводятся к грубой
основе — первые шесть букв без окончания: «сигналы», «сигнала» и «сигнал»
совпадают. Слова API (setInitialState, vcComponent) сравниваются целиком
и дополнительно по частям верблюжьего регистра. Заголовок фрагмента весит
втрое больше текста: «Операторы Процесса / Транспорт В» точнее описывает
фрагмент, чем любое слово внутри.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

import glossary

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb", "chunks.jsonl")
ACADEMY_PATH = os.path.join(os.path.dirname(PATH), "academy_chunks.jsonl")
IITB_PATH = os.path.join(os.path.dirname(PATH), "iitb_chunks.jsonl")
# Оценка A/B (25 вопросов): релевантность 1,44 → 2,32; поэтому по умолчанию включено,
# с ограничением «не больше одного урока в первых двух». Выключить: RPRO_KB_ACADEMY=0.
ACADEMY_DEFAULT = os.environ.get("RPRO_KB_ACADEMY", "1") != "0"
ACADEMY_WEIGHT = float(os.environ.get("RPRO_KB_ACADEMY_WEIGHT", "0.85"))

_ENDINGS = re.compile(
    r"(ами|ями|ого|его|ому|ему|ыми|ими|ах|ях|ой|ей|ий|ый|ая|яя|ое|ее|ые|ие|ов|ев|ам|ям|"
    r"ом|ем|ую|юю|а|я|о|е|ы|и|у|ю|ь)$")
_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_]+")

# Длина основы русского слова. Пять букв, а не шесть: глаголы иначе
# расходятся — «создать» давало «создат», «создавать» — «создав».
STEM = int(os.environ.get("RPRO_KB_STEM", "5"))
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

def _stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if re.match(r"[а-я]", w):
        if len(w) > 4:
            w = _ENDINGS.sub("", w)
        return w[:STEM]
    return w


# Служебные слова вопросов, которые только размывают поиск. Сравниваются по
# основе, поэтому и сами приводятся к ней: «сделать» → «сделат».
_STOP = {_stem(w) for w in (
    "как", "что", "где", "это", "для", "или", "при", "мне", "мой", "мою", "можно",
    "нужно", "надо", "сделать", "делать", "есть", "его", "её", "они", "так", "там",
    "тут", "чтобы", "если", "какой", "какая", "какие", "который", "будет", "было",
    "меня", "хочу", "пусть", "the", "and", "for", "how", "with")}


# Для каталога: та же основа слова и тот же список служебных слов.
tokens_stem = _stem
STOP = _STOP


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text):
        s = _stem(w)
        # Русские слова из двух букв — предлоги и частицы («на», «по», «не»).
        if len(s) < 2 or s in _STOP or (len(s) == 2 and re.match(r"[а-я]", s)):
            continue
        out.append(s)
        # vcComponent → vc, component; setInitialState → set, initial, state
        if re.search(r"[a-z][A-Z]", w):
            out += [p.lower() for p in _CAMEL.findall(w) if len(p) > 2]
    return out


class Index:
    def __init__(self, path: str = PATH):
        self.chunks: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                self.chunks.append(json.loads(line))
        # Уроки Academy (academy/academy_to_kb.py) лежат отдельным файлом, чтобы
        # пересборка справки их не стирала. Нет файла — агент работает как раньше.
        if path == PATH and os.path.exists(ACADEMY_PATH):
            with open(ACADEMY_PATH, encoding="utf-8") as f:
                for line in f:
                    self.chunks.append(json.loads(line))
        # Курс ИИТБ (iitb/iitb_to_kb.py): родной курс по R-Pro, без скидок и ограничений.
        if path == PATH and os.path.exists(IITB_PATH):
            with open(IITB_PATH, encoding="utf-8") as f:
                for line in f:
                    self.chunks.append(json.loads(line))
        self.tf: list[Counter] = []
        df: Counter = Counter()
        for c in self.chunks:
            # index_text — текст для индекса без дублей заголовка (у уроков Academy
            # заголовок повторяется в строке «Урок: …» и утраивался бы дважды)
            tf = Counter(tokens(c.get("index_text", c["text"])))
            for t in tokens(c["title"]):
                tf[t] += 3
            self.tf.append(tf)
            df.update(tf.keys())
        n = len(self.chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.lens = [sum(tf.values()) for tf in self.tf]
        self.avg = sum(self.lens) / max(n, 1)

    def search(self, query: str, limit: int = 3, sources: list[str] | None = None) -> list[dict]:
        # Слова пользователя весят полностью, термины из словаря — меньше:
        # они подсказывают, но не должны перебивать сам запрос.
        weights = {t: 0.7 for t in tokens(" ".join(glossary.expand(query)))}
        weights.update({t: 1.0 for t in tokens(query)})
        k1, b = 1.4, 0.75
        ql = query.strip().lower()
        scored = []
        for i, tf in enumerate(self.tf):
            if sources and self.chunks[i]["source"] not in sources:
                continue
            # Уроки Academy в общий поиск и автоподстановку идут, если не выключены
            # (RPRO_KB_ACADEMY=0); явно их можно искать через source="уроки".
            if not sources and not ACADEMY_DEFAULT and self.chunks[i]["source"] == "academy":
                continue
            s = 0.0
            for t, w in weights.items():
                f = tf.get(t)
                if f:
                    s += w * self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * self.lens[i] / self.avg))
            # Запрос по названию раздела («Генератор деталей», «vcSimulation»)
            # — это уточнение после первой выдачи: такой раздел идёт первым.
            title = self.chunks[i]["title"].lower()
            if ql and (title.endswith(ql) or title.endswith("/ " + ql)):
                s += 1000
            # У коротких уроков оценки завышены (оценка A/B: урок про конвейер для ПЛК
            # обошёл страницу справки «Подключение к серверу OPC UA») — небольшая скидка.
            if self.chunks[i]["source"] == "academy":
                s *= ACADEMY_WEIGHT
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        # В общей выдаче уроки идут рядом со справкой, а не вместо неё: в первых двух
        # местах не больше одного фрагмента урока (второй слот — лучший не-урок).
        if not sources and ACADEMY_DEFAULT and len(scored) > 2:
            def academy(k: int) -> bool:
                return self.chunks[scored[k][1]]["source"] == "academy"
            if academy(0) and academy(1):
                for k in range(2, len(scored)):
                    if not academy(k):
                        scored.insert(1, scored.pop(k))
                        break
        return [dict(self.chunks[i], score=round(s, 2)) for s, i in scored[:limit]]


_index: Index | None = None


def search(query: str, limit: int = 3, sources: list[str] | None = None) -> list[dict]:
    global _index
    if _index is None:
        _index = Index()
    return _index.search(query, limit, sources)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for hit in search(" ".join(sys.argv[1:]) or "подключить сигналы робота", 5):
        print(f"{hit['score']:6.2f}  [{hit['source']}] {hit['title']} {hit['part']}")
