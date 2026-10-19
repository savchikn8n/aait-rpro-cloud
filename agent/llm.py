# -*- coding: utf-8 -*-
"""Единая точка вызова модели: Ollama (локально/сервер предприятия) или облако OpenRouter.

Выбор — config.LLM_PROVIDER (RPRO_LLM): ollama | openrouter | auto. В режиме auto агент идёт в облако,
а при сбое (сеть, лимиты, ключ) переключается на Ollama и помечает это в describe().
Интерфейс тот же, что был у llm_ollama: chat, look, warm_up, list_models, describe.
"""

from __future__ import annotations

from typing import Any, Iterable

import config
import llm_ollama
import llm_openrouter


class LLMError(RuntimeError):
    pass


_errors = (llm_ollama.OllamaError, llm_openrouter.OpenRouterError)
_last: dict[str, Any] = {"backend": None, "fallback_reason": ""}


def provider() -> str:
    p = config.LLM_PROVIDER
    return p if p in ("ollama", "openrouter", "auto") else "ollama"


def _run(name: str, *args: Any, **kwargs: Any) -> Any:
    """Вызов функции модели у нужного поставщика, с переходом на Ollama в режиме auto."""
    p = provider()
    try:
        if p == "ollama":
            _last["backend"] = "ollama"
            return getattr(llm_ollama, name)(*args, **kwargs)
        try:
            result = getattr(llm_openrouter, name)(*args, **_cloud_kwargs(kwargs))
            _last.update(backend="openrouter", fallback_reason="")
            return result
        except llm_openrouter.OpenRouterError as exc:
            if p == "openrouter":
                raise
            _last.update(backend="ollama", fallback_reason=str(exc)[:200])
            print(f"[llm] облако недоступно, перехожу на Ollama: {exc}")
            return getattr(llm_ollama, name)(*args, **kwargs)
    except _errors as exc:
        raise LLMError(str(exc)) from exc


def _cloud_kwargs(kwargs: dict) -> dict:
    return kwargs


def chat(messages: list[dict], tools: Iterable[dict] | None = None,
         model: str | None = None, timeout: float = 600.0) -> dict:
    return _run("chat", messages, tools=tools, model=model, timeout=timeout)


def look(image_base64: str, question: str, timeout: float = 600.0) -> str:
    if provider() != "ollama" and not config.OPENROUTER_VISION_MODEL and not config.VISION_MODEL:
        return "Модель со зрением не настроена."
    return _run("look", image_base64, question, timeout=timeout)


def list_models() -> list[dict]:
    return _run("list_models")


def warm_up(model: str | None = None, timeout: float = 300.0) -> None:
    _run("warm_up", model=model, timeout=timeout)


def model_name() -> str:
    """Имя основной модели для панели и журнала."""
    p = provider()
    if p == "ollama" or (_last["backend"] == "ollama" and p == "auto"):
        return config.CHAT_MODEL
    return config.OPENROUTER_MODEL


def describe() -> str:
    p = provider()
    if p == "ollama" or (p == "auto" and _last["backend"] == "ollama"):
        text = llm_ollama.describe()
        if _last["fallback_reason"]:
            text += " (облако недоступно)"
        return text
    return llm_openrouter.describe()
