#!/usr/bin/env python3
"""Insights for the iPhone Duo. Python computes every number (so nothing in the report is invented); Claude writes the narrative from those numbers.
Lift and audience sentiment are reported side by side; they are never combined into a scale-or-fix verdict.
Output: data/insights.json (metrics + narrative + alerts) and state/snapshot.json (aggregates only, committed, used to detect change next run)."""
import json, os, sqlite3, statistics
from datetime import date, timedelta
from common import DATA, HERE, claude, parse_json, load, save

PS = "('product','price_value','apple_brand','competitor')"
SCOPE = "v.topic='duo' and v.format!='official'"
TOL = 0.05


def q(con, sql, *a):
    return [dict(r) for r in con.execute(sql, a)]


def size(tier):
    return "small (<250k)" if tier in ("nano <50k", "micro 50-250k") else "mid (250k-1M)" if tier == "mid 250k-1M" else "large (1M+)"


def video_rows(con):
    """Duo videos with lift, engagement and product-side sentiment. Lift and sentiment are reported side by side and never combined into a recommendation."""
    rows = q(con, f"""select v.video_id, v.title, v.url, v.format, v.is_short, cr.name creator, cr.tier, cr.kol_type, p.views, p.likes, p.comment_count, p.rel_lift, p.outperformer o,
                      s.n_product_side n, s.pct_positive pos, s.pct_negative neg
                      from content v join creators cr using(channel_id) join performance p using(video_id) left join v_video_sentiment s using(video_id) where {SCOPE}""")
    cut = {}
    for sh in (0, 1):                                  # a class can be empty (for example no Shorts), so only cut where there is data
        r = sorted(x["rel_lift"] for x in rows if x["rel_lift"] is not None and x["is_short"] == sh)
        if r: cut[sh] = r[int(len(r) * 0.25)]
    for x in rows:
        x["under"] = int(x["rel_lift"] is not None and x["is_short"] in cut and x["rel_lift"] <= cut[x["is_short"]])
    return rows


def topic_rows(con):
    """Audience topics (product pool): size, sentiment, share, whether discovered after the first run. Trend comes from the snapshot windows."""
    last = q(con, f"select max(c.published) d from comments c join content v using(video_id) where {SCOPE}")[0]["d"]
    end = date.fromisoformat(last); rf = str(end - timedelta(days=7))
    rows = q(con, f"""select t.topic_id id, t.name, t.summary, t.origin, t.first_seen, count(*) n, avg(c.sentiment='positive') pos, avg(c.sentiment='negative') neg, sum(c.published>?) recent
                      from comments c join topics t using(topic_id) join content v using(video_id)
                      where t.pool='product' and c.lang='en' and c.trivial=0 and {SCOPE} group by 1 order by n desc""", rf)
    tot, rec = sum(r["n"] for r in rows) or 1, sum(r["recent"] for r in rows)
    return [dict(id=r["id"], name=r["name"], summary=r["summary"], discovered=r["origin"] == "discovered", first_seen=r["first_seen"], n=r["n"], share=round(r["n"] / tot, 3),
                 pos=round(r["pos"], 3), neg=round(r["neg"], 3), recent=r["recent"], trend=round((r["recent"] / r["n"]) / (rec / tot), 2) if rec and r["n"] else None) for r in rows]


