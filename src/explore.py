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
import textcluster as tc

MAX_VIDEOS, MAX_COMMENTS = 20, 20
PRODUCT_SIDE = {"product", "price_value", "competitor"}
STEPS = [("search", "Retrieving videos from the YouTube API"), ("baseline", "Checking each channel's usual views"), ("comments", "Pulling the top comments"),
         ("label", "Reading every comment with Claude"), ("topics", "Finding and naming topics"), ("report", "Writing the report"), ("push", "Pushing the report to email and Slack")]


T_CODE = {"P": "product", "V": "price_value", "C": "video_or_creator", "R": "competitor", "O": "other"}
S_CODE = {"+": "positive", "0": "neutral", "-": "negative"}


def parse_label_lines(text):
    """Parse the compact reply  i|lang|target|sent|intent  into {index: label}. Malformed lines are skipped."""
    out = {}
    for ln in text.splitlines():
        p = ln.strip().split("|")
        if len(p) != 5 or not p[0].strip().isdigit(): continue
        out[int(p[0])] = {"l": "en" if p[1].strip() == "e" else "other", "t": T_CODE.get(p[2].strip()), "s": S_CODE.get(p[3].strip()), "in": p[4].strip()}
    return out


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
            parsed = parse_label_lines(claude(prompt, 3000, thinking={"type": "between_tools"}))
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


def side_rows(state):
    """English, product-side comments with their labels, rebuilt from the state so each stage can run in its own request."""
    flat = [(vid, t) for vid, ts in state["raw"].items() for t in ts]
    return [dict(vid=vid, text=t, lab=l) for (vid, t), l in zip(flat, state["labs"]) if l and l["l"] == "en" and l["t"] in PRODUCT_SIDE]


SENT = {"positive": 0, "neutral": 1, "negative": 2}


def do_search(state):
    state["vids"] = search_videos(state["keyword"])
    if not state["vids"]: raise SystemExit(f"No English videos with 1,000+ views found for '{state['keyword']}'. Try a broader keyword.")
    return f"{len(state['vids'])} videos from {len({x['channel_id'] for x in state['vids']})} channels"


def do_baseline(state):
    for v, base, subs in pool(channel_baseline, state["vids"]):
        v["subs"] = subs
        v["lift"] = round(v["views"] / base, 2) if base else None
    return f"lift vs the channel's own usual views for {sum(1 for v in state['vids'] if v['lift'])} of {len(state['vids'])} videos"


def do_comments(state):
    state["raw"] = dict(pool(pull_comments, state["vids"]))
    return f"{sum(len(x) for x in state['raw'].values()):,} comments from {sum(1 for x in state['raw'].values() if x)} videos"


def do_label(state):
    flat = [t for ts in state["raw"].values() for t in ts]
    state["labs"] = label(flat, state["keyword"])
    return f"{sum(1 for x in state['labs'] if x)} of {len(flat)} comments labelled (target, sentiment, intent)"


