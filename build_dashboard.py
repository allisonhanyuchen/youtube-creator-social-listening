#!/usr/bin/env python3
"""Build dashboard.html from data/pulse.db: one self-contained page (no CDN), all filtering and drill-down happen in the browser.
Embedded: per-video rows + per-video comment aggregates (sentiment, themes, rival brands, timeline, intent), a few hundred top quotes, contrast words.
Comment text is embedded only for those quotes, so keep dashboard.html local (gitignored)."""
import json, math, os, re, sqlite3
from collections import Counter, defaultdict
from common import DATA, HERE, load
from comments import THEMES

THEME_KEYS = list(THEMES)
PRODUCT_SIDE = {"product", "price_value", "apple_brand", "competitor"}
SENT = {"positive": 0, "neutral": 1, "negative": 2}
BRANDS = {"Samsung": r"samsung|galaxy|z ?fold|z ?flip", "Google Pixel": r"pixel", "Xiaomi": r"xiaomi|mi mix", "Oppo / Honor / Huawei": r"oppo|honor|huawei|vivo"}
STOP = set("this that with have from they their about would there what when which will just like been your more than them were some into very also only really does dont doesnt didnt cant its you the and for but are not was can all get one out has how why who our too any".split())


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db")); con.row_factory = sqlite3.Row
    vids = [dict(r) for r in con.execute("select * from v_content where topic='duo' and format!='official' order by views desc")]   # the dashboard is about the iPhone Duo; other topics stay in the database for the Q&A agent
    vidx = {v["video_id"]: i for i, v in enumerate(vids)}
    agg = [dict(n=0, ps=[0, 0, 0], cred=0, th={}, br={}, tl={}, it={}, tc=[]) for _ in vids]
    quotes_pool = defaultdict(list)
    words_pos, words_neg = Counter(), Counter()
    th_by_cid = defaultdict(list)
    for r in con.execute("select comment_id, theme from comment_themes"): th_by_cid[r["comment_id"]].append(THEME_KEYS.index(r["theme"]))
    brand_re = {b: re.compile(p, re.I) for b, p in BRANDS.items()}
    for c in con.execute("select * from comments where lang='en' and trivial=0"):
        if c["video_id"] not in vidx: continue
        a = agg[vidx[c["video_id"]]]; s = SENT[c["sentiment"]]; ths = th_by_cid.get(c["comment_id"], [])
        a["n"] += 1
        if c["target"] in PRODUCT_SIDE:
            a["ps"][s] += 1
            d = str(max(-3, min(c["day_since_launch"], 30))); a["tl"].setdefault(d, [0, 0, 0])[s] += 1
            for w in set(re.findall(r"[a-z]{4,}", c["text"].lower())):
                if w not in STOP: (words_pos if s == 0 else words_neg if s == 2 else Counter())[w] += 1
        if c["intent"] != "none": a["it"][c["intent"]] = a["it"].get(c["intent"], 0) + 1
        for t in ths:
            a["th"].setdefault(str(t), [0, 0, 0])[s] += 1
            if THEME_KEYS[t] == "creator_credibility_critique": a["cred"] += 1
        for b, rx in brand_re.items():
            if rx.search(c["text"]): a["br"].setdefault(b, [0, 0, 0])[s] += 1
        if 25 <= len(c["text"]) <= 240:
            a["tc"].append((c["likes"], c["text"], s, ths))
            for t in ths:
                if s in (0, 2): quotes_pool[(t, s)].append((c["likes"], vidx[c["video_id"]], c["text"]))
    quotes = []
    for (t, s), lst in quotes_pool.items():
        for likes, vi, text in sorted(lst, reverse=True)[:30]: quotes.append([vi, t, s, text, likes])
    for a in agg:
        a["tc"] = [[t, s, ths, l] for l, t, s, ths in sorted(a["tc"], reverse=True)[:2]]
    Np, Nn = sum(words_pos.values()), sum(words_neg.values())
    V = len(set(words_pos) | set(words_neg))
    def contrast(me, other, Nm, No):
        sc = {w: math.log((me[w] + 1) / (Nm + V)) - math.log((other.get(w, 0) + 1) / (No + V)) for w in me if me[w] >= 25}
        return [[w, me[w]] for w, _ in sorted(sc.items(), key=lambda kv: -kv[1])[:24]]
    cut = {}
    for sh in (0, 1):
        r = sorted(v["rel_lift"] for v in vids if v["rel_lift"] is not None and v["is_short"] == sh)
        cut[sh] = r[int(len(r) * 0.25)]
    creators = {}
    rows = []
    for i, v in enumerate(vids):
        cid = v["channel_id"]
        if cid not in creators: creators[cid] = dict(i=len(creators), name=v["creator"], kol=v["kol_type"], tier=v["tier"], subs=v["subscribers"], region=v["region"])
        rows.append(dict(id=v["video_id"], url=v["url"], t=v["title"][:110], c=creators[cid]["i"], f=v["format"], tp=v["topic"], d=v["day_since_launch"],
                         sh=v["is_short"], vw=v["views"], rl=v["rel_lift"], op=v["outperformer"],
                         er=v["eng_rate"], cr=v["comment_rate"], pub=v["published"], fr=v["title_framing"], lk=v["likes"], cc=v["comment_count"], bv=v["baseline_views"],
                         un=(int(v["rel_lift"] <= cut[v["is_short"]]) if v["rel_lift"] is not None else None), **{"a": agg[i]}))
    counts = dict(videos=len(vids), creators=len(creators), comments_labelled=con.execute("select count(*) from comments c join content v using(video_id) where v.topic='duo' and v.format!='official'").fetchone()[0],
                  comments_en=sum(a["n"] for a in agg),
                  modes=dict(con.execute("select label_mode, count(*) from comments c join content v using(video_id) where v.topic='duo' and v.format!='official' group by 1").fetchall()),
                  built=load("videos.json")[0].get("published", "")[:0])
    data = dict(videos=rows, creators=[c for c in sorted(creators.values(), key=lambda c: c["i"])], themes=[[k, THEMES[k]] for k in THEME_KEYS],
                quotes=quotes, words=dict(pos=contrast(words_pos, words_neg, Np, Nn), neg=contrast(words_neg, words_pos, Nn, Np)),
                brands=list(BRANDS), counts=counts, event="2026-09-09")
    html = open(os.path.join(HERE, "dashboard.tmpl.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out = os.path.join(HERE, "dashboard.html"); open(out, "w", encoding="utf-8").write(html)
    print(f"dashboard.html {os.path.getsize(out)/1e6:.2f} MB | {len(rows)} videos, {len(quotes)} quotes")


if __name__ == "__main__":
    main()
