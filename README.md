# YouTube Creator Social Listening

[![Tests](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml/badge.svg)](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml)

An AI workflow that listens to YouTube around a product and gives a creator or brand marketing team a readout they do not have to build by hand: which creators and formats beat their own baseline, what the audience is saying, and what changed since yesterday. It refreshes itself every day and pushes the update to email and Slack.

**Live demo: https://youtube-creator-social-listening.vercel.app/** (also on GitHub Pages: https://allisonhanyuchen.github.io/youtube-creator-social-listening/, where the chat falls back to recorded answers).
The demo case is the Apple iPhone Duo launch (2026-09-09). The public page shows no comment text.

## What the page shows

One page of five expandable sections, plus an "Ask the data" chat.

| Section | What it is |
|---|---|
| 1 Who this is for | Creator managers, launch marketers, analysts |
| 2 How this works | Collect (YouTube Data API: top videos under the keywords, top comments under each video) → Analyse (Claude API + local NLP: overview of creators and content, content performance, audience insights) → Report (dashboard, chat) → Push (Resend, Slack) → Refresh (GitHub Actions, daily) |
| 3 See an example | Type a keyword and watch each step with the tech it calls, then get a small report; the last step pushes it to email and Slack. The public page replays a recorded run |
| 4 The full report | Overview (creator types by level and region) · Content performance (a content-type overview that filters a sortable list: lift, views gained, sentiment score) · Audience insights (topic map, expandable topics, competitors) · Reports & automation (run log, example email and Slack digest, Refresh now) |
| 5 Make it yours | Bring your own keys, edit one config file, deploy |

Every metric explains itself on hover, starting with the business question it answers. Sentiment is shown as a **net sentiment score** (positive % minus negative %, -100 to +100) next to a bar that keeps the neutral share visible.

## Architecture

```
YouTube Data API v3 ──► Claude API + local NLP ──► SQLite ──► dashboard (static HTML) + Ask the data
  videos, stats,          per-comment labels,        lift,        │
  comments, daily         topic clustering,          trends,      ├─► daily email (Resend) and Slack digest / alerts / @mention agent
  view snapshots          narrative                  topics       └─► Vercel: the page, live Q&A, demo-code-gated keyword runs and Refresh now
                                  ▲
                      GitHub Actions, every day 15:00 UTC: light pass; full pass on Mondays
```

The split is deliberate: statistics where they are enough, Claude where reading and judgement add something.

| Step | Where | Why |
|---|---|---|
| Lift, baselines, outperformer cut-offs, trends, alerts, every number in a report | Local Python | Deterministic and testable, nothing is generated |
| Topics: TF-IDF, k-means, nearest-topic assignment, new-topic discovery | Local Python (`textcluster.py`, `topics.py`) | Topics come from the comments, so a new product needs no code change; IDs are stable week to week |
| Per-comment target, sentiment, intent | Claude | Needs reading: is it about the phone, the price or the creator? Sarcasm? |
| Naming topics, paraphrased notes, narrative, Q&A | Claude, on numbers computed locally | Grounded in the data, with the SQL shown |

## Repository layout

```
src/                  all the code (flat; run any script as  python3 src/<name>.py)
  collect.py classify.py snapshots.py performance.py creators.py comments.py   pipeline: videos, formats, view snapshots, baselines, comments
  db.py textcluster.py topics.py insights.py summaries.py examples.py          analysis: SQLite tables, topics, insights, paraphrased notes
  report.py notify.py build_dashboard.py dashboard.tmpl.html                    outputs: email, Slack, the page
  run_weekly.py state_io.py                                                    the scheduled runner (also runs one stage at a time)
  ask.py slack_bot.py serve.py explore.py demo_gate.py                         the agent, the local server, the keyword explorer, the demo-code gate
  common.py public_safety.py export_public_db.py                               helpers, the no-quoted-comments check, the text-free database
api/                  Vercel functions: chat.py (live Q&A), verify.py, step.py, refresh.py (demo-code gated), public.db (text-free copy of the data)
state/                committed, text-free: video stats, our labels per comment ID, topics, snapshots, run log, recorded sample
docs/                 the public page (index.html) and its data (data.json), rebuilt by every run
tests/                unit tests, standard library only
product.json         the one config file: product, keywords, launch date, competitors
.github/workflows/    refresh.yml (daily run, one step per stage), tests.yml
```

## Run it yourself

Keys live outside the repo in `~/.creator-scout.env` (or as environment variables / GitHub secrets):

```
YOUTUBE_API_KEY=...
ANTHROPIC_API_KEY=...
SLACK_WEBHOOK_URL=...            # digest and alerts
RESEND_API_KEY=...               # email
REPORT_EMAIL_TO=you@example.com  # the Resend test sender can only deliver to the account owner
SLACK_BOT_TOKEN=xoxb-...         # Q&A agent (Socket Mode), optional
SLACK_APP_TOKEN=xapp-...
```

```bash
python3 src/run_weekly.py --no-send      # the whole pipeline once (add --daily or --weekly to force a mode)
python3 src/serve.py                     # http://127.0.0.1:8770 with everything live: keyword input, Refresh now, chat
python3 src/explore.py "standing desk"   # a keyword report in the terminal (--push sends it, --sample saves the public sample)
python3 src/build_dashboard.py           # dashboard.html (local, with a few hundred quoted comments)

python3 -m venv .venv && .venv/bin/pip install slack_bolt
.venv/bin/python src/slack_bot.py        # Slack agent: mention it to ask a question
```

