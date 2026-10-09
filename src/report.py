#!/usr/bin/env python3
"""Step 7: HTML email report from data/insights.json. Table layout and inline CSS so it renders in mail clients.
Always writes data/report.html (preview). Sends through Resend only when RESEND_API_KEY and REPORT_EMAIL_TO exist and --send is passed."""
import base64, json, os, sys, urllib.request
from common import DATA, HERE, load, secret, title

INK, MUTE, LINE, ACC = "#1d1d1b", "#66665f", "#e3e3dd", "#2f5bea"
POS, NEU, NEG = "#2f8f5b", "#c4c4bb", "#d0553f"
COL = {"organic": "#5b7c99", "seeded": "#7a5fc7", "sponsored": "#d9822b"}
FMT = {"first_impressions": "First impressions", "full_review": "Full review", "comparison": "Comparison", "upgrade_advice": "Upgrade advice", "keynote_recap": "Keynote recap",
       "durability_test": "Durability test", "explainer_tips": "Explainer / tips", "rumor_leak": "Rumor / leak", "meme_short": "Meme / reaction", "other": "Other"}
pct = lambda x, d=0: "–" if x is None else f"{x*100:.{d}f}%"
esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar(frac, color, w=140):
    f = max(0, min(1, frac or 0)); a = round(w * f)
    return f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:{w}px"><tr><td style="width:{a}px;height:8px;background:{color};font-size:0;line-height:0">&nbsp;</td><td style="height:8px;background:{LINE};font-size:0;line-height:0">&nbsp;</td></tr></table>'


def sbar(p, u, g, w=180):
    t = (p + u + g) or 1
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:{w}px"><tr><td style="width:{round(w*p/t)}px;height:8px;background:{POS};font-size:0;line-height:0">&nbsp;</td>'
            f'<td style="width:{round(w*u/t)}px;height:8px;background:{NEU};font-size:0;line-height:0">&nbsp;</td><td style="height:8px;background:{NEG};font-size:0;line-height:0">&nbsp;</td></tr></table>')


def h(t):
    return f'<tr><td style="padding:22px 28px 6px;font:600 12px Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:{MUTE}">{t}</td></tr>'


def sc(x):
    return "–" if x is None else f"{x:+d}"


def num(x):
    return f"{x/1e9:.1f}B" if x >= 1e9 else f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}k" if x >= 1e3 else str(x)


LABEL = {"weekly": "monthly", "daily": "quick"}      # what a reader sees: the full pass runs on the monthly schedule


