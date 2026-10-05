#!/usr/bin/env python3
"""Keyword explorer: type a product or topic, get a small report in about a minute.
YouTube search -> channel baselines (lift) -> top comments -> Claude labels each comment -> local clustering finds topics, Claude names them -> summary.
Capped on purpose (20 videos, 20 comments each) so one run stays cheap: roughly 150 YouTube quota units and a few cents to a few tens of cents of Claude.
Run from the terminal:  python3 explore.py "iPhone Duo"      (add --sample to save the text-free sample shown on the public page, --push to also send it to your Slack and inbox)
The local server (serve.py) calls run() and streams the progress events to the dashboard."""
import json, os, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from common import HERE, USAGE, claude, parse_json, secret, yt
import comments as cm
import textcluster as tc

MAX_VIDEOS, MAX_COMMENTS = 20, 20
PRODUCT_SIDE = {"product", "price_value", "competitor"}
STEPS = [("search", "Retrieving videos from the YouTube API"), ("baseline", "Checking each channel's usual views"), ("comments", "Pulling the top comments"),
         ("label", "Reading every comment with Claude"), ("topics", "Finding and naming topics"), ("report", "Writing the report"), ("push", "Pushing the report to email and Slack")]


def pool(fn, items, workers=8):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def search_videos(keyword, n=MAX_VIDEOS):
    after = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = [it["id"]["videoId"] for it in yt("search", part="snippet", q=keyword, type="video", maxResults=30, order="relevance", relevanceLanguage="en", publishedAfter=after).get("items", [])]
    out = []
    for it in (yt("videos", part="snippet,statistics", id=",".join(ids)).get("items", []) if ids else []):
        st, sn = it.get("statistics", {}), it["snippet"]
        views = int(st.get("viewCount", 0) or 0)
        if views < 1000: continue
        out.append(dict(id=it["id"], url="https://www.youtube.com/watch?v=" + it["id"], title=sn["title"], channel=sn["channelTitle"], channel_id=sn["channelId"],
                        published=sn["publishedAt"][:10], views=views, likes=int(st.get("likeCount", 0) or 0), comment_count=int(st.get("commentCount", 0) or 0)))
    return out[:n]


def channel_baseline(v):
    """The channel's usual views: median of its latest uploads other than this video. None when there are fewer than 3 to compare with."""
    ch = yt("channels", soft=True, part="contentDetails,statistics", id=v["channel_id"])
    if not ch or not ch.get("items"): return v, None, None
    it = ch["items"][0]
    subs = int(it["statistics"].get("subscriberCount", 0) or 0)
    ups = yt("playlistItems", soft=True, part="contentDetails", playlistId=it["contentDetails"]["relatedPlaylists"]["uploads"], maxResults=12)
    ids = [x["contentDetails"]["videoId"] for x in (ups or {}).get("items", []) if x["contentDetails"]["videoId"] != v["id"]][:10]
    views = [int(x["statistics"].get("viewCount", 0) or 0) for x in (yt("videos", soft=True, part="statistics", id=",".join(ids)) or {}).get("items", [])] if ids else []
    return v, (statistics.median(views) if len(views) >= 3 else None), subs


