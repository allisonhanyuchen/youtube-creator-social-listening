#!/usr/bin/env python3
"""Build dashboard.html (local, with a few hundred quoted comments) or docs/index.html (--public, no comment text) from data/pulse.db.
One self-contained page, no CDN; all filtering and drill-down happen in the browser.
Embedded: per-video rows + per-video comment aggregates (sentiment, topics, competitor mentions, intent), the topic table, paraphrased topic notes."""
import json, os, re, sqlite3, sys
from collections import defaultdict
from datetime import date, timedelta
from common import DATA, HERE, product, scope_sql

PRODUCT_SIDE = {"product", "price_value", "apple_brand", "competitor"}
SENT = {"positive": 0, "neutral": 1, "negative": 2}


def read_json(name, default):
    p = os.path.join(HERE, "state", name)
    return json.load(open(p)) if os.path.exists(p) else default


def attach_summaries(data):
    """Paraphrased topic notes (state/summaries.json) go into both builds."""
    data["summaries"] = read_json("summaries.json", {"topics": {}})
    return data


def attach_public_text(data, corp):
    """Public demo only: recorded Q&A. Everything published as prose is re-checked against the comment corpus before it goes in."""
    import public_safety as safe
    data["examples"] = read_json("examples.json", [])
    strings = [b for t in data["summaries"].get("topics", {}).values() for bl in t.values() for b in bl] + [e["a"] for e in data["examples"]] \
        + [t["summary"] for t in data.get("topics", [])] + [t["name"] for t in data.get("topics", [])]
    bad = [s[:60] for s in strings if safe.overlap(s, corp)]
    if bad: raise SystemExit(f"public text overlaps comment wording, not publishing: {bad[:3]}")
    return data


def scrub_public(data):
    """Public demo: no comment text at all (quotes, per-video top comments). Aggregates, titles and stats stay."""
    data["quotes"] = []
    for r in data["videos"]:
        r["a"]["tc"] = []
    data["public"] = True
    return data


