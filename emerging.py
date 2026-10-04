#!/usr/bin/env python3
"""Emerging topics: local discovery, AI naming.
1. Local, pure Python: TF-IDF (unigrams + bigrams) over product-side comments about the Duo, spherical k-means.
2. For each cluster: how much of it the 12 fixed themes already describe (alignment), how fast it is growing (last 7 days vs the 7 before), sentiment.
3. Claude only names the clusters that look like gaps, writes one paraphrased sentence, and says whether an existing theme already covers it.
Output: state/emerging.json (no comment text)."""
import json, math, os, random, re, sqlite3, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from common import DATA, HERE, claude, parse_json
from comments import THEMES

PS = "('product','price_value','apple_brand','competitor')"
SCOPE = "v.topic='duo' and v.format!='official'"
STOP = set("""the and for that this with you your are was were have has had not but all can will just like they them their there then than from what when who how why its it's i'm i've don't doesn't didn't can't won't
about would could should into out over more most some any one two get got gets getting also only very really much many even still ever never every too own same such here where which while because been being does did doing
make makes made going gonna want wants need needs think thinks thought know knows say says said see seen look looks looking come comes came people thing things way lot lots something anything everything yeah yes
phone phones iphone iphones apple duo foldable fold folds video videos thanks thank guys guy dude man bro lol lmao omg wow""".split())


def tokens(text):
    w = [x.strip("'") for x in re.findall(r"[a-z']+", text.lower())]
    w = [x for x in w if len(x) >= 3 and x not in STOP]
    return w + [f"{a} {b}" for a, b in zip(w, w[1:])]


def tfidf(docs, min_df=4, max_df=0.35):
    N = len(docs)
    df = Counter(t for d in docs for t in set(d))
    keep = {t for t, c in df.items() if c >= min_df and c <= max_df * N}
    idf = {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in keep}
    vecs = []
    for d in docs:
        tf = Counter(t for t in d if t in keep)
        v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs


def dot(a, b):
    if len(a) > len(b): a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def centroid(members, vecs):
    c = defaultdict(float)
    for i in members:
        for t, x in vecs[i].items(): c[t] += x
    norm = math.sqrt(sum(x * x for x in c.values())) or 1.0
    return {t: x / norm for t, x in c.items()}


def kmeans(vecs, k, iters=15, seed=7):
    rnd = random.Random(seed)
    centers = [vecs[rnd.randrange(len(vecs))]]
    while len(centers) < k:                               # k-means++ style: prefer documents far from the centres chosen so far
        d = [max(1e-9, 1 - max(dot(v, c) for c in centers)) ** 2 for v in vecs]
        r, acc = rnd.random() * sum(d), 0
        for i, w in enumerate(d):
            acc += w
            if acc >= r: centers.append(vecs[i]); break
    assign = [-1] * len(vecs)
    for _ in range(iters):
        new = [max(range(k), key=lambda j: dot(v, centers[j])) for v in vecs]
        if new == assign: break
        assign = new
        groups = defaultdict(list)
        for i, a in enumerate(assign): groups[a].append(i)
        centers = [centroid(groups[j], vecs) if groups[j] else centers[j] for j in range(k)]
    return assign, centers


def top_terms(center, n=6):
    return [t for t, _ in sorted(center.items(), key=lambda kv: -kv[1])[:n]]


