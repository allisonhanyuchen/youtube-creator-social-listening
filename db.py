#!/usr/bin/env python3
"""Step 4: build the SQLite base tables (data/pulse.db) that every surface reads: dashboard, email, Slack, Q&A agent.
Tables: creators, content, performance, comments, comment_themes. Views: v_content, v_video_sentiment, v_theme_sentiment.
rel_lift = lift / median lift of the same format class (Short vs long) among non-official videos; outperformer = top quartile of rel_lift in its class."""
import os, sqlite3, statistics
from common import load, DATA

DB = os.path.join(DATA, "pulse.db")
PRODUCT_SIDE = "('product','price_value','apple_brand','competitor')"
SCHEMA = f"""
CREATE TABLE creators(channel_id TEXT PRIMARY KEY, name TEXT, kol_type TEXT, tier TEXT, subscribers INT, region TEXT);
CREATE TABLE content(video_id TEXT PRIMARY KEY, url TEXT, title TEXT, channel_id TEXT, format TEXT, topic TEXT, title_framing TEXT,
  published TEXT, day_since_launch INT, is_short INT, duration_s INT, promo_type TEXT, promo_sub TEXT, promo_evidence TEXT, has_affiliate INT);
CREATE TABLE performance(video_id TEXT PRIMARY KEY, views INT, likes INT, comment_count INT, eng_rate REAL, comment_rate REAL,
  baseline_n INT, baseline_views INT, lift REAL, rel_lift REAL, outperformer INT);
CREATE TABLE comments(comment_id TEXT PRIMARY KEY, video_id TEXT, text TEXT, likes INT, published TEXT, day_since_launch INT, source TEXT,
  lang TEXT, target TEXT, sentiment TEXT, intent TEXT, label_mode TEXT, trivial INT);
CREATE TABLE comment_themes(comment_id TEXT, theme TEXT);
CREATE INDEX ix_c_video ON comments(video_id); CREATE INDEX ix_t_theme ON comment_themes(theme); CREATE INDEX ix_ct_c ON comment_themes(comment_id);

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

CREATE VIEW v_theme_sentiment AS
  SELECT t.theme, c.sentiment, c.video_id, c.comment_id FROM comment_themes t JOIN comments c USING(comment_id) WHERE c.lang='en' AND c.trivial=0;
"""


def main():
    if os.path.exists(DB): os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    vids = load("videos.json")
    for c in load("creators.json"):
        con.execute("INSERT INTO creators VALUES (?,?,?,?,?,?)", (c["channel_id"], c["name"], c["kol_type"], c["tier"], c["subs"], c["region"]))
    med = {sh: statistics.median(v["lift"] for v in vids if v.get("lift") and v["promo_type"] != "official" and v["is_short"] == sh) for sh in (True, False)}
    for v in vids:
        v["rel_lift"] = v["lift"] / med[v["is_short"]] if v.get("lift") else None
    cut = {}
    for sh in (True, False):
        r = sorted(v["rel_lift"] for v in vids if v["rel_lift"] is not None and v["promo_type"] != "official" and v["is_short"] == sh)
        cut[sh] = r[int(len(r) * 0.75)]
    for v in vids:
        con.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (v["id"], v["url"], v["title"], v["channel_id"], v["format"], v["topic"], v["framing"],
                    v["published"][:10], v["day"], int(v["is_short"]), v["duration_s"], v["promo_type"], v["promo_sub"], v["promo_evidence"], int(v["has_affiliate"])))
        out = int(v["rel_lift"] >= cut[v["is_short"]]) if v["rel_lift"] is not None and v["promo_type"] != "official" else None
        con.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?,?,?,?)", (v["id"], v["views"], v["likes"], v["comments"], v["eng_rate"], v["comment_rate"],
                    v["baseline_n"], v.get("baseline_views"), v.get("lift"), round(v["rel_lift"], 3) if v["rel_lift"] is not None else None, out))
    day = {v["id"]: v["published"][:10] for v in vids}
    from datetime import date
    ev = date(2026, 9, 9)
    raw, lab = load("comments_raw.json"), load("comment_labels.json")
    for vid, cs in raw.items():
        for c in cs:
            l = lab.get(c["comment_id"])
            if not l: continue
            d = (date.fromisoformat(c["published"][:10]) - ev).days
            con.execute("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (c["comment_id"], vid, c["text"], c["likes"], c["published"][:10], d, c["source"],
                        l["lang"], l["target"], l["sentiment"], l["intent"], l["label_mode"], int(bool(l.get("trivial")))))
            for t in l["themes"]:
                con.execute("INSERT INTO comment_themes VALUES (?,?)", (c["comment_id"], t))
    con.commit()
    for t in ("creators", "content", "performance", "comments", "comment_themes"):
        print(f"{t:15} {con.execute(f'select count(*) from {t}').fetchone()[0]:>7} rows")
    print("outperformer cutoffs (rel_lift, top quartile):", {("short" if k else "long"): round(x, 2) for k, x in cut.items()})
    con.close()


if __name__ == "__main__":
    main()
