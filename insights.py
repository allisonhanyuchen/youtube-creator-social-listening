#!/usr/bin/env python3
"""Step 6: insights. Python computes every number (so nothing in the report is invented), Claude writes the narrative from those numbers.
Output: data/insights.json (metrics + narrative + alerts) and state/snapshot.json (aggregates only, committed, used to detect change next run)."""
import json, os, sqlite3, statistics
from datetime import date, timedelta
from common import DATA, HERE, claude, parse_json, load, save
from comments import THEMES

PS = "('product','price_value','apple_brand','competitor')"
TH_LABEL = {"hype_purchase_excitement": "hype and purchase intent", "fold_animation_ui": "fold animation and UI", "price_affordability": "price",
            "android_prior_art": "'Android did it first'", "android_rival_comparison": "rival comparison", "design_colors_form": "design and colours",
            "crease_screen_quality": "crease and screen", "camera_hardware": "camera", "durability_tests": "durability", "software_usability": "software and usability",
            "apple_brand_leadership": "Apple brand and leadership", "creator_credibility_critique": "ad-like or biased creator"}


def q(con, sql, *a):
    return [dict(r) for r in con.execute(sql, a)]


def sent(con, where="1=1", *a):
    r = q(con, f"""select count(*) n, avg(sentiment='positive') pos, avg(sentiment='neutral') neu, avg(sentiment='negative') neg
                   from comments c join content v using(video_id) where c.lang='en' and c.trivial=0 and c.target in {PS} and {where}""", *a)[0]
    return {k: (round(x, 3) if isinstance(x, float) else x) for k, x in r.items()}


def metrics(con):
    m = {}
    m["totals"] = q(con, "select count(*) videos, (select count(*) from creators) creators, sum(views) views from content c join performance using(video_id) where promo_type!='official'")[0]
    m["totals"]["comments_en"] = q(con, "select count(*) n from comments where lang='en' and trivial=0")[0]["n"]
    m["sentiment_all"] = sent(con)
    m["by_topic"] = {t: dict(sent(con, "v.topic=?", t), **q(con, "select count(*) videos, round(avg(outperformer),3) outperformer_rate, round(avg(rel_lift),2) mean_rel from content join performance using(video_id) where topic=? and promo_type!='official'", t)[0]) for t in ("duo", "iphone_18_pro")}
    seeded_days = {r["day_since_launch"] for r in q(con, "select day_since_launch from content where promo_sub='seeded'")}
    ph = ",".join(map(str, seeded_days))
    grp = {}
    for g, cond in (("organic", "promo_type='organic'"), ("seeded", "promo_sub='seeded'"), ("sponsored", "promo_sub='sponsored'")):
        for label, extra in (("all", ""), ("same_window", f" and day_since_launch in ({ph})")):
            r = q(con, f"select count(*) n, count(outperformer) n_eval, round(avg(outperformer),3) outperformer_rate, round(avg(lift),2) mean_lift from content join performance using(video_id) where {cond}{extra}")[0]
            r["median_rel"] = statistics.median([x["rel_lift"] for x in q(con, f"select rel_lift from content join performance using(video_id) where {cond}{extra} and rel_lift is not null")] or [0])
            r["sentiment"] = sent(con, cond.replace("promo_", "v.promo_") + extra.replace("day_since", "v.day_since"))
            cr = q(con, f"""select count(distinct c.comment_id) n, sum(t.theme='creator_credibility_critique') cred from comments c join content v using(video_id)
                            left join comment_themes t on t.comment_id=c.comment_id and t.theme='creator_credibility_critique' where c.lang='en' and c.trivial=0 and {cond.replace('promo_','v.promo_')}{extra.replace('day_since','v.day_since')}""")[0]
            r["ad_like_rate"] = round((cr["cred"] or 0) / cr["n"], 4) if cr["n"] else None
            grp.setdefault(g, {})[label] = r
    m["paid_vs_organic"] = grp
    m["formats"] = q(con, """select format, count(*) videos, count(outperformer) n_eval, round(avg(outperformer),3) outperformer_rate, round(avg(rel_lift),2) mean_rel
                             from content join performance using(video_id) where promo_type!='official' group by 1 having n_eval>=15 order by outperformer_rate desc""")
    th = q(con, """select theme, count(*) n, avg(sentiment='positive') pos, avg(sentiment='negative') neg from comment_themes t join comments c using(comment_id)
                   where c.lang='en' and c.trivial=0 group by 1 order by n desc""")
    m["themes"] = [dict(t, pos=round(t["pos"], 3), neg=round(t["neg"], 3)) for t in th]
    m["themes_by_topic"] = {tp: [dict(r, pos=round(r["pos"], 3), neg=round(r["neg"], 3)) for r in q(con, """select theme, count(*) n, avg(sentiment='positive') pos, avg(sentiment='negative') neg
                            from comment_themes t join comments c using(comment_id) join content v using(video_id) where c.lang='en' and c.trivial=0 and v.topic=? group by 1 having n>=40 order by n desc""", tp)] for tp in ("duo", "iphone_18_pro")}
    m["intent"] = {r["intent"]: r["n"] for r in q(con, "select intent, count(*) n from comments where lang='en' and trivial=0 and intent!='none' group by 1")}
    m["scale_candidates"] = q(con, f"""select v.title, v.url, cr.name creator, v.format, round(p.rel_lift,1) rel_lift, p.views,
        (select round(avg(sentiment='positive'),2) from comments c where c.video_id=v.video_id and c.lang='en' and c.trivial=0 and c.target in {PS}) pos
        from content v join performance p using(video_id) join creators cr using(channel_id)
        where v.promo_type='organic' and p.outperformer=1 and (select count(*) from comments c where c.video_id=v.video_id and c.lang='en' and c.target in {PS})>=20
        and (select count(*) from content x where x.channel_id=v.channel_id and x.promo_sub='sponsored')<2
        order by min(p.rel_lift,10)*pos desc limit 5""")
    return m


