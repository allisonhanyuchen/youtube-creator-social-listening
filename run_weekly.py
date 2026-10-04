#!/usr/bin/env python3
"""Weekly incremental run: collect new videos, label only what is new, rebuild the tables, write the insights, send the email and the Slack digest.
Used by the GitHub Actions schedule (and runnable locally):  python3 run_weekly.py [--no-send]
In CI the run starts from state/ (text-free), and writes it back at the end so the next run is incremental."""
import os, subprocess, sys, time
from common import HERE
import state_io

STEPS = [("collect new videos, refresh stats", ["collect.py", "--incremental"]), ("classify new videos", ["classify.py"]), ("paid vs organic", ["promo.py"]),
         ("channel baselines and lift", ["performance.py"]), ("creator types", ["creators.py"]), ("pull and label new comments", ["comments.py", "--refresh"]),
         ("recheck hype label", ["hype_recheck.py"]), ("recover ad-like label", ["credibility_pass.py"]), ("build tables", ["db.py"]), ("insights and alerts", ["insights.py"])]
SEND = [("email report", ["report.py", "--send"]), ("Slack digest", ["notify.py"])]


def main():
    send = "--no-send" not in sys.argv
    state_io.restore()
    rows, failed = [], False
    for name, cmd in STEPS + (SEND if send else []):
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
    if not failed or "--save-anyway" in sys.argv:
        state_io.save()
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a") as f:
            f.write("## Launch Pulse weekly run\n\n| Step | Result | Time | Detail |\n|---|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} | {d.replace('|', '/')} |" for a, b, c, d in rows) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
