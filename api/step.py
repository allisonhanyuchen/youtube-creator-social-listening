"""POST /api/step {code, step, state} -> {state, detail, secs}: runs ONE stage of a keyword run (search, baseline, comments, label, topics, report, push).
Each stage fits in a serverless request, the browser carries the state between them, and so it can show the steps live. With the demo code a run can be any size and can push; without it this is the open quick preview: capped at 20 videos x 20 comments, never pushed, limited per visitor and per day."""
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
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4_400_000)) or b"{}")
            ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
            sid, state = str(d.get("step", "")), d.get("state") or {}
            if sid not in explore.FUNCS: return self._send(400, {"error": "unknown step"})
            public = not d.get("code")                    # no code: the open quick preview (small, never pushed); with the owner's code: any size, and it can push
            if public:
                if not gate.configured(): return self._send(503, {"error": "Live runs are not configured on this host."})
                if sid == "push": return self._send(200, {"state": state, "detail": "skipped (open previews are not pushed)", "secs": 0, "more": False, "usage": None})
                if sid != "search":
                    state = gate.verify(state)
                    if state is None: return self._send(403, {"error": "That preview state is not valid. Start again."})
            else:
                ok, why = gate.check_code(d.get("code"), ip)
                if not ok: return self._send(401, {"error": why})
            if sid == "search":
                nv, nc = explore.clamp(d.get("n_videos"), explore.DEFAULT_VIDEOS, explore.CAP_VIDEOS), explore.clamp(d.get("n_comments"), explore.DEFAULT_COMMENTS, explore.CAP_COMMENTS)
                if public: nv, nc = min(nv, gate.PUBLIC_VIDEOS), min(nc, gate.PUBLIC_COMMENTS)
                ok, why = gate.allow_public(ip, explore.estimate(nv, nc)["yt_units"]) if public else gate.allow_run(explore.estimate(nv, nc)["yt_units"])
                if not ok: return self._send(429, {"error": why})
                state = {"keyword": str(d.get("keyword", "")).strip()[:80], "n_videos": nv, "n_comments": nc}
                if len(state["keyword"]) < 2: return self._send(400, {"error": "Type a keyword."})
            state, detail, secs = explore.run_step(sid, state, budget=40)       # a serverless request has about a minute; the label step stops early and the page asks again
            if public: state = gate.sign(state)
            out = {"state": state, "detail": detail, "secs": secs, "more": bool(state.get("_more")), "usage": state.get("usage")}
            if sid == "report":
                rep = explore.assemble(state); rep["summary"] = state["summary"]; rep["steps"] = []; rep["usage"] = {}; rep["secs"] = 0
                out["report"] = rep
            self._send(200, out)
        except SystemExit as e:
            self._send(200, {"error": str(e)})
        except Exception:
            self._send(500, {"error": "That stage failed. Try again."})

    def log_message(self, *a): pass
