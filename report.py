#!/usr/bin/env python3
"""Step 7: HTML email report from data/insights.json. Table layout and inline CSS so it renders in mail clients.
Always writes data/report.html (preview). Sends through Resend only when RESEND_API_KEY and REPORT_EMAIL_TO exist and --send is passed."""
import base64, json, os, sys, urllib.request
from common import DATA, HERE, load, secret

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


def build(ins, example=False, period="weekly"):
    m, n, al = ins["metrics"], ins["narrative"], ins["alerts"]
    tot, s = m["totals"], m["sentiment"]
    kp = lambda v, l: f'<td style="padding:10px 14px;border:1px solid {LINE};border-radius:8px"><div style="font:600 22px Arial,sans-serif;color:{INK}">{v}</div><div style="font:12px Arial,sans-serif;color:{MUTE}">{l}</div></td><td style="width:8px"></td>'
    kpis = kp(f"{tot['videos']}", "videos") + kp(f"{tot['views']/1e6:.0f}M", "views") + kp(f"{tot['comments_en']:,}", "English comments") + kp(pct(s["pos"]) + " / " + pct(s["neg"]), "positive / negative on the product")
    alerts = "".join(f'<tr><td style="padding:10px 28px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#fdf3e1;border-left:4px solid #d9822b;padding:9px 12px;font:13px Arial,sans-serif;color:#6b4710">{esc(a["text"])}</td></tr></table></td></tr>' for a in al[:3])
    rows = ""
    for g, lab in (("small (<250k)", "Small channels (under 250k)"), ("mid (250k-1M)", "Mid-size (250k to 1M)"), ("large (1M+)", "Large channels (1M+)")):
        a = m["by_channel_size"][g]
        rows += (f'<tr><td style="padding:8px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif;color:{INK}"><b>{lab}</b><br><span style="color:{MUTE};font-size:12px">{a["videos"]} videos</span></td>'
                 f'<td style="padding:8px 8px;border-top:1px solid {LINE};font:13px Arial,sans-serif">{pct(a["outperformer_rate"])}<br>{bar(a["outperformer_rate"], ACC, 130)}</td>'
                 f'<td style="padding:8px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif">{pct(a["pos"])} / {pct(a["neg"])}<br>{sbar(a["pos"], 1 - a["pos"] - a["neg"], a["neg"], 130)}</td></tr>')
    size = (f'<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr style="font:11px Arial,sans-serif;color:{MUTE}"><td></td><td style="padding:0 8px">Outperformers</td><td>Positive / negative</td></tr>{rows}</table>'
            f'<div style="font:12px Arial,sans-serif;color:{MUTE};padding-top:6px">Outperformer = top quarter of views relative to the channel\'s own usual views, within Shorts or long videos.</div></td></tr>')
    fnd = "".join(f'<tr><td style="padding:10px 28px 0"><div style="font:600 15px Arial,sans-serif;color:{INK}">{i+1}. {esc(f["title"])}</div><div style="font:14px/1.5 Arial,sans-serif;color:{INK};padding-top:2px">{esc(f["detail"])}</div><div style="font:13px/1.5 Arial,sans-serif;color:{ACC};padding-top:3px"><b>Do next:</b> {esc(f["action"])}</div></td></tr>' for i, f in enumerate(n["findings"]))
    frows = "".join(f'<tr><td style="padding:5px 0;font:13px Arial,sans-serif;width:150px">{FMT.get(f["format"], f["format"])} <span style="color:{MUTE};font-size:11px">n={f["videos"]}</span></td><td style="padding:5px 8px">{bar(f["outperformer_rate"], ACC, 160)}</td><td style="font:13px Arial,sans-serif">{pct(f["outperformer_rate"])}</td></tr>' for f in m["by_format"])
    tags = lambda t: (" · <b>new</b>" if t["discovered"] else "") + (" · gaining" if (t["trend"] or 0) >= 1.5 and t["recent"] >= 15 else "")
    trows = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif;width:210px"><b>{esc(t["name"])}</b><div style="color:{MUTE};font-size:11px">n={t["n"]:,} · {pct(t["share"])} of topic comments{tags(t)}</div></td><td style="padding:6px 8px;border-top:1px solid {LINE}">{sbar(t["pos"], 1 - t["pos"] - t["neg"], t["neg"])}</td><td style="border-top:1px solid {LINE};font:12px Arial,sans-serif;color:{MUTE}">{pct(t["pos"])} pos · {pct(t["neg"])} neg</td></tr>' for t in m["topics"][:5])
    cov = m["coverage"]
    coverage = f'{cov["videos"]} videos from {cov["creators"]} creators (small {cov["by_level"]["small (<250k)"]}, mid {cov["by_level"]["mid (250k-1M)"]}, large {cov["by_level"]["large (1M+)"]}). {cov["with_sentiment"]} have 10+ product comments, so sentiment is read for those; {cov["comments_en"]:,} English comments in total.'
    ch = m.get("changes")
    if ch:
        bits = [f'{ch["new_videos"]} new videos and {ch["new_comments"]:,} new comments since {esc(ch["since"])}.']
        if ch["sentiment_delta"]: bits.append(f'Product sentiment: {ch["sentiment_delta"]["pos"]*100:+.1f} pts positive, {ch["sentiment_delta"]["neg"]*100:+.1f} pts negative.')
        bits += [f'New topic: <b>{esc(t["name"])}</b> ({t["n"]} comments).' for t in ch["new_topics"]]
        changes = "".join(f'<div style="padding:3px 0">{b}</div>' for b in bits)
    else:
        changes = "First refresh: nothing to compare with yet. Changes appear from the next run."
    watch = "".join(f'<div style="padding:3px 0"><b>{esc(w["name"])}</b>: {esc(w["why"])}</div>' for w in m.get("watchlist", [])) or "Nothing flagged by the numbers this week."
    top = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid {LINE};font:13px Arial,sans-serif"><a href="{c["url"]}" style="color:{ACC};text-decoration:none">{esc(c["title"][:80])}</a><br><span style="color:{MUTE};font-size:12px">{esc(c["creator"])} · {c["channel_size"]} · {FMT.get(c["format"], c["format"])} · {c["rel_lift"]}x lift · {c["views"]/1e3:.0f}k views · {(pct(c["pos"]) + " positive, " + pct(c["neg"]) + " negative") if c.get("pos") is not None and c["product_comments"] >= 10 else "too few comments for sentiment"}</span></td></tr>' for c in m["highest_lift"][:3])
    ex_tag = '<span style="background:#fdf3e1;color:#6b4710;border-radius:6px;padding:2px 8px;font-size:12px;margin-right:8px">EXAMPLE</span>' if example else ""
    ex_note = '<tr><td style="padding:8px 28px 0;font:12px Arial,sans-serif;color:#6b4710">Example of the weekly email, to show the format. Figures are illustrative and not guaranteed to be accurate.</td></tr>' if example else ""
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YouTube Creator Social Listening</title></head><body style="margin:0;background:#f6f6f3"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f3"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:100%;background:#ffffff;border:1px solid {LINE};border-radius:12px">
<tr><td style="padding:24px 28px 0;font:600 20px Arial,sans-serif;color:{INK}">{ex_tag}iPhone Duo on YouTube<span style="font:13px Arial,sans-serif;color:{MUTE};font-weight:400"> &nbsp;{period} readout · data through {ins["as_of"]}</span></td></tr>
{ex_note}
<tr><td style="padding:12px 28px 0;font:600 17px/1.4 Arial,sans-serif;color:{INK}">{esc(n["headline"])}</td></tr>
<tr><td style="padding:8px 28px 0;font:14px/1.55 Arial,sans-serif;color:{INK}">{esc(n["summary"])}</td></tr>
<tr><td style="padding:16px 28px 0"><table role="presentation" cellpadding="0" cellspacing="0"><tr>{kpis}</tr></table></td></tr>
{h("Overview")}{size}
{h("Audience insights")}<tr><td style="padding:0 28px"><table role="presentation" cellpadding="0" cellspacing="0">{trows}</table><div style="font:12px Arial,sans-serif;color:{MUTE};padding-top:4px"><span style="color:{POS}">&#9632;</span> positive <span style="color:{NEU}">&#9632;</span> neutral <span style="color:{NEG}">&#9632;</span> negative. Topics come from local clustering of comments, named by AI; <b>new</b> means found after the first run.</div></td></tr>
{h("Content performance: highest-lift videos")}<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{top}</table></td></tr>
{h("What changed since last refresh")}<tr><td style="padding:0 28px;font:13px/1.5 Arial,sans-serif;color:{INK}">{changes}</td></tr>
{alerts}
{h("Watchlist")}<tr><td style="padding:0 28px;font:13px/1.5 Arial,sans-serif;color:{INK}">{watch}<div style="padding-top:6px;color:{MUTE}">{esc(n["watch"])}</div></td></tr>
<tr><td style="padding:22px 28px 24px;font:12px/1.5 Arial,sans-serif;color:{MUTE};border-top:1px solid {LINE};margin-top:18px">Built from public YouTube data (official API) on English-language videos about the iPhone Duo. Comments are a sample of up to 60 per video, labelled by Claude. Differences between groups are associations, and small groups can swing. Open the attached dashboard.html to filter and drill down; reply in Slack to ask a follow-up.</td></tr>
</table></td></tr></table></body></html>'''


def main():
    ins = load("insights.json")
    period = "daily" if "--daily" in sys.argv else "weekly"
    html = build(ins, period=period)
    out = os.path.join(DATA, "report.html"); open(out, "w", encoding="utf-8").write(html)
    print("wrote", out)
    if "--send" not in sys.argv: return
    key, to = secret("RESEND_API_KEY", False), secret("REPORT_EMAIL_TO", False)
    if not (key and to): print("RESEND_API_KEY or REPORT_EMAIL_TO missing; not sent"); return
    body = {"from": "YouTube Creator Social Listening <onboarding@resend.dev>", "to": [to], "subject": f"iPhone Duo on YouTube ({period}): {ins['narrative']['headline'][:80]}", "html": html}
    dash = os.path.join(HERE, "dashboard.html")
    if os.path.exists(dash): body["attachments"] = [{"filename": "launch-pulse-dashboard.html", "content": base64.b64encode(open(dash, "rb").read()).decode()}]
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "launch-pulse/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: print("Resend:", r.status, r.read().decode()[:200])
    except urllib.error.HTTPError as e: raise SystemExit(f"Resend error {e.code}: {e.read().decode()[:300]}")


if __name__ == "__main__":
    main()
