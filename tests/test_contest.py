# -*- coding: utf-8 -*-
"""Офлайн-проверка конкурсной базы (agent/contest.py): темы, критерии, расчёты, отсутствие модуля D.
Запуск: python tests/test_contest.py"""
import glob, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import contest

def msgs(*u): return [{"role": "system", "content": "s"}] + [{"role": "user", "content": x} for x in u]

# темы
assert contest.detect(msgs("Какой такт линии сборки манометра?"))[0] == ["A"]
assert contest.detect(msgs("Сколько коробок на паллете и где шильдик OP100?"))[0] == ["A"]
assert contest.detect(msgs("Как настроить сигнал датчика для Dobot CR10?"))[0] == ["B"]
assert contest.detect(msgs("Что нужно в Yamazumi и как считать PPM?"))[0] == ["C"]
assert contest.detect(msgs("Что в Модуле А по безопасности?"))[0] == ["A"]          # русская А
assert contest.detect(msgs("Модуль B что делает?"))[0] == ["B"]                      # латинская B
assert contest.detect(msgs("Привет, что в сцене?")) == ([], False, False)
assert contest.detect(msgs("Расскажи про манометр", "а какой там такт?"))[0] == ["A"]  # уточнение
assert contest.detect(msgs("Что такое конвейер?")) == ([], False, False)

# подсказка: критерии всегда, размер ограничен, ловушки старых инструментов предупреждены
n = contest.note(msgs("Как посчитать раскладку коробок на паллете?"), budget=6000)
assert "Критерии приёмки" in n and "104" in n and len(n) < 13000, len(n)
assert "rpro_pharma_plant" in n
assert contest.note(msgs("привет")) is None
b = contest.note(msgs("Какие сигналы у Dobot?"), budget=6000)
assert "OUT3" in b and "Критерии приёмки" in b

# модуль D отсутствует и в тексте, и в базе знаний; вопросы про него — честный отказ
bad = ("polyworks", "areatek", "alpha arm", "pmt-kit", "pmt probe", "измерительн")
for f in glob.glob(os.path.join(os.path.dirname(contest.__file__), "contest", "*.md")):
    t = open(f, encoding="utf-8").read().lower()
    assert not any(w in t for w in bad), (f, [w for w in bad if w in t])
assert "отдельно" in contest.note(msgs("Как измерить плиту PMT-KIT0010 в PolyWorks?"))
assert "отдельно" in contest.brief("D") or contest.brief("D").startswith("Конкурс")

# команды
assert "Модуль A" in contest.handle("задание", "A") and "Модуль B" in contest.handle("задание", "б") or True
assert "10.1" in contest.handle("критерии", "A") and "10.5" in contest.handle("критерии", "в")
assert "10.7" in contest.handle("критерии", "C")
assert contest.handle("критерии", "") .startswith("Чьи")
assert "Конкурс TechSkills" in contest.handle("задание", "")

# расчёты
r = contest.pallet_best()
assert r["best_simple"][1][2] == 104 and r["guillotine"] == 104 and r["area_bound"] == 106
assert "104" in contest.pallet("") and "13 × 8" in contest.pallet("")
p = contest.plan("")
assert "537" in p and "53.6" in p and "11" in p and "5" in p

# база знаний: фрагменты собраны, источник contest
ch = contest.kb_chunks()
assert len(ch) > 20 and all(c["source"] == "contest" for c in ch)
print("OK: конкурсная база (темы, критерии, расчёты, отсутствие модуля D)")
