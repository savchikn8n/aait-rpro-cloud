# -*- coding: utf-8 -*-
"""
Русские уроки Academy → база знаний агента: python academy_to_kb.py

Читает digests_ru/*.md и пишет ../kb/academy_chunks.jsonl (source = "academy").
kb.py подхватывает этот файл вместе с chunks.jsonl, поэтому пересборка
справки (kb_build.py) уроки не стирает.

Что делает по дороге:
- режет длинные уроки по разделам на фрагменты не длиннее MAX_CHARS
  (маленькая модель агента читает 1–2 фрагмента по ~1000 токенов; целый
  урок на 5 тыс. знаков в такой бюджет не влезает). Каждый фрагмент
  начинается со строки «Урок: …», чтобы быть понятным сам по себе;
  «Лайфхаки и ловушки» всегда идут отдельным фрагментом: по запросу
  «подводные камни …» находится именно он. «Ключевые слова» отдельным
  обрезком не живут (поиск вернул бы голый список слов): их получают
  первый фрагмент и фрагмент с советами;
- не берёт в поиск уроки с применимостью «не применимо» и уроки про
  Python 3 API (`await`, `import vc`): в R-Pro Python 2.7, и маленькая
  модель скопирует чужой синтаксис в код для rpro_exec. Список исключённых
  и причины — поля in_kb / excluded_why в реестре;
- уроки с применимостью «проверить» остаются, но с пометкой в «Урок: …»;
- сверяет идентификаторы из раздела «Скрипты и API» с kb/api_index.json
  (Python-API R-Pro 2.7). Строки с идентификаторами, которых там нет
  (.NET API, названия, услышанные на слух), получают пометку: агент не
  должен выдавать их за готовый код для rpro_exec.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import registry

HERE = Path(__file__).resolve().parent
KB = HERE.parent / "kb"
OUT = KB / "academy_chunks.jsonl"
MAX_CHARS = 3000
MARK = " ⚠ нет в Python-API R-Pro 2.7"
# Только настоящий код Python 3: простое упоминание «Python 3 API» в тексте не повод
_PY3 = re.compile(r"`[^`\n]*\b(?:await|async)\b[^`\n]*`|`import vc\b")


CHANGES: list[tuple[str, str]] = []  # (было, стало) последней сборки — для проверки на ложные замены
_DOTNET = re.compile(r"\.NET|IPlugin|ICommandRegistry|ActionItem|IEventAggregator|IMessageService")


def _key(name: str) -> str:
    """Ключ сопоставления имён: без регистра и подчёркиваний (get_component = getComponent)."""
    return name.lower().replace("_", "")


def known_names() -> set[str]:
    api = json.loads((KB / "api_index.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for cls, d in api.items():
        names.add(_key(cls))
        for key in ("methods", "properties", "events"):
            names.update(_key(x) for x in d.get(key, []))
    return names


def canonical_names() -> dict[str, str]:
    """ключ (без регистра и подчёркиваний) → единственное каноническое написание из api_index.json.

    Haiku восстанавливал имена на слух и ошибался: регистр (GetApplication вместо getApplication)
    и стиль (get_component вместо getComponent, как в Python-API Visual Components 5.x). В
    Python 2.7 R-Pro такой вызов даёт AttributeError. Неоднозначные имена (два написания) не трогаем."""
    api = json.loads((KB / "api_index.json").read_text(encoding="utf-8"))
    seen: dict[str, set[str]] = {}
    for cls, d in api.items():
        for n in [cls] + d.get("methods", []) + d.get("properties", []) + d.get("events", []):
            seen.setdefault(_key(n), set()).add(n)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def is_dotnet(text: str, category: str = "") -> bool:
    """.NET-уроки (C#: PascalCase) исправлять по Python-API нельзя."""
    return ".NET" in (category or "") or bool(_DOTNET.search(text))


def fix_case(section: str, canon: dict[str, str]) -> tuple[str, int]:
    """Приводит идентификаторы внутри `…` к написанию из API (регистр и подчёркивания).

    Текст внутри кавычек (строковые литералы, имена поведений) не трогаем."""
    fixed = 0

    def fix_word(i: re.Match) -> str:
        nonlocal fixed
        word = i.group(0)
        right = canon.get(_key(word))
        # простые слова строчными (path, from, name, count) не трогаем: это обычный Python,
        # а не имя API; исправляем snake_case (get_component → getComponent) и неверный регистр
        if word.islower() and "_" not in word:
            return word
        if right and right != word and len(word) > 3:
            fixed += 1
            CHANGES.append((word, right))
            return right
        return word

    def fix_token(m: re.Match) -> str:
        parts = re.split(r"(\"[^\"]*\"|'[^']*')", m.group(1))
        return "`" + "".join(
            p if k % 2 else re.sub(r"[A-Za-z_][A-Za-z0-9_]*", fix_word, p) for k, p in enumerate(parts)) + "`"

    return re.sub(r"`([^`\n]+)`", fix_token, section), fixed


def flag_api(section: str, names: set[str]) -> tuple[str, int]:
    """Помечает строки, где ни один идентификатор в `…` не найден в API."""
    out, flagged = [], 0
    for line in section.splitlines():
        toks = re.findall(r"`([^`]+)`", line)
        idents = [i for t in toks for i in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t)]
        if idents and not any(_key(i) in names for i in idents) and MARK not in line:
            line += MARK
            flagged += 1
        out.append(line)
    return "\n".join(out), flagged