def main():
    public = "--public" in sys.argv
    pr = product()
    con = sqlite3.connect(os.path.join(DATA, "pulse.db")); con.row_factory = sqlite3.Row
    vids = [dict(r) for r in con.execute(f"select * from v_content v where {scope_sql()} order by views desc")]
    vidx = {v["video_id"]: i for i, v in enumerate(vids)}
    topics = [dict(r) for r in con.execute("select * from topics order by pool, topic_id")]
    tidx = {t["topic_id"]: i for i, t in enumerate(topics)}
    agg = [dict(n=0, ps=[0, 0, 0], tp={}, br={}, it={}, tc=[]) for _ in vids]
    brand_re = {b: re.compile(p, re.I) for b, p in pr["competitors"].items()}
    quotes_pool = defaultdict(list)
    tstats = {t["topic_id"]: dict(n=0, c=[0, 0, 0], recent=0, prior=0) for t in topics}
    comments = [dict(r) for r in con.execute(f"select c.*, v.topic as vtopic from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and {scope_sql()}")]
    last = max((c["published"] for c in comments), default=str(date.today()))
    recent_from, prior_from = str(date.fromisoformat(last) - timedelta(days=7)), str(date.fromisoformat(last) - timedelta(days=14))
    for c in comments:
        a = agg[vidx[c["video_id"]]]; s = SENT[c["sentiment"]]
        a["n"] += 1
        if c["target"] in PRODUCT_SIDE: a["ps"][s] += 1
        if c["intent"] != "none": a["it"][c["intent"]] = a["it"].get(c["intent"], 0) + 1
        text = c["text"] or ""
        for b, rx in brand_re.items():
            if text and rx.search(text): a["br"].setdefault(b, [0, 0, 0])[s] += 1
        tid = c["topic_id"]
        if tid in tidx:
            ts = tstats[tid]; ts["n"] += 1; ts["c"][s] += 1
            ts["recent"] += c["published"] > recent_from; ts["prior"] += prior_from < c["published"] <= recent_from
            if topics[tidx[tid]]["pool"] == "product": a["tp"].setdefault(str(tidx[tid]), [0, 0, 0])[s] += 1
            if 25 <= len(text) <= 240 and s in (0, 2): quotes_pool[(tidx[tid], s)].append((c["likes"], vidx[c["video_id"]], text))
        if 25 <= len(text) <= 240: a["tc"].append((c["likes"], text, s, []))
    quotes = [[vi, t, s, text, likes] for (t, s), lst in quotes_pool.items() for likes, vi, text in sorted(lst, reverse=True)[:12]]
    for a in agg:
        a["tc"] = [[t, s, ths, l] for l, t, s, ths in sorted(a["tc"], reverse=True)[:2]]
    # share of product comments in the last 7 days overall, to say whether a topic is gaining
    prod_ids = [t["topic_id"] for t in topics if t["pool"] == "product"]
    tot_recent = sum(tstats[i]["recent"] for i in prod_ids); tot_n = sum(tstats[i]["n"] for i in prod_ids)
    for t in topics:
        ts = tstats[t["topic_id"]]
        t.update(n=ts["n"], c=ts["c"], recent=ts["recent"], prior=ts["prior"],
                 trend=round((ts["recent"] / ts["n"]) / (tot_recent / tot_n), 2) if ts["n"] and tot_recent and tot_n else None)
    cut = {}
    for sh in (0, 1):
        r = sorted(v["rel_lift"] for v in vids if v["rel_lift"] is not None and v["is_short"] == sh)
        if r: cut[sh] = r[int(len(r) * 0.25)]
    creators, rows = {}, []
    for i, v in enumerate(vids):
        cid = v["channel_id"]
        if cid not in creators: creators[cid] = dict(i=len(creators), name=v["creator"], kol=v["kol_type"], tier=v["tier"], subs=v["subscribers"], region=v["region"])
        rows.append(dict(id=v["video_id"], url=v["url"], t=v["title"][:110], c=creators[cid]["i"], f=v["format"], tp=v["topic"], d=v["day_since_launch"],
                         sh=v["is_short"], vw=v["views"], rl=v["rel_lift"], op=v["outperformer"], er=v["eng_rate"], cr=v["comment_rate"], pub=v["published"], fr=v["title_framing"],
                         lk=v["likes"], cc=v["comment_count"], bv=v["baseline_views"],
                         un=(int(v["rel_lift"] <= cut[v["is_short"]]) if v["rel_lift"] is not None and v["is_short"] in cut else None), a=agg[i]))
    prod_comments = sum(1 for c in comments if c["target"] in PRODUCT_SIDE)
    counts = dict(videos=len(vids), creators=len(creators), comments_en=sum(a["n"] for a in agg), as_of=last,
                  assigned=round(tot_n / prod_comments, 3) if prod_comments else None,
                  modes=dict(con.execute(f"select label_mode, count(*) from comments c join content v using(video_id) where {scope_sql()} group by 1").fetchall()))
    data = dict(topics=[dict(id=t["topic_id"], pool=t["pool"], name=t["name"], summary=t["summary"], terms=t["terms"], origin=t["origin"], first_seen=t["first_seen"], n=t["n"], c=t["c"],
                             recent=t["recent"], prior=t["prior"], trend=t["trend"]) for t in topics],
                videos=rows, creators=sorted(creators.values(), key=lambda c: c["i"]), quotes=quotes, brands=list(pr["competitors"]), counts=counts,
                event=pr["launch"], product=dict(name=pr["name"], brand=pr["brand"]))
    attach_summaries(data)
    if public:
        import public_safety as safe
        data = attach_public_text(scrub_public(data), safe.corpus(r[0] for r in con.execute("select text from comments where text is not null")))
    html = open(os.path.join(HERE, "dashboard.tmpl.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out = os.path.join(HERE, "docs", "index.html") if public else os.path.join(HERE, "dashboard.html")
    os.makedirs(os.path.dirname(out), exist_ok=True); open(out, "w", encoding="utf-8").write(html)
    if public:                                           # the same text-free data as plain JSON, handy for rebuilding the UI in another tool
        json.dump(data, open(os.path.join(HERE, "docs", "data.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{os.path.relpath(out, HERE)} {os.path.getsize(out)/1e6:.2f} MB | {len(rows)} videos, {len(topics)} topics, {len(quotes)} quotes")


if __name__ == "__main__":
    main()
