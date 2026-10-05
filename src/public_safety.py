"""Guard for the public demo: nothing that is copied from a comment may be published.
A text 'overlaps' a comment when it shares a run of 5 consecutive words with it that is distinctive: seen in at most 2 comments.
Runs that many comments share ('for the iphone 18 pro') are ordinary language, not someone's wording, so they do not count."""
import re
from collections import Counter

N = 5
COMMON = 2


def words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def shingles(text, n=N):
    w = words(text)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def corpus(comment_texts):
    """How many comments contain each 5-word run."""
    c = Counter()
    for t in comment_texts:
        c.update(shingles(t))
    return c


def overlap(text, corp):
    """Distinctive 5-word runs of `text` that also appear in a comment (empty set = safe)."""
    return {s for s in shingles(text) if 0 < corp.get(s, 0) <= COMMON}
