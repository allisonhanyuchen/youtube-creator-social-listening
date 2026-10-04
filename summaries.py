#!/usr/bin/env python3
"""Paraphrased 'what people say' notes for the public demo, one per comment theme and per price sub-theme (iPhone Duo, all channels).
Claude sees the most-liked comments but must paraphrase and generalise; every bullet is then checked against the comment corpus and any bullet that
shares a 5-word run with a comment is dropped. Output: state/summaries.json (no comment text)."""
import json, os, sqlite3
from common import DATA, HERE, claude, parse_json
from comments import THEMES
from price_sub import SUBS
import public_safety as safe

SCOPE = "v.topic='duo' and v.format!='official'"
RULES = ("Paraphrase and generalise. Never reproduce distinctive wording, jokes, usernames or quotes from the comments. Plain, neutral language, each bullet under 22 words. "
         "Do not give numbers unless several comments clearly say the same number.")


def top(con, theme, sentiment, n=25, price_sub=None):
    if price_sub:
        sql = f"select c.text from comments c join content v using(video_id) where c.price_sub=? and c.lang='en' and c.trivial=0 and c.text is not null and length(c.text) between 25 and 240 and {SCOPE} order by c.likes desc limit {n}"
        return [r[0] for r in con.execute(sql, (price_sub,))]
    sql = (f"select c.text from comments c join comment_themes t using(comment_id) join content v using(video_id) where t.theme=? and c.sentiment=? and c.lang='en' and c.trivial=0 "
           f"and c.text is not null and length(c.text) between 25 and 240 and {SCOPE} order by c.likes desc limit {n}")
    return [r[0] for r in con.execute(sql, (theme, sentiment))]


def summarise(texts, what, corp):
    if len(texts) < 5: return []
    for attempt in range(2):
        out = parse_json(claude(f"Here are the most-liked YouTube comments about {what} on videos about Apple's iPhone Duo. Write 2 to 3 bullets that capture the recurring points. {RULES}"
                                + (" Your previous bullets were too close to the original wording; generalise more." if attempt else "")
                                + '\nReturn JSON only: {"bullets": [str]}\n\nCOMMENTS:\n' + "\n".join("- " + t.replace("\n", " ") for t in texts), 1500))
        bullets = [b for b in out.get("bullets", []) if not safe.overlap(b, corp)]
        if bullets: return bullets[:3]
    return []


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db"))
    corp = safe.corpus(r[0] for r in con.execute("select text from comments where text is not null"))
    res = {"themes": {}, "price": {}}
    for key, desc in THEMES.items():
        res["themes"][key] = {s: summarise(top(con, key, s), f"{desc} ({s} comments)", corp) for s in ("positive", "negative")}
        print(key, {s: len(b) for s, b in res["themes"][key].items()}, flush=True)
    for key, (label, desc) in SUBS.items():
        res["price"][key] = summarise(top(con, None, None, price_sub=key), f"the price of the iPhone Duo: {label.lower()} ({desc})", corp)
        print("price", key, len(res["price"][key]), flush=True)
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "state", "summaries.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
