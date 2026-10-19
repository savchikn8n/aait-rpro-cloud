# -*- coding: utf-8 -*-
"""
Локальный приёмник транскриптов: python receiver.py

Слушает 127.0.0.1:8799 (только своя машина). Принимает POST с JSON
{id, title, seconds, segments:[[время, текст], ...]} от скрипта grab.js,
который выполняется на странице YouTube в браузере, и кладёт каждый ролик
в transcripts/<id>.json. GET /grab.js отдаёт сам скрипт, чтобы вызов из
браузера был коротким.

Порт 8765 занят мостом R-Pro — не менять на него.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "transcripts"
PORT = 8799


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.split("?")[0] != "/grab.js":
            self.send_response(404)
            self.end_headers()
            return
        body = (HERE / "grab.js").read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n).decode("utf-8"))
        vid = re.sub(r"[^\w-]", "", data["id"])
        OUT.mkdir(exist_ok=True)
        (OUT / f"{vid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    print(f"приёмник на http://127.0.0.1:{PORT}, файлы в {OUT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
