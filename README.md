# YouTube Creator Social Listening

An AI workflow that listens to YouTube around a product launch and answers three questions for a creator or brand marketing team:

1. Which content formats beat the creator's own baseline, and which do not?
2. How does paid creator content compare with organic content, and which organic videos are worth scaling?
3. What is the audience actually saying (sentiment, themes, pain points), and how does that change week over week?

The demo case is Apple's 2026-09-09 launch (iPhone Duo, the first foldable, with iPhone 18 Pro as the control). The same pipeline works for any launch by changing the search queries in `collect.py`.

Built with Python (standard library only), the YouTube Data API v3 (official API, no scraping), the Claude API, SQLite, Slack, and Resend for email.

## What you get

| Surface | Use | Entry point |
|---|---|---|
| Dashboard | Filter by topic, promotion type, format, creator type, channel size, region, posting window, and drill down. Each number shows its sample size and 95% intervals. | `dashboard.html` |
| Weekly email | Key metrics snapshot: headline, alerts, paid vs organic, formats, audience themes, organic videos worth scaling. | `report.py` |
| Slack digest and alerts | The same readout in a channel, plus an alert when sentiment or a theme shifts. | `notify.py` |
| Q&A agent | Ask ad hoc questions in Slack or in the dashboard. It writes a read-only SQL query, runs it, answers from the rows, and shows the query. | `slack_bot.py`, `serve.py`, `ask.py` |

## Pipeline

```
collect.py      YouTube search + videos + channels          -> data/videos_raw.json
classify.py     Claude labels content format and topic       -> data/videos.json
promo.py        paid (sponsored / seeded) vs organic         -> promo_type, promo_sub, promo_evidence
performance.py  channel baselines, relative lift             -> lift, rel_lift
creators.py     creator type, size tier, region
comments.py     pull comments, Claude labels each one        -> sentiment, target, themes, intent
db.py           builds data/pulse.db (SQLite base tables and views)
insights.py     numbers computed in Python, narrative by Claude, week-over-week alerts
report.py       HTML email           notify.py   Slack digest and alerts
build_dashboard.py  dashboard.html   ask.py      Q&A core (Slack bot and dashboard)
```

## Definitions

- **Relative lift**: a video's views divided by the median views of the same channel's comparable pre-launch videos (Shorts compared with Shorts, long with long), then divided by the median of that format class. 1.0 means a typical launch-week video.
- **Outperformer**: top quartile of relative lift within its format class. A fixed "2x baseline" bar was too loose in launch week, when most videos beat their baseline.
- **Sponsored**: the creator disclosed a commercial sponsor (YouTube paid-promotion flag, or sponsor wording in the description). The sponsor is often not Apple.
- **Seeded**: Apple early access in kind (pre-launch unit or event invite). Disclosed when the video says so. Otherwise inferred from timing (a hands-on posted on launch day or the next day, or a review on the embargo-lift day) and kept only when Claude judges from the title and description that the creator had the device. Public data cannot prove who was seeded, so inferred seeded is a lower bound.
- **Organic**: everything else. Affiliate links are tracked as a flag on organic videos, because they are creator monetization and not a promotion strategy.
- **Sentiment**: labelled per comment toward what the comment is about. Headline numbers count only comments about the product, price, Apple, or rivals. Comments about the video or creator are excluded.

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
python3 collect.py && python3 classify.py && python3 promo.py
python3 performance.py && python3 creators.py
python3 comments.py && python3 hype_recheck.py && python3 credibility_pass.py
python3 db.py && python3 insights.py
python3 build_dashboard.py          # dashboard.html
python3 report.py --send            # email
python3 notify.py                   # Slack digest (add --alerts for alert-only)
python3 serve.py                    # dashboard with the Ask tab on http://127.0.0.1:8770

python3 -m venv .venv && .venv/bin/pip install slack_bolt
.venv/bin/python slack_bot.py       # Slack Q&A agent
```

Steps are cached and resumable: searches, baselines, and comment labels are only recomputed for new items.

## Data and limits

- English-language videos only, found through search on launch-related queries. This is a sample of YouTube, not a census.
- Comments are a sample of up to 60 per video (40 top, 20 newest), so top comments lean toward liked opinions. Labels come from Claude.
- Comments were labelled in two modes on different videos: deeper reasoning first, then a faster mode with a recheck of the hype theme. Small differences between videos can partly reflect the labelling mode.
- Region is the channel-declared country. Audience geography is not public.
- Seeded videos are partly defined by early posting, and early videos earn more views. The dashboard offers a same-posting-window comparison. Seeded n is small.
- Apple's ad spend is not visible in public data. "Paid" here means creator content with a commercial relationship.
- Differences between groups are associations. Launch-day timing, channel size, and format all move performance.

## Privacy and keys

Comment text, the SQLite database, and the dashboard (which embeds a few hundred quoted comments) stay on your machine and are excluded by `.gitignore`. Only code and a text-free `state/` folder are committed: video titles, IDs and public stats, our labels per comment ID, channel baselines, and weekly snapshots. No comment text and no video descriptions. API keys are never stored in the repository.
