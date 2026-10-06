"""The demo code that protects the live parts of the hosted page (a keyword run and Refresh now).
Only whoever knows DEMO_CODE (a Vercel environment variable, never in the page or the repo) can start them; everyone else sees the recorded sample.
Limits are best effort per serverless instance; the hard stop is the spend limit on the API keys."""
import hashlib, hmac, json, os, time

FAILS, RUNS = {}, {"d": "", "n": 0, "units": 0, "refresh": 0.0}
MAX_FAILS, WINDOW = 5, 600
MAX_RUNS_PER_DAY = int(os.environ.get("DEMO_RUNS_PER_DAY", 25))
MAX_UNITS_PER_DAY = int(os.environ.get("DEMO_UNITS_PER_DAY", 3000))       # YouTube quota units the live runs may spend a day (the free quota is 10,000)
REFRESH_COOLDOWN = int(os.environ.get("DEMO_REFRESH_COOLDOWN", 300))
# the open quick preview: small, never pushed, and limited per visitor and per day
PUBLIC = {"d": "", "n": 0, "units": 0, "ip": {}}
PUBLIC_PER_DAY = int(os.environ.get("DEMO_PUBLIC_PER_DAY", 12))
PUBLIC_UNITS_PER_DAY = int(os.environ.get("DEMO_PUBLIC_UNITS_PER_DAY", 2000))
PUBLIC_PER_IP = int(os.environ.get("DEMO_PUBLIC_PER_IP", 2))
PUBLIC_VIDEOS, PUBLIC_COMMENTS = 20, 20


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


def allow_run(units=0):
    """Counts a keyword run (called once, at its first stage) against the day's run count and YouTube quota budget."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if RUNS["d"] != today: RUNS.update(d=today, n=0, units=0)
    if RUNS["n"] >= MAX_RUNS_PER_DAY: return False, "Today's live run budget is used up."
    if RUNS["units"] + units > MAX_UNITS_PER_DAY: return False, f"This run needs about {units:,} YouTube quota units and today's live budget has {max(0, MAX_UNITS_PER_DAY - RUNS['units']):,} left. Try fewer videos."
    RUNS["n"] += 1; RUNS["units"] += units
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


def allow_public(ip, units):
    """Counts one open quick preview against the visitor's and the day's allowance."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if PUBLIC["d"] != today: PUBLIC.update(d=today, n=0, units=0, ip={})
    if PUBLIC["ip"].get(ip, 0) >= PUBLIC_PER_IP: return False, f"You have used today's {PUBLIC_PER_IP} free previews. Try again tomorrow, or deploy your own copy with your own keys."
    if PUBLIC["n"] >= PUBLIC_PER_DAY or PUBLIC["units"] + units > PUBLIC_UNITS_PER_DAY: return False, "Today's free previews are used up. Try again tomorrow, or deploy your own copy with your own keys."
    PUBLIC["n"] += 1; PUBLIC["units"] += units; PUBLIC["ip"][ip] = PUBLIC["ip"].get(ip, 0) + 1
    return True, ""


def _key():
    return hashlib.sha256((os.environ.get("DEMO_CODE", "") + "|open-preview").encode()).digest()


def _canon(state):
    return json.dumps(json.loads(json.dumps(state, default=str)), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(state):
    """The browser carries a preview's state between stages; the server signs each state it returns so a visitor cannot hand in a bigger one."""
    st = {k: v for k, v in state.items() if k != "_sig"}
    st["_sig"] = hmac.new(_key(), _canon(st), hashlib.sha256).hexdigest()
    return st


def verify(state):
    """The state without its signature if the signature is ours, else None."""
    if not isinstance(state, dict) or not configured(): return None
    st = {k: v for k, v in state.items() if k != "_sig"}
    return st if hmac.compare_digest(str(state.get("_sig", "")), hmac.new(_key(), _canon(st), hashlib.sha256).hexdigest()) else None
