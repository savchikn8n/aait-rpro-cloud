# -*- coding: utf-8 -*-
"""Клиент HTTP-моста, живущего внутри R-Pro."""

from __future__ import annotations

from typing import Any

import requests

import config


class BridgeError(RuntimeError):
    """Мост ответил ошибкой или недоступен."""


class RProClient:
    def __init__(self, url: str | None = None, token: str | None = None,
                 timeout: float | None = None) -> None:
        self.url = (url or config.BRIDGE_URL).rstrip("/")
        self.token = token if token is not None else config.BRIDGE_TOKEN
        self.timeout = timeout or config.BRIDGE_TIMEOUT

    # -- низкий уровень -----------------------------------------------------
    def call(self, method: str, **params: Any) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Bridge-Token"] = self.token

        body = {"method": method, "params": params, "timeout": self.timeout - 5}
        try:
            response = requests.post(self.url, json=body, headers=headers,
                                     timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise BridgeError(
                f"Мост недоступен по адресу {self.url}. Запущена ли R-Pro "
                f"и установлен ли мост?") from exc
        except requests.exceptions.Timeout as exc:
            # Раньше здесь была догадка про модальный диалог, и она сбивала с
            # толку: на деле главный поток чаще занят долгой операцией —
            # прогоном симуляции, загрузкой планировки, импортом геометрии.
            raise BridgeError(
                f"R-Pro не ответила за {self.timeout} с: главный поток занят долгой "
                f"операцией (прогон симуляции, загрузка модели) либо открыт модальный "
                f"диалог. Программа при этом жива."
            ) from exc

        payload = response.json()
        if not payload.get("ok"):
            raise BridgeError(payload.get("error") or "неизвестная ошибка моста")
        return payload.get("result")

    def health(self) -> dict:
        try:
            return requests.get(f"{self.url}/health", timeout=5).json()
        except requests.exceptions.ConnectionError as exc:
            raise BridgeError(
                f"мост не отвечает на {self.url} — R-Pro не запущена "
                f"или мост не установлен") from exc
        except requests.exceptions.RequestException as exc:
            raise BridgeError(f"мост недоступен: {exc}") from exc

    # -- удобные обёртки ----------------------------------------------------
    def ping(self) -> dict:
        return self.call("ping")

    def status(self) -> dict:
        return self.call("status")

    def scene(self, limit: int = 200, with_position: bool = True) -> dict:
        return self.call("scene", limit=limit, with_position=with_position)

    def find(self, query: str, limit: int = 50) -> dict:
        return self.call("find", query=query, limit=limit)

    def component(self, name: str, with_properties: bool = True,
                  with_behaviours: bool = False, with_children: bool = False) -> dict:
        return self.call("component", name=name, with_properties=with_properties,
                         with_behaviours=with_behaviours, with_children=with_children)

    def set_property(self, component: str, prop: str, value: Any) -> dict:
        return self.call("set_property", component=component, property=prop, value=value)

    def select(self, names: list[str]) -> dict:
        return self.call("select", names=names)

    def messages(self, tail: int = 100, clear: bool = False) -> dict:
        return self.call("messages", tail=tail, clear=clear)

    def simulation(self, action: str = "status", seconds: float | None = None,
                   until: float | None = None) -> dict:
        return self.call("simulation", action=action, seconds=seconds, until=until)

    def screenshot(self, width: int = 1280, height: int = 720,
                   as_base64: bool = True, path: str | None = None) -> dict:
        return self.call("screenshot", width=width, height=height,
                         as_base64=as_base64, path=path)

    def exec_python(self, code: str) -> dict:
        return self.call("exec", code=code)

    def layout(self, action: str, uri: str = "") -> dict:
        return self.call("layout", action=action, uri=uri)
