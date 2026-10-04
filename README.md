# YouTube Creator Social Listening

[![Tests](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml/badge.svg)](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml)

**Live demo: https://allisonhanyuchen.github.io/youtube-creator-social-listening/** (the dashboard on iPhone Duo data. The public page shows no comment text: topics are summarised in paraphrase and checked against the comments, and the chat shows recorded answers from the live agent. It refreshes every Monday).

An AI workflow that listens to YouTube around a product and answers three questions for a creator or brand marketing team:

1. Which creators and content formats beat their own baseline, and at what channel size?
2. How do lift and audience reaction line up for each video? They are shown side by side, not merged into a score, because they measure different things.
3. What is the audience actually saying (topics, sentiment, competitors), which topics are new or growing, and what changed since the last refresh?

The demo case is the Apple iPhone Duo (the first foldable iPhone, launched 2026-09-09). iPhone 18 Pro videos are kept in the database as a comparison for the Q&A agent. The pipeline is pointed at another product by editing `product.json` (name, brand, launch date, competitors) and the search queries in `collect.py`; topics are discovered from the comments, not hand-written.

Built with Python (standard library only), the YouTube Data API v3 (official API, no scraping), the Claude API, SQLite, Slack, and Resend for email.

## What you get

| Surface | Use | Entry point |
|---|---|---|
| Dashboard (live demo above, or run locally for quotes and chat) | Overview (creator type by level and region, content type table with sentiment bars), Content insights (one sortable list of videos with creator, region, level, content type, lift, views, engagement and a sentiment bar), Audience insights (topic map and competitors, how local statistics and AI combine, one table of topics with sentiment, trend, new tags and summaries). Click a chart to filter; every metric explains itself on hover. | `dashboard.html` |
| Weekly email | Summary, coverage, performance (lift and sentiment side by side), audience topics with trend and new topics, highlights, changes since the last refresh, watchlist. | `report.py` |
| Slack digest and alerts | The same readout in a channel, plus an alert when sentiment or a topic shifts. | `notify.py` |
| Q&A agent | Ask in Slack or in the dashboard. It writes a read-only SQL query, runs it, answers from the rows, and shows the query. | `slack_bot.py`, `serve.py`, `ask.py` |

## Pipeline

```
collect.py      YouTube search + videos + channels          -> data/videos_raw.json
classify.py     Claude labels content format and topic       -> data/videos.json
performance.py  channel baselines, lift                      -> lift
creators.py     creator type, size tier, region
comments.py     pull comments, Claude labels each one        -> target, sentiment, intent
db.py           builds data/pulse.db (SQLite base tables and views)
insights.py     numbers computed in Python, narrative by Claude, week-over-week alerts
report.py       HTML email           notify.py   Slack digest and alerts
build_dashboard.py  dashboard.html   ask.py      Q&A core (Slack bot and dashboard)
textcluster.py / topics.py   local TF-IDF + k-means defines topics with stable IDs; Claude names them; every refresh assigns new comments and looks for new topics
summaries.py / examples.py / public_safety.py   paraphrased notes and recorded Q&A for the public demo, checked so nothing reuses a comment's wording
build_dashboard.py --public   docs/index.html (GitHub Pages)
```

## What runs locally and what uses AI

The split is deliberate: statistics where they are enough, Claude where reading and judgement add something.

| Step | Where | Why |
|---|---|---|
| Lift, baselines, outperformer cut-offs, alerts, every number in the report | Local Python | Deterministic and testable, nothing is generated |
| Language, no-signal filtering, SQL guard, public-demo safety check | Local Python | Cheap rules |
| Audience topics (`topics.py`) | **Local**: TF-IDF over unigrams and bigrams, spherical k-means, nearest-topic assignment, trend index, all pure Python. **AI**: one-time merge and naming of clusters, one paraphrased sentence each, and a yes/no on whether a new cluster is a real new topic | Topics come from the comments, so a new product or a new conversation needs no code change. Topic IDs and centroids are stored, so counts stay comparable week to week; comments that fit nothing are re-clustered on each refresh to discover new topics |
| Per-comment target, sentiment, intent | Claude | Needs reading: is it about the phone, the price, or the creator? Sarcasm? A lexicon cannot tell, and about a quarter of comments are about the creator |
| Narrative, Q&A, topic notes | Claude, on numbers computed locally | Grounded in the data, with the SQL shown |

## Definitions

- **Lift**: a video's views divided by the median views of the same channel's comparable pre-launch videos (Shorts compared with Shorts, long with long), then divided by the typical value among videos of the same product and format. 1.0 is a typical video.
- **Outperformer**: top quarter of lift within its format class. A fixed "2x baseline" bar was too loose in launch week, when most videos beat their baseline. **Underperformer**: bottom quarter.
- **Audience reaction**: sentiment is labelled per comment toward what the comment is about. Headline numbers count only comments about the product, price, Apple, or competitors; comments about the video or creator are excluded. A video needs at least 10 such comments before its reaction is judged.
- **Channel size**: small (under 250k subscribers), mid (250k to 1M), large (1M and above).

