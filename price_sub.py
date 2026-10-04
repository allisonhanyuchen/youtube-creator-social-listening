#!/usr/bin/env python3
"""Inside the price discussion: give every comment that carries the price theme one sub-theme.
Taxonomy comes from open coding on a sample of 300 price comments, then fixed here so labels stay comparable week to week.
Stored on the comment label as `psub`, so it persists in state/ without the comment text."""
import re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from common import claude, load, save, USAGE

SUBS = {
    "regional_price_gap": ("Regional price gaps", "outside the US, local prices are much higher than the US headline (taxes, tariffs, exchange rates)"),
    "samsung_fold_comparison": ("Versus Samsung Fold", "the Duo's price weighed against the Galaxy Z Fold 8 or other rival foldables, including their discounts"),
    "fair_for_foldables": ("Fair, better than feared", "the price is reasonable, in line with other foldables, or lower than expected"),
    "affordability_barrier": ("Can't afford it", "out of reach or beyond what the commenter will spend, often citing the economy or other priorities"),
    "overpriced_for_tradeoffs": ("Overpriced for compromises", "not worth the price because features are missing or downgraded (Face ID, telephoto, camera, battery)"),
    "vs_pro_and_ipad": ("Versus Pro or iPad", "the premium over Apple's own products, such as the gap to the Pro Max or the cost of an iPhone plus an iPad"),
    "storage_tradein_financing": ("Storage, trade-in, financing", "entry storage tier, trade-in value, or payment and lease plans that change the effective price"),
    "cost_jokes": ("Price jokes", "humour about the cost (kidneys, rent, a car) without a substantive argument"),
    "general": ("General or unspecific", "mentions price without any of the above"),
}
KEYS = list(SUBS)
lock = threading.Lock()


def parse_lines(text):
    """Parse  i|number  lines into {index: sub-theme key}. Numbers outside the taxonomy are dropped."""
    out = {}
    for ln in text.splitlines():
        m = re.match(r"\s*(\d+)\s*\|\s*(\d+)", ln)
        if m and 1 <= int(m.group(2)) <= len(KEYS): out[int(m.group(1))] = KEYS[int(m.group(2)) - 1]
    return out


def label(batch, raw):
    lines = "\n".join(f"{k}: {raw[i]['text'][:260]}" for k, i in enumerate(batch))
    legend = "\n".join(f"{n + 1}={k} ({d[1]})" for n, (k, d) in enumerate(SUBS.items()))
    prompt = ("Each comment is about the PRICE of Apple's iPhone Duo (first foldable iPhone, about $2,000). Give each comment its single best sub-theme number.\n" + legend +
              "\nOutput exactly one line per comment as  i|number  and nothing else.\n\nCOMMENTS:\n" + lines)
    for attempt in range(3):
        out = parse_lines(claude(prompt, 1500, thinking={"type": "between_tools"}))
        if len(out) >= len(batch) * 0.9: return out
        time.sleep(3)
    return {}


def main():
    raw = {c["comment_id"]: c for v in load("comments_raw.json", {}).values() for c in v}
    lab = load("comment_labels.json")
    todo = [i for i, l in lab.items() if "price_affordability" in l["themes"] and l["lang"] == "en" and not l.get("trivial") and not l.get("psub") and i in raw]
    print(f"{len(todo)} price comments to sub-label")
    batches = [todo[k:k + 50] for k in range(0, len(todo), 50)]
    def run(b):
        out = label(b, raw)
        with lock:
            for n, i in enumerate(b):
                if n in out: lab[i]["psub"] = out[n]
    with ThreadPoolExecutor(6) as ex: list(ex.map(run, batches))
    save("comment_labels.json", lab)
    from collections import Counter
    print(dict(Counter(l["psub"] for l in lab.values() if l.get("psub")).most_common()), f"| tokens in {USAGE['in']:,} out {USAGE['out']:,}")


if __name__ == "__main__":
    main()