def pull_comments(v):
    res = yt("commentThreads", soft=True, part="snippet", videoId=v["id"], maxResults=MAX_COMMENTS, order="relevance", textFormat="plainText")
    return v["id"], [x["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300] for x in (res or {}).get("items", [])]


def label(texts, keyword):
    """Same compact line format as the main pipeline, with a neutral prompt that works for any product or topic."""
    out = [None] * len(texts)
    for start in range(0, len(texts), 60):
        batch = texts[start:start + 60]
        lines = "\n".join(f"{k}: {t[:260]}" for k, t in enumerate(batch))
        prompt = (f"Label YouTube comments on videos about '{keyword}'.\nOutput exactly one line per comment, format  i|lang|target|sent|intent  and nothing else.\n"
                  "lang: e (English) or o (other)\n"
                  f"target (what the comment is about): P='{keyword}' itself, V=its price or value, C=the video or creator, R=a competing product or brand, O=other\n"
                  "sent (toward that target): + positive, 0 neutral, - negative. Curious or anticipatory comments are 0 unless they show a clear lean.\n"
                  "intent: b=buy, u=upgrade/wait, s=skip, w=switch from a competitor, n=none\nExample line:  7|e|P|-|n\n\nCOMMENTS:\n" + lines)
        for attempt in range(3):
            parsed = cm.parse_label_lines(claude(prompt, 3000, thinking={"type": "between_tools"}))
            if len(parsed) >= len(batch) * 0.9: break
            time.sleep(3)
        for k in range(len(batch)): out[start + k] = parsed.get(k)
    return out


def name_topics(cl, texts, keyword):
    items = [dict(id=c["id"], top_terms=c["terms"], examples=[texts[i][:180].replace("\n", " ") for i in c["rep"][:5]]) for c in cl]
    out = parse_json(claude(f"Each item is a cluster of YouTube comments about '{keyword}', found by keyword statistics. Name each cluster in <=4 plain words and write one sentence (<=25 words) "
                            "describing what commenters say, paraphrased in your own words, no quotes, no usernames. "
                            'Return JSON only: {"clusters": [{"id": int, "name": str, "summary": str}]}.\n\n' + json.dumps(items), 3000, thinking={"type": "between_tools"}))
    return {c["id"]: c for c in out.get("clusters", [])}


def net(ps):
    n = sum(ps)
    return round((ps[0] - ps[2]) / n * 100) if n else None


def build(keyword, emit=lambda e: None, push=False):
    t_all, steps = time.time(), []

    def step(sid, fn):
        label_ = dict(STEPS)[sid]
        emit(dict(step=sid, label=label_, status="start"))
        t0 = time.time()
        res, detail = fn()
        secs = round(time.time() - t0, 1)
        steps.append(dict(id=sid, label=label_, secs=secs, detail=detail))
        emit(dict(step=sid, label=label_, status="done", detail=detail, secs=secs))
        return res

    vids = step("search", lambda: (lambda v: (v, f"{len(v)} videos from {len({x['channel_id'] for x in v})} channels"))(search_videos(keyword)))
    if not vids: raise SystemExit(f"No English videos with 1,000+ views found for '{keyword}'. Try a broader keyword.")

    def baselines():
        for v, base, subs in pool(channel_baseline, vids):
            v["subs"] = subs
            v["lift"] = round(v["views"] / base, 2) if base else None
        return None, f"lift vs the channel's own usual views for {sum(1 for v in vids if v['lift'])} of {len(vids)} videos"
    step("baseline", baselines)

    def comments():
        got = dict(pool(pull_comments, vids))
        return got, f"{sum(len(x) for x in got.values()):,} comments from {sum(1 for x in got.values() if x)} videos"
    raw = step("comments", comments)
    flat = [(v["id"], t) for v in vids for t in raw.get(v["id"], [])]

    def labelling():
        labs = label([t for _, t in flat], keyword)
        return labs, f"{sum(1 for x in labs if x)} of {len(flat)} comments labelled (target, sentiment, intent)"
    labs = step("label", labelling)
    rows = [dict(vid=vid, text=t, lab=l) for (vid, t), l in zip(flat, labs) if l and l["l"] == "en"]
    side = [r for r in rows if r["lab"]["t"] in PRODUCT_SIDE]

    def topics():
        texts = [r["text"] for r in side]
        if len(texts) < 40: return [], "too few product comments to find topics"
        vecs, cl = tc.clusters(texts, k=max(3, min(7, len(texts) // 40)), min_size=max(8, len(texts) // 25))
        names = name_topics(cl, texts, keyword) if cl else {}
        res = []
        for c in cl:
            ps = [0, 0, 0]
            for i in c["members"]: ps[{"positive": 0, "neutral": 1, "negative": 2}[side[i]["lab"]["s"] or "neutral"]] += 1
            nm = names.get(c["id"], {})
            res.append(dict(name=nm.get("name") or "Topic", summary=nm.get("summary", ""), n=c["n"], share=round(c["n"] / len(texts), 3), ps=ps, score=net(ps), terms=c["terms"][:6]))
        res.sort(key=lambda t: -t["n"])
        return res, f"{len(res)} topics covering {sum(t['n'] for t in res)} of {len(texts)} product comments"
    tops = step("topics", topics)

    per = {}
    for r in side: per.setdefault(r["vid"], [0, 0, 0])[{"positive": 0, "neutral": 1, "negative": 2}[r["lab"]["s"] or "neutral"]] += 1
    videos = [dict(id=v["id"], url=v["url"], title=v["title"], channel=v["channel"], subs=v.get("subs"), views=v["views"], published=v["published"], lift=v["lift"],
                   ps=per.get(v["id"], [0, 0, 0])) for v in vids]
    tot = [sum(x["ps"][i] for x in videos) for i in range(3)]
    rep = dict(keyword=keyword, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), caps=dict(videos=MAX_VIDEOS, comments=MAX_COMMENTS),
               totals=dict(videos=len(videos), channels=len({v["channel_id"] for v in vids}), views=sum(v["views"] for v in videos), comments=len(flat), product_comments=sum(tot),
                           ps=tot, score=net(tot)), videos=videos, topics=tops)

    def write():
        brief = dict(keyword=keyword, totals=rep["totals"], topics=[{k: t[k] for k in ("name", "n", "score")} for t in tops],
                     top_lift=[{k: v[k] for k in ("title", "channel", "lift", "views")} for v in sorted([x for x in videos if x["lift"]], key=lambda x: -x["lift"])[:3]])
        s = parse_json(claude("You write a three-line readout of how a topic is landing on YouTube. Use ONLY the numbers below, never invent figures, flag small samples, plain and direct. "
                              'Return JSON only: {"headline": str (<=20 words), "bullets": [str, str, str] (each <=30 words)}.\n\n' + json.dumps(brief), 1500, thinking={"type": "between_tools"}))
        return s, "headline and three findings"
    rep["summary"] = step("report", write)
    if push:
        step("push", lambda: (lambda sent: (sent, ("Sent to " + " and ".join(sent)) if sent else "no Slack or email keys are set"))(deliver(rep)))
    else:
        emit(dict(step="push", label=dict(STEPS)["push"], status="done", detail="skipped (push is switched off)", secs=0))
    rep["steps"], rep["secs"], rep["usage"] = steps, round(time.time() - t_all, 1), dict(USAGE)
    rep["_corpus"] = [r["text"] for r in rows]                 # only used in memory for the public-safety check, never written out
    return rep


def clean(rep):
    rep = dict(rep); rep.pop("_corpus", None)
    return rep


def sanitise_for_public(rep):
    """The saved sample must not reuse a comment's wording: any topic or summary line that overlaps the comments is dropped."""
    import public_safety as safe
    corp = safe.corpus(rep.get("_corpus", []))
    for t in rep["topics"]:
        if safe.overlap(t["summary"], corp): t["summary"] = ""
    rep["summary"]["bullets"] = [b for b in rep["summary"]["bullets"] if not safe.overlap(b, corp)]
    if safe.overlap(rep["summary"]["headline"], corp): rep["summary"]["headline"] = f"How {rep['keyword']} is landing on YouTube"
    return clean(rep)


def slack_payload(rep):
    t, s = rep["totals"], rep["summary"]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"{rep['keyword']} on YouTube: keyword report"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*{s['headline']}*\n" + "\n".join(f"• {b}" for b in s["bullets"])}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{t['videos']} videos · {t['views']/1e6:.1f}M views · {t['comments']:,} comments read · sentiment score {t['score'] if t['score'] is not None else '–'}"}]}]
    if rep["topics"]: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Topics*\n" + "\n".join(f"• *{x['name']}* ({x['n']} comments, sentiment {x['score']:+d})" for x in rep["topics"][:5] if x["score"] is not None)}})
    top = [v for v in sorted(rep["videos"], key=lambda v: -(v["lift"] or 0)) if v["lift"]][:3]
    if top: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Highest-lift videos*\n" + "\n".join(f"• <{v['url']}|{v['title'][:70]}> ({v['channel']}, {v['lift']}x)" for v in top)}})
    return {"text": s["headline"], "blocks": blocks}


