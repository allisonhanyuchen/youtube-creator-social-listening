#!/usr/bin/env python3
"""Step 3a: pull a stratified comment sample and let Claude propose a theme taxonomy by open coding (human reviews it before full labelling).
30 videos = (topic duo / 18 pro) x (organic / sponsored / seeded) x top-5 by views with >=100 comments. Quota ~30 units."""
import json, random
from common import yt, claude, parse_json, load, save

random.seed(7)


def fetch_comments(video_id, n=100, order="relevance"):
    out, tok = [], None
    while len(out) < n:
        p = dict(part="snippet", videoId=video_id, maxResults=min(100, n - len(out)), order=order, textFormat="plainText")
        if tok: p["pageToken"] = tok
        r = yt("commentThreads", soft=True, **p)
        if not r: return out
        for i in r.get("items", []):
            s = i["snippet"]["topLevelComment"]["snippet"]
            out.append(dict(comment_id=i["id"], video_id=video_id, text=s["textDisplay"], likes=s.get("likeCount", 0), published=s["publishedAt"]))
        tok = r.get("nextPageToken")
        if not tok: break
    return out


def main():
    vids = [v for v in load("videos.json") if v["promo_type"] != "official" and v["comments"] >= 100 and v["topic"] in ("duo", "iphone_18_pro")]
    pick = []
    for t in ("duo", "iphone_18_pro"):
        for p in ("organic", "paid"):
            pool = sorted([v for v in vids if v["topic"] == t and v["promo_type"] == p], key=lambda v: -v["views"])
            pick += pool[:8] if p == "organic" else pool[:7]
    comments = load("comments_sample.json")          # reuse the pull if present (re-running Claude costs no YouTube quota)
    if not comments:
        comments = []
        for v in pick:
            comments += fetch_comments(v["id"], 100)
        save("comments_sample.json", comments)
    print(f"{len(pick)} videos, {len(comments)} comments")
    texts = random.sample(comments, min(400, len(comments)))
    out = parse_json(claude(
        "You are doing open coding on YouTube comments about Apple's Sept 2026 launch (iPhone Duo foldable, iPhone 18 Pro). "
        "Propose a theme taxonomy a brand marketing team can use to see what people like and dislike. Rules: 10-14 themes, mutually clear, "
        "each with a short key, a definition, 2 verbatim example comments from the sample, and the share of the sample that mentions it. "
        "Also propose: (a) the 'target' values (what the comment is about: product, price_value, video_or_creator, apple_brand, competitor, other), "
        "(b) 'intent' values (buy, upgrade_wait, skip, switch_from_android, none). "
        "Say which themes are mostly positive, mostly negative or split. "
        'Return valid JSON only (escape any double quotes inside strings; keep examples under 140 characters): {"themes":[{"key":str,"definition":str,"examples":[str,str],"share_pct":number,"lean":"positive|negative|split"}],'
        '"targets":[str],"intents":[str],"notes":str}\n\nCOMMENTS:\n' + "\n".join("- " + c["text"][:220].replace("\n", " ") for c in texts), 9000))
    save("taxonomy_draft.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
