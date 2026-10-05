"""POST /api/step {code, step, state} -> {state, detail, secs}: runs ONE stage of a keyword run (search, baseline, comments, label, topics, report, push).
Each stage fits in a serverless request, the browser carries the state between them, and so it can show the steps live. Needs the demo code."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import demo_gate as gate  # noqa: E402
import explore  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        if not gate.same_site(self.headers): return self._send(403, {"error": "Not allowed from this site."})
        try:
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 3_000_000)) or b"{}")
            ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
            ok, why = gate.check_code(d.get("code"), ip)
            if not ok: return self._send(401, {"error": why})
            sid, state = str(d.get("step", "")), d.get("state") or {}
            if sid not in explore.FUNCS: return self._send(400, {"error": "unknown step"})
            if sid == "search":
                ok, why = gate.allow_run()
                if not ok: return self._send(429, {"error": why})
                state = {"keyword": str(d.get("keyword", "")).strip()[:80]}
                if len(state["keyword"]) < 2: return self._send(400, {"error": "Type a keyword."})
            state, detail, secs = explore.run_step(sid, state)
            out = {"state": state, "detail": detail, "secs": secs}
            if sid == "report":
                rep = explore.assemble(state); rep["summary"] = state["summary"]; rep["steps"] = []; rep["usage"] = {}; rep["secs"] = 0
                out["report"] = rep
            self._send(200, out)
        except SystemExit as e:
            self._send(200, {"error": str(e)})
        except Exception:
            self._send(500, {"error": "That stage failed. Try again."})

    def log_message(self, *a): pass
