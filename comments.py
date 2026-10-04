#!/usr/bin/env python3
"""Step 3b: pull comments (40 top + 20 newest per video) and label every one with Claude.
Labels: lang, target (what it is about), sentiment toward that target, themes (fixed taxonomy), intent.
Both stages are cached and resumable: data/comments_raw.json, data/comment_labels.json. Quota ~2 units per video."""
import json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from common import yt, claude, parse_json, load, save, QuotaError, USAGE

THEMES = {
    "hype_purchase_excitement": "excitement, anticipation, preorders, upgrade plans",
    "fold_animation_ui": "fold/unfold animation, transitions, UI polish, smoothness",
    "price_affordability": "price, cost, regional pricing, affordability",
    "android_prior_art": "Apple is late / not original because Android shipped it first",
    "android_rival_comparison": "direct comparison with or loyalty to Samsung, Xiaomi, Oppo, Pixel",
    "design_colors_form": "colours, shape, corners, size, weight, closed-state look",
    "crease_screen_quality": "inner-screen crease, finish, pixel quality, screen protectors",
    "camera_hardware": "cameras, under-display camera, aperture, image quality",
    "durability_tests": "durability, hinge life, drop/scratch/bend/water tests, teardown",
    "software_usability": "day-to-day use: ergonomics, left-handed use, keyboard, multitasking, battery, apps",
    "apple_brand_leadership": "Apple as a company: CEO, executives, trust, marketing spin",
    "creator_credibility_critique": "video or creator seen as biased, ad-like, sponsored, shilling",
}
MIN_COMMENTS = 10      # videos with fewer comments than this are skipped; sentiment still needs 10 product-side comments to be judged
TARGETS = ["product", "price_value", "video_or_creator", "apple_brand", "competitor", "other"]
INTENTS = ["buy", "upgrade_wait", "skip", "switch_from_android", "none"]
SENT = ["positive", "neutral", "negative"]
lock = threading.Lock()


def pull_video(v):
    seen, out = set(), []
    for order, n in (("relevance", 40), ("time", 20)):
        r = yt("commentThreads", soft=True, part="snippet", videoId=v["id"], maxResults=n, order=order, textFormat="plainText")
        for i in (r or {}).get("items", []):
            s = i["snippet"]["topLevelComment"]["snippet"]
            if i["id"] in seen: continue
            seen.add(i["id"])
            out.append(dict(comment_id=i["id"], video_id=v["id"], text=s["textDisplay"].replace("\n", " ")[:400], likes=s.get("likeCount", 0),
                            published=s["publishedAt"], source=order))
    return out


THEME_KEYS = list(THEMES)
T_CODE = {"P": "product", "V": "price_value", "C": "video_or_creator", "A": "apple_brand", "R": "competitor", "O": "other"}
S_CODE = {"+": "positive", "0": "neutral", "-": "negative"}
I_CODE = {"b": "buy", "u": "upgrade_wait", "s": "skip", "w": "switch_from_android", "n": "none"}
FIRST_RE = re.compile(r"^\W*(first|1st|early|who'?s here|here in 20\d\d)\b", re.I)


def meta(c):
    """Non-text fields kept with each label so the database can be rebuilt without the comment text (CI never stores text)."""
    return dict(v=c["video_id"], p=c["published"][:10], k=c["likes"], s=c["source"])


def trivial(text):
    t = re.sub(r"\d{1,2}:\d{2}", "", text)
    letters = re.findall(r"[A-Za-z]{2,}", t)
    return len(letters) == 0 or (len(letters) <= 1 and len(t) < 20) or bool(FIRST_RE.match(t))


