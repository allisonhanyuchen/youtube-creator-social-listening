"""The app's input: keywords, how many top videos per keyword, how many comments per video. Saved in input.json, which the daily run reads, so what you type in the page
is what every later refresh repeats. New keywords mean a new product: the file is rewritten around them and the next run starts from scratch."""
import re
from datetime import date, timedelta

GENERIC = {"review", "reviews", "hands", "hand", "on", "worth", "it", "vs", "versus", "problems", "problem", "the", "a", "an", "best", "new", "unboxing", "first", "impressions", "and", "for", "of", "in"}
CAP_VIDEOS, CAP_COMMENTS = 200, 150


def split_keywords(text):
    """'iPhone Duo review, iPhone Duo vs Pixel' (or one per line) -> a clean list, at most 12."""
    items = text if isinstance(text, list) else re.split(r"[\n,;]+", str(text or ""))
    out = []
    for k in items:
        k = re.sub(r"\s+", " ", str(k)).strip()[:80]
        if len(k) >= 2 and k.lower() not in {x.lower() for x in out}: out.append(k)
    return out[:12]


def name_of(keyword):
    words = keyword.split()
    while len(words) > 1 and words[-1].lower() in GENERIC: words.pop()
    return " ".join(words)


def regex_of(keywords):
    """A video counts as on topic when its title or description mentions any distinctive word from the keywords."""
    words = {w.lower() for k in keywords for w in re.findall(r"[A-Za-z0-9]{3,}", k) if w.lower() not in GENERIC}
    return "|".join(sorted(re.escape(w) for w in words)) or re.escape(keywords[0])


def clamp(v, default, cap):
    try: v = int(v)
    except (TypeError, ValueError): v = default
    return max(1, min(cap, v))


def merge_input(current, keywords, top_videos, comments_per_video, today=None):
    """Returns (new input dict, fresh). `fresh` is true when the keywords describe a different product than the saved one, so the run must start from an empty state.
    Same product: only the sizes (and the keyword list) change and everything else, such as brand, competitors and topic labels, is kept."""
    kws = split_keywords(keywords)
    if not kws: raise ValueError("Type at least one keyword.")
    today = today or date.today()
    top, per = clamp(top_videos, 50, CAP_VIDEOS), clamp(comments_per_video, 60, CAP_COMMENTS)
    same = bool(current.get("name")) and name_of(kws[0]).lower() == str(current["name"]).lower()
    if same:
        new = dict(current, keywords=kws, top_videos=top, comments_per_video=per)
        new.pop("queries", None)
        return new, False
    name = name_of(kws[0])
    launch = today - timedelta(days=30)
    new = dict(keywords=kws, top_videos=top, comments_per_video=per, since=(launch - timedelta(days=45)).isoformat() + "T00:00:00Z",
               name=name, brand="", launch=launch.isoformat(), blurb=f"{name}, as searched on YouTube", topic="main", topic_regex=regex_of(kws), competitors={})
    for keep in ("pricing", "demo", "demo_video"):                                  # settings of the deployment, not of the product
        if keep in current: new[keep] = current[keep]
    return new, True