def metrics(con):
    rows = video_rows(con)
    ev = [x for x in rows if x["o"] is not None]
    rate = lambda xs, k: round(sum(x[k] for x in xs) / len(xs), 3) if xs else None
    sent_of = lambda xs: dict(n=sum((x["n"] or 0) for x in xs), pos=round(sum((x["pos"] or 0) * (x["n"] or 0) for x in xs) / max(sum((x["n"] or 0) for x in xs), 1), 3),
                              neg=round(sum((x["neg"] or 0) * (x["n"] or 0) for x in xs) / max(sum((x["n"] or 0) for x in xs), 1), 3))
    m = {}
    m["totals"] = dict(videos=len(rows), creators=len({x["creator"] for x in rows}), views=sum(x["views"] for x in rows), engagements=sum(x["likes"] + x["comment_count"] for x in rows),
                       comments_en=q(con, f"select count(*) n from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and {SCOPE}")[0]["n"])
    m["outperformer_rate"], m["underperformer_rate"] = rate(ev, "o"), rate(ev, "under")
    m["sentiment"] = sent_of(rows)
    m["by_channel_size"] = {g: dict(videos=len(xs), outperformer_rate=rate([x for x in xs if x["o"] is not None], "o"), **sent_of(xs))
                            for g in ("small (<250k)", "mid (250k-1M)", "large (1M+)") for xs in [[x for x in rows if size(x["tier"]) == g]]}
    m["by_creator_type"] = [dict(kol_type=k, videos=len(xs), outperformer_rate=rate([x for x in xs if x["o"] is not None], "o"), **sent_of(xs))
                            for k in sorted({x["kol_type"] for x in rows}) for xs in [[x for x in rows if x["kol_type"] == k]] if len(xs) >= 10]
    m["by_format"] = sorted([dict(format=f, videos=len(xs), outperformer_rate=rate([x for x in xs if x["o"] is not None], "o"), **sent_of(xs))
                             for f in sorted({x["format"] for x in rows}) for xs in [[x for x in rows if x["format"] == f]] if len([x for x in xs if x["o"] is not None]) >= 10],
                            key=lambda r: -(r["outperformer_rate"] or 0))
    m["coverage"] = dict(videos=len(rows), creators=len({x["creator"] for x in rows}), with_sentiment=sum(1 for x in rows if (x["n"] or 0) >= 10), comments_en=m["totals"]["comments_en"],
                         by_level={g: sum(1 for x in rows if size(x["tier"]) == g) for g in ("small (<250k)", "mid (250k-1M)", "large (1M+)")})
    m["topics"] = topic_rows(con)
    m["intent"] = {r["intent"]: r["n"] for r in q(con, f"select intent, count(*) n from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and c.intent!='none' and {SCOPE} group by 1")}
    top = sorted([x for x in rows if x["rel_lift"] is not None], key=lambda x: -x["rel_lift"])[:6]
    m["highest_lift"] = [dict(title=x["title"], url=x["url"], creator=x["creator"], channel_size=size(x["tier"]), format=x["format"], rel_lift=round(x["rel_lift"], 1), views=x["views"],
                              product_comments=x["n"] or 0, pos=round(x["pos"], 2) if x["pos"] is not None else None, neg=round(x["neg"], 2) if x["neg"] is not None else None) for x in top]
    return m


def snapshot(con):
    last = max(r["d"] for r in q(con, f"select max(c.published) d from comments c join content v using(video_id) where {SCOPE}"))
    end = date.fromisoformat(last)
    def win(a, b):
        r = q(con, f"""select count(*) n, avg(sentiment='positive') pos, avg(sentiment='negative') neg from comments c join content v using(video_id)
                       where c.lang='en' and c.trivial=0 and c.target in {PS} and {SCOPE} and c.published>? and c.published<=?""", str(a), str(b))[0]
        th = {t["topic_id"]: t["n"] for t in q(con, f"select c.topic_id, count(*) n from comments c join topics t using(topic_id) join content v using(video_id) where t.pool='product' and c.lang='en' and c.trivial=0 and {SCOPE} and c.published>? and c.published<=? group by 1", str(a), str(b))}
        tot = q(con, f"select count(*) n from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and {SCOPE} and c.published>? and c.published<=?", str(a), str(b))[0]["n"]
        return dict(n=r["n"], pos=r["pos"], neg=r["neg"], by_topic=th, total=tot)
    tm = {t["id"]: dict(name=t["name"], n=t["n"], pos=t["pos"], neg=t["neg"]) for t in topic_rows(con)}
    tot = q(con, f"select count(*) n from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and {SCOPE}")[0]["n"]
    vids = [r["video_id"] for r in q(con, f"select v.video_id from content v where {SCOPE}")]
    sent = q(con, f"select avg(sentiment='positive') pos, avg(sentiment='negative') neg from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and c.target in {PS} and {SCOPE}")[0]
    return dict(as_of=last, videos=vids, comments=tot, sentiment=dict(pos=sent["pos"], neg=sent["neg"]), topics=tm, recent=win(end - timedelta(days=7), end), prior=win(end - timedelta(days=14), end - timedelta(days=7)),
                outperformers=[r["video_id"] for r in q(con, f"select video_id from performance p join content v using(video_id) where p.outperformer=1 and {SCOPE}")])


def alerts(snap, prev):
    out, r, p = [], snap["recent"], snap["prior"]
    if r["n"] >= 300 and p["n"] >= 300 and r["neg"] is not None and p["neg"] is not None:
        d = r["neg"] - p["neg"]
        if abs(d) >= 0.05: out.append(dict(kind="sentiment", text=f"Negative share of product comments {'rose' if d > 0 else 'fell'} {abs(d)*100:.0f} points week over week ({p['neg']*100:.0f}% to {r['neg']*100:.0f}%, n={r['n']} vs {p['n']})."))
    for t, n in r["by_topic"].items():
        rt, pt = r["by_topic"][t] / max(r["total"], 1), p["by_topic"].get(t, 0) / max(p["total"], 1)
        if n >= 40 and pt > 0 and rt / pt >= 1.5: out.append(dict(kind="topic", text=f"'{snap['topics'].get(t, {}).get('name', t)}' mentions are up {rt/pt:.1f}x as a share of comments week over week (n={n})."))
    if prev:
        new = [v for v in snap["outperformers"] if v not in set(prev.get("outperformers", []))]
        if new: out.append(dict(kind="outperformers", text=f"{len(new)} new outperforming videos since the last run.", ids=new))
    return out


