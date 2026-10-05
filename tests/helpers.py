import contextlib, io, json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import common, db
ORIG_DATA, ORIG_DB, ORIG_STATE = common.DATA, db.DB, db.STATE


def make_data(tmp, lifts, comments, topic="duo", fmt="first_impressions", official=()):
    """Write fixture JSON files that db.main() reads. `comments` maps video index -> (n_product_side, n_positive, n_negative)."""
    vids, labels = [], {}
    for i, lift in enumerate(lifts):
        vid = f"v{i:02d}"
        vids.append(dict(id=vid, url=f"https://youtu.be/{vid}", title=f"Video {i}", channel_id=f"c{i}", format="official" if i in official else fmt, topic=topic, framing="neutral",
                         published="2026-09-12T00:00:00Z", day=3, is_short=False, duration_s=600, views=1000 * (i + 1), likes=10, comments=40, eng_rate=0.01, comment_rate=0.001,
                         baseline_n=30, baseline_views=1000, lift=lift))
        n, pos, neg = comments.get(i, (0, 0, 0))
        for k in range(n):
            labels[f"{vid}-{k}"] = dict(lang="en", target="product", sentiment="positive" if k < pos else "negative" if k < pos + neg else "neutral",
                                        themes=[], intent="none", label_mode="fast", v=vid, p="2026-09-13", k=1, s="relevance")
    creators = [dict(channel_id=f"c{i}", name=f"Creator {i}", kol_type="pro_reviewer", subs=1000, tier="nano <50k", region="US") for i in range(len(lifts))]
    for name, obj in (("videos.json", vids), ("creators.json", creators), ("comment_labels.json", labels), ("comments_raw.json", {})):
        json.dump(obj, open(os.path.join(tmp, name), "w"))


def build(tmp, *a, **kw):
    """Point common/db at the temp folder, build the database, return an open connection."""
    make_data(tmp, *a, **kw)
    common.DATA = tmp
    db.DB = os.path.join(tmp, "pulse.db")
    db.STATE = os.path.join(tmp, "state")
    with contextlib.redirect_stdout(io.StringIO()):
        db.main()
    con = sqlite3.connect(db.DB)
    con.row_factory = sqlite3.Row
    return con
