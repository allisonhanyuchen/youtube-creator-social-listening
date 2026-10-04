#!/usr/bin/env python3
"""Step 4: build the SQLite base tables (data/pulse.db) that every surface reads: dashboard, email, Slack, Q&A agent.
Tables: creators, content, performance, comments, topics. Views: v_content, v_video_sentiment.
Topics come from topics.py (state/topics.json + state/comment_topics.json) and are re-applied whenever the database is rebuilt.
rel_lift = lift / median lift of the same class (iPhone Duo videos vs the rest, Short vs long); outperformer = top quartile of rel_lift in its class.
Apple's own channel (format = official) is excluded from lift and outperformer. Paid/seeded labels were dropped: no sponsor in this data was Apple or a competitor, and seeding could only be inferred."""
import json, os, sqlite3, statistics
from common import load, DATA, HERE

DB = os.path.join(DATA, "pulse.db")
STATE = os.path.join(HERE, "state")
PRODUCT_SIDE = "('product','price_value','apple_brand','competitor')"
SCHEMA = f"""
CREATE TABLE creators(channel_id TEXT PRIMARY KEY, name TEXT, kol_type TEXT, tier TEXT, subscribers INT, region TEXT);
CREATE TABLE content(video_id TEXT PRIMARY KEY, url TEXT, title TEXT, channel_id TEXT, format TEXT, topic TEXT, title_framing TEXT,
  published TEXT, day_since_launch INT, is_short INT, duration_s INT);
CREATE TABLE performance(video_id TEXT PRIMARY KEY, views INT, likes INT, comment_count INT, eng_rate REAL, comment_rate REAL,
  baseline_n INT, baseline_views INT, lift REAL, rel_lift REAL, outperformer INT);
CREATE TABLE comments(comment_id TEXT PRIMARY KEY, video_id TEXT, text TEXT, likes INT, published TEXT, day_since_launch INT, source TEXT,
  lang TEXT, target TEXT, sentiment TEXT, intent TEXT, label_mode TEXT, trivial INT, topic_id TEXT);
CREATE TABLE topics(topic_id TEXT PRIMARY KEY, pool TEXT, name TEXT, summary TEXT, terms TEXT, origin TEXT, first_seen TEXT);
CREATE INDEX ix_c_video ON comments(video_id); CREATE INDEX ix_c_topic ON comments(topic_id);

CREATE VIEW v_video_sentiment AS
  SELECT video_id, COUNT(*) AS n_labelled,
         SUM(target IN {PRODUCT_SIDE}) AS n_product_side,
         AVG(CASE WHEN target IN {PRODUCT_SIDE} THEN sentiment='positive' END) AS pct_positive,
         AVG(CASE WHEN target IN {PRODUCT_SIDE} THEN sentiment='neutral' END)  AS pct_neutral,
         AVG(CASE WHEN target IN {PRODUCT_SIDE} THEN sentiment='negative' END) AS pct_negative
  FROM comments WHERE lang='en' AND trivial=0 GROUP BY video_id;

CREATE VIEW v_content AS
  SELECT c.*, cr.name AS creator, cr.kol_type, cr.tier, cr.subscribers, cr.region,
         p.views, p.likes, p.comment_count, p.eng_rate, p.comment_rate, p.baseline_views, p.lift, p.rel_lift, p.outperformer,
         s.n_product_side, s.pct_positive, s.pct_neutral, s.pct_negative
  FROM content c JOIN creators cr USING(channel_id) JOIN performance p USING(video_id) LEFT JOIN v_video_sentiment s USING(video_id);

"""


def _json(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def apply_topics(con):
    """Copy the topic table and each comment's topic from state/ into the database (safe to call again after topics.py runs)."""
    st, ct = _json(os.path.join(STATE, "topics.json"), {}), _json(os.path.join(STATE, "comment_topics.json"), {})
    con.execute("DELETE FROM topics"); con.execute("UPDATE comments SET topic_id=NULL")
    for pool, p in (st.get("pools") or {}).items():
        for t in p["topics"]:
            con.execute("INSERT INTO topics VALUES (?,?,?,?,?,?,?)", (t["id"], pool, t["name"], t.get("summary", ""), ", ".join(t.get("terms", [])), t.get("origin", ""), t.get("first_seen", "")))
    con.executemany("UPDATE comments SET topic_id=? WHERE comment_id=?", [(tid, cid) for cid, tid in ct.items() if tid])
    con.commit()


def main():
    if os.path.exists(DB): os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    vids = load("videos.json")
    for c in load("creators.json"):
        con.execute("INSERT INTO creators VALUES (?,?,?,?,?,?)", (c["channel_id"], c["name"], c["kol_type"], c["tier"], c["subs"], c["region"]))
    grp = lambda v: v["topic"] == "duo"                  # a Duo video is compared with other Duo videos
    ok = lambda v: v["format"] != "official" and v.get("lift") is not None
    groups = {}                                           # (is Duo, is Short) -> lifts; a group may be empty (no Shorts, no other topics), so build it from the data
    for v in vids:
        if ok(v): groups.setdefault((grp(v), v["is_short"]), []).append(v["lift"])
    med = {k: statistics.median(x) for k, x in groups.items()}
    for v in vids:
        v["rel_lift"] = v["lift"] / med[(grp(v), v["is_short"])] if ok(v) else None
    cut = {}
    for k in groups:
        r = sorted(v["rel_lift"] for v in vids if v["rel_lift"] is not None and (grp(v), v["is_short"]) == k)
        cut[k] = r[int(len(r) * 0.75)]
    for v in vids:
        con.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?,?,?,?,?)", (v["id"], v["url"], v["title"], v["channel_id"], v["format"], v["topic"], v["framing"],
                    v["published"][:10], v["day"], int(v["is_short"]), v["duration_s"]))
        out = int(v["rel_lift"] >= cut[(grp(v), v["is_short"])]) if v["rel_lift"] is not None else None
        con.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?,?,?,?)", (v["id"], v["views"], v["likes"], v["comments"], v["eng_rate"], v["comment_rate"],
                    v["baseline_n"], v.get("baseline_views"), v.get("lift"), round(v["rel_lift"], 3) if v["rel_lift"] is not None else None, out))
    from datetime import date
    ev = date(2026, 9, 9)
    raw, lab = load("comments_raw.json", {}), load("comment_labels.json")
    text = {c["comment_id"]: c for v in raw.values() for c in v}           # text exists only where the comment was pulled in this environment
    known = {v["id"] for v in vids}
    for cid, l in lab.items():
        t = text.get(cid, {})
        vid, pub, likes, src = l.get("v") or t.get("video_id"), l.get("p") or (t.get("published", "")[:10]), l.get("k", t.get("likes", 0)), l.get("s") or t.get("source", "")
        if not vid or not pub or vid not in known: continue
        dd = (date.fromisoformat(pub) - ev).days
        con.execute("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid, vid, t.get("text"), likes, pub, dd, src,
                    l["lang"], l["target"], l["sentiment"], l["intent"], l.get("label_mode", "fast"), int(bool(l.get("trivial"))), None))
    apply_topics(con)
    con.commit()
    for t in ("creators", "content", "performance", "comments", "topics"):
        print(f"{t:15} {con.execute(f'select count(*) from {t}').fetchone()[0]:>7} rows")
    print("outperformer cutoffs (rel_lift, top quartile):", {("duo " if k[0] else "other ") + ("short" if k[1] else "long"): round(x, 2) for k, x in cut.items()})
    con.close()


if __name__ == "__main__":
    main()
