#!/usr/bin/env python3
"""Export a text-free copy of data/pulse.db for the public Q&A (api/public.db): comment text and any video description are removed,
labels, counts, topics and public video stats stay. Run after db.py / topics.py (run_weekly.py does it). Fails if any comment text is left."""
import os, shutil, sqlite3
from common import DATA, HERE

SRC, OUT = os.path.join(DATA, "pulse.db"), os.path.join(HERE, "api", "public.db")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT): os.remove(OUT)
    shutil.copy(SRC, OUT)
    con = sqlite3.connect(OUT)
    con.execute("UPDATE comments SET text=NULL")
    cols = [r[1] for r in con.execute("PRAGMA table_info(content)")]
    if "description" in cols: con.execute("UPDATE content SET description=NULL")
    con.commit(); con.execute("VACUUM")
    left = con.execute("SELECT count(*) FROM comments WHERE text IS NOT NULL").fetchone()[0]
    if left: raise SystemExit(f"{left} comments still have text, not exporting")
    n = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("creators", "content", "comments", "topics")}
    con.close()
    print(f"api/public.db {os.path.getsize(OUT)/1e6:.2f} MB (no comment text) | {n}")


if __name__ == "__main__":
    main()
