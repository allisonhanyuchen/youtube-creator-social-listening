#!/usr/bin/env python3
"""Recorded answers from the live Q&A agent, shown in the public demo (which has no chat). Each answer is generated with 'no quotes' and
checked against the comment corpus; an answer that shares a 5-word run with any comment is regenerated once, then dropped.
Output: state/examples.json  [{q, a, sql}]"""
import json, os, sqlite3
from common import DATA, HERE
from ask import ask
import public_safety as safe

QUESTIONS = [
    "Which channel sizes break out most, and are their audiences happy? Give n.",
    "Which content formats work best for mid-sized channels?",
    "Which high-lift videos have the most negative audience reaction? Name two examples, with lift and sentiment shown separately.",
    "Which audience topics are largest, and which are growing fastest this week?",
    "How does audience sentiment on the iPhone Duo compare with the iPhone 18 Pro?",
    "What do people like most about the Duo, and what do they criticise most?",
]


def main():
    con = sqlite3.connect(os.path.join(DATA, "pulse.db"))
    corp = safe.corpus(r[0] for r in con.execute("select text from comments where text is not null"))
    out = []
    for q in QUESTIONS:
        for attempt in range(2):
            r = ask(q, no_quotes=True)
            bad = safe.overlap(r["answer"], corp)
            if not bad and r["sql"]:
                out.append(dict(q=q, a=r["answer"], sql=r["sql"])); break
            print("  retry (overlap or no SQL):", q[:50], list(bad)[:1])
        else:
            print("  dropped:", q)
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "state", "examples.json"), "w"), ensure_ascii=False, indent=1)
    print(len(out), "examples saved")


if __name__ == "__main__":
    main()
