"""The demo code that protects the live parts of the hosted page (a keyword run and Refresh now).
Only whoever knows DEMO_CODE (a Vercel environment variable, never in the page or the repo) can start them; everyone else sees the recorded sample.
Limits are best effort per serverless instance; the hard stop is the spend limit on the API keys."""
import hmac, os, time

FAILS, RUNS = {}, {"d": "", "n": 0, "refresh": 0.0}
MAX_FAILS, WINDOW = 5, 600
MAX_RUNS_PER_DAY = int(os.environ.get("DEMO_RUNS_PER_DAY", 25))
REFRESH_COOLDOWN = int(os.environ.get("DEMO_REFRESH_COOLDOWN", 300))


def configured():
    return bool(os.environ.get("DEMO_CODE"))


def check_code(code, ip="-"):
    """(ok, message). A wrong code counts against the visitor; five misses lock them out for ten minutes."""
    now = time.time()
    miss = [t for t in FAILS.get(ip, []) if now - t < WINDOW]
    if len(miss) >= MAX_FAILS: return False, "Too many wrong codes. Try again in a few minutes."
    want = os.environ.get("DEMO_CODE", "")
    if want and hmac.compare_digest(str(code or "").encode(), want.encode()): return True, ""
    FAILS[ip] = miss + [now]
    return False, "That code is not right." if want else "Live runs are not configured on this host."


def allow_run():
    """Counts a keyword run (called once, at its first stage)."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if RUNS["d"] != today: RUNS.update(d=today, n=0)
    if RUNS["n"] >= MAX_RUNS_PER_DAY: return False, "Today's live run budget is used up."
    RUNS["n"] += 1
    return True, ""


def allow_refresh():
    wait = REFRESH_COOLDOWN - (time.time() - RUNS["refresh"])
    if wait > 0: return False, f"A refresh was just started. Try again in {int(wait)} seconds."
    RUNS["refresh"] = time.time()
    return True, ""


def same_site(headers):
    o = headers.get("Origin", "")
    host = headers.get("X-Forwarded-Host") or headers.get("Host", "")
    return (not o) or o.split("://", 1)[-1].split("/")[0] == host or o.startswith("http://localhost") or o.startswith("http://127.0.0.1")
