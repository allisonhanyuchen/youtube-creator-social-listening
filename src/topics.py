#!/usr/bin/env python3
"""One consistent set of topics, built from the comments themselves.

Local (no AI): TF-IDF + k-means groups comments by the words they share; every comment is assigned to the nearest topic centre.
AI (light): Claude merges near-duplicate clusters, drops clusters with no real subject, names each topic and writes one paraphrased sentence.
Counts and sentiment shares are then counted from the per-comment labels (comments.py), never judged again here.

Stability and discovery on refresh:
  * topic ids, names and centres persist in state/topics.json, and each comment's topic in state/comment_topics.json, so weeks are comparable;
  * new comments are assigned to the closest existing topic when similar enough;
  * comments that fit no topic are clustered again; clusters that are real become NEW topics (origin 'discovered', with a first_seen date).
Two pools use the same method: comments about the product, and comments about the video or creator."""
import json, os, sqlite3
from collections import Counter
from common import DATA, HERE, claude, parse_json, product, scope_sql
import textcluster as tc
import db

STATE = os.path.join(HERE, "state")
POOLS = {"product": dict(prefix="p", targets=("product", "price_value", "apple_brand", "competitor"), min_size=30, min_rows=300,
                         about="comments about the product, its price, the brand or competitors"),
         "creator": dict(prefix="c", targets=("video_or_creator",), min_size=25, min_rows=200, about="comments addressed to the creator or about the video itself")}
DISCOVER_MIN = 150      # unassigned comments needed before we look for new topics


