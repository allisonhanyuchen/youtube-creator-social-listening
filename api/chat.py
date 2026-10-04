"""Vercel serverless function: live Q&A for the hosted dashboard.
POST /api/chat {question, history, context} -> {answer, sql, cols, rows}.  GET /api/chat -> {live: true} (the page uses this to decide between live and recorded answers).
Same core as the Slack agent (ask.py), but over api/public.db, which has no comment text. The Anthropic key lives only in the host's environment.
Guards: same-site requests only, short questions, per-visitor and global caps (best effort, per instance), a kill switch (CHAT_DISABLED=1).
The hard spend limit is the one set on the Anthropic key itself."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PULSE_DB", os.path.join(ROOT, "api", "public.db"))
os.environ["PULSE_PUBLIC"] = "1"
import ask as core                                         # noqa: E402

PER_VISITOR_HOUR, GLOBAL_DAY = int(os.environ.get("CHAT_PER_HOUR", 8)), int(os.environ.get("CHAT_PER_DAY", 300))
HITS, DAY = {}, {"d": "", "n": 0}


def allowed(ip):
    now, today = time.time(), time.strftime("%Y-%m-%d", time.gmtime())
    if DAY["d"] != today: DAY.update(d=today, n=0)
    if DAY["n"] >= GLOBAL_DAY: return False, "Today's live question budget is used up. The recorded examples still work; try again tomorrow."
    hits = [t for t in HITS.get(ip, []) if now - t < 3600]
    if len(hits) >= PER_VISITOR_HOUR: return False, f"Limit of {PER_VISITOR_HOUR} live questions per hour reached. Try again later or pick a recorded example."
    HITS[ip] = hits + [now]; DAY["n"] += 1
    return True, ""


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _same_site(self):
        o = self.headers.get("Origin", "")
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
        return (not o) or o.split("://", 1)[-1].split("/")[0] == host or o.startswith("http://localhost") or o.startswith("http://127.0.0.1")

    def do_GET(self):
        self._send(200, {"live": not os.environ.get("CHAT_DISABLED")})

    def do_POST(self):
        if os.environ.get("CHAT_DISABLED"): return self._send(503, {"error": "Live chat is switched off."})
        if not self._same_site(): return self._send(403, {"error": "Not allowed from this site."})
        try:
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20000)))
            q = str(d.get("question", "")).strip()[:300]
            if len(q) < 3: return self._send(400, {"error": "Ask a question."})
            ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
            ok, why = allowed(ip)
            if not ok: return self._send(429, {"error": why})
            r = core.ask(q, (d.get("history") or [])[-2:], str(d.get("context", ""))[:300], no_quotes=True)
            self._send(200, dict(answer=r["answer"], sql=r["sql"], cols=r["cols"], rows=r["rows"][:15]))
        except Exception as e:
            self._send(500, {"error": "Something went wrong answering that. Try rephrasing."})

    def log_message(self, *a): pass
