#!/usr/bin/env python3
"""Step 9b: Slack Q&A agent (Socket Mode, runs on your machine, no public URL needed).
Mention @Launch Pulse in a channel or DM it. It answers from the SQLite tables through ask.py and offers a button to show the query it ran.
Run:  .venv/bin/python slack_bot.py     Needs SLACK_BOT_TOKEN (xoxb-) and SLACK_APP_TOKEN (xapp-) in ~/.creator-scout.env"""
import re, threading, uuid
from collections import defaultdict
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from common import secret
from ask import ask

app = App(token=secret("SLACK_BOT_TOKEN"))
HIST, SQLS, LOCK = defaultdict(list), {}, threading.Lock()
HELP = ("Ask me about the Apple launch on YouTube, for example:\n• what are people saying about Duo's price?\n• did seeded videos beat organic ones posted on the same days?\n"
        "• which formats work best for Duo under 250k subs?\n• why did negative sentiment rise this week?")


def answer(client, channel, thread_ts, question):
    q = re.sub(r"<@[^>]+>", "", question).strip()
    if not q or q.lower() in ("help", "hi", "hello"):
        client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=HELP); return
    msg = client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="Looking into it…")
    key = f"{channel}:{thread_ts}"
    try:
        r = ask(q, HIST[key])
    except Exception as e:
        client.chat_update(channel=channel, ts=msg["ts"], text=f"That one failed ({str(e)[:120]}). Try rephrasing."); return
    HIST[key].append(dict(q=q, a=r["answer"], sql=r["sql"] or ""))
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": r["answer"][:2900]}}]
    if r["sql"]:
        sid = uuid.uuid4().hex[:10]; SQLS[sid] = r["sql"]
        blocks.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Show the query"}, "action_id": "show_sql", "value": sid}]})
    client.chat_update(channel=channel, ts=msg["ts"], text=r["answer"][:300], blocks=blocks)


@app.event("app_mention")
def on_mention(event, client):
    answer(client, event["channel"], event.get("thread_ts") or event["ts"], event["text"])


@app.event("message")
def on_dm(event, client):
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"): return
    answer(client, event["channel"], event.get("thread_ts") or event["ts"], event["text"])


@app.action("show_sql")
def show_sql(ack, body, client):
    ack()
    sql = SQLS.get(body["actions"][0]["value"], "(query no longer cached)")
    client.chat_postMessage(channel=body["channel"]["id"], thread_ts=body["message"]["ts"], text="```" + sql[:2800] + "```")


if __name__ == "__main__":
    print("Launch Pulse bot connecting to Slack…")
    SocketModeHandler(app, secret("SLACK_APP_TOKEN")).start()
