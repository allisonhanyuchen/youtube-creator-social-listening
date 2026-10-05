#!/usr/bin/env python3
"""Paraphrased 'what people say' notes per topic (what the positive comments say, what the negative comments say).
Claude sees the most-liked comments of the topic but must paraphrase and generalise; every bullet is then checked against the comment corpus and any bullet that
shares a distinctive 5-word run with a comment is dropped. Output: state/summaries.json (no comment text)."""
import json, os, sqlite3
from common import DATA, HERE, claude, parse_json, product, scope_sql
import public_safety as safe

RULES = ("Paraphrase and generalise. Never reproduce distinctive wording, jokes, usernames or quotes from the comments. Plain, neutral language, each bullet under 22 words. "
         "Do not give numbers unless several comments clearly say the same number.")


def top(con, topic_id, sentiment, n=25):
    sql = (f"select c.text from comments c join content v using(video_id) where c.topic_id=? and c.sentiment=? and c.lang='en' and c.trivial=0 and c.text is not null "
           f"and length(c.text) between 25 and 240 and {scope_sql()} order by c.likes desc limit {n}")
    return [r[0] for r in con.execute(sql, (topic_id, sentiment))]


def summarise(texts, what, corp):
    if len(texts) < 5: return []
    pr = product()
    for attempt in range(2):
        out = parse_json(claude(f"Here are the most-liked YouTube comments about {what} on videos about {pr['brand']} {pr['name']}. Write 2 to 3 bullets that capture the recurring points. {RULES}"
                                + (" Your previous bullets were too close to the original wording; generalise more." if attempt else "")
                                + '\nReturn JSON only: {"bullets": [str]}\n\nCOMMENTS:\n' + "\n".join("- " + t.replace("\n", " ") for t in texts), 1500))
        bullets = [b for b in out.get("bullets", []) if not safe.overlap(b, corp)]
        if bullets: return bullets[:3]
    return []


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db"))
    corp = safe.corpus(r[0] for r in con.execute("select text from comments where text is not null"))
    res = {"topics": {}}
    for tid, name in con.execute("select topic_id, name from topics where pool='product' order by topic_id"):
        res["topics"][tid] = {s: summarise(top(con, tid, s), f"the topic '{name}' ({s} comments)", corp) for s in ("positive", "negative")}
        print(tid, name, {s: len(b) for s, b in res["topics"][tid].items()}, flush=True)
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "state", "summaries.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