def changes(snap, prev):
    """What moved since the previous refresh, computed locally from two snapshots. None on the first run."""
    if not prev or "topics" not in prev: return None
    pv, pt = set(prev.get("videos", [])), prev["topics"]
    new_t = [dict(id=i, name=t["name"], n=t["n"]) for i, t in snap["topics"].items() if i not in pt]
    moved = [dict(id=i, name=t["name"], n=t["n"], d_n=t["n"] - pt[i]["n"], d_neg=round(t["neg"] - pt[i]["neg"], 3)) for i, t in snap["topics"].items()
             if i in pt and (t["n"] - pt[i]["n"] >= 25 or abs(t["neg"] - pt[i]["neg"]) >= 0.05 and t["n"] >= 40)]
    ds = (snap["sentiment"]["pos"] - prev["sentiment"]["pos"], snap["sentiment"]["neg"] - prev["sentiment"]["neg"]) if prev.get("sentiment") and prev["sentiment"]["pos"] is not None else None
    return dict(since=prev.get("as_of"), new_videos=len([v for v in snap["videos"] if v not in pv]), new_comments=snap["comments"] - prev.get("comments", 0), new_topics=new_t, moved=moved[:6],
                sentiment_delta=dict(pos=round(ds[0], 3), neg=round(ds[1], 3)) if ds else None)


def watchlist(m):
    """Topics worth watching next refresh, from the numbers only: growing fast, or large with a clearly negative tilt."""
    out = []
    for t in m["topics"]:
        if (t["trend"] or 0) >= 1.5 and t["recent"] >= 15: out.append(dict(id=t["id"], name=t["name"], why=f"gaining: {t['trend']}x its usual share of recent comments (n={t['recent']})"))
        elif t["n"] >= 150 and t["neg"] - t["pos"] >= 0.15: out.append(dict(id=t["id"], name=t["name"], why=f"net negative: {t['neg']*100:.0f}% negative vs {t['pos']*100:.0f}% positive (n={t['n']})"))
    return out[:5]


def narrative(m):
    prompt = ("You are a creator-marketing analyst writing the weekly readout on how the Apple iPhone Duo (first foldable iPhone, launched 2026-09-09) is landing on YouTube. "
              "Use ONLY numbers in the JSON below; never invent figures. Be direct, plain, no hype. Flag small samples. "
              "Definitions: outperformer = a video in the top quarter of views relative to the channel's own usual views (compared within Shorts or long videos); underperformer = bottom quarter. "
              "Lift and audience sentiment are different measures and must not be merged into a 'scale' or 'fix' recommendation; describe them side by side. "
              "Sponsorship and Apple seeding are NOT analysed; do not mention them. 'topics' are audience topics found by local clustering of comments and named by AI, with share, sentiment and trend (recent share vs usual); 'discovered' ones appeared after the first run. 'changes' is what moved since the last refresh (null on the first run); 'watchlist' lists topics to monitor. "
              "Return JSON only: "
              '{"headline": str (<=22 words), "summary": str (<=90 words), "findings": [{"title": str, "detail": str (<=45 words, with numbers), "action": str (<=25 words, a concrete creator-brief or measurement step)}] (exactly 4), '
              '"watch": str (<=40 words, what to monitor next week)}\n\nMETRICS:\n' + json.dumps(m, ensure_ascii=False))
    for attempt in range(3):
        try:
            return parse_json(claude(prompt + ("\n\nReturn strictly valid JSON. Do not use double quotes inside string values; use single quotes." if attempt else ""), 4000))
        except ValueError:
            continue
    raise SystemExit("could not get valid JSON for the narrative after 3 tries")


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db")); con.row_factory = sqlite3.Row
    m = metrics(con)
    snap = snapshot(con)
    prev_path = os.path.join(HERE, "state", "snapshot.json")
    prev = json.load(open(prev_path)) if os.path.exists(prev_path) else None
    al = alerts(snap, prev)
    ch = changes(snap, prev)
    for t in (ch or {}).get("new_topics", []): al.append(dict(kind="topic", text=f"New audience topic since the last refresh: '{t['name']}' ({t['n']} comments)."))
    m["changes"], m["watchlist"] = ch, watchlist(m)
    nar = narrative(m)
    save("insights.json", dict(metrics=m, narrative=nar, alerts=al, as_of=snap["as_of"]))
    json.dump(snap, open(prev_path, "w"))
    print(json.dumps(nar, indent=1, ensure_ascii=False)); print("\nALERTS:", json.dumps(al, indent=1, ensure_ascii=False))
    print("\noutperformers", m["outperformer_rate"], "| underperformers", m["underperformer_rate"])


if __name__ == "__main__":
    main()
