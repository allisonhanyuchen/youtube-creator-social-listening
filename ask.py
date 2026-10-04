#!/usr/bin/env python3
"""Step 9a: the Q&A core shared by Slack and the dashboard. Question -> read-only SQLite query -> grounded answer.
Claude writes one SELECT against data/pulse.db (read-only connection, SELECT/WITH only, row and time caps), then summarises the rows.
Returns the answer plus the SQL it ran, so the asker can check the work.  CLI: python3 ask.py "your question" """
import json, os, re, sqlite3, sys, time
from common import DATA, claude, parse_json

DB = os.path.join(DATA, "pulse.db")
MAX_ROWS = 40

SCHEMA = """
YouTube data on the Apple iPhone Duo (first foldable iPhone, launched 2026-09-09). iPhone 18 Pro videos are in the database as a comparison. SQLite, read only.
Default scope: topic='duo' and format!='official' (official = Apple's own channel, no lift). Only use other topics when the question names them (e.g. iPhone 18 Pro, comparisons).

creators(channel_id, name, kol_type, tier, subscribers, region)
  kol_type: pro_reviewer, apple_focused, lifestyle_vlogger, tech_news_media, commentary_analyst, entertainment_shorts, official_brand, other
  tier: 'nano <50k','micro 50-250k','mid 250k-1M','macro 1-5M','mega 5M+'   region: channel-declared country code or 'undeclared'
content(video_id, url, title, channel_id, format, topic, title_framing, published, day_since_launch, is_short, duration_s)
  format: first_impressions, full_review, comparison, upgrade_advice, keynote_recap, durability_test, explainer_tips, rumor_leak, meme_short, official, other
  topic: duo, iphone_18_pro, iphone_18, event_general, competitor_foldable, other
performance(video_id, views, likes, comment_count, eng_rate, comment_rate, baseline_n, baseline_views, lift, rel_lift, outperformer)
  lift = views / the channel's own pre-launch median for the same format class (Short vs long). rel_lift = lift / median lift of that class, computed among Duo videos for Duo videos (1.0 = typical Duo video).
  outperformer = 1 if top quartile of rel_lift within Shorts or long; NULL for official Apple videos or videos without a baseline. avg(outperformer) = outperformer rate. Underperformer = bottom quartile of rel_lift in its class.
comments(comment_id, video_id, text, likes, published, day_since_launch, source, lang, target, sentiment, intent, label_mode, trivial)
  Always filter lang='en' AND trivial=0. target: product, price_value, apple_brand, competitor (= product-side), video_or_creator, other.
  Headline sentiment uses only product-side targets. sentiment: positive|neutral|negative (toward the target). intent: buy, upgrade_wait, skip, switch_from_android, none.
  published = comment date; day_since_launch counts from 2026-09-09.
comment_themes(comment_id, theme)  themes (a comment can have several): hype_purchase_excitement, fold_animation_ui, price_affordability, android_prior_art, android_rival_comparison,
  design_colors_form, crease_screen_quality, camera_hardware, durability_tests, software_usability, apple_brand_leadership, creator_credibility_critique (= calls the video biased or ad-like)
views: v_content (content + creator + performance + video-level sentiment: n_product_side, pct_positive, pct_neutral, pct_negative), v_video_sentiment, v_theme_sentiment(theme, sentiment, video_id, comment_id)
Joins: comments.video_id = content.video_id; content.channel_id = creators.channel_id; comment_themes.comment_id = comments.comment_id.
Rules: report n with every rate. Prefer rel_lift / outperformer over raw views when comparing groups. Channel size groups: small = tier nano+micro, mid = 'mid 250k-1M', large = macro+mega.
Scale vs improve: scale = outperformer whose net sentiment (pos minus neg, product-side) is at least the typical video's minus 5 points; improve = outperformer with clearly worse net sentiment, or an underperformer. Needs >=10 product-side comments to judge sentiment.
Sponsorship and Apple seeding are not analysed (no sponsor in this data was Apple or a rival; seeding could not be verified). Say so if asked.
"""
SQL_PROMPT = SCHEMA + """
Write ONE SQLite SELECT (CTEs allowed) that answers the question. Use LIMIT <= 40. Round rates to 3 decimals. Include counts (n) as columns.
If the question cannot be answered from this data (e.g. ad spend, sales, private data, other platforms), return {"clarify": "<one sentence on what the data can and cannot say>"}.
Return JSON only: {"sql": "...", "note": "<=15 words on what the query measures"} or {"clarify": "..."}.
"""


def run_sql(sql):
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", s) or ";" in s or re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|pragma|replace|vacuum)\b", s):
        raise ValueError("only a single read-only SELECT is allowed")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    t0 = time.time()
    con.set_progress_handler(lambda: 1 if time.time() - t0 > 8 else 0, 20000)
    cur = con.execute(s)
    cols = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchmany(MAX_ROWS)]
    con.close()
    return cols, rows


def ask(question, history=None, context=""):
    hist = "".join(f"\nEarlier Q: {h['q']}\nEarlier SQL: {h.get('sql','')[:400]}\nEarlier answer: {h['a'][:300]}\n" for h in (history or [])[-3:])
    last_err = None
    for attempt in range(2):
        prompt = SQL_PROMPT + (f"\nThe user is looking at the dashboard: {context}. Use this only when the question refers to 'this', 'these', 'the current view' or similar; otherwise answer over all data.\n" if context else "") + (f"\nConversation so far:{hist}" if hist else "") + (f"\nYour previous SQL failed: {last_err}. Fix it.\n" if last_err else "") + f"\nQuestion: {question}"
        try:
            plan = parse_json(claude(prompt, 6000))
        except ValueError:
            last_err = "the previous reply was not valid JSON"; continue
        if "clarify" in plan:
            return dict(answer=plan["clarify"], sql=None, rows=[], cols=[], note="")
        try:
            cols, rows = run_sql(plan["sql"])
            break
        except Exception as e:
            last_err = str(e)[:200]
    else:
        return dict(answer=f"I couldn't run a valid query for that ({last_err}). Try rephrasing, for example by naming the topic, format or time window.", sql=None, rows=[], cols=[], note="")
    table = json.dumps({"columns": cols, "rows": rows}, ensure_ascii=False, default=str)[:9000]
    answer = claude(
        "You are the analyst behind Launch Pulse. Answer the question using ONLY the query result below. Plain language, <=130 words, lead with the answer, cite numbers with n, "
        "say plainly when n is small or the result is empty, and mention one relevant caveat (comment sample, small n, associations not causes) only if it applies. "
        "If the rows contain comment text, quote at most 3, each under 25 words. No headings, no preamble. Use Slack-friendly plain text (no markdown tables).\n\n"
        f"Question: {question}\nWhat the query measures: {plan.get('note','')}\nResult:\n{table}", 3000).strip()
    return dict(answer=answer, sql=plan["sql"], rows=rows, cols=cols, note=plan.get("note", ""))


if __name__ == "__main__":
    r = ask(" ".join(sys.argv[1:]))
    print(r["answer"], "\n\n--- SQL ---\n" + (r["sql"] or "(none)"))
