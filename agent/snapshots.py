# -*- coding: utf-8 -*-
"""Автосохранение сцены перед изменениями и откат к нему.

Перед первой правкой в ходе (chat._loop) агент сам сохраняет сцену копией .rpro в
%LOCALAPPDATA%\\R-Pro\\AIAgentBridge\\snapshots и записывает её в index.json. Фраза «откатись до последнего
автосохранения» (или /откат) открывает последнюю копию. Откат сам тоже сохраняет текущую сцену, поэтому его
можно отменить следующим «откатись».

Что неизвестно без живой R-Pro: сохранение копии через app.save(...) может действовать как «Сохранить как»,
и тогда программа дальше считает текущим файлом автосохранение. take() и rollback() это замечают (адрес
планировки до и после) и возвращают предупреждение — показываем его пользователю.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse

import config

KEEP = int(os.environ.get("RPRO_SNAPSHOT_KEEP", "30"))


def folder() -> str:
    base = os.environ.get("RPRO_SNAPSHOT_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "R-Pro", "AIAgentBridge", "snapshots")
    os.makedirs(base, exist_ok=True)
    return base


def _uri(path: str) -> str:
    return "file:///" + path.replace("\\", "/")


def _index_path() -> str:
    return os.path.join(folder(), "index.json")


def _load() -> list[dict]:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and os.path.exists(d.get("path", ""))]
    except (OSError, ValueError):
        return []


def _store(items: list[dict]) -> None:
    for old in items[:-KEEP]:
        try:
            os.remove(old["path"])
        except OSError:
            pass
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(items[-KEEP:], f, ensure_ascii=False, indent=1)


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\- ]+", "", s, flags=re.U).strip()[:40] or "сцена"


def _state(client) -> dict:
    try:
        st = client.status()
    except Exception:  # noqa: BLE001 — состояние нужно для подписи, без него копию всё равно делаем
        st = {}
    return {"components": st.get("component_count"), "layout_uri": st.get("layout_uri") or "",
            "modified": bool(st.get("layout_modified"))}


def take(client, reason: str = "автосохранение") -> dict:
    """Сохранить копию сцены. Возвращает запись индекса (с «warning», если адрес планировки сменился)."""
    st = _state(client)
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    path = os.path.join(folder(), f"{stamp} {_safe_name(reason)}.rpro")
    k = 1
    while os.path.exists(path):          # две копии в одну секунду не должны затирать друг друга
        k += 1
        path = os.path.join(folder(), f"{stamp} {_safe_name(reason)} ({k}).rpro")
    res = client.layout("save", _uri(path))
    entry = {"path": path, "ts": time.time(), "stamp": stamp, "reason": reason,
             "components": st["components"], "layout_before": st["layout_uri"]}
    after = (res or {}).get("layout_uri") or ""
    if after and st["layout_uri"] and urllib.parse.unquote(after) != urllib.parse.unquote(st["layout_uri"]):
        entry["warning"] = ("R-Pro теперь ведёт проект как файл автосохранения. Чтобы не потерять работу, "
                            "сохраните проект под своим именем (Файл → Сохранить как).")
    items = _load()
    items.append(entry)
    _store(items)
    return entry


def entries() -> list[dict]:
    return _load()


def latest() -> dict | None:
    items = _load()
    return items[-1] if items else None


def _when(e: dict) -> str:
    return time.strftime("%H:%M:%S", time.localtime(e["ts"])) + time.strftime(" %d.%m", time.localtime(e["ts"]))


def list_text() -> str:
    items = _load()
    if not items:
        return "Автосохранений пока нет: их делает агент перед первой правкой сцены. Своё — /сохрани <название>."
    lines = ["Автосохранения (новые внизу):"]
    for i, e in enumerate(items[-10:], max(1, len(items) - 9)):
        n = e.get("components")
        lines.append(f"{i}. {_when(e)} — {e['reason']}" + (f", компонентов {n}" if n is not None else ""))
    lines.append("Вернуть последнее — «откатись» или /откат; номер — /откат N.")
    return "\n".join(lines)


# Фразы «верни как было»: узкий список, чтобы не перехватывать «верни робота домой» и т.п.
ROLLBACK = re.compile(
    r"^\s*(пожалуйста,?\s*)?("
    r"откат\w*|"
    r"отмен\w+\s+(все\s+|последни\w+\s+|эти\s+)?(изменени|правк|действи)\w*|"
    r"верн\w+\s+(сцену\s+|всё\s+|все\s+|проект\s+)?(как\s+было|назад|к\s+автосохранени\w*|до\s+(последн\w+\s+)?(автосохранени\w*|изменени\w*))|"
    r"восстанов\w+\s+(сцену\s+|проект\s+)?(из|до|с)\s+(последн\w+\s+)?автосохранени\w*"
    r")", re.I)


def rollback_text(client, which: int | None = None) -> str:
    items = _load()
    if not items:
        return "Откатываться не к чему: автосохранений нет. Они появляются, когда агент собирается менять сцену."
    if which is not None:
        if not 1 <= which <= len(items):
            return f"Нет автосохранения №{which}. Есть: 1…{len(items)} (список — /автосохранение)."
        target = items[which - 1]
    else:
        target = items[-1]
    # Текущее состояние — тоже копией: откат можно отменить следующим «откатись».
    try:
        before = take(client, "перед откатом")
    except Exception as exc:  # noqa: BLE001
        return (f"Откат не выполнен: не удалось сохранить текущую сцену перед ним ({type(exc).__name__}: "
                f"{str(exc)[:150]}). Сцену я не трогал.")
    try:
        client.layout("open", _uri(target["path"]))
    except Exception as exc:  # noqa: BLE001
        return (f"Не удалось открыть автосохранение ({type(exc).__name__}: {str(exc)[:200]}). Сцена осталась как "
                f"есть; копия текущей — «{before['reason']}» ({_when(before)}).")
    st = _state(client)
    ok = target.get("components")
    check = ""
    if ok is not None and st["components"] is not None and st["components"] != ok:
        check = f" Внимание: компонентов {st['components']}, в копии было {ok} — проверьте сцену."
    note = f"\n{before['warning']}" if before.get("warning") else ""
    return (f"Сцена возвращена к автосохранению от {_when(target)} («{target['reason']}»)." + check +
            f" Перед откатом текущее состояние сохранено ({_when(before)}): чтобы вернуть его, скажите «откатись» "
            f"ещё раз." + note)
