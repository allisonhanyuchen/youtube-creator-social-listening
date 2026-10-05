#!/usr/bin/env python3
"""Local server for the dashboard with everything live: python3 serve.py  ->  http://127.0.0.1:8770
  /                      dashboard.html
  POST /api/ask          Q&A (same core as the Slack agent)
  POST /api/explore      keyword report; streams progress events (server-sent events), ends with the report
  POST /api/explore/send send the last keyword report to your Slack channel and inbox
  POST /api/refresh      run the scheduled pipeline now (daily pass, with the email and Slack push); streams the steps
Bound to localhost; your API keys never reach the browser. The public page has none of these: its input and Refresh button are disabled."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from common import HERE
from ask import ask
import explore

LOCK, BUSY, LAST = threading.Lock(), threading.Lock(), {}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _stream_start(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store"); self.end_headers()

    def _event(self, obj):
        self.wfile.write(("data: " + json.dumps(obj, default=str) + "\n\n").encode()); self.wfile.flush()

    def do_GET(self):
        p = self.path.split("#")[0].split("?")[0]
        if p in ("/", "/dashboard.html"):
            self._send(200, open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
        elif p == "/api/ping":
            self._send(200, json.dumps({"local": True}))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/ask":
                q = str(d.get("question", ""))[:600].strip()
                if not q: return self._send(400, json.dumps({"error": "empty question"}))
                with LOCK:
                    r = ask(q, d.get("history", [])[-3:], str(d.get("context", ""))[:400])
                return self._send(200, json.dumps(dict(answer=r["answer"], sql=r["sql"], cols=r["cols"], rows=r["rows"][:15]), default=str))
            if self.path == "/api/explore": return self._explore(str(d.get("keyword", "")).strip()[:80], bool(d.get("push")))
            if self.path == "/api/explore/send":
                if not LAST.get("report"): return self._send(400, json.dumps({"error": "run a keyword first"}))
                return self._send(200, json.dumps({"sent": explore.deliver(LAST["report"])}))
            if self.path == "/api/refresh": return self._refresh()
            self._send(404, "{}")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try: self._send(500, json.dumps({"error": str(e)[:200]}))
            except Exception: pass

    def _explore(self, kw, push=False):
        if len(kw) < 2: return self._send(400, json.dumps({"error": "type a keyword"}))
        if not BUSY.acquire(blocking=False): return self._send(409, json.dumps({"error": "another run is in progress"}))
        try:
            self._stream_start()
            try:
                rep = explore.build(kw, self._event, push)
                LAST["report"] = explore.clean(rep)
                self._event(dict(done=True, report=LAST["report"]))
            except SystemExit as e:
                self._event(dict(error=str(e)))
        finally:
            BUSY.release()

    def _refresh(self):
        if not BUSY.acquire(blocking=False): return self._send(409, json.dumps({"error": "another run is in progress"}))
        try:
            self._stream_start()
            p = subprocess.Popen([sys.executable, "-u", "run_weekly.py", "--daily"], cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                line = line.strip()
                if line.startswith("[start] "): self._event(dict(step=line[8:], status="start"))
                elif line.startswith("[ok] ") or line.startswith("[FAILED] "):
                    ok = line.startswith("[ok]"); body = line.split("] ", 1)[1]
                    name, _, rest = body.partition(" (")
                    self._event(dict(step=name, status="done" if ok else "failed", detail=rest.split(") ", 1)[-1] if rest else "", secs=rest.split("s)")[0] if rest else ""))
            p.wait()
            subprocess.run([sys.executable, "build_dashboard.py"], cwd=HERE, capture_output=True)          # the local dashboard (with quotes) is rebuilt too
            self._event(dict(done=True, ok=p.returncode == 0))
        finally:
            BUSY.release()

    def log_message(self, *a): pass


if __name__ == "__main__":
    print("Launch Pulse dashboard on http://127.0.0.1:8770  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", 8770), H).serve_forever()
