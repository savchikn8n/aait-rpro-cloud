# -*- coding: utf-8 -*-
"""Тонкая обёртка над Ollama: чат с инструментами и зрение.

Адрес модели выбирается сам: сначала локальная Ollama (config.OLLAMA_URL), если она не отвечает —
запасные серверы (config.OLLAMA_FALLBACK_URLS, по умолчанию сервер предприятия). Так агент работает
и на рабочей станции с видеокартой, и на выезде/ноутбуке по VPN. Выбор помнится минуту; при обрыве
соединения в середине работы — повторяется с остальными адресами.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import requests

import config


class OllamaError(RuntimeError):
    pass


# --- выбор сервера ---------------------------------------------------------------

_state: dict[str, Any] = {"url": None, "checked": 0.0, "models": [], "tried": []}
RECHECK_S = 60.0            # как долго верим найденному адресу
PROBE_TIMEOUT_S = 4.0       # сколько ждём ответ /api/tags при выборе


def endpoints() -> list[str]:
    seen: list[str] = []
    for u in [config.OLLAMA_URL.rstrip("/")] + list(config.OLLAMA_FALLBACK_URLS):
        if u and u not in seen:
            seen.append(u)
    return seen


def _probe(url: str) -> list[dict] | None:
    try:
        r = requests.get(f"{url}/api/tags", timeout=PROBE_TIMEOUT_S)
        if r.status_code == 200:
            return r.json().get("models", [])
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def pick(force: bool = False, skip: tuple[str, ...] = ()) -> str:
    """Адрес рабочего сервера моделей (с кэшем). Нет ни одного — OllamaError."""
    now = time.time()
    if not force and _state["url"] and _state["url"] not in skip and now - _state["checked"] < RECHECK_S:
        return _state["url"]
    tried = []
    for url in endpoints():
        if url in skip:
            continue
        models = _probe(url)
        tried.append(url)
        if models is not None:
            _state.update(url=url, checked=now, models=models, tried=tried)
            return url
    _state.update(url=None, checked=now, models=[], tried=tried)
    raise OllamaError(
        "Ни один сервер моделей не отвечает: " + ", ".join(tried or endpoints()) + ". "
        "Запустите локальную Ollama (значок в трее) или подключитесь к сети предприятия (VPN).")


def is_local(url: str | None = None) -> bool:
    u = url or _state["url"] or ""
    return u.startswith(("http://127.0.0.1", "http://localhost"))


def describe() -> str:
    """Для /health и панели: где сейчас модель."""
    if not _state["url"]:
        return "не выбран"
    return "локальная Ollama" if is_local() else f"сервер предприятия ({_state['url']})"


def _model_names() -> list[str]:
    return [m.get("name", "") for m in _state["models"]]


def _chat_model(model: str | None) -> str:
    """Нужная модель, а если на выбранном сервере её нет — лучшая из имеющихся с инструментами."""
    want = model or config.CHAT_MODEL
    names = _model_names()
    if not names or want in names:
        return want
    for m in _state["models"]:
        if "tools" in (m.get("capabilities") or []) and m.get("name") not in ("",):
            return m["name"]
    return want


def _vision_model() -> str:
    want = config.VISION_MODEL
    names = _model_names()
    if not names or want in names:
        return want
    for m in _state["models"]:
        if "vision" in (m.get("capabilities") or []):
            return m["name"]
    return want


def _post(path: str, payload: dict, timeout: float) -> dict:
    skip: tuple[str, ...] = ()
    last: Exception | None = None
    for _ in range(max(1, len(endpoints()))):
        url = pick(skip=skip)
        body = dict(payload)
        if "model" in body and not body.get("_fixed"):
            body["model"] = _chat_model(body["model"])      # на сервере нет такой модели — берём подходящую
        body.pop("_fixed", None)
        try:
            response = requests.post(f"{url}{path}", json=body, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as exc:
            last = exc
            skip += (url,)
            _state["url"] = None          # выбрать заново, без этого адреса
            continue
        if response.status_code != 200:
            raise OllamaError(f"Модель ({url}) вернула {response.status_code}: {response.text[:400]}")
        return response.json()
    raise OllamaError("Сервер моделей оборвал соединение: " + str(last)[:200]) from last


def list_models() -> list[dict]:
    pick()
    return list(_state["models"])


def chat(messages: list[dict], tools: Iterable[dict] | None = None,
         model: str | None = None, timeout: float = 600.0) -> dict:
    """Один ход модели. Возвращает объект message из ответа Ollama."""
    payload: dict[str, Any] = {
        "model": model or config.CHAT_MODEL,
        "messages": _without_thinking(messages) if not config.THINKING else messages,
        "stream": False,
        "keep_alive": config.KEEP_ALIVE,
        "options": {"num_ctx": config.NUM_CTX, "temperature": 0.3},
    }
    if tools:
        payload["tools"] = list(tools)
    return _post("/api/chat", payload, timeout).get("message", {})


def _without_thinking(messages: list[dict]) -> list[dict]:
    """
    Просит модель не рассуждать вслух — пометкой /no_think в системном сообщении.

    Казалось бы, для этого есть параметр think=false, но у моделей Qwen3 он
    ведёт себя коварно: рассуждения никуда не деваются, а переезжают из
    отдельного поля прямо в текст ответа. Пользователь получает «Хорошо,
    пользователь спрашивает…» вместо ответа. На большой модели это было
    незаметно, на средних полезло наружу.

    Пометка /no_think, в отличие от параметра, и ответ оставляет чистым, и
    работает быстрее всего.
    """
    if not messages:
        return messages

    подготовленные = list(messages)
    первое = dict(подготовленные[0])
    if первое.get("role") == "system" and "/no_think" not in (первое.get("content") or ""):
        первое["content"] = (первое.get("content") or "") + "\n\n/no_think"
        подготовленные[0] = первое
    return подготовленные


def look(image_base64: str, question: str, timeout: float = 600.0) -> str:
    """Задаёт вопрос по картинке модели со зрением."""
    if not config.VISION_MODEL:
        return "Модель со зрением не настроена (RPRO_VISION_MODEL пустая)."
    pick()
    payload = {
        "model": _vision_model(),
        "_fixed": True,
        "messages": [{
            "role": "user",
            "content": question,
            "images": [image_base64],
        }],
        "stream": False,
        "think": False,
        "keep_alive": config.KEEP_ALIVE,
        "options": {"temperature": 0.2},
    }
    return _post("/api/chat", payload, timeout).get("message", {}).get("content", "")


def warm_up(model: str | None = None, timeout: float = 300.0) -> None:
    """
    Загружает модель в память заранее, не задавая ей вопросов.

    Первая загрузка идёт десятки секунд. Если отложить её до первого вопроса,
    инженер решит, что агент завис. Пустой запрос к /api/generate — штатный
    способ Ollama просто поднять модель и держать её keep_alive.

    num_ctx обязан совпадать с тем, что передаёт chat(): Ollama держит модель
    загруженной под определённую длину контекста и при другой перезагружает.
    Без него Ollama 0.35 брала контекст по умолчанию (40960): модель занимала
    11,6 ГБ вместо 6,2, половина уезжала на процессор, а первый вопрос всё
    равно перезагружал её под 8192.
    """
    pick(force=True)
    _post("/api/generate", {
        "model": model or config.CHAT_MODEL,
        "keep_alive": config.KEEP_ALIVE,
        "options": {"num_ctx": config.NUM_CTX},
    }, timeout)