def build(ins, example=False, period="weekly"):
    """The email follows the page: Summary, Overview, Content performance, Audience insights, then what changed and the watchlist."""
    m, n, al = ins["metrics"], ins["narrative"], ins["alerts"]
    o, hl = m["overview"], m["highlights"]
    kp = lambda v, l: (f'<td style="padding:10px 12px;border:1px solid {LINE};border-radius:8px;width:33%"><div style="font:600 20px Arial,sans-serif;color:{INK}">{v}</div>'
                       f'<div style="font:12px Arial,sans-serif;color:{MUTE}">{l}</div></td>')
    row = lambda *cells: "<tr>" + '<td style="width:8px"></td>'.join(cells) + "</tr>"
    kpis = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + row(kp(o["creators"], "creators"), kp(o["videos"], "content"), kp(num(o["views"]), "views"))
            + '<tr><td colspan="5" style="height:8px"></td></tr>' + row(kp(num(o["engagements"]), "engagements"), kp(pct(o["engagement_rate"], 2), "engagement rate"), kp(pct(o["outperformer_rate"]), f"outperformers ({pct(o['underperformer_rate'])} under)")) + "</table>")
    # content performance: top 3 and bottom 3 content types per measure
    fmt = lambda c: FMT.get(c["format"], c["format"])
    def ctl(items, key, f):
        return "".join(f'<div style="padding:2px 0">{esc(fmt(c))} <span style="color:{MUTE}">{f(c[key])}</span></div>' for c in items) or f'<span style="color:{MUTE}">not enough data</span>'
    cp_rows = ""
    for label, key, f, grp in (("Views", "views", num, hl["content"]["views"]), ("Engagement rate", "engagement_rate", lambda v: pct(v, 2), hl["content"]["engagement"]), ("Sentiment score", "score", sc, hl["content"]["sentiment"])):
        cp_rows += (f'<tr><td style="padding:8px 0;border-top:1px solid {LINE};font:600 13px Arial,sans-serif;color:{INK};width:130px;vertical-align:top">{label}</td>'
                    f'<td style="padding:8px 8px;border-top:1px solid {LINE};font:13px Arial,sans-serif;vertical-align:top">{ctl(grp["high"], key, f)}</td>'
                    f'<td style="padding:8px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif;vertical-align:top">{ctl(grp["low"], key, f)}</td></tr>')
    content = (f'<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr style="font:11px Arial,sans-serif;color:{MUTE}"><td></td>'
               f'<td style="padding:0 8px">Highest 3 content types</td><td>Lowest 3</td></tr>{cp_rows}</table>'
               f'<div style="font:12px Arial,sans-serif;color:{MUTE};padding-top:6px">Content types with at least 5 videos; the sentiment score needs 30+ product comments.</div></td></tr>')
    top = "".join(f'<div style="padding:3px 0;font:13px Arial,sans-serif"><a href="{c["url"]}" style="color:{ACC};text-decoration:none">{esc(c["title"][:70])}</a> <span style="color:{MUTE};font-size:12px">{c["rel_lift"]}x lift'
                  f'{(" · sentiment " + sc(round((c["pos"] - c["neg"]) * 100))) if c.get("pos") is not None and c["product_comments"] >= 10 else " · too few comments for sentiment"}</span></div>' for c in m["highest_lift"][:3])
    # audience insights: topics by sentiment, size and trend
    tl = lambda items, f: "".join(f'<div style="padding:2px 0">{esc(t["name"])} <span style="color:{MUTE}">{f(t)}</span></div>' for t in items) or f'<span style="color:{MUTE}">none right now</span>'
    ts = lambda t: f'{sc(t["score"])} · n={t["n"]:,}'
    au_rows = ""
    for label, items, f in (("Highest sentiment", hl["topics"]["sentiment"]["high"], ts), ("Lowest sentiment", hl["topics"]["sentiment"]["low"], ts),
                            ("Largest", hl["topics"]["largest"], lambda t: f'{t["n"]:,} comments · {sc(t["score"])}'), ("Gaining", hl["topics"]["gaining"], lambda t: f'{t["trend"]}x its usual share')):
        au_rows += (f'<tr><td style="padding:8px 0;border-top:1px solid {LINE};font:600 13px Arial,sans-serif;color:{INK};width:130px;vertical-align:top">{label}</td>'
                    f'<td style="padding:8px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif">{tl(items, f)}</td></tr>')
    audience = (f'<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{au_rows}</table>'
                f'<div style="font:12px Arial,sans-serif;color:{MUTE};padding-top:6px">Top 3 topics from local clustering of comments, named by AI. Sentiment ranking needs 50+ comments; score = positive % minus negative %.</div></td></tr>')
    alerts = "".join(f'<tr><td style="padding:10px 28px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#fdf3e1;border-left:4px solid #d9822b;padding:9px 12px;'
                     f'font:13px Arial,sans-serif;color:#6b4710">{esc(a["text"])}</td></tr></table></td></tr>' for a in al[:3])
    ch = m.get("changes")
    if ch:
        bits = [f'{ch["new_videos"]} new videos and {ch["new_comments"]:,} new comments since {esc(ch["since"])}.']
        if ch["sentiment_delta"]: bits.append(f'Sentiment score: {(ch["sentiment_delta"]["pos"] - ch["sentiment_delta"]["neg"])*100:+.1f} pts.')
        bits += [f'New topic: <b>{esc(t["name"])}</b> ({t["n"]} comments).' for t in ch["new_topics"]]
        changes = "".join(f'<div style="padding:3px 0">{b}</div>' for b in bits)
    else:
        changes = "First refresh: nothing to compare with yet. Changes appear from the next run."
    watch = "".join(f'<div style="padding:3px 0"><b>{esc(w["name"])}</b>: {esc(w["why"])}</div>' for w in m.get("watchlist", [])) or "Nothing flagged by the numbers this week."
    ex_tag = '<span style="background:#fdf3e1;color:#6b4710;border-radius:6px;padding:2px 8px;font-size:12px;margin-right:8px">EXAMPLE</span>' if example else ""
    ex_note = '<tr><td style="padding:8px 28px 0;font:12px Arial,sans-serif;color:#6b4710">Example of the email, to show the format. Figures are illustrative and not guaranteed to be accurate.</td></tr>' if example else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YouTube Creator Social Listening</title></head><body style="margin:0;background:#f6f6f3"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f3"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:100%;background:#ffffff;border:1px solid {LINE};border-radius:12px">
