#!/usr/bin/env python3
"""Weekly incremental run: collect new videos, label only what is new, rebuild the tables, write the insights, send the email and the Slack digest.
Used by the GitHub Actions schedule (and runnable locally):  python3 src/run_weekly.py [--no-send] [--daily|--weekly]
It can also run one stage at a time (--stage refresh|analyse|report|push|finish) so the workflow shows each stage as its own step, live, and the page can follow it.
In CI the run starts from state/ (text-free), and writes it back at the end so the next run is incremental."""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from common import HERE, SRC
import state_io

STEPS = [("collect new videos, refresh stats", ["collect.py", "--incremental"]), ("classify new videos", ["classify.py"]), ("daily view snapshot", ["snapshots.py"]), ("channel baselines and lift", ["performance.py"]), ("creator types", ["creators.py"]), ("pull and label new comments", ["comments.py", "--refresh"]),
         ("build tables", ["db.py"]), ("assign comments to topics, discover new ones", ["topics.py"]), ("insights, changes and alerts", ["insights.py"]), ("text-free database for the hosted Q&A", ["export_public_db.py"]), ("paraphrased topic notes", ["summaries.py"]), ("recorded Q&A examples", ["examples.py"]), ("public demo page", ["build_dashboard.py", "--public"])]
SEND = [("email report", ["report.py", "--send"]), ("Slack digest", ["notify.py"])]
DAILY_SKIP = {"paraphrased topic notes", "recorded Q&A examples", "text-free database for the hosted Q&A"}              # the slow, Claude-heavy steps only run in the weekly full pass
DAILY_SEND = [("email report", ["report.py", "--send", "--daily"]), ("Slack digest", ["notify.py", "--daily"])]
RUNS = os.path.join(HERE, "state", "runs.json")
ROWS = os.path.join(HERE, "data", "stage_rows.json")          # progress carried between stages when they run as separate processes
STAGES = {"refresh": ["collect new videos, refresh stats", "classify new videos", "daily view snapshot", "channel baselines and lift", "creator types"],
          "analyse": ["pull and label new comments", "build tables", "assign comments to topics, discover new ones", "insights, changes and alerts"],
          "report": ["text-free database for the hosted Q&A", "paraphrased topic notes", "recorded Q&A examples", "public demo page"]}


def mode():
    """daily = light pass (new data, topics, alerts) that still sends a short update; weekly = full pass with topic notes and the full email and digest. Auto: weekly on Mondays (UTC)."""
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


def run_one(name, cmd, rows):
    t0 = time.time()
    print(f"[start] {name}", flush=True)
    r = subprocess.run([sys.executable, os.path.join(SRC, cmd[0])] + cmd[1:], cwd=HERE, capture_output=True, text=True)
    out = (r.stdout.strip().splitlines() or [""])[-1][:160]
    err = (r.stderr.strip().splitlines() or [""])[-1][:160]
    ok = r.returncode == 0
    rows.append([name, "ok" if ok else "FAILED", f"{time.time() - t0:.0f}s", out if ok else err])
    print(f"[{'ok' if ok else 'FAILED'}] {name} ({time.time() - t0:.0f}s) {out if ok else err}", flush=True)
    return ok


def stage_steps(stage, md, send):
    steps = dict(STEPS)
    if stage == "push": return [] if not send else (SEND if md == "weekly" else DAILY_SEND)
    return [(n, steps[n]) for n in STAGES[stage] if md == "weekly" or n not in DAILY_SKIP]


def load_rows():
    return json.load(open(ROWS)) if os.path.exists(ROWS) else dict(started=datetime.now(timezone.utc).isoformat(), rows=[], failed=False)


def finish(md, st, send):
    rows, failed = st["rows"], st["failed"]
    record(md, datetime.fromisoformat(st["started"]), [tuple(r) for r in rows], failed, send)
    subprocess.run([sys.executable, os.path.join(SRC, "build_dashboard.py"), "--public"], cwd=HERE, capture_output=True)       # the page shows this run in its status strip
    if not failed or "--save-anyway" in sys.argv:
        state_io.save()
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a") as f:
            f.write("## Launch Pulse run\n\n| Step | Result | Time | Detail |\n|---|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} | {d.replace('|', '/')} |" for a, b, c, d in rows) + "\n")
    if os.path.exists(ROWS): os.remove(ROWS)
    return failed


def main():
    send = "--no-send" not in sys.argv
    md = mode()
    stage = sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else None
    print(f"mode: {md}" + (f" · stage: {stage}" if stage else ""), flush=True)
    if stage in (None, "refresh"):
        state_io.restore()
        if os.path.exists(ROWS): os.remove(ROWS)
    st = load_rows()
    if stage == "finish":
        sys.exit(1 if finish(md, st, send) else 0)
    for sg in ([stage] if stage else ["refresh", "analyse", "report", "push"]):
        if st["failed"]: break                                  # a failed stage stops the later ones
        for name, cmd in stage_steps(sg, md, send):
            if not run_one(name, cmd, st["rows"]):
                st["failed"] = True
                if name in dict(STEPS): break                   # later steps depend on this one
    os.makedirs(os.path.dirname(ROWS), exist_ok=True); json.dump(st, open(ROWS, "w"))
    if not stage: sys.exit(1 if finish(md, st, send) else 0)
    sys.exit(1 if st["failed"] else 0)


if __name__ == "__main__":
    main()