def split_sections(text: str) -> tuple[str, str, list[tuple[str, str]]]:
    lines = text.strip().splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    head, sections, cur, buf = [], [], None, []
    for ln in lines[1:]:
        if ln.startswith("## "):
            if cur is not None:
                sections.append((cur, "\n".join(buf).strip()))
            cur, buf = ln[3:].strip(), []
        elif cur is None:
            head.append(ln)
        else:
            buf.append(ln)
    if cur is not None:
        sections.append((cur, "\n".join(buf).strip()))
    return title, "\n".join(head).strip(), sections


def pack(title: str, head: str, sections: list[tuple[str, str]], tag: str = "") -> list[str]:
    """Жадно собирает разделы во фрагменты; слишком длинный раздел режется по строкам."""
    prefix = f"Урок: {title}{tag}\n"
    room = MAX_CHARS - len(prefix) - 400  # запас под строку ключевых слов
    keywords = ""
    blocks: list[tuple[str, str]] = []
    if head:
        blocks.append(("", head))
    for name, body in sections:
        if not body:
            continue
        if name.startswith("Ключевые"):
            keywords = "Ключевые слова: " + body.replace("\n", " ")
            continue
        blocks.append((name, f"## {name}\n{body}"))

    chunks: list[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        cur = ""

    for name, block in blocks:
        if name.startswith("Лайфхаки"):
            flush()  # советы и ловушки — отдельным фрагментом
            cur = block + "\n\n"
            continue
        if len(block) > room:
            # режем по строкам, начиная с остатка текущего фрагмента
            for ln in block.splitlines():
                if len(cur) + len(ln) + 1 > room and cur.strip():
                    flush()
                    cur = f"## {name} (продолжение)\n"
                cur += ln + "\n"
            cur += "\n"
        elif len(cur) + len(block) + 2 > room:
            flush()
            cur = block + "\n\n"
        else:
            cur += block + "\n\n"
    flush()
    if not chunks:
        return []
    # ключевые слова: первому фрагменту и фрагменту с советами
    for i, c in enumerate(chunks):
        if keywords and (i == 0 or c.startswith("## Лайфхаки")):
            chunks[i] = c + "\n\n" + keywords
    return [prefix + c for c in chunks]


def classify(head: str) -> str:
    """ok / check / no — по строке применимости из урока."""
    m = re.search(r"Применимость к R-Pro:\s*(.*)", head)
    line = (m.group(1) if m else "").lower()
    if line.startswith("не применимо"):
        return "no"
    if line.startswith("проверить"):
        return "check"
    return "ok"


def build(recs: dict[str, dict]) -> tuple[list[dict], dict[str, str], dict[str, str], dict]:
    """Фрагменты базы агента из записей реестра (нужно поле ru).

    Возвращает (фрагменты, исключённые slug → причина, slug → применимость ok/check/no, статистика).
    Порядок — как у прежних файлов digests_ru (по имени файла), чтобы пересборка совпадала побайтно."""
    names = known_names()
    canon = canonical_names()
    case_fixed = flagged_total = lessons = 0
    chunks: list[dict] = []
    excluded: dict[str, str] = {}
    applicability: dict[str, str] = {}
    for slug in sorted(recs, key=lambda s: s + ".md"):
        text = recs[slug].get("ru") or ""
        title, head, sections = split_sections(text)
        if not title or not sections:
            excluded[slug] = "не разобран"
            continue
        status = classify(head)
        applicability[slug] = status
        if status == "no":
            excluded[slug] = "не применимо к R-Pro"
            continue
        if _PY3.search(text):
            excluded[slug] = "Python 3 API (в R-Pro Python 2.7)"
            continue
        fixed = []
        dotnet = is_dotnet(text, recs[slug].get("category") or "")
        for name, body in sections:
            # раздел-заглушка («Нет.», «В руководстве нет.») — шум в поиске, пропускаем
            if re.fullmatch(r"(нет|none|в руководстве нет)\.?", body.strip().lower()):
                continue
            if not dotnet:
                body, k = fix_case(body, canon)
                case_fixed += k
            if name.startswith("Скрипты"):
                body, n = flag_api(body, names)
                flagged_total += n
            fixed.append((name, body))
        tag = " (⚠ проверить применимость к R-Pro)" if status == "check" else ""
        parts = pack(title, head, fixed, tag)
        lessons += 1
        for k, t in enumerate(parts, 1):
            chunks.append({
                "source": "academy",
                "title": f"Уроки Academy / {title}",
                "part": f"{k}/{len(parts)}" if len(parts) > 1 else "",
                "text": t,
                # для индекса: без строки «Урок: …» (заголовок и так весит втрое)
                "index_text": t.split("\n", 1)[1] if "\n" in t else t,
                "slug": slug,
                "applicability": status,
                "id": 0,
            })
    for i, c in enumerate(chunks):
        c["id"] = 100000 + i  # не пересекается с id справки
    sizes = sorted(len(c["text"]) for c in chunks) or [0]
    stats = {"lessons": lessons, "excluded": len(excluded), "chunks": len(chunks),
             "median": sizes[len(sizes) // 2], "max": sizes[-1],
             "flagged": flagged_total, "case_fixed": case_fixed}
    return chunks, excluded, applicability, stats


def write_chunks(chunks: list[dict]) -> None:
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")


def rebuild(recs: dict[str, dict]) -> dict:
    """Пересобрать базу агента из реестра и обновить в записях in_kb / excluded_why / applicability."""
    chunks, excluded, applicability, stats = build(recs)
    for slug, rec in recs.items():
        rec["in_kb"] = slug not in excluded
        rec["excluded_why"] = excluded.get(slug, "")
        if slug in applicability:
            rec["applicability"] = applicability[slug]
    write_chunks(chunks)
    return stats


def report(stats: dict) -> str:
    return (f"уроков в базе: {stats['lessons']}, исключено: {stats['excluded']}, фрагментов: {stats['chunks']}, "
            f"длина медиана {stats['median']}, максимум {stats['max']}; "
            f"строк API с пометкой: {stats['flagged']}, исправлен регистр имён API: {stats['case_fixed']}")


def main() -> None:
    recs = registry.load_lessons()
    if not recs:
        # первый запуск до появления реестра: берём файлы digests_ru
        for f in sorted((HERE / "digests_ru").glob("*.md")):
            recs[f.stem] = {"slug": f.stem, "ru": f.read_text(encoding="utf-8")}
        print(f"реестра ещё нет, читаю digests_ru: {len(recs)} уроков")
        print(report(rebuild(recs)))
        return
    stats = rebuild(recs)
    registry.save_lessons(recs)
    print(report(stats))


if __name__ == "__main__":
    main()
