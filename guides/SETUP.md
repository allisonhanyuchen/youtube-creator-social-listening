# Setup guide

Everything you need to run this for your own product, from the first account to a live page. Short version: fork, add five keys, edit `input.json`, run the workflow.


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
Open `input.json` in your fork (click the file → the pencil icon) and change the values:

| Field | What to put |
|---|---|
| `name`, `brand` | the product and its maker, for example `Galaxy Z Fold 8` and `Samsung` |
| `launch` | the launch date, `YYYY-MM-DD`. Lift compares videos after launch with the channel's usual views before it |
| `since` | the earliest video date to include, ISO format, for example `2026-06-01T00:00:00Z` |
| `keywords` | what to search for on YouTube, a list. Three to nine is plenty; each costs at least 100 quota units. Same idea as the keyword box on the page |
| `top_videos` | how many top videos to take per keyword (default 50, up to 200). Same as "Top videos" on the page |
| `comments_per_video` | how many comments to read under each video (default 60, up to 150): two thirds top comments, the rest newest. Same as "Comments per video" on the page |
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

> Good to know: the creator-type list (`src/creators.py`) assumes consumer tech (reviewers, tech news, lifestyle vlogger and so on). For a very different category, edit that short list. The name, brand, competitors, titles in the email, Slack and page, and every prompt come from `input.json`.

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


## Hosting on Vercel (optional, gives live chat and live runs)

`vercel.json` serves `docs/` and adds serverless functions in `api/`. Import the repo in Vercel (Framework: Other, no build command) and set these environment variables:

| Variable | For |
|---|---|
| `ANTHROPIC_API_KEY` | live chat and keyword runs. Use a dedicated key with a spend limit set in the Anthropic console: that limit is the hard cap |
| `DEMO_CODE` | the code that unlocks keyword runs and Refresh now. Without it they stay off and the page shows the recorded sample |
| `YOUTUBE_API_KEY` | keyword runs |
| `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`, `REPORT_EMAIL_TO` | where a keyword run pushes its report |
| `GITHUB_TOKEN` | Refresh now: a fine-grained token with Actions read and write on this repo only |
| optional | `GITHUB_REPO`, `CHAT_PER_HOUR` (8), `CHAT_PER_DAY` (300), `CHAT_DISABLED`, `DEMO_RUNS_PER_DAY` (25), `DEMO_UNITS_PER_DAY` (3,000), `DEMO_REFRESH_COOLDOWN` (300 s) |

- **Keyword run size and cost.** The page lets you pick the number of top videos (up to 200) and comments per video (up to 100) and shows an estimate first: YouTube quota is about `100 x search pages + 3 x videos + one comment call per video`, and Claude is about 45 input and 8 output tokens per comment read plus a small fixed amount. Dollars use `pricing` in `input.json` (default 3 and 15 USD per million input and output tokens; change it to your plan's price). Measured: a 20 x 20 run used about 17k input and 4k output tokens; the default 200 x 20 is estimated at roughly 1,300 quota units and about 1 USD. The hosted page also caps live runs per day by YouTube units (`DEMO_UNITS_PER_DAY`, default 3,000).
- **Cost per scheduled run.** Every step logs the tokens and quota units it used; the Run log shows them with the estimated cost for each run.
- **Live chat** (`api/chat.py`) reuses the Q&A core over `api/public.db`, a copy of the database with no comment text. It accepts same-site requests only, short questions, and limited questions per visitor.
- **Keyword runs** (`api/step.py`) run one stage per request and the browser carries the state, so the page can show the steps live; every call needs the demo code. Five wrong codes lock a visitor out for ten minutes.
- **Refresh now** (`api/refresh.py`) starts the real workflow on GitHub Actions and the page follows its four stages through GitHub's public API.
- Where the functions are missing (GitHub Pages), the page falls back to the recorded sample and recorded answers by itself.


## The daily run

`refresh.yml` runs every day at 15:00 UTC and on demand, in four stages that appear as four workflow steps: **1 Refresh source data** (new videos, stats, daily view snapshot, baselines) → **2 Analyse** (label new comments, assign topics and discover new ones, insights and changes) → **3 Update reports** (topic notes, recorded Q&A, the text-free database, the page) → **4 Push to email and Slack**. Then it records the run in `state/runs.json` and commits `state/`, `docs/` and `api/` back, so the next run is incremental and the hosted page redeploys.

- **Light pass** (Tuesday to Sunday): skips the slow Claude steps but still sends a short "daily" email and Slack digest.
- **Full pass** (Monday): everything, plus the full "weekly" email and digest.
- Inputs when started by hand: `send` (off = no email or Slack) and `mode` (auto, daily, weekly).


## Run it on your computer

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