On the local server the keyword input and **Refresh now** run for real (Refresh now runs the daily pass and pushes to email and Slack with your keys). Tests: `python3 -m unittest discover -s tests -t .` (no keys, no network).

## Make it your own

1. Fork the repo and add the keys as repository secrets.
2. Edit `product.json`: `name`, `brand`, `launch`, `since` (earliest video date), `queries` (the YouTube searches), `topic_regex` (a video must match it), `competitors`, and optionally `demo_video` (a link shown on the page).
3. Clear `state/`, then run the **Refresh and push** workflow (Actions tab). Topics are rediscovered from your comments.
4. Turn on GitHub Pages from `/docs`, or deploy to Vercel (below).

Still specific to the Duo case, worth a look when you switch product: the product labels in `classify.py` (`TOPICS`) and the `topic = 'duo'` scope in `common.scope_sql()`. Content-type labels are generic. A search costs 100 YouTube quota units.

## The daily run

`refresh.yml` runs every day at 15:00 UTC and on demand, in four stages that appear as four workflow steps: **1 Refresh source data** (new videos, stats, daily view snapshot, baselines) → **2 Analyse** (label new comments, assign topics and discover new ones, insights and changes) → **3 Update reports** (topic notes, recorded Q&A, the text-free database, the page) → **4 Push to email and Slack**. Then it records the run in `state/runs.json` and commits `state/`, `docs/` and `api/` back, so the next run is incremental and the hosted page redeploys.

- **Light pass** (Tuesday to Sunday): skips the slow Claude steps but still sends a short "daily" email and Slack digest.
- **Full pass** (Monday): everything, plus the full "weekly" email and digest.
- Inputs when started by hand: `send` (off = no email or Slack) and `mode` (auto, daily, weekly).

## Hosting on Vercel

`vercel.json` serves `docs/` and adds serverless functions in `api/`. Import the repo in Vercel (Framework: Other, no build command) and set these environment variables:

| Variable | For |
|---|---|
| `ANTHROPIC_API_KEY` | live chat and keyword runs. Use a dedicated key with a spend limit set in the Anthropic console: that limit is the hard cap |
| `DEMO_CODE` | the code that unlocks keyword runs and Refresh now. Without it they stay off and the page shows the recorded sample |
| `YOUTUBE_API_KEY` | keyword runs |
| `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`, `REPORT_EMAIL_TO` | where a keyword run pushes its report |
| `GITHUB_TOKEN` | Refresh now: a fine-grained token with Actions read and write on this repo only |
| optional | `GITHUB_REPO`, `CHAT_PER_HOUR` (8), `CHAT_PER_DAY` (300), `CHAT_DISABLED`, `DEMO_RUNS_PER_DAY` (25), `DEMO_REFRESH_COOLDOWN` (300 s) |

- **Live chat** (`api/chat.py`) reuses the Q&A core over `api/public.db`, a copy of the database with no comment text. It accepts same-site requests only, short questions, and limited questions per visitor.
- **Keyword runs** (`api/step.py`) run one stage per request and the browser carries the state, so the page can show the steps live; every call needs the demo code. Five wrong codes lock a visitor out for ten minutes.
- **Refresh now** (`api/refresh.py`) starts the real workflow on GitHub Actions and the page follows its four stages through GitHub's public API.
- Where the functions are missing (GitHub Pages), the page falls back to the recorded sample and recorded answers by itself.

## Definitions

- **Lift**: a video's views divided by the median views of the same channel's comparable pre-launch videos (Shorts with Shorts, long with long), then divided by the typical value among videos of the same product and format. 1.0 is a typical video.
- **Outperformer**: top quarter of lift within its format class. **Underperformer**: bottom quarter.
- **Sentiment score**: positive share minus negative share of the comments about the product, price, Apple or competitors (comments about the video or creator are left out). A video needs at least 10 such comments before its reaction is shown.
- **Views gained (24h / 7d)**: views added since the latest daily snapshot that is at least a day (or a week) old. The API has no history, so `snapshots.py` stores one count a day; the columns fill in as snapshots accumulate.
- **Topic trend**: the share of a topic's comments posted in the last 7 days divided by its usual share. Above 1.5x with 15+ recent comments is "gaining". New topics are marked "new this week".
- **Channel size**: small (under 250k subscribers), mid (250k to 1M), large (1M and above).

## Data and limits

- English-language videos found through search: a sample of YouTube, not a census. Comments are up to 60 per video (40 top, 20 newest), so liked opinions are over-represented. Labels come from Claude and were produced in two modes (deeper reasoning, then a faster one).
- About 85% of product comments fit a topic; the rest are shown as unassigned. In the scheduled run old comment text is not kept, so new topics are discovered among that run's unassigned comments.
- Region is the channel-declared country. Lift compares a video with its own channel, so small channels reach high multiples more easily; differences between groups are associations.
- Sponsorship and Apple seeding are deliberately not analysed: in an earlier version none of the 58 sponsored videos was sponsored by Apple or a competitor, and seeding could only be inferred from timing, which also drives views.

## Privacy and keys

Comment text, the SQLite database and the local dashboard (which embeds a few hundred quotes) stay on your machine and are git-ignored. The public page contains no comment text; its paraphrased notes and recorded answers are checked at build time and the build fails if any shares a distinctive 5-word run with a comment. Only code and text-free state are committed: video titles, IDs and public stats, our labels per comment ID, baselines, topics and snapshots. API keys are never stored in the repository, and the demo code lives only in the host's environment.
