#!/usr/bin/env python3
"""Step 2b: creator table. Claude assigns a KOL type from the channel's name, about text and recent pre-launch titles;
size tier comes from subscribers; region is the channel-declared country (blank = not declared). Output: data/creators.json, fields copied onto videos."""
import json
from common import claude, parse_json, load, save, product

KOL = {"pro_reviewer": "professional tech reviewer: broad consumer-tech reviews, testing and benchmarks (MKBHD, Mrwhosetheboss type)",
       "apple_focused": f"creator or outlet whose core subject is {product()['brand']} products and ecosystem",
       "lifestyle_vlogger": "lifestyle, vlog, photography, productivity or daily-life creator who covers gadgets as part of their life",
       "tech_news_media": "news outlet or publication that reports and recaps (The Verge, CNET, MacRumors type)",
       "commentary_analyst": "opinion, analysis or business-of-tech commentary",
       "entertainment_shorts": "entertainer, meme, reaction or Shorts-first channel where tech is incidental",
       "other": "none of the above"}
# Content domain only. Reach (tier) and market (region) are separate fields, so no 'regional' type.


def tier(s):
    return "nano <50k" if s < 5e4 else "micro 50-250k" if s < 2.5e5 else "mid 250k-1M" if s < 1e6 else "macro 1-5M" if s < 5e6 else "mega 5M+"


def main():
    vids, base, meta = load("videos.json"), load("baselines.json"), load("channels_meta.json")
    ch = {}
    for v in vids:
        ch.setdefault(v["channel_id"], dict(channel_id=v["channel_id"], name=v["channel"], subs=v["subs"], official=v["format"] == "official"))
    prev = {c["channel_id"]: c for c in load("creators.json", []) if c.get("kol_type") in KOL}   # delete data/creators.json to reclassify after a taxonomy change
    todo = [c for k, c in ch.items() if k not in prev]
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        payload = [{"id": c["channel_id"], "name": c["name"], "subs": c["subs"], "country": meta[c["channel_id"]]["country"],
                    "about": meta[c["channel_id"]]["about"][:140],
                    "titles": meta[c["channel_id"]].get("titles", [])} for c in batch]
        out = parse_json(claude("Classify each YouTube channel into exactly one kol_type from: " + json.dumps(KOL) +
                                '\nReturn JSON only: {"results": [{"id": str, "kol_type": str}]}\n\n' + json.dumps(payload, ensure_ascii=False), 5000))
        by = {r["id"]: r["kol_type"] for r in out["results"]}
        for c in batch:
            c["kol_type"] = by.get(c["channel_id"], "other") if by.get(c["channel_id"]) in KOL else "other"
            prev[c["channel_id"]] = c
    for k, c in ch.items():
        c = prev[k]; c.update(name=ch[k]["name"], subs=ch[k]["subs"], tier=tier(ch[k]["subs"]), region=meta[k]["country"] or "undeclared")
        if ch[k]["official"]: c["kol_type"] = "official_brand"
    save("creators.json", list(prev.values()))
    for v in vids:
        c = prev[v["channel_id"]]; v["kol_type"], v["tier"], v["region"] = c["kol_type"], c["tier"], c["region"]
    save("videos.json", vids)
    from collections import Counter
    print("kol_type", dict(Counter(c["kol_type"] for c in prev.values()).most_common()))
    print("tier", dict(Counter(c["tier"] for c in prev.values()).most_common()))
    print("region", dict(Counter(c["region"] for c in prev.values()).most_common(8)))


if __name__ == "__main__":
    main()
