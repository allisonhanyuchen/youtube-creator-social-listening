"""Slim, text-free state that the scheduled run commits to the repo so each run can work incrementally.
Everything here is public metadata or our own labels. Comment text is never written to state/."""
import json, os, shutil
from common import DATA, HERE, load

STATE = os.path.join(HERE, "state")
FILES = ["videos.json", "creators.json", "channels_meta.json", "baselines.json", "comment_labels.json", "device_check.json"]


def restore():
    """Fresh CI checkout has no data/: seed it from state/."""
    for f in FILES:
        src, dst = os.path.join(STATE, f), os.path.join(DATA, f)
        if os.path.exists(src) and not os.path.exists(dst): shutil.copy(src, dst)
    if not os.path.exists(os.path.join(DATA, "videos_raw.json")) and os.path.exists(os.path.join(DATA, "videos.json")):
        # videos_raw is the collect step's memory of known videos; videos.json carries the same raw fields
        json.dump(load("videos.json"), open(os.path.join(DATA, "videos_raw.json"), "w"), ensure_ascii=False)


def save():
    os.makedirs(STATE, exist_ok=True)
    raw = {c["comment_id"]: c for v in load("comments_raw.json", {}).values() for c in v}
    for f in FILES:
        obj = load(f)
        if obj is None: continue
        if f == "comment_labels.json":                      # make sure every label carries its non-text meta
            for cid, l in obj.items():
                c = raw.get(cid)
                if c and "v" not in l: l.update(v=c["video_id"], p=c["published"][:10], k=c["likes"], s=c["source"])
        if f == "videos.json":                              # descriptions are re-fetched from the API on every run, no need to publish them
            obj = [dict(v, desc="") for v in obj]
        json.dump(obj, open(os.path.join(STATE, f), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("state saved:", {f: os.path.getsize(os.path.join(STATE, f)) // 1024 for f in FILES if os.path.exists(os.path.join(STATE, f))}, "KB")