def label_batch(batch, model=None, thinking=None):
    """Compact line format to keep output tokens low: i|lang|target|sentiment|theme numbers|intent."""
    theme_list = "; ".join(f"{k + 1}={key} ({d})" for k, (key, d) in enumerate(THEMES.items()))
    lines = "\n".join(f"{k}: {c['text'][:260]}" for k, c in enumerate(batch))
    prompt = ("Label YouTube comments on videos about Apple's Sept 2026 launch (iPhone Duo foldable, iPhone 18 Pro).\n"
              "Output exactly one line per comment, format  i|lang|target|sent|themes|intent  and nothing else.\n"
              "lang: e (English) or o (other)\n"
              "target (what the comment is about): P=product, V=price/value, C=the video or creator, A=Apple the company, R=rival brand, O=other\n"
              "sent (toward that target): + positive, 0 neutral, - negative. Curious or anticipatory comments are 0 unless they show a clear lean.\n"
              f"themes: comma-separated numbers, or - for none. Only for targets P, V, A, R. For target C use 12 only if it calls the video biased/ad-like/shilling, else -.\n{theme_list}\n"
              "intent: b=buy, u=upgrade/wait, s=skip, w=switch from Android, n=none\n"
              "Example line:  7|e|P|-|3,10|n\n\nCOMMENTS:\n" + lines)
    for attempt in range(4):
        try:
            out, text = {}, claude(prompt, 3000, model=model, thinking=thinking)
            for ln in text.splitlines():
                p = ln.strip().split("|")
                if len(p) != 6 or not p[0].strip().isdigit(): continue
                th = [THEME_KEYS[int(x) - 1] for x in p[4].replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= len(THEME_KEYS)]
                out[int(p[0])] = {"l": "en" if p[1].strip() == "e" else "other", "t": T_CODE.get(p[2].strip()), "s": S_CODE.get(p[3].strip()),
                                  "th": th, "in": I_CODE.get(p[5].strip(), "none")}
            if len(out) >= len(batch) * 0.9:
                return [out.get(k) for k in range(len(batch))]
        except SystemExit:
            pass
        time.sleep(5 * (attempt + 1))
    return [None] * len(batch)


def main():
    vids = [v for v in load("videos.json") if v["comments"] >= MIN_COMMENTS]
    raw = load("comments_raw.json", {})
    refresh = "--refresh" in sys.argv        # weekly run: re-pull every eligible video, label only comment ids not seen before
    todo = vids if refresh else [v for v in vids if v["id"] not in raw]
    print(f"{len(vids)} videos eligible, {len(todo)} to pull")
    def pull(v):
        try:
            res = pull_video(v)
        except QuotaError:
            return None
        with lock:
            merged = {c["comment_id"]: c for c in raw.get(v["id"], [])}
            merged.update({c["comment_id"]: c for c in res})
            raw[v["id"]] = list(merged.values())
        return v["id"]
    with ThreadPoolExecutor(6) as ex:
        done = list(ex.map(pull, todo))
    save("comments_raw.json", raw)
    if any(d is None for d in done): print("STOP: YouTube quota exhausted; re-run after reset to continue pulling")
    comments = [c for v in raw.values() for c in v]
    print(f"{len(comments)} comments pulled")

    labels = load("comment_labels.json", {})
    for l in labels.values(): l.setdefault("label_mode", "full")      # labels written before the fast mode existed
    for c in comments:                                   # emoji-only, timestamps, "first": no signal, label locally
        if c["comment_id"] not in labels and trivial(c["text"]):
            labels[c["comment_id"]] = dict(lang="en", target="other", sentiment="neutral", themes=[], intent="none", trivial=True, label_mode="fast", **meta(c))
    todo = [c for c in comments if c["comment_id"] not in labels]
    batches = [todo[i:i + 50] for i in range(0, len(todo), 50)]
    cap = int(sys.argv[sys.argv.index("--max-batches") + 1]) if "--max-batches" in sys.argv else None
    if cap: batches = batches[:cap]
    print(f"labelling {sum(len(b) for b in batches)} comments in {len(batches)} batches (trivial skipped: {sum(1 for l in labels.values() if l.get('trivial'))})")
    count = [0]
    def run(batch):
        res = label_batch(batch, thinking={"type": "between_tools"})      # thinking off: ~4x fewer output tokens
        with lock:
            for c, r in zip(batch, res):
                if r and r.get("t") in TARGETS and r.get("s") in SENT:
                    labels[c["comment_id"]] = dict(lang=r.get("l", "en"), target=r["t"], sentiment=r["s"],
                                                   themes=[t for t in r.get("th", []) if t in THEMES],
                                                   intent=r.get("in") if r.get("in") in INTENTS else "none", label_mode="fast", **meta(c))
            count[0] += 1
            if count[0] % 20 == 0:
                save("comment_labels.json", labels); print(f"  {count[0]}/{len(batches)} batches, {len(labels)} labelled", flush=True)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(run, batches))
    save("comment_labels.json", labels)
    print(f"done: {len(labels)}/{len(comments)} labelled | tokens this run: in {USAGE['in']:,} out {USAGE['out']:,} over {USAGE['calls']} calls")


if __name__ == "__main__":
    main()
