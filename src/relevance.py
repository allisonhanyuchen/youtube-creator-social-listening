"""Is a video really about the product? Search results also bring accessories (cases, chargers, mice, stands), other products or brands that share a name
(another company's "Duo"), and unrelated videos. This asks Claude once per 60 titles and returns the ids that are NOT about the product itself,
so classify.py and the keyword explorer can leave them out of the numbers."""
import json
from common import claude, parse_json

BATCH = 60


def not_about(items, subject, blurb="", model=None):
    """items: [{id, title, channel}]. Returns the set of ids judged not to be mainly about `subject` itself. On any failure it keeps the video (returns nothing for that batch)."""
    out = set()
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        prompt = (f"For each YouTube video decide whether it is mainly about {subject} itself{f' ({blurb})' if blurb else ''}.\n"
                  "Answer about=false for: accessories for it (cases, chargers, cables, screen protectors, mice, keyboards, stands, bands), a different product or brand that only shares part of the name "
                  "(for example another company's product with a similar name), apps or services with a similar name, and videos that are not about the product.\n"
                  "Answer about=true for reviews, hands-on, comparisons, news, rumours, unboxings, tips, memes, jokes and reactions that are mainly about the product itself, including a comparison with a competitor. When unsure, answer true.\n"
                  'Return JSON only: {"results": [{"id": str, "about": true or false}]}\n\n'
                  + json.dumps([{"id": x["id"], "title": x["title"][:120], "channel": x.get("channel", "")} for x in batch], ensure_ascii=False))
        try:
            res = parse_json(claude(prompt, 3000, model=model, thinking={"type": "between_tools"}))["results"]
        except (ValueError, KeyError, SystemExit):
            continue
        out |= {r["id"] for r in res if r.get("about") is False}
    return out


def apply(videos, off_topic_ids, main_topic):
    """Marks every checked video and moves the ones that are not about the product out of its topic (the original label is kept in topic_raw). Returns how many moved."""
    moved = 0
    for v in videos:
        if v["id"] in off_topic_ids:
            if v.get("topic") == main_topic: v["topic_raw"] = main_topic; v["topic"] = "other"; moved += 1
            v["relevant"] = False
        else:
            v["relevant"] = True
    return moved
