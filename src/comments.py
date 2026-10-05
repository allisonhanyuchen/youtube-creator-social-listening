#!/usr/bin/env python3
"""Step 3b: pull comments (40 top + 20 newest per video) and label every one with Claude.
Labels: lang, target (what it is about), sentiment toward that target, intent. Topics are not labelled per comment: they come from topics.py.
Both stages are cached and resumable: data/comments_raw.json, data/comment_labels.json. Quota ~2 units per video."""
import json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from common import yt, claude, parse_json, load, save, QuotaError, USAGE, product

MIN_COMMENTS = 10      # videos with fewer comments than this are skipped; sentiment still needs 10 product-side comments to be judged
TARGETS = ["product", "price_value", "video_or_creator", "apple_brand", "competitor", "other"]
INTENTS = ["buy", "upgrade_wait", "skip", "switch_from_android", "none"]
SENT = ["positive", "neutral", "negative"]
lock = threading.Lock()


def pull_video(v):
    """Up to comments_per_video comments (input.json, default 60): two thirds by relevance (the top comments), the rest the newest."""
    seen, out = set(), []
    total = max(3, min(150, int(product().get("comments_per_video", 60))))
    top = -(-total * 2 // 3)
    for order, n in (("relevance", top), ("time", total - top)):
        r = yt("commentThreads", soft=True, part="snippet", videoId=v["id"], maxResults=n, order=order, textFormat="plainText")
        for i in (r or {}).get("items", []):
            s = i["snippet"]["topLevelComment"]["snippet"]
            if i["id"] in seen: continue
            seen.add(i["id"])
            out.append(dict(comment_id=i["id"], video_id=v["id"], text=s["textDisplay"].replace("\n", " ")[:400], likes=s.get("likeCount", 0),
                            published=s["publishedAt"], source=order))
    return out


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


def parse_label_lines(text):
    """Parse the compact reply  i|lang|target|sent|intent  into {index: label}. Malformed lines are skipped."""
    out = {}
    for ln in text.splitlines():
        p = ln.strip().split("|")
        if len(p) != 5 or not p[0].strip().isdigit(): continue
        out[int(p[0])] = {"l": "en" if p[1].strip() == "e" else "other", "t": T_CODE.get(p[2].strip()), "s": S_CODE.get(p[3].strip()), "in": I_CODE.get(p[4].strip(), "none")}
    return out


def label_batch(batch, model=None, thinking=None):
    """Compact line format to keep output tokens low: i|lang|target|sentiment|theme numbers|intent."""
    lines = "\n".join(f"{k}: {c['text'][:260]}" for k, c in enumerate(batch))
    pr = product()
    prompt = (f"Label YouTube comments on videos about {pr['brand']} {pr['name']} ({pr['blurb']}).\n"
              "Output exactly one line per comment, format  i|lang|target|sent|intent  and nothing else.\n"
              "lang: e (English) or o (other)\n"
              f"target (what the comment is about): P=the product, V=price/value, C=the video or creator, A={pr['brand']} the company, R=a competitor brand, O=other\n"
              "sent (toward that target): + positive, 0 neutral, - negative. Curious or anticipatory comments are 0 unless they show a clear lean.\n"
              "intent: b=buy, u=upgrade/wait, s=skip, w=switch from a competitor, n=none\n"
              "Example line:  7|e|P|-|n\n\nCOMMENTS:\n" + lines)
    for attempt in range(4):
        try:
            out = parse_label_lines(claude(prompt, 3000, model=model, thinking=thinking))
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
            labels[c["comment_id"]] = dict(lang="en", target="other", sentiment="neutral", intent="none", trivial=True, label_mode="fast", **meta(c))
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