def do_topics(state):
    side = side_rows(state); texts = [r["text"] for r in side]
    state["topics"] = []
    if len(texts) < 40: return "too few product comments to find topics"
    vecs, cl = tc.clusters(texts, k=max(3, min(7, len(texts) // 40)), min_size=max(8, len(texts) // 25))
    names = name_topics(cl, texts, state["keyword"]) if cl else {}
    for c in cl:
        ps = [0, 0, 0]
        for i in c["members"]: ps[SENT[side[i]["lab"]["s"] or "neutral"]] += 1
        nm = names.get(c["id"], {})
        state["topics"].append(dict(name=nm.get("name") or "Topic", summary=nm.get("summary", ""), n=c["n"], share=round(c["n"] / len(texts), 3), ps=ps, score=net(ps), terms=c["terms"][:6]))
    state["topics"].sort(key=lambda t: -t["n"])
    return f"{len(state['topics'])} topics covering {sum(t['n'] for t in state['topics'])} of {len(texts)} product comments"


def assemble(state):
    per = {}
    for r in side_rows(state): per.setdefault(r["vid"], [0, 0, 0])[SENT[r["lab"]["s"] or "neutral"]] += 1
    videos = [dict(id=v["id"], url=v["url"], title=v["title"], channel=v["channel"], subs=v.get("subs"), views=v["views"], published=v["published"], lift=v["lift"], ps=per.get(v["id"], [0, 0, 0])) for v in state["vids"]]
    tot = [sum(x["ps"][i] for x in videos) for i in range(3)]
    return dict(keyword=state["keyword"], generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), caps=dict(videos=MAX_VIDEOS, comments=MAX_COMMENTS),
                totals=dict(videos=len(videos), channels=len({v["channel_id"] for v in state["vids"]}), views=sum(v["views"] for v in videos), comments=sum(len(x) for x in state["raw"].values()),
                            product_comments=sum(tot), ps=tot, score=net(tot)), videos=videos, topics=state["topics"])


def do_report(state):
    rep = assemble(state)
    brief = dict(keyword=state["keyword"], totals=rep["totals"], topics=[{k: t[k] for k in ("name", "n", "score")} for t in rep["topics"]],
                 top_lift=[{k: v[k] for k in ("title", "channel", "lift", "views")} for v in sorted([x for x in rep["videos"] if x["lift"]], key=lambda x: -x["lift"])[:3]])
    state["summary"] = parse_json(claude("You write a three-line readout of how a topic is landing on YouTube. Lead with the net sentiment score (positive % minus negative %, -100 to +100) when you mention sentiment. "
                                         "Use ONLY the numbers below, never invent figures, flag small samples, plain and direct. "
                                         'Return JSON only: {"headline": str (<=20 words), "bullets": [str, str, str] (each <=30 words)}.\n\n' + json.dumps(brief), 1500, thinking={"type": "between_tools"}))
    return "headline and three findings"


def do_push(state):
    rep = assemble(state); rep["summary"] = state["summary"]
    sent = deliver(rep)
    return ("Sent to " + " and ".join(sent)) if sent else "no Slack or email keys are set"


FUNCS = dict(search=do_search, baseline=do_baseline, comments=do_comments, label=do_label, topics=do_topics, report=do_report, push=do_push)


def run_step(sid, state):
    """One stage on its own: used by the hosted endpoint, which gets the state from the browser and hands it back."""
    t0 = time.time()
    detail = FUNCS[sid](state)
    return state, detail, round(time.time() - t0, 1)


def finish(state, steps, t_all):
    rep = assemble(state); rep["summary"] = state["summary"]
    rep["steps"], rep["secs"], rep["usage"] = steps, round(time.time() - t_all, 1), dict(USAGE)
    return rep


def build(keyword, emit=lambda e: None, push=False):
    t_all, steps, state = time.time(), [], dict(keyword=keyword)
    for sid, label_ in STEPS:
        if sid == "push" and not push:
            emit(dict(step="push", label=label_, status="done", detail="skipped (push is switched off)", secs=0)); continue
        emit(dict(step=sid, label=label_, status="start"))
        _, detail, secs = run_step(sid, state)
        steps.append(dict(id=sid, label=label_, secs=secs, detail=detail))
        emit(dict(step=sid, label=label_, status="done", detail=detail, secs=secs))
    rep = finish(state, steps, t_all)
    rep["_corpus"] = [r["text"] for r in side_rows(state)]       # only used in memory for the public-safety check, never written out
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


def email_html(rep):
    """The keyword report as an email in the same look as the daily email (report.py): headline, score tiles, topics and videos with the sentiment score first."""
    import report as R
    esc, t, sm = R.esc, rep["totals"], rep["summary"]
    caps = rep.get("caps") or dict(videos=MAX_VIDEOS, comments=MAX_COMMENTS)
    sc = lambda ps: (f"{net(ps):+d}" if net(ps) is not None else "–")
    kp = lambda v, l: (f'<td style="padding:10px 14px;border:1px solid {R.LINE};border-radius:8px"><div style="font:600 22px Arial,sans-serif;color:{R.INK}">{v}</div>'
                       f'<div style="font:12px Arial,sans-serif;color:{R.MUTE}">{l}</div></td><td style="width:8px"></td>')
    kpis = kp(t["videos"], "videos") + kp(f"{t['views']/1e6:.1f}M", "views") + kp(f"{t['comments']:,}", "comments read") + kp(sc(t["ps"]), "sentiment score (positive minus negative, -100 to +100)")
    bullets = "".join(f'<div style="padding:3px 0">&bull; {esc(b)}</div>' for b in sm["bullets"])
    topics = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid {R.LINE};font:13px Arial,sans-serif;width:300px"><b>{esc(x["name"])}</b><div style="color:{R.MUTE};font-size:12px">{esc(x["summary"])}</div>'
                     f'<div style="color:{R.MUTE};font-size:11px">{x["n"]} comments</div></td><td style="padding:6px 8px;border-top:1px solid {R.LINE};font:13px Arial,sans-serif"><b>{sc(x["ps"])}</b><br>{R.sbar(*x["ps"], w=150)}</td></tr>'
                     for x in rep["topics"][:5])
    top = [v for v in sorted(rep["videos"], key=lambda v: -(v["lift"] or 0)) if v["lift"]][:5]
    vids = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid {R.LINE};font:13px Arial,sans-serif"><a href="{esc(v["url"])}" style="color:{R.ACC};text-decoration:none">{esc(v["title"][:80])}</a><br>'
                   f'<span style="color:{R.MUTE};font-size:12px">{esc(v["channel"])} &middot; {v["lift"]}x lift &middot; {v["views"]/1e3:.0f}k views &middot; '
                   f'{("sentiment " + sc(v["ps"])) if sum(v["ps"]) >= 10 else "too few comments for sentiment"}</span></td></tr>' for v in top)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(rep['keyword'])} keyword report</title></head><body style="margin:0;background:#f6f6f3"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f3"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:100%;background:#ffffff;border:1px solid {R.LINE};border-radius:12px">
