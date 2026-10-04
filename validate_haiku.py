"""Compare Haiku 4.5 against the Sonnet labels already produced, on a random sample of comments."""
import random
from collections import Counter
from common import load
from comments import label_batch, THEMES

HAIKU = "claude-haiku-4-5-20251001"
random.seed(11)
raw = {c["comment_id"]: c for v in load("comments_raw.json").values() for c in v}
lab = load("comment_labels.json")
ids = random.sample(sorted(lab), 300)
batch = [raw[i] for i in ids]
new = []
for k in range(0, 300, 50):
    new += label_batch(batch[k:k + 50], model=HAIKU)
ok = [(i, n) for i, n in zip(ids, new) if n]
from common import save
save("haiku_check.json", {i: n for i, n in ok})
print(f"Haiku returned labels for {len(ok)}/300")
agree = lambda f: sum(f(lab[i], n) for i, n in ok) / len(ok)
print(f"lang      {agree(lambda a, n: a['lang'] == n.get('l')):.0%}")
print(f"target    {agree(lambda a, n: a['target'] == n.get('t')):.0%}")
print(f"sentiment {agree(lambda a, n: a['sentiment'] == n.get('s')):.0%}")
print(f"intent    {agree(lambda a, n: a['intent'] == n.get('in')):.0%}")
print(f"themes exact-set {agree(lambda a, n: set(a['themes']) == set(n.get('th', []))):.0%}")
jac = [len(set(lab[i]['themes']) & set(n.get('th', []))) / max(len(set(lab[i]['themes']) | set(n.get('th', []))), 1) for i, n in ok]
print(f"themes mean Jaccard {sum(jac)/len(jac):.2f}")
# sentiment confusion + agreement restricted to comments about the product side
conf = Counter((lab[i]['sentiment'], n.get('s')) for i, n in ok)
print("sentiment confusion (sonnet -> haiku):", dict(conf))
side = [(i, n) for i, n in ok if lab[i]['target'] in ('product', 'price_value', 'apple_brand', 'competitor')]
print(f"sentiment agreement on product-side comments (n={len(side)}): {sum(lab[i]['sentiment']==n.get('s') for i,n in side)/len(side):.0%}")
print("per theme (sonnet as reference): theme  n_sonnet  recall  precision")
for t in THEMES:
    s = {i for i, n in ok if t in lab[i]['themes']}; h = {i for i, n in ok if t in n.get('th', [])}
    if s or h: print(f"  {t:30} {len(s):>3}  {len(s & h)/max(len(s),1):>5.0%}  {len(s & h)/max(len(h),1):>5.0%}")
