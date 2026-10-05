#!/usr/bin/env python3
"""Step 1: collect YouTube videos for the product in input.json: its search queries, from input.json "since" on.
Search results are cached per query in data/search_cache.json so re-runs cost nothing. Output: data/videos_raw.json.
Quota: ~100 units per new search query, ~1 per 50 videos/channels.
"""
import re, sys
from datetime import datetime, timedelta, timezone
from common import yt, load, save, QuotaError, parse_json, product

MIN_VIEWS = 2000
P = product()
EVENT, SINCE = P["launch"], P.get("since", "2026-08-01T00:00:00Z")      # videos from SINCE on (include pre-launch rumour videos)
QUERIES = P.get("keywords") or P["queries"]                                 # what to search for, edit them in input.json
TOP_VIDEOS = max(1, min(200, int(P.get("top_videos", 50))))                  # results taken per keyword (the API gives 50 a page)
TOPIC_RE = re.compile(P.get("topic_regex", re.escape(P["name"])), re.I)   # a video must match this to count as on-topic

def iso_seconds(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    h, mi, s = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + s


def looks_english(v):
    sn = v["snippet"]
    lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
    if lang:
        return lang.startswith("en")
    text = sn.get("title", "") + sn.get("channelTitle", "")
    nonlatin = sum(1 for ch in text if ord(ch) > 0x24F and ch.isalpha())
    return nonlatin / max(len(text), 1) < 0.1


def main():
    incremental = "--incremental" in sys.argv     # weekly run: find videos posted since the last run, refresh stats for every known video
    cache = load("search_cache.json", {})
    known = {v["id"]: v for v in load("videos_raw.json", [])}
    ids = set(load("probe_videos.json", {})) | set(known)
    if incremental and known:
        newest = max(v["published"] for v in known.values())[:10]
        since = (datetime.fromisoformat(newest) - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z")
        for q in QUERIES:
            try:
                res = yt("search", part="id", q=q, type="video", maxResults=50, order="date", publishedAfter=since, relevanceLanguage="en", regionCode="US")
            except QuotaError as e:
                print("STOP:", e); break
            ids |= {i["id"]["videoId"] for i in res.get("items", [])}
        print(f"incremental: searching since {since[:10]}, {len(ids) - len(known)} ids not yet kept")
    else:
        for q in QUERIES:
            if q not in cache:
                try:
                    found, token = [], None
                    while len(found) < TOP_VIDEOS:                                  # top N videos for this keyword, a page of 50 at a time
                        res = yt("search", part="id", q=q, type="video", maxResults=min(50, TOP_VIDEOS - len(found)), order="relevance",
                                 publishedAfter=SINCE, relevanceLanguage="en", regionCode="US", **({"pageToken": token} if token else {}))
                        found += [i["id"]["videoId"] for i in res.get("items", [])]
                        token = res.get("nextPageToken")
                        if not token: break
                except QuotaError as e:
                    print("STOP:", e); break
                cache[q] = found
                save("search_cache.json", cache)
                print(f"  searched: {q} ({len(cache[q])})")
            ids |= set(cache[q])
    ids = sorted(ids)
    vids = {}
    for i in range(0, len(ids), 50):
        for v in yt("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).get("items", []):
            vids[v["id"]] = v
    ch_ids = sorted({v["snippet"]["channelId"] for v in vids.values()})
    chans = {}
    for i in range(0, len(ch_ids), 50):
        for c in yt("channels", part="statistics", id=",".join(ch_ids[i:i + 50])).get("items", []):
            chans[c["id"]] = c
    rows, dropped = [], {"not_english": 0, "off_topic": 0, "low_views": 0}
    for vid, v in vids.items():
        sn, st = v["snippet"], v.get("statistics", {})
        views = int(st.get("viewCount", 0) or 0)
        if not looks_english(v): dropped["not_english"] += 1; continue
        if not TOPIC_RE.search(sn["title"] + " " + sn.get("description", "")[:300]): dropped["off_topic"] += 1; continue
        if views < MIN_VIEWS: dropped["low_views"] += 1; continue
        dur = iso_seconds(v["contentDetails"].get("duration"))
        rows.append(dict(id=vid, url=f"https://www.youtube.com/watch?v={vid}", title=sn["title"], channel_id=sn["channelId"],
                         channel=sn["channelTitle"], published=sn["publishedAt"], day=(datetime.fromisoformat(sn["publishedAt"][:10]) - datetime.fromisoformat(EVENT)).days,
                         duration_s=dur, is_short=dur <= 180, views=views, likes=int(st.get("likeCount", 0) or 0),
                         comments=int(st.get("commentCount", 0) or 0),
                         subs=int(chans.get(sn["channelId"], {}).get("statistics", {}).get("subscriberCount", 0) or 0),
                         desc=sn.get("description", "")[:300].replace("\n", " ")))
    rows.sort(key=lambda r: -r["views"])
    save("videos_raw.json", rows)
    print(f"{len(vids)} fetched | dropped {dropped} | kept {len(rows)} | channels {len({r['channel_id'] for r in rows})}")
    print(f"shorts {sum(r['is_short'] for r in rows)} | views {sum(r['views'] for r in rows):,} | comments {sum(r['comments'] for r in rows):,}")


if __name__ == "__main__":
    main()
