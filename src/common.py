"""Shared helpers: keys, YouTube Data API v3 calls, Claude calls. Standard library only."""
import json, os, time, urllib.parse, urllib.request

SRC = os.path.dirname(os.path.abspath(__file__))        # the code lives in src/
HERE = os.path.dirname(SRC)                              # the repository root: product.json, data/, state/, docs/, api/
DATA = os.path.join(HERE, "data")
ENV_FILE = os.path.expanduser("~/.creator-scout.env")   # outside the repo; in CI the same names come from env vars
YT_API = "https://www.googleapis.com/youtube/v3/"
MODEL = "claude-sonnet-5-5"
try:
    os.makedirs(DATA, exist_ok=True)
except OSError:                                  # read-only host (serverless): nothing is written there
    pass
USAGE = {"calls": 0, "in": 0, "out": 0}      # token tally for cost checks
YT = {"calls": 0, "units": 0}               # YouTube quota units used by this process (a search costs 100, a list call 1)


def secret(name, required=True):
    if os.environ.get(name):
        return os.environ[name]
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.startswith(name + "="):
                return line.strip().split("=", 1)[1]
    if required:
        raise SystemExit(f"{name} not found (env var or {ENV_FILE})")


class QuotaError(SystemExit):
    pass


def yt(endpoint, soft=False, **params):
    """YouTube call. soft=True returns None on 403/404 (comments disabled, private video) instead of exiting."""
    params["key"] = secret("YOUTUBE_API_KEY")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(YT_API + endpoint + "?" + urllib.parse.urlencode(params), timeout=30) as r:
                YT["calls"] += 1; YT["units"] += 100 if endpoint == "search" else 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if "quotaExceeded" in body or ("uota" in body and "xceeded" in body):
                raise QuotaError(f"YouTube quota exhausted on {endpoint} (resets at midnight Pacific)")
            if soft and e.code in (403, 404):
                return None
            if e.code >= 500 and attempt < 3:
                time.sleep(2 * (attempt + 1)); continue
            raise SystemExit(f"YouTube API error on {endpoint}: {e.code} {body}")
        except (OSError, TimeoutError) as e:            # socket timeouts and connection resets: retry with backoff
            if attempt == 3: raise SystemExit(f"YouTube request failed on {endpoint}: {e}")
            time.sleep(2 * (attempt + 1))


def claude(prompt, max_tokens=4000, model=None, thinking=None):
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", method="POST",
        data=json.dumps({"model": model or MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}], **({"thinking": thinking} if thinking else {})}).encode(),
        headers={"x-api-key": secret("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(3):
        try:
            return _claude_once(req)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise SystemExit(f"Claude API error {e.code}: {e.read().decode()[:300]}")
        except (OSError, TimeoutError):
            if attempt == 2: raise SystemExit("Claude request failed (network)")
            time.sleep(5 * (attempt + 1))


def _claude_once(req):
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    USAGE["calls"] += 1; USAGE["in"] += d.get("usage", {}).get("input_tokens", 0); USAGE["out"] += d.get("usage", {}).get("output_tokens", 0)
    return "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")


def parse_json(text):
    return json.loads(text[text.index("{"): text.rindex("}") + 1], strict=False)


def load(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(name, obj):
    json.dump(obj, open(os.path.join(DATA, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def product():
    """What the pipeline is about (product.json at the repo root). Prompts and labels read it, so another launch needs a new file, not new code."""
    p = json.load(open(os.path.join(HERE, "product.json"), encoding="utf-8"))
    p.setdefault("topic", "main")                                                     # the label that marks videos about THIS product
    p.setdefault("blurb", f"{p['name']}, launched {p['launch']}")
    p.setdefault("topics", {p["topic"]: p["name"], "other": "another product or not about the product"})      # labels classify.py may give a video
    p.setdefault("competitors", {})
    return p


def pricing():
    """USD per million tokens, used for cost estimates only. Defaults to a Sonnet-class list price; set "pricing" in product.json to match your plan."""
    return product().get("pricing") or {"input_per_m": 3.0, "output_per_m": 15.0}


def usd(tokens_in, tokens_out):
    p = pricing()
    return tokens_in / 1e6 * p["input_per_m"] + tokens_out / 1e6 * p["output_per_m"]


def _log_usage():
    """When a script ends, append what it used to data/usage.jsonl; run_weekly.py reads it to show tokens, quota units and cost per run."""
    if not (USAGE["calls"] or YT["units"]): return
    try:
        with open(os.path.join(DATA, "usage.jsonl"), "a") as f:
            f.write(json.dumps(dict(step=os.environ.get("PULSE_STEP", ""), claude_in=USAGE["in"], claude_out=USAGE["out"], calls=USAGE["calls"], yt_units=YT["units"])) + "\n")
    except OSError:
        pass


import atexit
atexit.register(_log_usage)


def title():
    """Used in the email, Slack and page titles."""
    return f"{product()['name']} on YouTube"


def scope_sql(alias="v"):
    """SQL for 'videos about this product': the topic label from product.json, excluding the brand's own channel."""
    return f"{alias}.topic='{product()['topic']}' and {alias}.format!='official'"
