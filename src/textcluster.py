"""Local text clustering, pure Python and deterministic: TF-IDF over unigrams and bigrams, spherical k-means. No AI, no dependencies.
Used by topics.py to find what people talk about; Claude only names the clusters afterwards."""
import math, random, re
from collections import Counter, defaultdict

STOP = set("""the and for that this with you your are was were have has had not but all can will just like they them their there then than from what when who how why its it's i'm i've don't doesn't didn't can't won't
about would could should into out over more most some any one two get got gets getting also only very really much many even still ever never every too own same such here where which while because been being does did doing
make makes made going gonna want wants need needs think thinks thought know knows say says said see seen look looks looking come comes came people thing things way lot lots something anything everything yeah yes
video videos thanks thank guys guy dude man bro lol lmao omg wow""".split())


def tokens(text, extra_stop=()):
    w = [x.strip("'") for x in re.findall(r"[a-z']+", text.lower())]
    w = [x for x in w if len(x) >= 3 and x not in STOP and x not in extra_stop]
    return w + [f"{a} {b}" for a, b in zip(w, w[1:])]


def tfidf(docs, min_df=4, max_df=0.35):
    """docs: lists of tokens. Returns L2-normalised sparse vectors (dicts)."""
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
    return normalise(c)


def normalise(c):
    norm = math.sqrt(sum(x * x for x in c.values())) or 1.0
    return {t: x / norm for t, x in c.items()}


def truncate(c, n=60):
    """Keep the n heaviest terms (stored in state/, so no comment can be reconstructed from it)."""
    return normalise(dict(sorted(c.items(), key=lambda kv: -kv[1])[:n]))


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


def clusters(texts, k=None, min_size=30, max_df=0.35, extra_stop=()):
    """Cluster texts. Returns (vecs, list of cluster dicts: id, members, n, coherence, center, terms, rep) for clusters with at least min_size members, largest first."""
    vecs = tfidf([tokens(t, extra_stop) for t in texts], max_df=max_df)
    k = k or max(2, min(30, len(texts) // 180))
    assign, centers = kmeans(vecs, k)
    out = []
    for j in range(k):
        mem = [i for i, a in enumerate(assign) if a == j]
        if len(mem) < min_size: continue
        out.append(dict(id=j, members=mem, n=len(mem), center=centers[j], terms=top_terms(centers[j]),
                        coherence=round(sum(dot(vecs[i], centers[j]) for i in mem) / len(mem), 3),
                        rep=sorted(mem, key=lambda i: -dot(vecs[i], centers[j]))[:8]))
    return vecs, sorted(out, key=lambda c: -c["n"])


def nearest(vec, centers, tau):
    """Index of the closest centre if its cosine similarity is at least tau, else None."""
    best, bs = None, 0.0
    for j, c in enumerate(centers):
        s = dot(vec, c)
        if s > bs: best, bs = j, s
    return best if bs >= tau else None