def snapshot(con):
    last = max(r["d"] for r in q(con, "select max(published) d from comments"))
    end = date.fromisoformat(last)
    def win(a, b):
        r = q(con, f"""select count(*) n, avg(sentiment='positive') pos, avg(sentiment='negative') neg from comments where lang='en' and trivial=0 and target in {PS} and published>? and published<=?""",
              str(a), str(b))[0]
        th = {t["theme"]: t["n"] for t in q(con, "select theme, count(*) n from comment_themes t join comments c using(comment_id) where c.lang='en' and c.trivial=0 and c.published>? and c.published<=? group by 1", str(a), str(b))}
        tot = q(con, "select count(*) n from comments where lang='en' and trivial=0 and published>? and published<=?", str(a), str(b))[0]["n"]
        return dict(n=r["n"], pos=r["pos"], neg=r["neg"], themes=th, total=tot)
    return dict(as_of=last, recent=win(end - timedelta(days=7), end), prior=win(end - timedelta(days=14), end - timedelta(days=7)),
                outperformers=[r["video_id"] for r in q(con, "select video_id from performance where outperformer=1")])


def alerts(snap, prev):
    out, r, p = [], snap["recent"], snap["prior"]
    if r["n"] >= 300 and p["n"] >= 300 and r["neg"] is not None and p["neg"] is not None:
        d = r["neg"] - p["neg"]
        if abs(d) >= 0.05: out.append(dict(kind="sentiment", text=f"Negative share of product comments {'rose' if d > 0 else 'fell'} {abs(d)*100:.0f} points week over week ({p['neg']*100:.0f}% to {r['neg']*100:.0f}%, n={r['n']} vs {p['n']})."))
    for t, n in r["themes"].items():
        pn, rt, pt = p["themes"].get(t, 0), r["themes"][t] / max(r["total"], 1), p["themes"].get(t, 0) / max(p["total"], 1)
        if n >= 40 and pt > 0 and rt / pt >= 1.5: out.append(dict(kind="theme", text=f"'{TH_LABEL.get(t, t)}' mentions are up {rt/pt:.1f}x as a share of comments week over week (n={n})."))
    if prev:
        new = [v for v in snap["outperformers"] if v not in set(prev.get("outperformers", []))]
        if new: out.append(dict(kind="outperformers", text=f"{len(new)} new outperforming videos since the last run.", ids=new))
    return out


def narrative(m):
    prompt = ("You are a creator-marketing analyst writing the weekly readout on how Apple's Sept 2026 launch (iPhone Duo foldable, iPhone 18 Pro) is landing on YouTube. "
              "Use ONLY numbers in the JSON below; never invent figures. Be direct, plain, no hype. Flag small samples and that seeded is partly defined by early posting. "
              "Definitions: outperformer = top quartile of a video's views relative to the channel's own baseline within Shorts or long videos. "
              "seeded = Apple early access (pre-launch unit or event invite), sponsored = third-party commercial sponsor, organic = neither. "
              "ad_like_rate = share of comments calling the creator biased or ad-like. Return JSON only: "
              '{"headline": str (<=22 words), "summary": str (<=90 words), "findings": [{"title": str, "detail": str (<=45 words, with numbers), "action": str (<=25 words, a concrete creator-brief or measurement step)}] (exactly 4), '
              '"watch": str (<=40 words, what to monitor next week)}\n\nMETRICS:\n' + json.dumps(m, ensure_ascii=False))
    return parse_json(claude(prompt, 3000))


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db")); con.row_factory = sqlite3.Row
    m = metrics(con)
    snap = snapshot(con)
    prev_path = os.path.join(HERE, "state", "snapshot.json")
    prev = json.load(open(prev_path)) if os.path.exists(prev_path) else None
    al = alerts(snap, prev)
    nar = narrative(m)
    save("insights.json", dict(metrics=m, narrative=nar, alerts=al, as_of=snap["as_of"]))
    json.dump(snap, open(prev_path, "w"))
    print(json.dumps(nar, indent=1, ensure_ascii=False)); print("\nALERTS:", json.dumps(al, indent=1, ensure_ascii=False))
    print("\nscale candidates:", [(c["creator"], c["rel_lift"], c["pos"]) for c in m["scale_candidates"]])


if __name__ == "__main__":
    main()
