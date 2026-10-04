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
    out = []
    for i in range(0, len(ids), 50):
        for v in (yt("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])) or {}).get("items", []):
            st = v.get("statistics", {})
            out.append(dict(id=v["id"], title=v["snippet"]["title"], pub=v["snippet"]["publishedAt"],
                            views=int(st.get("viewCount", 0) or 0), likes=int(st.get("likeCount", 0) or 0),
                            comments=int(st.get("commentCount", 0) or 0),
                            short=iso_seconds(v["contentDetails"].get("duration")) <= 180))
    return out


def main():
    vids = load("videos.json")
    cache = load("baselines.json", {})
    chans = sorted({v["channel_id"] for v in vids})
    for n, ch in enumerate(chans, 1):
        if ch in cache: continue
        try:
            cache[ch] = pull(ch)
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
            meta[c["id"]] = {"country": c["snippet"].get("country", ""), "about": c["snippet"].get("description", "")[:200]}
    for c in need: meta.setdefault(c, {"country": "", "about": ""})
    save("channels_meta.json", meta)

    for v in vids:
        pre = [x for x in cache.get(v["channel_id"], []) if x["pub"] < PRE_CUTOFF and x["short"] == v["is_short"]
               and "iphone" not in x["title"].lower()][:30]
        v["baseline_n"] = len(pre)
        v["baseline_views"] = int(statistics.median(x["views"] for x in pre)) if len(pre) >= MIN_BASE else None
        v["lift"] = round(v["views"] / v["baseline_views"], 2) if v["baseline_views"] else None
        v["eng_rate"] = round((v["likes"] + v["comments"]) / v["views"], 4) if v["views"] else 0
        v["comment_rate"] = round(v["comments"] / v["views"], 5) if v["views"] else 0
        v["country"] = meta.get(v["channel_id"], {}).get("country", "")
    save("videos.json", vids)
    ok = [v for v in vids if v["lift"] is not None]
    print(f"baseline available for {len(ok)}/{len(vids)} videos | channels pulled {len(cache)}/{len(chans)}")


if __name__ == "__main__":
    main()
