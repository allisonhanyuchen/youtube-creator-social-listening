#!/usr/bin/env python3
"""Step 8: Slack digest and alerts through the incoming webhook (SLACK_WEBHOOK_URL).
  python3 notify.py              weekly digest (headline, key findings, scale candidates, alerts)
  python3 notify.py --alerts     only post when an alert fired
  python3 notify.py --dry-run    print the payload instead of posting"""
import json, sys, urllib.request
from common import load, secret, product, title


def slack_text(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "/")


LABEL = {"weekly": "monthly", "daily": "quick"}


def build(ins, alerts_only=False, example=False, period="weekly"):
    n, m, al = ins["narrative"], ins["metrics"], ins["alerts"]
    if alerts_only:
        if not al: return None
        return {"text": f"{product()['name']} alert", "blocks": [{"type": "header", "text": {"type": "plain_text", "text": f"{product()['name']} alert"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f":rotating_light: {a['text']}" for a in al)}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Data through {ins['as_of']}. Mention me to dig in, for example: _why did negative sentiment rise this week?_"}]}]}
    o, hl = m["overview"], m["highlights"]
    sc = lambda x: "–" if x is None else f"{x:+d}"
    num = lambda x: f"{x/1e9:.1f}B" if x >= 1e9 else f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}k" if x >= 1e3 else str(x)
    names = {"first_impressions": "First impressions", "full_review": "Full review", "comparison": "Comparison", "upgrade_advice": "Upgrade advice", "keynote_recap": "Keynote recap",
             "durability_test": "Durability test", "explainer_tips": "Explainer / tips", "rumor_leak": "Rumor / leak", "meme_short": "Meme / reaction", "other": "Other"}
    cl = lambda items, key, f: ", ".join(f"{names.get(c['format'], c['format'])} {f(c[key])}" for c in items) or "not enough data"
    tl = lambda items, f: ", ".join(f"{x['name']} {f(x)}" for x in items) or "none right now"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": ("EXAMPLE · " if example else "") + f"{title()}: {LABEL.get(period, period)} readout"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary*\n*{n['headline']}*\n{n['summary']}"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": f"*Overview*\n{o['creators']} creators · {o['videos']} content · {num(o['views'])} views · {num(o['engagements'])} engagements · {o['engagement_rate']*100:.2f}% engagement rate · "
                                                                  f"{o['outperformer_rate']*100:.0f}% outperformers ({o['underperformer_rate']*100:.0f}% under)"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": "*Content performance* (content types, highest 3 | lowest 3)\n"
                    f"• *Views*: {cl(hl['content']['views']['high'], 'views', num)} | {cl(hl['content']['views']['low'], 'views', num)}\n"
                    f"• *Engagement rate*: {cl(hl['content']['engagement']['high'], 'engagement_rate', lambda v: f'{v*100:.2f}%')} | {cl(hl['content']['engagement']['low'], 'engagement_rate', lambda v: f'{v*100:.2f}%')}\n"
                    f"• *Sentiment score*: {cl(hl['content']['sentiment']['high'], 'score', sc)} | {cl(hl['content']['sentiment']['low'], 'score', sc)}"
                    + ("\n*Highest-lift videos*\n" + "\n".join(f"• <{c['url']}|{slack_text(c['title'][:70])}> {c['rel_lift']}x lift" + (f" · sentiment {sc(round((c['pos'] - c['neg']) * 100))}" if c.get('pos') is not None and c['product_comments'] >= 10 else " · too few comments for sentiment") for c in m["highest_lift"][:3]) if m.get("highest_lift") else "")}},
              {"type": "section", "text": {"type": "mrkdwn", "text": "*Audience insights* (top 3 topics)\n"
                    f"• *Highest sentiment*: {tl(hl['topics']['sentiment']['high'], lambda x: sc(x['score']))}\n• *Lowest sentiment*: {tl(hl['topics']['sentiment']['low'], lambda x: sc(x['score']))}\n"
                    f"• *Largest*: {tl(hl['topics']['largest'], lambda x: format(x['n'], ','))}\n• *Gaining*: {tl(hl['topics']['gaining'], lambda x: str(x['trend']) + 'x')}"}}]
    ch = m.get("changes")
    chg = "*What changed since last refresh*\n" + (f"{ch['new_videos']} new videos, {ch['new_comments']:,} new comments since {ch['since']}" + "".join(f"\n• new topic: *{t['name']}* ({t['n']})" for t in ch["new_topics"]) if ch else "First refresh: nothing to compare with yet.")
    if al: chg += "\n" + "\n".join(f":rotating_light: {a['text']}" for a in al[:3])
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chg}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Watchlist*\n" + ("\n".join(f"• *{w['name']}*: {w['why']}" for w in m["watchlist"]) if m.get("watchlist") else "Nothing flagged by the numbers this week.")}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ("Example of the Slack digest, to show the format. Figures are illustrative and not guaranteed to be accurate. " if example else "") + f"Data through {ins['as_of']}. Ask a follow-up: mention the app or message it."}]})
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
