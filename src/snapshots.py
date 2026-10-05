#!/usr/bin/env python3
"""Daily view-count snapshots, the only way to get a real trend for videos: the YouTube API returns the current count, never a history.
Appends today's views for every known video to state/view_history.json ({video_id: {date: views}}, public counts only, last 45 days kept).
build_dashboard.py turns two snapshots into 'views gained in the last 24h / 7 days'."""
import json, os
from datetime import date, timedelta
from common import HERE, load

PATH = os.path.join(HERE, "state", "view_history.json")


def main():
    hist = json.load(open(PATH)) if os.path.exists(PATH) else {}
    today = str(date.today())
    cutoff = str(date.today() - timedelta(days=45))
    vids = load("videos.json") or []
    for v in vids:
        h = hist.setdefault(v["id"], {})
        h[today] = int(v["views"])
        for d in [d for d in h if d < cutoff]: del h[d]
    json.dump(hist, open(PATH, "w"), separators=(",", ":"))
    days = sorted({d for h in hist.values() for d in h})
    print(f"view snapshots: {len(vids)} videos today, {len(days)} snapshot day(s) on file ({days[0]} to {days[-1]})")


if __name__ == "__main__":
    main()