<tr><td style="padding:24px 28px 0;font:600 20px Arial,sans-serif;color:{INK}">{ex_tag}{esc(title())}<span style="font:13px Arial,sans-serif;color:{MUTE};font-weight:400"> &nbsp;{LABEL.get(period, period)} readout &middot; data through {ins["as_of"]}</span></td></tr>
{ex_note}
{h("Summary")}<tr><td style="padding:0 28px;font:600 17px/1.4 Arial,sans-serif;color:{INK}">{esc(n["headline"])}</td></tr>
<tr><td style="padding:8px 28px 0;font:14px/1.55 Arial,sans-serif;color:{INK}">{esc(n["summary"])}</td></tr>
{h("Overview")}<tr><td style="padding:0 28px">{kpis}</td></tr>
{h("Content performance")}{content}
<tr><td style="padding:12px 28px 0;font:12px Arial,sans-serif;color:{MUTE}">Highest-lift videos</td></tr><tr><td style="padding:2px 28px 0">{top}</td></tr>
{h("Audience insights")}{audience}
{h("What changed since last refresh")}<tr><td style="padding:0 28px;font:13px/1.5 Arial,sans-serif;color:{INK}">{changes}</td></tr>
{alerts}
{h("Watchlist")}<tr><td style="padding:0 28px;font:13px/1.5 Arial,sans-serif;color:{INK}">{watch}<div style="padding-top:6px;color:{MUTE}">{esc(n["watch"])}</div></td></tr>
<tr><td style="padding:22px 28px 24px;font:12px/1.5 Arial,sans-serif;color:{MUTE};border-top:1px solid {LINE}">Built from public YouTube data (official API) on English-language videos about the product. Comments are a sample of up to 60 per video, labelled by Claude. Differences between groups are associations, and small groups can swing. Open the dashboard to filter and drill down; mention the Slack app to ask a follow-up.</td></tr>
</table></td></tr></table></body></html>"""


def main():
    ins = load("insights.json")
    period = "daily" if "--daily" in sys.argv else "weekly"
    html = build(ins, period=period)
    out = os.path.join(DATA, "report.html"); open(out, "w", encoding="utf-8").write(html)
    print("wrote", out)
    if "--send" not in sys.argv: return
    key, to = secret("RESEND_API_KEY", False), secret("REPORT_EMAIL_TO", False)
    if not (key and to): print("RESEND_API_KEY or REPORT_EMAIL_TO missing; not sent"); return
    body = {"from": "YouTube Creator Social Listening <onboarding@resend.dev>", "to": [to], "subject": f"{title()} ({LABEL.get(period, period)}): {ins['narrative']['headline'][:80]}", "html": html}
    dash = os.path.join(HERE, "dashboard.html")
    if os.path.exists(dash): body["attachments"] = [{"filename": "launch-pulse-dashboard.html", "content": base64.b64encode(open(dash, "rb").read()).decode()}]
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "launch-pulse/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: print("Resend:", r.status, r.read().decode()[:200])
    except urllib.error.HTTPError as e: raise SystemExit(f"Resend error {e.code}: {e.read().decode()[:300]}")


if __name__ == "__main__":
    main()
