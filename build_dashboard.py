#!/usr/bin/env python3
"""Build dashboard.html (local, with a few hundred quoted comments) or docs/index.html (--public, no comment text) from data/pulse.db.
One self-contained page, no CDN; all filtering and drill-down happen in the browser.
Embedded: per-video rows + per-video comment aggregates (sentiment, themes, rival brands, intent), the discovered topics, paraphrased theme notes."""
import json, os, re, sqlite3, sys
from collections import defaultdict
from common import DATA, HERE, load
from comments import THEMES

THEME_KEYS = list(THEMES)
PRODUCT_SIDE = {"product", "price_value", "apple_brand", "competitor"}
SENT = {"positive": 0, "neutral": 1, "negative": 2}
BRANDS = {"Samsung": r"samsung|galaxy|z ?fold|z ?flip", "Google Pixel": r"pixel", "Xiaomi": r"xiaomi|mi mix", "Oppo / Honor / Huawei": r"oppo|honor|huawei|vivo"}


def read_json(name, default):
    p = os.path.join(HERE, "state", name)
    return json.load(open(p)) if os.path.exists(p) else default


def attach_summaries(data):
    """Paraphrased theme notes (state/summaries.json) go into both builds."""
    data["summaries"] = read_json("summaries.json", {"themes": {}})
    return data


def attach_public_text(data, corp):
    """Public demo only: recorded Q&A. Everything published as prose is re-checked against the comment corpus before it goes in."""
    import public_safety as safe
    data["examples"] = read_json("examples.json", [])
    strings = [b for t in data["summaries"].get("themes", {}).values() for bl in t.values() for b in bl] + [e["a"] for e in data["examples"]] \
        + [c["summary"] for c in data.get("emerging", [])] + [c["label"] for c in data.get("emerging", [])]
    bad = [s[:60] for s in strings if safe.overlap(s, corp)]
    if bad: raise SystemExit(f"public text overlaps comment wording, not publishing: {bad[:3]}")
    return data


def scrub_public(data):
    """Public demo: no comment text at all (quotes, per-video top comments). Aggregates, titles and stats stay."""
    data["quotes"], data["pquotes"] = [], []
    for r in data["videos"]:
        r["a"]["tc"] = []
    data["public"] = True
    return data


def main():
    public = "--public" in sys.argv
    con = sqlite3.connect(os.path.join(DATA, "pulse.db")); con.row_factory = sqlite3.Row
    vids = [dict(r) for r in con.execute("select * from v_content where topic='duo' and format!='official' order by views desc")]   # the dashboard is about the iPhone Duo; other topics stay in the database for the Q&A agent
    vidx = {v["video_id"]: i for i, v in enumerate(vids)}
    agg = [dict(n=0, ps=[0, 0, 0], cred=0, th={}, br={}, it={}, tc=[]) for _ in vids]
    quotes_pool = defaultdict(list)
    th_by_cid = defaultdict(list)
    for r in con.execute("select comment_id, theme from comment_themes"): th_by_cid[r["comment_id"]].append(THEME_KEYS.index(r["theme"]))
    brand_re = {b: re.compile(p, re.I) for b, p in BRANDS.items()}
    for c in con.execute("select * from comments where lang='en' and trivial=0"):
        if c["video_id"] not in vidx: continue
        a = agg[vidx[c["video_id"]]]; s = SENT[c["sentiment"]]; ths = th_by_cid.get(c["comment_id"], [])
        a["n"] += 1
        if c["target"] in PRODUCT_SIDE: a["ps"][s] += 1
        if c["intent"] != "none": a["it"][c["intent"]] = a["it"].get(c["intent"], 0) + 1
        for t in ths:
            a["th"].setdefault(str(t), [0, 0, 0])[s] += 1
            if THEME_KEYS[t] == "creator_credibility_critique": a["cred"] += 1
        text = c["text"] or ""
        for b, rx in brand_re.items():
            if text and rx.search(text): a["br"].setdefault(b, [0, 0, 0])[s] += 1
        if 25 <= len(text) <= 240:
            a["tc"].append((c["likes"], text, s, ths))
            for t in ths:
                if s in (0, 2): quotes_pool[(t, s)].append((c["likes"], vidx[c["video_id"]], text))
    quotes = [[vi, t, s, text, likes] for (t, s), lst in quotes_pool.items() for likes, vi, text in sorted(lst, reverse=True)[:30]]
    for a in agg:
        a["tc"] = [[t, s, ths, l] for l, t, s, ths in sorted(a["tc"], reverse=True)[:2]]
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
    counts = dict(videos=len(vids), creators=len(creators), comments_en=sum(a["n"] for a in agg),
                  modes=dict(con.execute("select label_mode, count(*) from comments c join content v using(video_id) where v.topic='duo' and v.format!='official' group by 1").fetchall()))
    data = dict(emerging=read_json("emerging.json", {"clusters": []})["clusters"], videos=rows, creators=sorted(creators.values(), key=lambda c: c["i"]),
                themes=[[k, THEMES[k]] for k in THEME_KEYS], quotes=quotes, brands=list(BRANDS), counts=counts, event="2026-09-09")
    attach_summaries(data)
    if public:
        import public_safety as safe
        data = attach_public_text(scrub_public(data), safe.corpus(r[0] for r in con.execute("select text from comments where text is not null")))
    html = open(os.path.join(HERE, "dashboard.tmpl.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    out = os.path.join(HERE, "docs", "index.html") if public else os.path.join(HERE, "dashboard.html")
    os.makedirs(os.path.dirname(out), exist_ok=True); open(out, "w", encoding="utf-8").write(html)
    print(f"{os.path.relpath(out, HERE)} {os.path.getsize(out)/1e6:.2f} MB | {len(rows)} videos, {len(quotes)} quotes")


if __name__ == "__main__":
    main()
