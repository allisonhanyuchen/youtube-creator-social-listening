#!/usr/bin/env python3
"""Step 8: Slack digest and alerts through the incoming webhook (SLACK_WEBHOOK_URL).
  python3 notify.py              weekly digest (headline, key findings, scale candidates, alerts)
  python3 notify.py --alerts     only post when an alert fired
  python3 notify.py --dry-run    print the payload instead of posting"""
import json, sys, urllib.request
from common import load, secret


def build(ins, alerts_only=False, example=False, period="weekly"):
    n, m, al = ins["narrative"], ins["metrics"], ins["alerts"]
    if alerts_only:
        if not al: return None
        return {"text": "iPhone Duo alert", "blocks": [{"type": "header", "text": {"type": "plain_text", "text": "iPhone Duo alert"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f":rotating_light: {a['text']}" for a in al)}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Data through {ins['as_of']}. Mention me to dig in, for example: _why did negative sentiment rise this week?_"}]}]}
    t, s = m["totals"], m["sentiment"]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": ("EXAMPLE · " if example else "") + f"iPhone Duo on YouTube: {period} readout"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*{n['headline']}*\n{n['summary']}"}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{t['videos']} videos · {t['views']/1e6:.0f}M views · {t['comments_en']:,} English comments · sentiment score {(s['pos'] - s['neg'])*100:+.0f} · data through {ins['as_of']}"}]}]
    if m.get("highest_lift"): blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Content performance: highest-lift videos*\n" + "\n".join(f"• <{c['url']}|{c['title'][:70]}> ({c['creator']}, {c['rel_lift']}x lift" + (f", sentiment {(c['pos'] - c['neg'])*100:+.0f}" if c["pos"] is not None else ", too few comments for sentiment") + ")" for c in m["highest_lift"][:3])}})
    if m.get("topics"): blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Audience insights: top topics*\n" + "\n".join(f"• *{c['name']}* ({c['n']:,} comments, sentiment {(c['pos'] - c['neg'])*100:+.0f}" + (", new" if c["discovered"] else "") + (", gaining" if (c["trend"] or 0) >= 1.5 and c["recent"] >= 15 else "") + ")" for c in m["topics"][:5])}})
    ch = m.get("changes")
    chg = "*Changes since last refresh*\n" + (f"{ch['new_videos']} new videos, {ch['new_comments']:,} new comments since {ch['since']}" + "".join(f"\n• new topic: *{t['name']}* ({t['n']})" for t in ch["new_topics"]) if ch else "First refresh: nothing to compare with yet.")
    if al: chg += "\n" + "\n".join(f":rotating_light: {a['text']}" for a in al[:3])
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chg}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Watchlist*\n" + ("\n".join(f"• *{w['name']}*: {w['why']}" for w in m["watchlist"]) if m.get("watchlist") else "Nothing flagged by the numbers this week.")}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ("Example of the Slack digest, to show the format. Figures are illustrative and not guaranteed to be accurate. " if example else "") + "Ask a follow-up: mention the app or message it. The full report is in your inbox."}]})
    return {"text": n["headline"], "blocks": blocks}


def post(payload):
    req = urllib.request.Request(secret("SLACK_WEBHOOK_URL"), data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode()


def main():
    ins = load("insights.json")
    payload = build(ins, "--alerts" in sys.argv, period="daily" if "--daily" in sys.argv else "weekly")
    if payload is None: print("no alerts; nothing posted"); return
    if "--dry-run" in sys.argv: print(json.dumps(payload, indent=1, ensure_ascii=False)); return
    print("Slack:", *post(payload))


if __name__ == "__main__":
    main()
