"""Tiny local receiver: the browser pane POSTs text (inline SVG logos) to http://localhost:8766/save?name=<file>; saved under data/board/inbox."""
import os, re, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "board", "inbox"))
class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Private-Network", "true")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_POST(self):
        q = parse_qs(urlparse(self.path).query); name = re.sub(r"[^A-Za-z0-9_.-]", "", (q.get("name") or ["blob.txt"])[0])
        n = int(self.headers.get("Content-Length") or 0); data = self.rfile.read(n)
        open(os.path.join(ROOT, name), "wb").write(data); print("saved", name, n, flush=True)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
os.makedirs(ROOT, exist_ok=True); print("inbox on 8766 ->", ROOT, flush=True)
HTTPServer(("127.0.0.1", 8766), H).serve_forever()
