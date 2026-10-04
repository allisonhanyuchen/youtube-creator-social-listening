#!/usr/bin/env python3
"""Weekly incremental run: collect new videos, label only what is new, rebuild the tables, write the insights, send the email and the Slack digest.
Used by the GitHub Actions schedule (and runnable locally):  python3 run_weekly.py [--no-send]
In CI the run starts from state/ (text-free), and writes it back at the end so the next run is incremental."""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from common import HERE
import state_io

STEPS = [("collect new videos, refresh stats", ["collect.py", "--incremental"]), ("classify new videos", ["classify.py"]), ("channel baselines and lift", ["performance.py"]), ("creator types", ["creators.py"]), ("pull and label new comments", ["comments.py", "--refresh"]),
         ("build tables", ["db.py"]), ("assign comments to topics, discover new ones", ["topics.py"]), ("insights, changes and alerts", ["insights.py"]), ("paraphrased topic notes", ["summaries.py"]), ("recorded Q&A examples", ["examples.py"]), ("public demo page", ["build_dashboard.py", "--public"])]
SEND = [("email report", ["report.py", "--send"]), ("Slack digest", ["notify.py"])]
DAILY_SKIP = {"paraphrased topic notes", "recorded Q&A examples"}              # the slow, Claude-heavy steps only run in the weekly full pass
DAILY_SEND = [("Slack alerts (only if something fired)", ["notify.py", "--alerts"])]
RUNS = os.path.join(HERE, "state", "runs.json")


def mode():
    """daily = light pass (new data, topics, alerts); weekly = full pass with narrative, email and digest. Auto: weekly on Mondays (UTC)."""
    if "--daily" in sys.argv: return "daily"
    if "--weekly" in sys.argv: return "weekly"
    return "weekly" if datetime.now(timezone.utc).weekday() == 0 else "daily"


def record(md, started, rows, failed, send):
    """Append this run to state/runs.json (kept to the last 30), which the dashboard shows as the run log and status strip."""
    ins = {}
    try: ins = json.load(open(os.path.join(HERE, "data", "insights.json")))
    except Exception: pass
    ch = ((ins.get("metrics") or {}).get("changes")) or {}
    ok = {a: b == "ok" for a, b, _, _ in rows}
    run = dict(started=started.isoformat(timespec="seconds"), finished=datetime.now(timezone.utc).isoformat(timespec="seconds"), mode=md, ok=not failed,
               source="github-actions" if os.environ.get("GITHUB_ACTIONS") else "local", new_videos=ch.get("new_videos"), new_comments=ch.get("new_comments"),
               new_topics=[t["name"] for t in ch.get("new_topics", [])], alerts=len(ins.get("alerts", [])),
               email=bool(ok.get("email report")), slack=bool(ok.get("Slack digest")), slack_alerts=bool(ok.get("Slack alerts (only if something fired)")),
               steps=[dict(name=a, status=b, secs=int(c.rstrip("s"))) for a, b, c, _ in rows])
    old = json.load(open(RUNS)) if os.path.exists(RUNS) else []
    json.dump((old + [run])[-30:], open(RUNS, "w"), indent=1)


def main():
    send = "--no-send" not in sys.argv
    md = mode(); started = datetime.now(timezone.utc)
    print(f"mode: {md}", flush=True)
    state_io.restore()
    rows, failed = [], False
    steps = [s for s in STEPS if md == "weekly" or s[0] not in DAILY_SKIP]
    for name, cmd in steps + ((SEND if md == "weekly" else DAILY_SEND) if send else []):
        t0 = time.time()
        r = subprocess.run([sys.executable] + cmd, cwd=HERE, capture_output=True, text=True)
        out = (r.stdout.strip().splitlines() or [""])[-1][:160]
        err = (r.stderr.strip().splitlines() or [""])[-1][:160]
        ok = r.returncode == 0
        rows.append((name, "ok" if ok else "FAILED", f"{time.time() - t0:.0f}s", out if ok else err))
        print(f"[{'ok' if ok else 'FAILED'}] {name} ({time.time() - t0:.0f}s) {out if ok else err}", flush=True)
        if not ok:
            failed = True
            if name in dict(STEPS): break          # later steps depend on this one
    record(md, started, rows, failed, send)
    subprocess.run([sys.executable, "build_dashboard.py", "--public"], cwd=HERE, capture_output=True)       # the page shows this run in its status strip
    if not failed or "--save-anyway" in sys.argv:
        state_io.save()
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a") as f:
            f.write("## Launch Pulse weekly run\n\n| Step | Result | Time | Detail |\n|---|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} | {d.replace('|', '/')} |" for a, b, c, d in rows) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
