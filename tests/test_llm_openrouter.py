# -*- coding: utf-8 -*-
"""Офлайн-проверка облачного слоя на заглушке OpenRouter (без сети и ключа).
Запуск: python tests/test_llm_openrouter.py"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
os.environ.update(OPENROUTER_API_KEY="sk-or-test", RPRO_LLM="openrouter", OPENROUTER_RETRIES="1")

SEEN = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._j(200, {"data": {"label": "t"}})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        if body["model"].endswith("ultra-550b-a55b:free"):
            return self._j(429, {"error": "free-models-per-day limit"})  # суточный лимит -> сразу запасная
        msgs = body["messages"]
        if isinstance(msgs[-1]["content"], list):
            msg = {"role": "assistant", "content": "на снимке цех"}
        elif msgs[-1]["role"] == "tool":
            msg = {"role": "assistant", "content": "<think>x</think>Готово: 3 компонента."}
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                   "function": {"name": "rpro_status", "arguments": "{\"a\": 1}"}}]}
        self._j(200, {"choices": [{"message": msg}]})

srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OPENROUTER_URL"] = f"http://127.0.0.1:{srv.server_port}"

import llm
tools = [{"type": "function", "function": {"name": "rpro_status", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "что в сцене?"}]

m = llm.chat(messages, tools=tools, model="qwen3:8b")
assert m["tool_calls"][0]["function"] == {"name": "rpro_status", "arguments": {"a": 1}}, m
assert SEEN[0]["model"].endswith("ultra-550b-a55b:free") and SEEN[1]["model"].endswith("super-120b-a12b:free"), [s["model"] for s in SEEN]
assert SEEN[1]["tools"] and SEEN[1]["tool_choice"] == "auto"
messages.append(m); messages.append({"role": "tool", "name": "rpro_status", "content": "{\"n\": 3}"})
m2 = llm.chat(messages, tools=tools)
last = SEEN[-1]["messages"]
assert last[2]["tool_calls"][0]["function"]["arguments"] == "{\"a\": 1}" and last[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"n\": 3}"}, last
assert m2["content"] == "Готово: 3 компонента." and not m2.get("tool_calls"), m2
assert "OpenRouter" in llm.describe() and llm.warm_up() is None
v = llm.look("QUJD", "что на снимке?")
assert SEEN[-1]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,") and v
os.environ.pop("OPENROUTER_API_KEY"); import config; config.OPENROUTER_API_KEY = ""
try: llm.chat(messages); raise SystemExit("ожидали LLMError без ключа")
except llm.LLMError as e: assert "ключ" in str(e)
print("OK: облачный слой работает (перевод формата, повтор на запасной модели, зрение, ошибка без ключа)")