def jload(name, default):
    p = os.path.join(STATE, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def jsave(name, obj):
    os.makedirs(STATE, exist_ok=True)
    json.dump(obj, open(os.path.join(STATE, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def load_rows(con, targets):
    q = ",".join("'%s'" % t for t in targets)
    sql = (f"select c.comment_id, c.text, c.published, c.sentiment from comments c join content v using(video_id) where {scope_sql()} and c.lang='en' and c.trivial=0 "
           f"and c.target in ({q}) and c.text is not null and length(c.text) >= 20")
    return [dict(id=r[0], text=r[1], published=r[2], sentiment=r[3]) for r in con.execute(sql)]


def ask_names(clusters, texts, existing, pool):
    """One Claude call. existing=[] on a cold start (merge and name); otherwise decide for each candidate: same as an existing topic, new, or drop."""
    pr = product()
    items = [dict(id=c["id"], top_terms=c["terms"], examples=[texts[i][:180].replace("\n", " ") for i in c["rep"][:6]]) for c in clusters]
    base = (f"Each item is a cluster of YouTube {POOLS[pool]['about']} on videos about {pr['brand']} {pr['name']} ({pr['blurb']}), found by keyword statistics with no AI. "
            "Write names that are plain and specific (<=4 words) and one sentence (<=25 words) paraphrased in your own words, with no quotes and no usernames. ")
    if not existing:
        prompt = (base + "Produce the final topic list: merge clusters about the same subject, and drop clusters that share no real subject. "
                  'Return JSON only: {"topics": [{"name": str, "summary": str, "cluster_ids": [int]}], "dropped": [int]}\n\n' + json.dumps(items, ensure_ascii=False))
    else:
        prompt = (base + "Existing topics (id: name): " + json.dumps({t["id"]: t["name"] for t in existing}, ensure_ascii=False) + ". For each cluster decide: it is essentially an existing topic "
                  '(same_as = that id), or a genuinely new topic (give name and summary), or it has no real subject (drop). Be strict about \\"new\\". '
                  'Return JSON only: {"clusters": [{"id": int, "same_as": str|null, "drop": bool, "name": str, "summary": str}]}\\n\\n' + json.dumps(items, ensure_ascii=False))
    for _ in range(3):
        try:
            return parse_json(claude(prompt, 4000))
        except ValueError:
            continue
    raise SystemExit("could not get topic names")


def new_topic(tid, name, summary, center, as_of, origin):
    c = tc.truncate(center, 60)
    return dict(id=tid, name=name, summary=summary, terms=tc.top_terms(c, 8), centroid={t: round(x, 4) for t, x in c.items()}, origin=origin, first_seen=as_of)


def assign_all(vecs, topics, tau):
    cents = [t["centroid"] for t in topics]
    return [(topics[j]["id"] if (j := tc.nearest(v, cents, tau)) is not None else None) for v in vecs]


def cold_start(rows, pool, as_of):
    cfg = POOLS[pool]
    texts = [r["text"] for r in rows]
    vecs, cl = tc.clusters(texts, k=max(6, min(30, len(texts) // 65)), min_size=cfg["min_size"])      # fine clusters first; naming then merges those about the same subject
    cl = [c for c in cl if c["coherence"] >= 0.13]
    out = ask_names(cl, texts, [], pool)
    by = {c["id"]: c for c in cl}
    topics, sims = [], []
    for n, t in enumerate(out.get("topics", []), 1):
        ids = [i for i in t.get("cluster_ids", []) if i in by]
        if not ids: continue
        center = tc.normalise({k: sum(by[i]["center"].get(k, 0) for i in ids) for i in ids for k in by[i]["center"]})
        topics.append(new_topic(f"{cfg['prefix']}{n:02d}", t["name"], t.get("summary", ""), center, as_of, "initial"))
        for i in ids:
            sims += [tc.dot(vecs[m], by[i]["center"]) for m in by[i]["members"]]
    sims.sort()
    tau = min(0.25, max(0.05, sims[int(len(sims) * 0.15)] if sims else 0.1))
    return topics, tau


def as_of_pool(rows):
    return max(r["published"] for r in rows)


def refresh(rows, vecs, pool, state, assigned, as_of, origin="discovered"):
    """Assign new comments to existing topics, then look for new topics among those that fit none."""
    cfg, topics, tau = POOLS[pool], state["topics"], state["tau"]
    guess = assign_all(vecs, topics, tau)
    for r, g in zip(rows, guess):
        if r["id"] not in assigned or not assigned[r["id"]]:
            assigned[r["id"]] = g
    residual = [i for i, r in enumerate(rows) if not assigned.get(r["id"])]
    new_ids = []
    if len(residual) >= DISCOVER_MIN:
        texts = [rows[i]["text"] for i in residual]
        rvecs, cl = tc.clusters(texts, k=max(2, min(12, len(texts) // 50)), min_size=25)
        cl = [c for c in cl if c["coherence"] >= 0.15]
        if cl:
            out = ask_names(cl, texts, topics, pool)
            by = {c["id"]: c for c in cl}
            nxt = max([int(t["id"][1:]) for t in topics] + [0]) + 1
            for r in out.get("clusters", []):
                c = by.get(r.get("id"))
                if not c or r.get("drop"): continue
                if r.get("same_as") in {t["id"] for t in topics}:
                    tid = r["same_as"]
                else:
                    tid = f"{cfg['prefix']}{nxt:02d}"; nxt += 1
                    topics.append(new_topic(tid, r.get("name", "New topic"), r.get("summary", ""), c["center"], as_of, origin)); new_ids.append(tid)
                for m in c["members"]: assigned[rows[residual[m]]["id"]] = tid
    return new_ids


def sanitize(st, corp):
    """Never keep a topic sentence that reuses a comment's distinctive wording: replace it with a high-level one written without seeing any comment."""
    import public_safety as safe
    pr = product()
    for pool in st["pools"].values():
        for t in pool["topics"]:
            if t.get("summary") and safe.overlap(t["summary"], corp):
                out = parse_json(claude(f"One sentence (<=25 words, plain) describing, at a high level, what viewers discuss under the topic '{t['name']}' (keywords: {', '.join(t['terms'][:6])}) "
                                        f"in YouTube comments about {pr['brand']} {pr['name']}. No examples, no quotes. Return JSON only: " + '{"summary": str}', 800))
                t["summary"] = out.get("summary", "")


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db"))
    st = jload("topics.json", {"pools": {}, "runs": []})
    ct = jload("comment_topics.json", {})
    summary = {}
    as_of = ""
    for pool, cfg in POOLS.items():
        rows = load_rows(con, cfg["targets"])
        if not rows or (len(rows) < cfg["min_rows"] and pool not in st["pools"]):
            print(f"{pool}: only {len(rows)} comments with text here, not enough to build topics"); continue
        as_of = max(as_of, max(r["published"] for r in rows))
        vecs = tc.tfidf([tc.tokens(r["text"]) for r in rows])
        state = st["pools"].get(pool)
        if not state:
            topics, tau = cold_start(rows, pool, max(r["published"] for r in rows))
            state = st["pools"][pool] = dict(topics=topics, tau=round(tau, 4))
            guess = assign_all(vecs, topics, tau)
            for r, g in zip(rows, guess): ct[r["id"]] = g
            new_ids = [t["id"] for t in topics]
            new_ids += refresh(rows, vecs, pool, state, ct, as_of_pool(rows), "initial")     # the first pass leaves a pool of comments that fit no topic; text is not kept between cloud runs, so look for more topics in it right now
        else:
            new_ids = refresh(rows, vecs, pool, state, ct, max(r["published"] for r in rows))
        n_assigned = sum(1 for r in rows if ct.get(r["id"]))
        summary[pool] = dict(rows=len(rows), assigned=round(n_assigned / len(rows), 3), topics=len(state["topics"]), new=new_ids)
    import public_safety as safe
    sanitize(st, safe.corpus(r[0] for r in con.execute("select text from comments where text is not null")))
    st["runs"] = (st.get("runs", []) + [dict(as_of=as_of, **{p: s for p, s in summary.items()})])[-40:]
    jsave("topics.json", st); jsave("comment_topics.json", ct)
    db.apply_topics(con)
    for pool, s in summary.items():
        print(f"{pool}: {s['topics']} topics, {s['assigned']:.0%} of {s['rows']} comments assigned, new this run: {s['new'] or 'none'}")
    for pool in st["pools"]:
        counts = Counter(r[0] for r in con.execute("select topic_id from comments where topic_id like ?", (POOLS[pool]["prefix"] + "%",)))
        for t in st["pools"][pool]["topics"]:
            print(f"  {t['id']} {counts.get(t['id'], 0):5} {t['name']:30} | {', '.join(t['terms'][:5])}")


if __name__ == "__main__":
    main()
