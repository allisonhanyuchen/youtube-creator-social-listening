"""POST /api/refresh {code} -> {run_id, url}: starts the real refresh-and-push workflow on GitHub Actions (the same one the daily schedule runs).
The page then follows the run's stages live through GitHub's public API. Needs the demo code and a GITHUB_TOKEN (fine-grained, Actions: read and write on this repo)."""
import json, os, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import demo_gate as gate  # noqa: E402

REPO = os.environ.get("GITHUB_REPO", "allisonhanyuchen/youtube-creator-social-listening")


def gh(path, body=None):
    req = urllib.request.Request("https://api.github.com" + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                 headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json", "User-Agent": "launch-pulse"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        if not gate.same_site(self.headers): return self._send(403, {"error": "Not allowed from this site."})
        try:
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 2000)) or b"{}")
            ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
            ok, why = gate.check_code(d.get("code"), ip)
            if not ok: return self._send(401, {"error": why})
            if not os.environ.get("GITHUB_TOKEN"): return self._send(503, {"error": "GITHUB_TOKEN is not set on this host."})
            ok, why = gate.allow_refresh()
            if not ok: return self._send(429, {"error": why})
            t0 = time.time()
            gh(f"/repos/{REPO}/actions/workflows/refresh.yml/dispatches", {"ref": "main", "inputs": {"send": "true", "mode": "daily"}})
            run = None
            for _ in range(8):                                  # the new run shows up a moment after the dispatch
                time.sleep(1.5)
                for r in gh(f"/repos/{REPO}/actions/runs?event=workflow_dispatch&per_page=5").get("workflow_runs", []):
                    if r["created_at"] >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 - 5)): run = r; break
                if run: break
            self._send(200, {"run_id": run["id"] if run else None, "url": run["html_url"] if run else None})
        except Exception:
            self._send(500, {"error": "Could not start the refresh."})

    def log_message(self, *a): pass
