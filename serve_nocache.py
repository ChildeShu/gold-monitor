#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启一个强制 no-cache 的本地静态服务器"""
import http.server
import socketserver
import os
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
ROOT = Path(__file__).parent.resolve()

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()
    def log_message(self, fmt, *args):
        pass  # 静默

os.chdir(ROOT)
with socketserver.TCPServer(("", PORT), NoCacheHandler) as httpd:
    print(f"serving {ROOT} at http://localhost:{PORT}", flush=True)
    httpd.serve_forever()
