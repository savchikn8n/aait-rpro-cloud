# -*- coding: utf-8 -*-
"""Облачная модель через OpenRouter (OpenAI-совместимый API) — тот же интерфейс, что у llm_ollama.

chat() принимает и возвращает сообщения в формате Ollama (его использует chat.py): аргументы вызова
инструмента — словарь, ответ инструмента — {"role": "tool", "name", "content"}. Здесь они переводятся
в формат OpenAI (id вызовов, аргументы-строка JSON, tool_call_id) и обратно.

Бесплатные модели ограничены по частоте: на 429 и 5xx запрос повторяется, затем берётся
следующая модель из config.OPENROUTER_FALLBACK_MODELS.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

import requests

import config


class OpenRouterError(RuntimeError):
    pass


_state: dict[str, Any] = {"model": None, "last_ok": 0.0}
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def configured() -> bool:
    return bool(config.OPENROUTER_API_KEY)


def describe() -> str:
    model = _state["model"] or config.OPENROUTER_MODEL
    return f"облако OpenRouter ({model})"


def _headers() -> dict[str, str]:
    if not configured():
        raise OpenRouterError(
            "Не задан ключ OpenRouter. Получите его на openrouter.ai/keys и положите в "
            "%LOCALAPPDATA%\\R-Pro\\AIAgentBridge\\settings.json: {\"OPENROUTER_API_KEY\": \"sk-or-…\"}.")
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://rpro.itc.kl.avtotor.ru",
        "X-Title": "aait-rpro agent",
    }


def _safe(text: str) -> str:
    """Текст ошибки без ключа."""
    key = config.OPENROUTER_API_KEY
    return text.replace(key, "***") if key else text


# --- перевод формата сообщений --------------------------------------------------

def to_openai(messages: list[dict]) -> list[dict]:
    """Сообщения Ollama → OpenAI. Ответы инструментов привязываются к вызовам по порядку и имени."""
    out: list[dict] = []
    pending: list[tuple[str, str]] = []   # (id, имя) вызовов, на которые ещё нет ответа
    counter = 0
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                fn = c.get("function", {})
                counter += 1
                cid = c.get("id") or f"call_{counter}"
                args = fn.get("arguments") or {}
                calls.append({"id": cid, "type": "function", "function": {
                    "name": fn.get("name", ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
                pending.append((cid, fn.get("name", "")))
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": calls})
        elif role == "tool":
            name = m.get("name", "")
            idx = next((i for i, (_, n) in enumerate(pending) if n == name), 0 if pending else None)
            if idx is None:      # ответ без вызова (история сжата) — пересказываем как обычный текст
                out.append({"role": "user", "content": f"[результат {name}] {m.get('content', '')}"})
            else:
                cid, _ = pending.pop(idx)
                out.append({"role": "tool", "tool_call_id": cid, "content": m.get("content") or ""})
        else:
            if pending and role == "user":
                pending.clear()
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def from_openai(message: dict) -> dict:
    """Ответ OpenAI → сообщение в формате Ollama (с id вызовов, они пригодятся при обратном переводе)."""
    content = _THINK.sub("", message.get("content") or "").strip()
    result: dict[str, Any] = {"role": "assistant", "content": content}
    calls = []
    for c in message.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": c.get("id"), "function": {"name": fn.get("name", ""), "arguments": args}})
    if calls:
        result["tool_calls"] = calls
    return result


# --- запросы ----------------------------------------------------------------------

def _post(payload: dict, timeout: float) -> dict:
    url = f"{config.OPENROUTER_URL}/chat/completions"
    headers = _headers()
    models = [payload["model"]] + [m for m in config.OPENROUTER_FALLBACK_MODELS if m != payload["model"]]
    if payload.get("_no_fallback"):
        models = models[:1]
    last = "нет ответа"
    for model in models:
        body = {k: v for k, v in payload.items() if not k.startswith("_")}
        body["model"] = model
        for attempt in range(max(1, config.OPENROUTER_RETRIES)):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                last = _safe(f"{type(exc).__name__}: {exc}")[:300]
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    last = "ответ не JSON"
                    continue
                if data.get("error"):      # OpenRouter иногда отдаёт ошибку провайдера с кодом 200
                    last = _safe(json.dumps(data["error"], ensure_ascii=False))[:300]
                    break
                choices = data.get("choices") or []
                if not choices or not choices[0].get("message"):
                    last = "пустой ответ модели"
                    continue
                _state.update(model=model, last_ok=time.time())
                return choices[0]["message"]
            last = _safe(f"{r.status_code}: {r.text}")[:300]
            if r.status_code in (401, 403):
                raise OpenRouterError(f"OpenRouter отклонил ключ или доступ ({last})")
            if r.status_code == 402:
                raise OpenRouterError(f"OpenRouter: нужна оплата или нет кредитов ({last})")
            if r.status_code in (429, 500, 502, 503, 504):
                wait = r.headers.get("Retry-After", "")
                time.sleep(min(float(wait) if wait.replace(".", "", 1).isdigit() else 2.0 * (attempt + 1), 20))
                continue
            break        # 400/404 и прочее — эта модель не подойдёт, берём следующую
    raise OpenRouterError(f"OpenRouter не ответил ни одной моделью ({', '.join(models)}): {last}")


def list_models() -> list[dict]:
    """Для selfcheck: проверка ключа и список настроенных моделей."""
    r = requests.get(f"{config.OPENROUTER_URL}/auth/key", headers=_headers(), timeout=15)
    if r.status_code != 200:
        raise OpenRouterError(f"OpenRouter: проверка ключа — {r.status_code}: {_safe(r.text)[:200]}")
    names = [config.OPENROUTER_MODEL] + config.OPENROUTER_FALLBACK_MODELS + [config.OPENROUTER_VISION_MODEL]
    return [{"name": n, "size": 0, "capabilities": ["tools"]} for n in names if n]


def chat(messages: list[dict], tools: Iterable[dict] | None = None,
         model: str | None = None, timeout: float = 180.0) -> dict:
    # model из chat.py — локальное имя (qwen3:8b); облачной модели оно не подходит
    chosen = model if model and "/" in model else config.OPENROUTER_MODEL
    payload: dict[str, Any] = {
        "model": chosen,
        "messages": to_openai(messages),
        "temperature": config.OPENROUTER_TEMPERATURE,
    }
    tools = list(tools or [])
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return from_openai(_post(payload, timeout))


def look(image_base64: str, question: str, timeout: float = 180.0) -> str:
    payload = {
        "model": config.OPENROUTER_VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
        ]}],
        "temperature": 0.2,
        "_no_fallback": True,      # запасные модели — текстовые, картинку не поймут
    }
    return from_openai(_post(payload, timeout)).get("content", "")


def warm_up(model: str | None = None, timeout: float = 30.0) -> None:
    """Облаку прогрев не нужен — проверяем только ключ."""
    list_models()