## Scheduled run

`.github/workflows/weekly.yml` runs `run_weekly.py` every Monday (and on demand from the Actions tab). It starts from `state/`, finds videos posted since the last run, refreshes stats for every known video, labels only comments it has not seen before, rebuilds the tables, writes the insights and week-over-week alerts, sends the email and the Slack digest, and commits the updated `state/` back. API keys come from repository secrets.

## Run it

Keys live outside the repo in `~/.creator-scout.env` (or as environment variables in CI):

```
YOUTUBE_API_KEY=...
ANTHROPIC_API_KEY=...
SLACK_WEBHOOK_URL=...            # digest and alerts
RESEND_API_KEY=...               # email
REPORT_EMAIL_TO=you@example.com  # the Resend test sender can only deliver to the account owner
SLACK_BOT_TOKEN=xoxb-...         # Q&A agent (Socket Mode)
SLACK_APP_TOKEN=xapp-...
```

```bash
python3 collect.py && python3 classify.py
python3 performance.py && python3 creators.py
python3 comments.py
python3 db.py && python3 topics.py && python3 insights.py && python3 summaries.py
python3 build_dashboard.py          # dashboard.html
python3 report.py --send            # email
python3 notify.py                   # Slack digest (add --alerts for alert-only)
python3 serve.py                    # dashboard with chat on http://127.0.0.1:8770

python3 -m venv .venv && .venv/bin/pip install slack_bolt
.venv/bin/python slack_bot.py       # Slack Q&A agent
```

Steps are cached and resumable: searches, baselines, and comment labels are only recomputed for new items.

## Make it your own

The live page is a static demo of one product. To run the same pipeline on your own keywords or product:

1. Fork the repo and add the keys as repository secrets (or put them in `~/.creator-scout.env` locally): `YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY`, plus `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`, `REPORT_EMAIL_TO` if you want the digest and email.
2. Edit `product.json`: `name`, `brand`, `launch` date, `since` (earliest video date), `queries` (the YouTube searches), `topic_regex` (a video must match it to count), and `competitors` (name to regex).
3. Clear `state/` and `data/`, then run `python3 run_weekly.py --no-send` (or the Actions workflow). Topics are rediscovered from your comments, so there is no taxonomy to rewrite.
4. Open `dashboard.html`, or turn on GitHub Pages from `/docs`. `docs/data.json` holds the same text-free data as the public page, if you want to rebuild the UI in another tool.

Still specific to the Duo case and worth a look when you switch product: the product labels in `classify.py` (`TOPICS`) and the `topic = 'duo'` scope in `common.scope_sql()`. Content-type labels (first impressions, review, comparison and so on) are generic. The search costs 100 quota units per query per day.

## Tests

```bash
python3 -m unittest discover -s tests -t . -v      # standard library only, no keys, no network
```

They cover the pieces that decide what the dashboard says: the compact label parser, the text clustering and nearest-topic assignment, change and watchlist detection, the no-signal comment filter, outperformer cut-offs, week-over-week alerts, the read-only SQL guard behind the Q&A agent, that `state/` and the public demo contain no comment text, and that the email report renders and escapes HTML. They run on every push (Python 3.9 and 3.12).

## Data and limits

- English-language videos only, found through search. This is a sample of YouTube, not a census.
- Comments are a sample of up to 60 per video (40 top, 20 newest), so top comments lean toward liked opinions. Videos with fewer than 10 comments are skipped. Labels come from Claude.
- Comments were labelled in two modes on different videos: deeper reasoning first, then a faster mode. Small differences between videos can partly reflect the labelling mode.
- Topics cover about 86% of product comments; the rest fit no topic and are shown as unassigned. In the scheduled run old comment text is not kept, so new topics are discovered only among that week's unassigned comments.
- Region is the channel-declared country. Audience geography is not public.
- Lift compares a video with its own channel's usual videos, so small channels reach high multiples more easily. Differences between groups are associations, and small groups can swing.
- Sponsorship and Apple seeding are deliberately not analysed. In an earlier version, none of the 58 sponsored videos was sponsored by Apple or a competitor (they were case makers, VPNs and similar), and seeding could only be inferred from posting time, which also drives views. Neither produced a reliable comparison.

## Privacy and keys

Comment text, the SQLite database, and the local dashboard (which embeds a few hundred quoted comments) stay on your machine and are excluded by `.gitignore`. The public demo in `docs/` contains no comment text; its paraphrased notes and recorded answers are checked at build time and the build fails if any of them shares a distinctive 5-word run with a comment. Only code and a text-free `state/` folder are committed: video titles, IDs and public stats, our labels per comment ID, channel baselines, and weekly snapshots. No comment text and no video descriptions. API keys are never stored in the repository.
