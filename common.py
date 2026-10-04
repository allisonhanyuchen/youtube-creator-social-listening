"""Shared helpers: keys, YouTube Data API v3 calls, Claude calls. Standard library only."""
import json, os, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ENV_FILE = os.path.expanduser("~/.creator-scout.env")   # outside the repo; in CI the same names come from env vars
YT_API = "https://www.googleapis.com/youtube/v3/"
MODEL = "claude-sonnet-5-5"
try:
    os.makedirs(DATA, exist_ok=True)
except OSError:                                  # read-only host (serverless): nothing is written there
    pass
USAGE = {"calls": 0, "in": 0, "out": 0}      # token tally for cost checks


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
    return json.load(open(os.path.join(HERE, "product.json"), encoding="utf-8"))


def scope_sql(alias="v"):
    """SQL for 'videos about this product': the topic label from product.json, excluding the brand's own channel."""
    return f"{alias}.topic='{product()['topic']}' and {alias}.format!='official'"
