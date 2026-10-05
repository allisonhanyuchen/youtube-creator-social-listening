"""POST /api/run {code, keywords, top_videos, comments_per_video}: the page's Run button.
Saves the input to input.json in the repository (so every later daily refresh repeats it) and starts the real pipeline on GitHub Actions: collect, analyse, report, push.
New keywords for a different product start from an empty state. The page follows the run's four stages through GitHub's public API.
Needs the demo code and a GITHUB_TOKEN with Contents and Actions read and write on this repository."""
import base64, json, os, sys, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import demo_gate as gate  # noqa: E402
import inputs  # noqa: E402

REPO = os.environ.get("GITHUB_REPO", "allisonhanyuchen/youtube-creator-social-listening")


def gh(path, body=None, method=None):
    req = urllib.request.Request("https://api.github.com" + path, data=json.dumps(body).encode() if body is not None else None, method=method or ("POST" if body is not None else "GET"),
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
            d = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4000)) or b"{}")
            ip = (self.headers.get("X-Forwarded-For", "") or self.client_address[0]).split(",")[0].strip()
            ok, why = gate.check_code(d.get("code"), ip)
            if not ok: return self._send(401, {"error": why})
            if not os.environ.get("GITHUB_TOKEN"): return self._send(503, {"error": "GITHUB_TOKEN is not set on this host."})
            ok, why = gate.allow_refresh()
            if not ok: return self._send(429, {"error": why})
            cur = gh(f"/repos/{REPO}/contents/input.json")
            current = json.loads(base64.b64decode(cur["content"]))
            new, fresh = inputs.merge_input(current, d.get("keywords"), d.get("top_videos"), d.get("comments_per_video"))
            gh(f"/repos/{REPO}/contents/input.json", {"message": "Input from the page: " + ", ".join(new["keywords"])[:80], "sha": cur["sha"], "branch": "main",
                                                      "content": base64.b64encode((json.dumps(new, indent=1, ensure_ascii=False) + "\n").encode()).decode()}, "PUT")
            t0 = time.time()
            gh(f"/repos/{REPO}/actions/workflows/refresh.yml/dispatches", {"ref": "main", "inputs": {"send": "true", "mode": "weekly", "fresh": "true" if fresh else "false"}})
            run = None
            for _ in range(8):
                time.sleep(1.5)
                for r in gh(f"/repos/{REPO}/actions/runs?event=workflow_dispatch&per_page=5").get("workflow_runs", []):
                    if r["created_at"] >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 - 5)): run = r; break
                if run: break
            self._send(200, {"run_id": run["id"] if run else None, "url": run["html_url"] if run else None, "fresh": fresh, "input": {k: new[k] for k in ("keywords", "top_videos", "comments_per_video")}})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except urllib.error.HTTPError as e:
            gate.RUNS["refresh"] = 0
            try: msg = json.loads(e.read()).get("message", "")
            except Exception: msg = ""
            hint = {401: "The GitHub token is invalid or expired.", 403: "The GitHub token lacks permission: it needs Actions and Contents read and write on this repository.", 404: "The GitHub token cannot see this repository or input.json (check the repository access and Contents permission)."}.get(e.code, "")
            self._send(502, {"error": f"GitHub refused the request ({e.code}). {hint} {msg}".strip()})
        except Exception as e:
            gate.RUNS["refresh"] = 0
            self._send(500, {"error": "Could not start the run: " + type(e).__name__})

    def log_message(self, *a): pass
