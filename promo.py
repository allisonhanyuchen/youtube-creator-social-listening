#!/usr/bin/env python3
"""Step 1c: promo_type = paid | organic, with sub-types and evidence level.
paid / sponsored : creator disclosed a commercial sponsor (YouTube paid-promotion flag, or sponsor wording in the description)
paid / seeded    : Apple-supported early access, in kind (no cash): pre-launch review unit or event invite
                   - disclosed : the video or description says so
                   - inferred  : timing signature (hands-on within 0-1 days of the keynote; reviews on the embargo-lift day)
organic          : everything else. has_affiliate is a flag on top (creator monetisation, not a promotion strategy).
Public data cannot prove who Apple seeded, so 'inferred' is a lower bound, and creators who posted later are missed.
"""
import re
from collections import Counter
import json
from common import load, save, claude, parse_json

DISCLOSE = re.compile(r"(invited|apple park|briefing|early access|embargo|apple (sent|provided|loaned)|(sent|provided|loaned) (me|us)|review unit|thanks to apple|courtesy of apple)", re.I)
HANDS_ON_FORMATS = {"first_impressions", "keynote_recap"}
EMBARGO_FORMATS = {"full_review", "explainer_tips", "durability_test"}


def device_check(cands):
    """Claude judges from title + description whether the creator physically had the device. Cached by video id."""
    cache = load("device_check.json", {})
    todo = [v for v in cands if v["id"] not in cache]
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        out = parse_json(claude(
            "These YouTube videos about Apple's Sept 2026 launch were published at the launch or review-embargo time. For each, decide from "
            "the title and description whether the creator PHYSICALLY HAD the device (hands-on footage, real usage, a review based on use) "
            "or is only recapping the keynote / reacting / speculating / commenting on news. "
            "Return JSON only: {\"results\": [{\"id\": str, \"has_device\": \"yes\"|\"no\"|\"unclear\", \"why\": \"<=10 words\"}]}\n\n"
            + json.dumps([{"id": v["id"], "title": v["title"], "channel": v["channel"], "desc": v["desc"][:220]} for v in batch], ensure_ascii=False), 4000))
        for r in out["results"]: cache[r["id"]] = r
        save("device_check.json", cache)
    return cache


def main():
    vids = load("videos.json")
    longform = [v for v in vids if not v["is_short"] and v["format"] in EMBARGO_FORMATS and v["day"] > 1]
    by_day = Counter(v["day"] for v in longform)
    embargo_day, n = by_day.most_common(1)[0]
    chans = len({v["channel_id"] for v in longform if v["day"] == embargo_day})
    print(f"embargo-lift day = D+{embargo_day} ({n} long-form videos from {chans} channels)")
    for v in vids:
        text = v["title"] + " " + v["desc"]
        v["has_affiliate"] = v["collab"] == "affiliate"
        if v["format"] == "official":
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "official", "apple_channel", "channel"
        elif v["collab"] in ("paid_flag", "sponsored_text"):
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "paid", "sponsored", "disclosed"
        elif v["collab"] == "apple_provided_unit" or DISCLOSE.search(text):
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "paid", "seeded", "disclosed"
        elif not v["is_short"] and v["format"] in HANDS_ON_FORMATS and 0 <= v["day"] <= 1:
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "paid", "seeded", "inferred"
        elif not v["is_short"] and v["format"] in EMBARGO_FORMATS and v["day"] == embargo_day:
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "paid", "seeded", "inferred"
        else:
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "organic", "", ""
    cands = [v for v in vids if v["promo_evidence"] == "inferred"]
    chk = device_check(cands)
    for v in cands:
        r = chk.get(v["id"], {})
        v["device_check"] = r.get("has_device", "unclear")
        if v["device_check"] != "yes":      # recap / reaction / unclear: not enough to call it Apple-seeded
            v["promo_type"], v["promo_sub"], v["promo_evidence"] = "organic", "", ""
    save("videos.json", vids)
    c = Counter((v["promo_type"], v["promo_sub"], v["promo_evidence"]) for v in vids)
    for k, n in sorted(c.items(), key=lambda t: -t[1]): print(f"  {k}: {n}")
    print("organic with affiliate links:", sum(v["has_affiliate"] for v in vids if v["promo_type"] == "organic"))
    print("device check:", dict(Counter(v["device_check"] for v in cands)))
    print("\nkept as inferred-seeded:")
    for v in sorted((v for v in cands if v["promo_sub"] == "seeded"), key=lambda v: v["day"]):
        print(f"  D+{v['day']} {v['channel'][:22]:22} subs {v['subs']:>9,} | {v['title'][:55]} | {chk[v['id']].get('why','')}")
    print("\ndemoted to organic:")
    for v in (v for v in cands if v["promo_sub"] != "seeded"):
        print(f"  D+{v['day']} {v['channel'][:22]:22} | {v['title'][:50]} | {chk[v['id']].get('has_device')}: {chk[v['id']].get('why','')}")


if __name__ == "__main__":
    main()