<tr><td style="padding:24px 28px 0;font:600 20px Arial,sans-serif;color:{R.INK}">{esc(rep['keyword'])} on YouTube<span style="font:13px Arial,sans-serif;color:{R.MUTE};font-weight:400"> &nbsp;keyword report &middot; {caps['videos']} videos x {caps['comments']} comments</span></td></tr>
<tr><td style="padding:12px 28px 0;font:600 17px/1.4 Arial,sans-serif;color:{R.INK}">{esc(sm['headline'])}</td></tr>
<tr><td style="padding:8px 28px 0;font:14px/1.55 Arial,sans-serif;color:{R.INK}">{bullets}</td></tr>
<tr><td style="padding:16px 28px 0"><table role="presentation" cellpadding="0" cellspacing="0"><tr>{kpis}</tr></table></td></tr>
{R.h("Topics people talk about")}<tr><td style="padding:0 28px"><table role="presentation" cellpadding="0" cellspacing="0">{topics}</table></td></tr>
{R.h("Highest-lift videos")}<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{vids}</table></td></tr>
<tr><td style="padding:22px 28px 24px;font:12px/1.5 Arial,sans-serif;color:{R.MUTE};border-top:1px solid {R.LINE}">A small sample: the top videos and comments for this keyword, read by Claude. Treat the numbers as directional.</td></tr>
</table></td></tr></table></body></html>"""


def deliver(rep):
    """Send the report to the owner's Slack channel and inbox (their own keys). Returns what was sent."""
    import urllib.request
    sent = []
    hook = secret("SLACK_WEBHOOK_URL", False)
    if hook:
        urllib.request.urlopen(urllib.request.Request(hook, data=json.dumps(slack_payload(rep)).encode(), headers={"content-type": "application/json"}), timeout=30); sent.append("Slack")
    key, to = secret("RESEND_API_KEY", False), secret("REPORT_EMAIL_TO", False)
    if key and to:
        html = email_html(rep)
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
