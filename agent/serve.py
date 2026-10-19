# -*- coding: utf-8 -*-
"""
Сервер агента для окна чата внутри R-Pro.

Панель в R-Pro написана на C# и намеренно сделана тонкой: она только рисует
переписку и отправляет вопросы сюда. Вся работа с моделью, инструментами и
историей разговора остаётся здесь, в Python, — ровно там же, где она была
для терминального диалога.

Запуск: python serve.py
Проверка: Invoke-RestMethod http://127.0.0.1:8766/health

Обычно запускать руками не нужно: плагин в R-Pro поднимает сервер сам при
старте программы (см. install-autostart.ps1). Тогда он получает два ключа:
  --log FILE         писать вывод в файл, раз консоли нет;
  --parent-pid PID   завершиться вместе с процессом R-Pro.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chat
import config
import llm
import tools
from rpro_client import BridgeError

HOST = os.environ.get("RPRO_AGENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("RPRO_AGENT_PORT", "8766"))

# Разговор один на всех: окно чата в R-Pro — единственный собеседник.
# Замок нужен, потому что ответ модели идёт долго, а панель нетерпелива.
_lock = threading.Lock()
_messages: list[dict] = [{"role": "system", "content": config.SYSTEM_PROMPT}]


# Состояние модели: "загружается", "готова" или текст ошибки. Панель в R-Pro
# показывает приветствие, только когда модель готова, — иначе первый ответ
# шёл бы минуту, и инженер решил бы, что агент завис.
_model_state = "загружается"


def _warm_up() -> None:
    """
    Поднимает модель, а если не вышло — пробует ещё, пока жив сервер.

    Раньше одна неудача (06.10: прогрев 300 с простоял в очереди Ollama за
    чужими запросами к видеокарте) навсегда оставляла в панели «модель не
    загрузилась», хотя через минуту видеокарта освобождалась. Теперь ошибка
    показывается понятными словами, а прогрев повторяется; как только модель
    поднимется, состояние станет «готова».
    """
    global _model_state
    import time

    attempt = 0
    while True:
        attempt += 1
        try:
            llm.warm_up(timeout=120.0)
            _model_state = "готова"
            print(f"Модель {llm.model_name()} загружена (попытка {attempt}): {llm.describe()}.")
            return
        except Exception as exc:
            _model_state = "ошибка: " + _explain_warm_up_error(exc)
            print(f"Модель не загрузилась (попытка {attempt}): {exc}")
        time.sleep(min(30 * attempt, 300))


def _explain_warm_up_error(exc: Exception) -> str:
    """Текст для инженера в панели, а не трассировка requests."""
    text = str(exc)
    if "OpenRouter" in text:
        return text[:300]
    if "Read timed out" in text or "timed out" in text.lower():
        return (f"Ollama не успела поднять {config.CHAT_MODEL} за 2 минуты — "
                "обычно видеокарта занята другой моделью или чужим запросом. "
                "Агент повторит загрузку сам; первые ответы могут задержаться.")
    if "Ни один сервер" in text or "недоступна" in text or "Connection" in text:
        return ("ни локальная Ollama, ни сервер предприятия не отвечают. Запустите Ollama "
                "(значок в трее) или подключитесь к сети предприятия (VPN) — агент подхватит модель сам.")
    if "not found" in text:
        return (f"в Ollama нет модели {config.CHAT_MODEL}. "
                f"Скачайте её: ollama pull {config.CHAT_MODEL}")
    return text[:300]


def _reset() -> None:
    global _messages
    _messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]


def _handle_ask(payload: dict) -> dict:
    question = (payload.get("message") or "").strip()
    if payload.get("reset"):
        _reset()
        if not question:
            return {"answer": "История разговора очищена.", "steps": []}
    if not question:
        return {"answer": "Пустой вопрос.", "steps": []}
    # Панель не разбирает команды сама: без этого «/сброс» уходил модели
    # как обычный вопрос, и история не очищалась.
    if question.lower() in ("/сброс", "/reset", "/очистить", "/заново"):
        _reset()
        print("\n[пользователь] /сброс — история очищена", flush=True)
        return {"answer": "История разговора очищена — начнём заново.", "steps": []}

    steps: list[dict] = []

    def remember_tool(name, arguments, output):
        steps.append({
            "tool": name,
            "arguments": arguments,
            "result": output[:2000],
        })

    chat.PROGRESS["text"] = ""
    _messages.append({"role": "user", "content": question})
    # в журнал — и вопрос, и ответ: без них разбор неудачного разговора
    # приходилось делать по тексту панели
    print(f"\n[пользователь] {question}", flush=True)
    answer = chat.ask(_messages, on_tool=remember_tool)
    print(f"[агент] {answer}\n", flush=True)
    warning = _bridge_warning()
    if warning:
        answer = f"⚠ {warning}\n\n{answer}"
    return {"answer": answer, "steps": steps}


def _bridge_warning() -> str | None:
    """
    Предупреждение, если мост в R-Pro не той версии, под которую написан агент.

    Говорим прямо в ответе, а не только в журнале: журнал никто не читает, а
    старый мост умеет подвесить программу (см. config.EXPECTED_BRIDGE_VERSION).
    """
    try:
        version = tools.client.health().get("bridge_version")
    except BridgeError:
        return None
    if version == config.EXPECTED_BRIDGE_VERSION:
        return None
    return (f"Мост в R-Pro устарел: версия {version}, а нужна "
            f"{config.EXPECTED_BRIDGE_VERSION}. Часть команд может работать "
            f"неправильно. Закройте R-Pro, выполните bridge\\install.ps1 и "
            f"запустите программу снова.")


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "RProAgent/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/progress"):
            # панель спрашивает, пока ждёт ответа: что агент делает сейчас
            self._send(200, {"ok": True, "busy": _lock.locked(),
                             "text": chat.PROGRESS["text"] if _lock.locked() else ""})
            return
        if self.path.startswith("/commands"):
            # подсказка команд в панели R-Pro: всплывает, когда набран «/»
            import intents
            self._send(200, {"ok": True, "commands": [
                {"name": c, "args": a, "description": d, "group": g} for c, a, d, g in intents.COMMANDS]})
            return
        if not self.path.startswith("/health"):
            self._send(404, {"ok": False, "error": "не найдено"})
            return

        bridge = "недоступен"
        try:
            health = tools.client.health()
            bridge = f"версия {health.get('bridge_version')}"
        except BridgeError as exc:
            bridge = str(exc)[:200]

        self._send(200, {
            "ok": True,
            "model": llm.model_name(),
            "model_state": _model_state,
            "model_source": llm.describe(),
            "bridge": bridge,
            "messages": len(_messages),
            "busy": _lock.locked(),
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send(400, {"ok": False, "error": "тело запроса не разобрано как JSON"})
            return

        if not self.path.startswith("/ask"):
            self._send(404, {"ok": False, "error": "не найдено"})
            return

        # Пока агент думает над одним вопросом, второй не принимаем: у модели
        # всё равно одна очередь, а перемешанная история хуже отказа.
        if not _lock.acquire(blocking=False):
            self._send(200, {"ok": False, "error": "агент занят предыдущим вопросом"})
            return

        try:
            result = _handle_ask(payload)
            self._send(200, {"ok": True, **result})
        except BridgeError as exc:
            self._send(200, {"ok": False, "error": str(exc)})
        except Exception:
            self._send(200, {"ok": False, "error": traceback.format_exc()[-1500:]})
        finally:
            _lock.release()


class AgentServer(ThreadingHTTPServer):
    # По умолчанию HTTPServer ставит SO_REUSEADDR, а на Windows он значит не
    # «переиспользовать остывший порт», как в Linux, а «пустить второй сервер
    # на занятый». Проверено: два агента спокойно слушали один порт, и
    # запросы расходились между ними как попало. Нам нужен ровно обратный
    # эффект — второй экземпляр должен получить отказ и уйти.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _watch_parent(pid: int, server: AgentServer) -> None:
    """
    Останавливает сервер, когда закрывается R-Pro.

    Плагин и сам гасит сервер при выходе из программы, но если R-Pro упадёт,
    до этого не дойдёт. Тогда агент висел бы в памяти без хозяина.
    os.kill(pid, 0) для проверки не годится: на Windows он не проверяет
    процесс, а завершает его.
    """
    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        print(f"Процесс R-Pro {pid} не найден — завершаюсь.")
        server.shutdown()
        return
    kernel32.WaitForSingleObject(handle, INFINITE)
    kernel32.CloseHandle(handle)
    print("R-Pro закрыта — завершаюсь.")
    server.shutdown()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Сервер агента для окна чата в R-Pro")
    parser.add_argument("--log", help="писать вывод в этот файл")
    parser.add_argument("--parent-pid", type=int, help="завершиться вместе с этим процессом")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.log:
        # Запуск из плагина: консоли нет, а выводить есть что — вызовы
        # инструментов печатает chat.ask. Построчная буферизация, чтобы файл
        # можно было читать, пока сервер работает.
        log = open(args.log, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    else:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass

    try:
        server = AgentServer((HOST, PORT), AgentHandler)
    except OSError as exc:
        # Порт занят — почти наверняка агент уже запущен: руками в терминале
        # или прошлым запуском R-Pro. Второй не нужен, панель поговорит с первым.
        print(f"Порт {PORT} занят ({exc}) — агент, видимо, уже запущен. Выхожу.")
        return 0

    print(f"Агент слушает http://{HOST}:{PORT}")
    print(f"  модель: {llm.model_name()} ({llm.provider()})")
    print(f"  мост:   {config.BRIDGE_URL}")

    threading.Thread(target=_warm_up, daemon=True).start()
    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid, server),
                         daemon=True).start()
        print(f"  работаю, пока жива R-Pro (процесс {args.parent_pid})")
    else:
        print("Окно чата в R-Pro обращается сюда. Остановка — Ctrl+C.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
