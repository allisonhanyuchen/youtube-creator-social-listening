# YouTube Creator Social Listening

[![Tests](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml/badge.svg)](https://github.com/allisonhanyuchen/youtube-creator-social-listening/actions/workflows/tests.yml)

An AI workflow that listens to YouTube around a product and gives a creator or brand marketing team a readout they do not have to build by hand: which creators and formats beat their own baseline, what the audience is saying, and what changed since yesterday. It refreshes itself every day and pushes the update to email and Slack.

**Live demo: https://youtube-creator-social-listening.vercel.app/**
The demo case is the Apple iPhone Duo launch (2026-09-09). The public page shows no comment text.

## What the page shows

One page with a left sidebar of four modules (click one to show it, no scrolling), plus an "Ask the data" chat at the bottom right.

| Section | What it is |
|---|---|
| 1 Who this is for | Creator managers, launch marketers, analysts |
| 2 How this works | Collect (YouTube Data API: top videos under the keywords, top comments under each video) → Analyse (Claude API + local NLP: overview of creators and content, content performance, audience insights) → Report (dashboard, chat) → Push (Resend, Slack) → Refresh (GitHub Actions, daily) |
| 3 See it in action | **A** type a keyword, choose how many top videos (default 200) and comments per video (default 20), see the estimated YouTube quota and Claude cost, and watch each step with the tech it calls; the last step pushes the full report's key summary to email and Slack, and the actual usage is shown afterwards. **B** the full report and auto-refresh: Overview · Content performance · Audience insights · Reports & automation (run log, the email and Slack digest that get pushed), with **Refresh now** to run the real daily refresh and see it pushed. The public page replays a recorded keyword run |
| 4 Make it yours | Bring your own keys, edit one config file, deploy |

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
python3 src/explore.py "standing desk"   # a keyword run in the terminal (--videos 200 --comments 20 set the size and print the estimate; --push also pushes the full report's key summary; --sample saves the public sample)
python3 src/build_dashboard.py           # dashboard.html (local, with a few hundred quoted comments)

python3 -m venv .venv && .venv/bin/pip install slack_bolt
.venv/bin/python src/slack_bot.py        # Slack agent: mention it to ask a question
```

On the local server the keyword input and **Refresh now** run for real (Refresh now runs the daily pass and pushes to email and Slack with your keys). Tests: `python3 -m unittest discover -s tests -t .` (no keys, no network).

## Make it your own

A step-by-step guide, no coding needed except editing one small file. You will create accounts for five services, copy a key from each, and paste the keys into GitHub and Vercel. Plan on about an hour, plus 10 to 25 minutes for the first run.

**What it costs** (estimates from this demo): YouTube Data API is free (10,000 quota units a day; one search is 100). Claude is pay-as-you-go: the first full run reads about 7,000 comments and cost a few dollars; each daily run after that is cents. Resend, Slack, GitHub, GitHub Actions and Vercel have free tiers that are enough.

### Step 0 · Accounts you need
A [GitHub](https://github.com/signup) account, plus the services below as you reach them. Keep a text file open to hold the keys while you set up. Never post a key in a chat, an issue or a commit.

### Step 1 · Fork the repo
Open this repository on GitHub, click **Fork** (top right), and keep the default name. Everything below happens in your fork.

### Step 2 · Get the keys
You need five values. Do them in this order.

**A. YouTube Data API key** (`YOUTUBE_API_KEY`)
1. Go to https://console.cloud.google.com and sign in with a Google account.
2. Click the project picker at the top → **New project** → name it (for example `social-listening`) → **Create**, then make sure it is selected.
3. Menu → **APIs & Services** → **Library** → search **YouTube Data API v3** → **Enable**.
4. **APIs & Services** → **Credentials** → **Create credentials** → **API key**. Copy the key.
5. Click the key's name → under **API restrictions** choose **Restrict key** → tick **YouTube Data API v3** → **Save**.

**B. Claude API key** (`ANTHROPIC_API_KEY`)
1. Go to https://console.anthropic.com and create an account.
2. **Settings** → **Billing**: add a payment method and a few dollars of credit.
3. **Settings** → **API keys** → **Create key**. Copy it right away (it is shown once).
4. Under **Limits**, set a monthly spend limit so a mistake can never cost more than you chose.

**C. Slack webhook** (`SLACK_WEBHOOK_URL`) for the digest and alerts
1. Go to https://api.slack.com/apps → **Create New App** → **From scratch** → name it and pick your workspace.
2. Left menu **Incoming Webhooks** → switch **Activate Incoming Webhooks** on → **Add New Webhook to Workspace** → choose the channel → **Allow**.
3. Copy the **Webhook URL** (it starts with `https://hooks.slack.com/services/`).

**D. Resend key** (`RESEND_API_KEY`) and your email (`REPORT_EMAIL_TO`) for the email report
1. Go to https://resend.com and sign up with the email address where you want the reports.
2. **API Keys** → **Create API Key** (permission: Sending access) → copy it.
3. `REPORT_EMAIL_TO` is that same sign-up address. Without a verified domain, Resend only delivers to the account owner's address. To email other people, verify a domain under **Domains** and change the `from` address in `src/report.py`.

**E. Optional: the Slack agent you can @mention** (`SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`)
In the same Slack app: **Socket Mode** → enable → create an app-level token with the `connections:write` scope (this is `SLACK_APP_TOKEN`, starts with `xapp-`). **OAuth & Permissions** → add bot scopes `app_mentions:read`, `chat:write`, `im:history`, `im:read` → **Install to Workspace** → copy the **Bot User OAuth Token** (`SLACK_BOT_TOKEN`, starts with `xoxb-`). **Event Subscriptions** → enable → subscribe to `app_mention` and `message.im`. **Interactivity & Shortcuts** → enable. Run it with the commands under "Run it yourself". It runs on your computer, not in the cloud.

### Step 3 · Put the keys into GitHub
In your fork: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add one secret for each of `YOUTUBE_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`, `REPORT_EMAIL_TO` (name exactly as written, value pasted in). Then open the **Actions** tab and click **I understand my workflows, enable them** (GitHub turns workflows off in forks).

### Step 4 · Point it at your product
Open `product.json` in your fork (click the file → the pencil icon) and change the values:

| Field | What to put |
|---|---|
| `name`, `brand` | the product and its maker, for example `Galaxy Z Fold 8` and `Samsung` |
| `launch` | the launch date, `YYYY-MM-DD`. Lift compares videos after launch with the channel's usual views before it |
| `since` | the earliest video date to include, ISO format, for example `2026-06-01T00:00:00Z` |
| `queries` | the YouTube searches, a list. Three to nine is plenty; each costs 100 quota units |
| `topic_regex` | a video's title or channel must match this to count, for example `fold|samsung` |
| `competitors` | brand name → a pattern that finds it in comments, for example `"Apple": "iphone|apple"` |
| `demo_video` | optional: a link (for example a Loom) the page offers as the full-flow walkthrough |

Then delete the demo's data so your run starts clean: in `state/` delete every file except `.gitkeep` (create one if the folder becomes empty), and delete `docs/data.json`, `docs/index.html` and `api/public.db`. (On the GitHub website: open the file → the trash icon → commit. Or do it locally with `git rm`.)

Optional fields, with sensible defaults when left out:

| Field | What it does |
|---|---|
| `blurb` | one line the prompts use to describe the product (default: name and launch date) |
| `topic`, `topics` | the label that marks a video as about your product (default `main`) and the labels Claude may give a video, for example `{"main": "Galaxy Z Fold 8", "fold_7": "last year's Fold 7", "other": "something else"}`. Add labels for products you want kept separate for comparison |
| `baseline_exclude` | a pattern for pre-launch videos about the product itself (rumours), which should not count as a channel's usual views (default: `topic_regex`) |

> Good to know: the creator-type list (`src/creators.py`) assumes consumer tech (reviewers, tech news, lifestyle vlogger and so on). For a very different category, edit that short list. The name, brand, competitors, titles in the email, Slack and page, and every prompt come from `product.json`.

### Step 5 · First run
**Actions** tab → **Refresh and push** → **Run workflow** → set **Send the email and Slack update** to off for the very first run → **Run workflow**. Open the run to watch the four stages go green: 1 Refresh source data, 2 Analyse, 3 Update reports, 4 Push. It takes 10 to 25 minutes the first time. When it is green, run it again with send on to check that the email and the Slack message arrive. From then on it runs by itself every day at 15:00 UTC.

### Step 6 · Publish the page
Pick one:
- **GitHub Pages** (free, simplest): **Settings** → **Pages** → Source **Deploy from a branch** → branch `main`, folder `/docs` → **Save**. Your page is at `https://<your-username>.github.io/<repo-name>/`. The chat shows recorded answers there.
- **Vercel** (also gives the live chat and the demo-code protected live runs): see "Hosting on Vercel" below.

### Step 7 · Optional: live runs on Vercel
1. Go to https://vercel.com, sign up with GitHub, **Add New** → **Project** → import your fork. Framework **Other**, leave the build command empty → **Deploy**.
2. **Settings** → **Environment Variables**: add the variables in the table under "Hosting on Vercel". For `GITHUB_TOKEN`: https://github.com/settings/personal-access-tokens/new → **Only select repositories** → your fork → **Repository permissions** → **Actions: Read and write** → generate and copy.
3. Choose your own `DEMO_CODE`. Redeploy (Deployments → the latest → Redeploy).
4. Open your Vercel page. The **Generate report** and **Refresh now** buttons now ask for the code.

### If something goes wrong
- **"quotaExceeded"**: YouTube's 10,000 units a day are used up; the run resumes tomorrow (the quota resets at midnight Pacific time).
- **Claude "credit balance too low"**: add credit in the Anthropic console and re-run the workflow.
- **No email**: Resend only delivers to your sign-up address until you verify a domain. Check **Logs** in Resend.
- **No Slack message**: re-create the webhook and update the `SLACK_WEBHOOK_URL` secret.
- **Workflow does not appear or will not run**: in a fork, enable workflows on the Actions tab (Step 3).
- **A step is red**: open the run, click the red step and read its last lines; the message names the missing key or file.

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
| optional | `GITHUB_REPO`, `CHAT_PER_HOUR` (8), `CHAT_PER_DAY` (300), `CHAT_DISABLED`, `DEMO_RUNS_PER_DAY` (25), `DEMO_UNITS_PER_DAY` (3,000), `DEMO_REFRESH_COOLDOWN` (300 s) |

- **Keyword run size and cost.** The page lets you pick the number of top videos (up to 200) and comments per video (up to 100) and shows an estimate first: YouTube quota is about `100 x search pages + 3 x videos + one comment call per video`, and Claude is about 45 input and 8 output tokens per comment read plus a small fixed amount. Dollars use `pricing` in `product.json` (default 3 and 15 USD per million input and output tokens; change it to your plan's price). Measured: a 20 x 20 run used about 17k input and 4k output tokens; the default 200 x 20 is estimated at roughly 1,300 quota units and about 1 USD. The hosted page also caps live runs per day by YouTube units (`DEMO_UNITS_PER_DAY`, default 3,000).
- **Cost per scheduled run.** Every step logs the tokens and quota units it used; the Run log shows them with the estimated cost for each run.
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
