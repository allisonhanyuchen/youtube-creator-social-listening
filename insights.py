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
TH_LABEL = {"hype_purchase_excitement": "hype and purchase intent", "fold_animation_ui": "fold animation and UI", "price_affordability": "price",
            "android_prior_art": "'Android did it first'", "android_rival_comparison": "competitor comparison", "design_colors_form": "design and colours",
            "crease_screen_quality": "crease and screen", "camera_hardware": "camera", "durability_tests": "durability", "software_usability": "software and usability",
            "apple_brand_leadership": "Apple brand and leadership", "creator_credibility_critique": "ad-like or biased creator"}


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
    th = q(con, f"""select theme, count(*) n, avg(sentiment='positive') pos, avg(sentiment='negative') neg from comment_themes t join comments c using(comment_id) join content v using(video_id)
                    where c.lang='en' and c.trivial=0 and {SCOPE} group by 1 order by n desc""")
    m["themes"] = [dict(t, pos=round(t["pos"], 3), neg=round(t["neg"], 3)) for t in th]
    from price_sub import SUBS
    pb = q(con, f"""select c.price_sub sub, count(*) n, avg(c.sentiment='positive') pos, avg(c.sentiment='negative') neg from comments c join content v using(video_id)
                    where c.price_sub is not null and c.lang='en' and c.trivial=0 and {SCOPE} group by 1 order by n desc""")
    tot_pb = sum(r["n"] for r in pb) or 1
    m["price_breakdown"] = [dict(sub=SUBS[r["sub"]][0], n=r["n"], share=round(r["n"] / tot_pb, 3), pos=round(r["pos"], 3), neg=round(r["neg"], 3)) for r in pb]
    em = os.path.join(HERE, "state", "emerging.json")
    if os.path.exists(em):
        cl = json.load(open(em))["clusters"]
        m["topics_beyond_themes"] = [dict(label=c["label"], n=c["n"], share=c["share"], pos=c["pos"], neg=c["neg"], summary=c["summary"], trend_index=c["trend_index"])
                                     for c in sorted(cl, key=lambda c: -c["n"]) if not c["covered_by"]][:5]
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
        th = {t["theme"]: t["n"] for t in q(con, f"select theme, count(*) n from comment_themes t join comments c using(comment_id) join content v using(video_id) where c.lang='en' and c.trivial=0 and {SCOPE} and c.published>? and c.published<=? group by 1", str(a), str(b))}
        tot = q(con, f"select count(*) n from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and {SCOPE} and c.published>? and c.published<=?", str(a), str(b))[0]["n"]
        return dict(n=r["n"], pos=r["pos"], neg=r["neg"], themes=th, total=tot)
    return dict(as_of=last, recent=win(end - timedelta(days=7), end), prior=win(end - timedelta(days=14), end - timedelta(days=7)),
                outperformers=[r["video_id"] for r in q(con, f"select video_id from performance p join content v using(video_id) where p.outperformer=1 and {SCOPE}")])


def alerts(snap, prev):
    out, r, p = [], snap["recent"], snap["prior"]
    if r["n"] >= 300 and p["n"] >= 300 and r["neg"] is not None and p["neg"] is not None:
        d = r["neg"] - p["neg"]
        if abs(d) >= 0.05: out.append(dict(kind="sentiment", text=f"Negative share of product comments {'rose' if d > 0 else 'fell'} {abs(d)*100:.0f} points week over week ({p['neg']*100:.0f}% to {r['neg']*100:.0f}%, n={r['n']} vs {p['n']})."))
    for t, n in r["themes"].items():
        rt, pt = r["themes"][t] / max(r["total"], 1), p["themes"].get(t, 0) / max(p["total"], 1)
        if n >= 40 and pt > 0 and rt / pt >= 1.5: out.append(dict(kind="theme", text=f"'{TH_LABEL.get(t, t)}' mentions are up {rt/pt:.1f}x as a share of comments week over week (n={n})."))
    if prev:
        new = [v for v in snap["outperformers"] if v not in set(prev.get("outperformers", []))]
        if new: out.append(dict(kind="outperformers", text=f"{len(new)} new outperforming videos since the last run.", ids=new))
    return out


def topic_alerts():
    em = os.path.join(HERE, "state", "emerging.json")
    if not os.path.exists(em): return []
    return [dict(kind="topic", text=f"A topic outside the 12 themes is gaining ground: '{c['label']}' ({c['n']} comments, {c['trend_index']}x its usual share of recent comments).")
            for c in json.load(open(em))["clusters"] if not c["covered_by"] and (c["trend_index"] or 0) >= 1.5 and c["recent"] >= 15 and c["n"] >= 40][:2]


def narrative(m):
    prompt = ("You are a creator-marketing analyst writing the weekly readout on how the Apple iPhone Duo (first foldable iPhone, launched 2026-09-09) is landing on YouTube. "
              "Use ONLY numbers in the JSON below; never invent figures. Be direct, plain, no hype. Flag small samples. "
              "Definitions: outperformer = a video in the top quarter of views relative to the channel's own usual views (compared within Shorts or long videos); underperformer = bottom quarter. "
              "Lift and audience sentiment are different measures and must not be merged into a 'scale' or 'fix' recommendation; describe them side by side. "
              "Sponsorship and Apple seeding are NOT analysed; do not mention them. 'topics_beyond_themes' are subjects commenters raise that none of the 12 fixed themes names, found by keyword clustering. "
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
    al = alerts(snap, prev) + topic_alerts()
    nar = narrative(m)
    save("insights.json", dict(metrics=m, narrative=nar, alerts=al, as_of=snap["as_of"]))
    json.dump(snap, open(prev_path, "w"))
    print(json.dumps(nar, indent=1, ensure_ascii=False)); print("\nALERTS:", json.dumps(al, indent=1, ensure_ascii=False))
    print("\noutperformers", m["outperformer_rate"], "| underperformers", m["underperformer_rate"])


if __name__ == "__main__":
    main()
