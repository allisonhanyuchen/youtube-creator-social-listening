#!/usr/bin/env python3
"""Step 1: collect YouTube videos about the Apple launch (event: 2026-09-09, iPhone Duo + iPhone 18 Pro).
Search results are cached per query in data/search_cache.json so re-runs cost nothing. Output: data/videos_raw.json.
Quota: ~100 units per new search query, ~1 per 50 videos/channels.
"""
import re, sys
from datetime import datetime, timedelta, timezone
from common import yt, load, save, QuotaError, parse_json

EVENT = "2026-09-09"
SINCE = "2026-08-01T00:00:00Z"        # include pre-launch rumor videos
MIN_VIEWS = 2000
QUERIES = ["iPhone Duo review", "iPhone Duo hands on", "iPhone Duo worth it", "iPhone Duo problems",
           "iPhone 18 Pro review", "iPhone 18 Pro worth upgrading", "iPhone Duo vs Galaxy Z Fold",
           "iPhone Duo vs Pixel Fold", "Apple event reaction iPhone Duo"]
TOPIC_RE = re.compile(r"iphone|\bduo\b|apple", re.I)
SPONSOR_RE = re.compile(r"\b(sponsored|sponsor(ed)? by|paid partnership|paid promotion|in partnership with|#ad\b|#sponsored|brought to you by)", re.I)
GIFTED_RE = re.compile(r"(apple (sent|provided|loaned)|(sent|provided|loaned) (me|us|by apple)|review unit|thanks to apple|courtesy of apple)", re.I)
AFFIL_RE = re.compile(r"(amzn\.to|geni\.us|bhpho\.to|affiliate|commission|use code|discount code)", re.I)


def collab_type(v):
    d = v["snippet"].get("description", "")
    if v.get("paidProductPlacementDetails", {}).get("hasPaidProductPlacement"): return "paid_flag"
    if SPONSOR_RE.search(d): return "sponsored_text"
    if GIFTED_RE.search(d): return "apple_provided_unit"
    if AFFIL_RE.search(d): return "affiliate"
    return "organic"


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
    cache = load("search_cache.json", {})
    ids = set(load("probe_videos.json", {}))
    for q in QUERIES:
        if q not in cache:
            try:
                res = yt("search", part="id", q=q, type="video", maxResults=50, order="relevance",
                         publishedAfter=SINCE, relevanceLanguage="en", regionCode="US")
            except QuotaError as e:
                print("STOP:", e); break
            cache[q] = [i["id"]["videoId"] for i in res.get("items", [])]
            save("search_cache.json", cache)
            print(f"  searched: {q} ({len(cache[q])})")
        ids |= set(cache[q])
    ids = sorted(ids)
    vids = {}
    for i in range(0, len(ids), 50):
        for v in yt("videos", part="snippet,statistics,contentDetails,paidProductPlacementDetails", id=",".join(ids[i:i + 50])).get("items", []):
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
                         duration_s=dur, is_short=dur <= 180, collab=collab_type(v), views=views, likes=int(st.get("likeCount", 0) or 0),
                         comments=int(st.get("commentCount", 0) or 0),
                         subs=int(chans.get(sn["channelId"], {}).get("statistics", {}).get("subscriberCount", 0) or 0),
                         desc=sn.get("description", "")[:300].replace("\n", " ")))
    rows.sort(key=lambda r: -r["views"])
    save("videos_raw.json", rows)
    print(f"{len(vids)} fetched | dropped {dropped} | kept {len(rows)} | channels {len({r['channel_id'] for r in rows})}")
    from collections import Counter
    print("collab types:", dict(Counter(r["collab"] for r in rows)))
    print(f"shorts {sum(r['is_short'] for r in rows)} | views {sum(r['views'] for r in rows):,} | comments {sum(r['comments'] for r in rows):,}")


if __name__ == "__main__":
    main()
