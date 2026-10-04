#!/usr/bin/env python3
"""Recover recall for creator_credibility_critique on fast-mode labels.
Keyword prefilter -> Sonnet with thinking on judges only those candidates. Cheap and targeted."""
import json, re
from common import claude, parse_json, load, save, USAGE

HINT = re.compile(r"\b(ads?|advert\w*|sponsor\w*|paid|shill\w*|glazer|glazing|bias\w*|fanboy\w*|propaganda|bribe\w*|bought|commercial|promo\w*|"
                  r"pay(ing)? you|apple (fan|stan)|sell ?out|infomercial|marketing|astroturf\w*|is this an ad)\b", re.I)


def main():
    raw = {c["comment_id"]: c for v in load("comments_raw.json").values() for c in v}
    lab = load("comment_labels.json")
    cand = [i for i, l in lab.items() if l.get("label_mode") == "fast" and "creator_credibility_critique" not in l["themes"]
            and not l.get("cred_checked") and HINT.search(raw[i]["text"])]
    print(f"{len(cand)} fast-mode candidates matched the keyword prefilter")
    added = 0
    for k in range(0, len(cand), 40):
        batch = cand[k:k + 40]
        items = [{"id": n, "t": raw[i]["text"][:300]} for n, i in enumerate(batch)]
        out = parse_json(claude(
            "Each item is a YouTube comment on a video about Apple's Sept 2026 launch. Mark yes ONLY if the comment accuses the video or creator "
            "of being biased, ad-like, sponsored, paid, a shill or an Apple fanboy/glazer. Mark no for comments about Apple's own ads, "
            "praise, jokes, or mentions of buying a phone. Return JSON only: {\"r\": [{\"id\": int, \"yes\": true|false}]}\n\n" + json.dumps(items, ensure_ascii=False), 3000))
        yes = {r["id"] for r in out["r"] if r.get("yes")}
        for n, i in enumerate(batch):
            lab[i]["cred_checked"] = True
            if n in yes:
                lab[i]["themes"] = sorted(set(lab[i]["themes"]) | {"creator_credibility_critique"}); added += 1
                if lab[i]["target"] == "other": lab[i]["target"] = "video_or_creator"
    save("comment_labels.json", lab)
    print(f"added creator_credibility_critique to {added} comments | tokens in {USAGE['in']:,} out {USAGE['out']:,}")


if __name__ == "__main__":
    main()
