#!/usr/bin/env python3
"""Step 8: Slack digest and alerts through the incoming webhook (SLACK_WEBHOOK_URL).
  python3 notify.py              weekly digest (headline, key findings, scale candidates, alerts)
  python3 notify.py --alerts     only post when an alert fired
  python3 notify.py --dry-run    print the payload instead of posting"""
import json, sys, urllib.request
from common import load, secret


def build(ins, alerts_only=False):
    n, m, al = ins["narrative"], ins["metrics"], ins["alerts"]
    if alerts_only:
        if not al: return None
        return {"text": "iPhone Duo alert", "blocks": [{"type": "header", "text": {"type": "plain_text", "text": "iPhone Duo alert"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f":rotating_light: {a['text']}" for a in al)}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Data through {ins['as_of']}. Mention me to dig in, for example: _why did negative sentiment rise this week?_"}]}]}
    t, s = m["totals"], m["sentiment"]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "iPhone Duo on YouTube: weekly readout"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*{n['headline']}*\n{n['summary']}"}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{t['videos']} videos · {t['views']/1e6:.0f}M views · {t['comments_en']:,} English comments · product sentiment {s['pos']*100:.0f}% positive, {s['neg']*100:.0f}% negative · data through {ins['as_of']}"}]}]
    if al: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Alerts*\n" + "\n".join(f":rotating_light: {a['text']}" for a in al)}})
    blocks += [{"type": "divider"}, {"type": "section", "text": {"type": "mrkdwn", "text": "*Highlights*\n" + "\n".join(f"{i+1}. *{f['title']}*\n    _{f['action']}_" for i, f in enumerate(n["findings"]))}}]
    if m.get("topics"): blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Audience topics*\n" + "\n".join(f"• *{c['name']}* ({c['n']:,} comments, {c['pos']*100:.0f}% positive, {c['neg']*100:.0f}% negative" + (", new" if c["discovered"] else "") + (", gaining" if (c["trend"] or 0) >= 1.5 and c["recent"] >= 15 else "") + ")" for c in m["topics"][:5])}})
    ch = m.get("changes")
    if ch: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Since {ch['since']}*\n{ch['new_videos']} new videos, {ch['new_comments']:,} new comments" + "".join(f"\n• new topic: *{t['name']}* ({t['n']})" for t in ch["new_topics"])}})
    if m.get("watchlist"): blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Watchlist*\n" + "\n".join(f"• *{w['name']}*: {w['why']}" for w in m["watchlist"])}})
    if m["highest_lift"]: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Highest-lift videos*\n" + "\n".join(f"• <{c['url']}|{c['title'][:70]}> ({c['creator']}, {c['rel_lift']}x lift" + (f", {c['pos']*100:.0f}% positive / {c['neg']*100:.0f}% negative)" if c.get('pos') is not None and c['product_comments'] >= 10 else ", too few comments for sentiment)") for c in m["highest_lift"][:3])}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Ask a follow-up: mention *@Launch Pulse* or message me. The full report is in your inbox."}]})
    return {"text": n["headline"], "blocks": blocks}


def post(payload):
    req = urllib.request.Request(secret("SLACK_WEBHOOK_URL"), data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode()


def main():
    ins = load("insights.json")
    payload = build(ins, "--alerts" in sys.argv)
    if payload is None: print("no alerts; nothing posted"); return
    if "--dry-run" in sys.argv: print(json.dumps(payload, indent=1, ensure_ascii=False)); return
    print("Slack:", *post(payload))


if __name__ == "__main__":
    main()
