#!/usr/bin/env python3
"""Fast-mode labels over-assign hype_purchase_excitement (precision ~56% in the validation sample).
Re-judge only those comments with thinking on, and drop the theme where it does not hold."""
import json, threading
from concurrent.futures import ThreadPoolExecutor
from common import claude, parse_json, load, save, USAGE
from comments import THEMES

lock = threading.Lock()


def judge(batch, raw):
    items = [{"id": n, "t": raw[i]["text"][:300]} for n, i in enumerate(batch)]
    for _ in range(3):
        try:
            out = parse_json(claude(
                "Each item is a YouTube comment on a video about Apple's Sept 2026 launch. Mark yes ONLY if the commenter themselves expresses excitement, "
                "anticipation or concrete purchase/upgrade intent about the product (" + THEMES["hype_purchase_excitement"] + "). "
                "Mark no for: reactions to the creator or video, jokes or memes, complaints, price shock, general praise of a feature without wanting it, "
                "and neutral remarks. Return JSON only: {\"r\": [{\"id\": int, \"yes\": true|false}]}\n\n" + json.dumps(items, ensure_ascii=False), 3000))
            return {r["id"]: bool(r.get("yes")) for r in out["r"]}
        except (SystemExit, ValueError, KeyError):
            continue
    return {}


def main():
    raw = {c["comment_id"]: c for v in load("comments_raw.json").values() for c in v}
    lab = load("comment_labels.json")
    cand = [i for i, l in lab.items() if l.get("label_mode") == "fast" and "hype_purchase_excitement" in l["themes"] and not l.get("hype_checked") and i in raw]
    print(f"{len(cand)} fast-mode hype labels to recheck")
    batches = [cand[k:k + 50] for k in range(0, len(cand), 50)]
    stats = {"kept": 0, "dropped": 0, "unjudged": 0}
    def run(batch):
        res = judge(batch, raw)
        with lock:
            for n, i in enumerate(batch):
                if n not in res: stats["unjudged"] += 1; continue
                lab[i]["hype_checked"] = True
                if res[n]: stats["kept"] += 1
                else:
                    lab[i]["themes"] = [t for t in lab[i]["themes"] if t != "hype_purchase_excitement"]; stats["dropped"] += 1
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))
    save("comment_labels.json", lab)
    print(stats, f"| tokens in {USAGE['in']:,} out {USAGE['out']:,}")


if __name__ == "__main__":
    main()
