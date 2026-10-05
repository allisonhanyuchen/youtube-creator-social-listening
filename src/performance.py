#!/usr/bin/env python3
"""Step 2: channel baselines and lift.
Baseline = the channel's own median views on comparable (same format: Short / long) pre-launch videos, so a Short is never
compared with a long video. lift = views / baseline. Raw per-channel pulls are cached in data/baselines.json (resumable).
Quota ~4 units per channel.
"""
import statistics
from common import yt, load, save, QuotaError
from collect import iso_seconds, EVENT

PRE_CUTOFF = "2026-09-01T00:00:00Z"     # baseline videos must predate the launch week
MIN_BASE = 5


def pull(channel_id):
    ids, tok = [], None
    for _ in range(2):
        p = dict(part="contentDetails", playlistId="UU" + channel_id[2:], maxResults=50)
        if tok: p["pageToken"] = tok
        r = yt("playlistItems", soft=True, **p)
        if not r: break
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok: break
    out, titles = [], []
    for i in range(0, len(ids), 50):
        for v in (yt("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])) or {}).get("items", []):
            st = v.get("statistics", {})
            if v["snippet"]["publishedAt"] < PRE_CUTOFF and len(titles) < 5: titles.append(v["snippet"]["title"][:60])
            out.append(dict(p=v["snippet"]["publishedAt"], v=int(st.get("viewCount", 0) or 0),
                            s=iso_seconds(v["contentDetails"].get("duration")) <= 180, ip="iphone" in v["snippet"]["title"].lower()))   # compact: only what the baseline needs
    return out, titles


def main():
    vids = load("videos.json")
    cache = load("baselines.json", {})
    for ch, items in cache.items():          # convert the older verbose cache format once
        cache[ch] = [x if "p" in x else dict(p=x["pub"], v=x["views"], s=x["short"], ip="iphone" in x["title"].lower()) for x in items]
    chans = sorted({v["channel_id"] for v in vids})
    new_titles = {}
    for n, ch in enumerate(chans, 1):
        if ch in cache: continue
        try:
            cache[ch], new_titles[ch] = pull(ch)
        except QuotaError as e:
            print("STOP:", e); break
        if n % 25 == 0:
            save("baselines.json", cache); print(f"  {n}/{len(chans)} channels")
    save("baselines.json", cache)

    # channel country (declared) for region
    meta = load("channels_meta.json", {})
    need = [c for c in chans if c not in meta]
    for i in range(0, len(need), 50):
        for c in yt("channels", part="snippet", id=",".join(need[i:i + 50])).get("items", []):
            meta[c["id"]] = {"country": c["snippet"].get("country", ""), "about": c["snippet"].get("description", "")[:200], "titles": new_titles.get(c["id"], [])}
    for c in need: meta.setdefault(c, {"country": "", "about": "", "titles": new_titles.get(c, [])})
    save("channels_meta.json", meta)

    for v in vids:
        pre = [x for x in cache.get(v["channel_id"], []) if x["p"] < PRE_CUTOFF and x["s"] == v["is_short"] and not x["ip"]][:30]
        v["baseline_n"] = len(pre)
        v["baseline_views"] = int(statistics.median(x["v"] for x in pre)) if len(pre) >= MIN_BASE else None
        v["lift"] = round(v["views"] / v["baseline_views"], 2) if v["baseline_views"] else None
        v["eng_rate"] = round((v["likes"] + v["comments"]) / v["views"], 4) if v["views"] else 0
        v["comment_rate"] = round(v["comments"] / v["views"], 5) if v["views"] else 0
        v["country"] = meta.get(v["channel_id"], {}).get("country", "")
    save("videos.json", vids)
    ok = [v for v in vids if v["lift"] is not None]
    print(f"baseline available for {len(ok)}/{len(vids)} videos | channels pulled {len(cache)}/{len(chans)}")


if __name__ == "__main__":
    main()
