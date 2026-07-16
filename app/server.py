#!/usr/bin/env python3
"""
Gold Monitor App Server
- Serves the app (index.html)
- API: GET /api/messages -> messages.json
- API: POST /api/messages -> append message
- API: GET /api/latest -> ../latest.json
- Serves static files from app/ and parent dir
"""
import json
import os
import sys
import io
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
MESSAGES_FILE = SCRIPT_DIR / "messages.json"
PARENT_DIR = SCRIPT_DIR.parent
BEIJING_TZ = timezone(timedelta(hours=8))
PORT = 8088


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def log_message(self, format, *args):
        ts = datetime.now(BEIJING_TZ).strftime("%H:%M:%S")
        sys.stdout.write(f"[{ts}] {args[0]}\n")
        sys.stdout.flush()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        # API: /api/messages
        if path == "/api/messages":
            self.serve_api_messages()
            return

        # API: /api/latest
        if path == "/api/latest":
            self.serve_json_file(PARENT_DIR / "latest.json")
            return

        # API: /api/history
        if path == "/api/history":
            self.serve_json_file(PARENT_DIR / "history.json")
            return

        # API: /api/status
        if path == "/api/status":
            self.serve_status()
            return

        # Redirect / to index.html
        if path == "/":
            self.path = "/index.html"
            super().do_GET()
            return

        # For chart.umd.min.js, look in parent dir
        if path == "/chart.umd.min.js":
            self.serve_file(PARENT_DIR / "chart.umd.min.js", "application/javascript")
            return

        # Default: static file
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/messages":
            self.handle_message_post()
            return

        self.send_response(405)
        self.end_headers()
        self.wfile.write(b'{"error":"Method not allowed"}')

    def serve_api_messages(self):
        if MESSAGES_FILE.exists():
            try:
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                data = []
        else:
            data = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def serve_json_file(self, filepath):
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                pass
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error":"Not found"}')

    def serve_file(self, filepath, content_type):
        if filepath.exists():
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

    def serve_status(self):
        msg_count = 0
        if MESSAGES_FILE.exists():
            try:
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    msg_count = len(json.load(f))
            except:
                pass
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "running",
            "message_count": msg_count,
            "time": datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False).encode("utf-8"))

    def handle_message_post(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"Invalid JSON"}')
            return

        # Add timestamp
        msg["time"] = msg.get("time", datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"))

        # Load existing
        messages = []
        if MESSAGES_FILE.exists():
            try:
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    messages = json.load(f)
            except:
                messages = []

        messages.append(msg)

        # Keep only last 500 messages
        if len(messages) > 500:
            messages = messages[-500:]

        with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "count": len(messages)}, ensure_ascii=False).encode("utf-8"))


def main():
    server = HTTPServer(("0.0.0.0", PORT), AppHandler)
    print(f"   Gold Monitor App Server")
    print(f"   http://localhost:{PORT}")
    print(f"   API: http://localhost:{PORT}/api/messages")
    print(f"   API: http://localhost:{PORT}/api/latest")
    print(f"   Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Server stopped")
        server.server_close()


if __name__ == "__main__":
    main()
