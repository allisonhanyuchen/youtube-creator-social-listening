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
        return {"text": "Launch Pulse alert", "blocks": [{"type": "header", "text": {"type": "plain_text", "text": "Launch Pulse alert"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f":rotating_light: {a['text']}" for a in al)}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Data through {ins['as_of']}. Mention me to dig in, for example: _why did negative sentiment rise this week?_"}]}]}
    t, s = m["totals"], m["sentiment_all"]
    seen, cand = set(), []
    for c in m["scale_candidates"]:
        if c["creator"] not in seen: seen.add(c["creator"]); cand.append(c)
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "Launch Pulse weekly readout"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*{n['headline']}*\n{n['summary']}"}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{t['videos']} videos · {t['views']/1e6:.0f}M views · {t['comments_en']:,} English comments · product sentiment {s['pos']*100:.0f}% positive, {s['neg']*100:.0f}% negative · data through {ins['as_of']}"}]}]
    if al: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Alerts*\n" + "\n".join(f":rotating_light: {a['text']}" for a in al)}})
    blocks += [{"type": "divider"}, {"type": "section", "text": {"type": "mrkdwn", "text": "*What to do with it*\n" + "\n".join(f"{i+1}. *{f['title']}*\n    _{f['action']}_" for i, f in enumerate(n["findings"]))}}]
    if cand: blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Organic videos worth scaling*\n" + "\n".join(f"• <{c['url']}|{c['title'][:70]}> ({c['creator']}, {c['rel_lift']}x own baseline, {c['pos']*100:.0f}% positive)" for c in cand[:3])}})
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