def analyse(rows, k=None, min_size=30, max_df=0.35):
    """rows: dicts with text, published (YYYY-MM-DD), sentiment, themes (list). Returns cluster dicts, largest first."""
    docs = [tokens(r["text"]) for r in rows]
    vecs = tfidf(docs, max_df=max_df)
    k = k or max(6, min(30, len(rows) // 180))
    assign, centers = kmeans(vecs, k)
    end = max(r["published"] for r in rows); e = date.fromisoformat(end)
    recent_from, prior_from = str(e - timedelta(days=7)), str(e - timedelta(days=14))
    out = []
    for j in range(k):
        mem = [i for i, a in enumerate(assign) if a == j]
        if len(mem) < min_size: continue
        coh = sum(dot(vecs[i], centers[j]) for i in mem) / len(mem)
        th = Counter(t for i in mem for t in rows[i]["themes"])
        dom, dom_n = (th.most_common(1)[0] if th else (None, 0))
        rec = sum(rows[i]["published"] > recent_from for i in mem)
        pri = sum(prior_from < rows[i]["published"] <= recent_from for i in mem)
        out.append(dict(id=j, n=len(mem), coherence=round(coh, 3), terms=top_terms(centers[j]), members=mem,
                        no_theme=round(sum(1 for i in mem if not rows[i]["themes"]) / len(mem), 3),
                        dominant_theme=dom, alignment=round(dom_n / len(mem), 3),
                        pos=round(sum(rows[i]["sentiment"] == "positive" for i in mem) / len(mem), 3), neg=round(sum(rows[i]["sentiment"] == "negative" for i in mem) / len(mem), 3),
                        recent=rec, prior=pri, rep=sorted(mem, key=lambda i: -dot(vecs[i], centers[j]))[:8]))
    return sorted(out, key=lambda c: -c["n"])


def load_rows(con):
    th = defaultdict(list)
    for r in con.execute("select comment_id, theme from comment_themes"): th[r[0]].append(r[1])
    sql = (f"select c.comment_id, c.text, c.published, c.sentiment from comments c join content v using(video_id) where {SCOPE} and c.lang='en' and c.trivial=0 "
           f"and c.target in {PS} and c.text is not null and length(c.text) >= 20")
    return [dict(id=r[0], text=r[1], published=r[2], sentiment=r[3], themes=th.get(r[0], [])) for r in con.execute(sql)]


def name_clusters(clusters, rows):
    """One Claude call: name the clusters, paraphrase in one sentence, say whether an existing theme already covers it."""
    theme_list = "\n".join(f"- {k}: {d}" for k, d in THEMES.items())
    items = [dict(id=c["id"], top_terms=c["terms"], examples=[rows[i]["text"][:180].replace("\n", " ") for i in c["rep"][:6]]) for c in clusters]
    prompt = ("Each item is a cluster of YouTube comments about Apple's iPhone Duo, found by keyword statistics (no AI). Name what each cluster is about. "
              "Existing themes (the fixed taxonomy):\n" + theme_list + "\n\n"
              "For each cluster return: label (<=4 words, plain), summary (one sentence, <=25 words, paraphrased in your own words, no quotes, no usernames), "
              "coherent (false if the comments share no real topic), covered_by (the key of an existing theme if the cluster is essentially that theme, otherwise null). "
              'A cluster about a specific sub-topic that no theme names (for example a particular feature or accessory) is NOT covered. Return JSON only: {"clusters": [{"id": int, "label": str, "summary": str, "coherent": bool, "covered_by": str|null}]}\n\n'
              + json.dumps(items, ensure_ascii=False))
    for _ in range(3):
        try:
            return {r["id"]: r for r in parse_json(claude(prompt, 4000))["clusters"]}
        except (ValueError, KeyError):
            continue
    raise SystemExit("could not get cluster names")


def main():
    import public_safety as safe
    con = sqlite3.connect(os.path.join(DATA, "pulse.db"))
    rows = load_rows(con)
    out = dict(as_of=max((r["published"] for r in rows), default=""), n_comments=len(rows), clusters=[])
    if len(rows) >= 300:
        found = [c for c in analyse(rows) if c["n"] >= 40 and c["coherence"] >= 0.15][:16]
        names = name_clusters(found, rows)
        corp = safe.corpus(r["text"] for r in rows)
        overall_recent = sum(c["recent"] for c in analyse(rows)) / max(sum(c["n"] for c in analyse(rows)), 1)
        for c in found:
            nm = names.get(c["id"])
            if not nm or not nm.get("coherent"): continue
            summary = nm.get("summary", "")
            if safe.overlap(summary, corp): summary = ""            # never publish a sentence that reuses a comment's wording
            share_recent = c["recent"] / c["n"]
            out["clusters"].append(dict(label=nm["label"], summary=summary, n=c["n"], share=round(c["n"] / len(rows), 3), pos=c["pos"], neg=c["neg"], recent=c["recent"], prior=c["prior"],
                                        trend_index=round(share_recent / overall_recent, 2) if overall_recent else None, covered_by=nm.get("covered_by") if nm.get("covered_by") in THEMES else None,
                                        dominant_theme=c["dominant_theme"], alignment=c["alignment"], terms=c["terms"]))
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "state", "emerging.json"), "w"), ensure_ascii=False, indent=1)
    new = [c for c in out["clusters"] if not c["covered_by"]]
    print(f"{len(out['clusters'])} coherent clusters, {len(new)} not covered by the 12 themes")
    for c in out["clusters"]:
        print(f"  {'NEW ' if not c['covered_by'] else 'in   '} n={c['n']:4} trend={c['trend_index']} pos={c['pos']:.2f} neg={c['neg']:.2f} | {c['label']} | {c['summary'][:90]}")


if __name__ == "__main__":
    main()