def deliver(rep):
    """Send the report to the owner's Slack channel and inbox (their own keys). Returns what was sent."""
    import urllib.request
    sent = []
    hook = secret("SLACK_WEBHOOK_URL", False)
    if hook:
        urllib.request.urlopen(urllib.request.Request(hook, data=json.dumps(slack_payload(rep)).encode(), headers={"content-type": "application/json"}), timeout=30); sent.append("Slack")
    key, to = secret("RESEND_API_KEY", False), secret("REPORT_EMAIL_TO", False)
    if key and to:
        s = rep["summary"]; li = "".join(f"<li>{b}</li>" for b in s["bullets"])
        tp = "".join(f"<li><b>{x['name']}</b>: {x['summary']} ({x['n']} comments, sentiment {x['score']:+d})</li>" for x in rep["topics"][:5] if x["score"] is not None)
        html = f"<div style='font:14px Arial'><h2>{rep['keyword']} on YouTube</h2><p><b>{s['headline']}</b></p><ul>{li}</ul><h3>Topics</h3><ul>{tp}</ul></div>"
        body = {"from": "YouTube Creator Social Listening <onboarding@resend.dev>", "to": [to], "subject": f"{rep['keyword']} on YouTube: keyword report", "html": html}
        urllib.request.urlopen(urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "launch-pulse/1.0"}), timeout=30); sent.append("email")
    return sent


def main():
    kw = " ".join(a for a in sys.argv[1:] if not a.startswith("--")).strip()
    if not kw: raise SystemExit('usage: python3 explore.py "keyword" [--sample]')
    rep = build(kw, push="--push" in sys.argv, emit=lambda e: print(f"  [{e['status']}] {e['label']}" + (f" ({e['secs']}s): {e['detail']}" if e["status"] == "done" else ""), flush=True))
    print("\n" + rep["summary"]["headline"]); [print(" -", b) for b in rep["summary"]["bullets"]]
    print(f"\n{rep['secs']}s | tokens in {rep['usage']['in']:,} out {rep['usage']['out']:,}")
    if "--sample" in sys.argv:
        out = os.path.join(HERE, "state", "explore_sample.json")
        json.dump(sanitise_for_public(rep), open(out, "w"), ensure_ascii=False, indent=1); print("saved", out)


if __name__ == "__main__":
    main()
