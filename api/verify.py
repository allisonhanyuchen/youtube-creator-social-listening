"""GET /api/verify -> {gate: true} when a demo code is configured (the page uses this to know live runs can be unlocked).
POST /api/verify {code} -> {ok}."""
import json, os, sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import demo_gate as gate  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"gate": gate.configured()})

    def do_POST(self):
        if not gate.same_site(self.headers): return self._send(403, {"ok": False, "error": "Not allowed from this site."})
        try:
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 2000)) or b"{}")
        except ValueError:
            d = {}
        ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
        ok, why = gate.check_code(d.get("code"), ip)
        self._send(200 if ok else 401, {"ok": ok, "error": why})

    def log_message(self, *a): pass
