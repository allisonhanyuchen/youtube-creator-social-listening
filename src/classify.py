#!/usr/bin/env python3
"""Step 1b: Claude labels every collected video with content format, topic and framing.
Output: data/videos.json (videos_raw + labels). Labels are cached by video id, so re-runs only classify new videos."""
import json
from common import claude, parse_json, load, save, product

P = product()

FORMATS = {
    "official": f"{P['brand']}'s own channel",
    "keynote_recap": "event recap / reaction / everything announced",
    "first_impressions": "hands-on or first impressions right after launch",
    "full_review": "in-depth review after real usage",
    "comparison": "vs a competing product" + (f" ({', '.join(P['competitors'])})" if P["competitors"] else "") + " or an older model",
    "upgrade_advice": "should you buy / worth upgrading / don't buy",
    "durability_test": "crease, bend, drop, scratch or teardown tests",
    "explainer_tips": "features explained, tips, how it works, camera tests",
    "rumor_leak": "rumors, leaks, predictions (mostly pre-launch)",
    "meme_short": "meme, reaction or skit, usually a Short",
    "other": "none of the above",
}
TOPICS = P["topics"]                      # key -> what it means; the key in P["topic"] marks videos about the product itself
BATCH = 30


def main():
    raw = load("videos_raw.json")
    done = {v["id"]: v for v in load("videos.json", [])}
    for v in raw:                       # refresh raw fields (e.g. new collab flag), keep labels
        if v["id"] in done: done[v["id"]] = {**done[v["id"]], **v}
    todo = [v for v in raw if v["id"] not in done]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        payload = [{"id": v["id"], "title": v["title"], "channel": v["channel"], "short": v["is_short"], "desc": v["desc"][:160]} for v in batch]
        out = parse_json(claude(
            f"Label YouTube videos about {P['brand']} {P['name']} ({P['blurb']}). Use ONLY these values.\n"
            f"format: {json.dumps(FORMATS)}\ntopic: {json.dumps(TOPICS)}\n"
            "framing: how the TITLE frames the product: positive | neutral | negative | clickbait_alarm (e.g. 'DON'T BUY', 'is it dead?').\n"
            "Return JSON only: {\"results\": [{\"id\": str, \"format\": str, \"topic\": str, \"framing\": str}]}\n\n"
            + json.dumps(payload, ensure_ascii=False), 6000))
        by = {r["id"]: r for r in out["results"]}
        for v in batch:
            lab = by.get(v["id"], {})
            done[v["id"]] = {**v, "format": lab.get("format", "other") if lab.get("format") in FORMATS else "other",
                             "topic": lab.get("topic", "other") if lab.get("topic") in TOPICS else "other",
                             "framing": lab.get("framing", "neutral")}
        print(f"  classified {min(i + BATCH, len(todo))}/{len(todo)}")
    vids = sorted(done.values(), key=lambda v: -v["views"])
    save("videos.json", vids)
    from collections import Counter
    for key in ("format", "topic", "framing"):
        print(key, dict(Counter(v[key] for v in vids).most_common()))
    main_t = P["topic"]
    print(f"\nformat x views (M), {main_t} vs the rest:")
    for f in FORMATS:
        a = round(sum(v["views"] for v in vids if v["format"] == f and v["topic"] == main_t) / 1e6, 1)
        b = round(sum(v["views"] for v in vids if v["format"] == f and v["topic"] != main_t) / 1e6, 1)
        print(f"  {f:18} n={sum(1 for v in vids if v['format'] == f):3}  {main_t} {a:>6}M  rest {b:>6}M")


if __name__ == "__main__":
    import json
    main()
