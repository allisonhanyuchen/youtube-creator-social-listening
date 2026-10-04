#!/usr/bin/env python3
"""Local server for the dashboard with the Ask tab live: python3 serve.py  ->  http://127.0.0.1:8770
Serves dashboard.html and POST /api/ask (same Q&A core as the Slack agent). Bound to localhost; the API key never reaches the browser."""
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from common import HERE
from ask import ask

LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.split("#")[0].split("?")[0] in ("/", "/dashboard.html"):
            self._send(200, open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/ask": return self._send(404, "{}")
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            q = str(d.get("question", ""))[:600].strip()
            if not q: return self._send(400, json.dumps({"error": "empty question"}))
            with LOCK:
                r = ask(q, d.get("history", [])[-3:])
            self._send(200, json.dumps(dict(answer=r["answer"], sql=r["sql"], cols=r["cols"], rows=r["rows"][:15]), default=str))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)[:200]}))

    def log_message(self, *a): pass


if __name__ == "__main__":
    print("Launch Pulse dashboard on http://127.0.0.1:8770  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", 8770), H).serve_forever()
