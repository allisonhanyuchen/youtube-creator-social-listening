import tempfile, unittest
from tests import helpers
import insights

# 12 Duo videos, lifts chosen so the quartile cut-offs are known: median 1.3, top-quarter cut at lift 3 (rel 2.31), bottom-quarter cut at lift 0.8
LIFTS = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0, 3.0, 5.0, 8.0]
# (product-side comments, positive, negative). Mid videos carry a mildly positive typical reaction (net +0.1).
MID = (20, 6, 4)
COMMENTS = {i: MID for i in range(12)}
COMMENTS.update({11: (20, 15, 2),     # lift 8: happy audience -> scale
                 10: (20, 3, 12),     # lift 5: unhappy audience -> improve
                 9: (4, 4, 0)})       # lift 3: too few comments -> unverified


class DatabaseAndBuckets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = helpers.build(self.tmp.name, LIFTS, COMMENTS)

    def tearDown(self):
        self.con.close(); self.tmp.cleanup(); helpers.common.DATA, helpers.db.DB = helpers.ORIG_DATA, helpers.ORIG_DB

    def test_outperformer_is_top_quartile_of_rel_lift(self):
        got = {r["video_id"] for r in self.con.execute("select video_id from performance where outperformer=1")}
        self.assertEqual(got, {"v09", "v10", "v11"})
        self.assertAlmostEqual(self.con.execute("select rel_lift from performance where video_id='v11'").fetchone()[0], 8.0 / 1.3, places=2)

    def test_official_channel_gets_no_lift(self):
        tmp = tempfile.TemporaryDirectory()
        con = helpers.build(tmp.name, LIFTS, COMMENTS, official={11})
        self.assertIsNone(con.execute("select outperformer from performance where video_id='v11'").fetchone()[0])
        self.assertIsNone(con.execute("select rel_lift from performance where video_id='v11'").fetchone()[0])
        con.close(); tmp.cleanup()

    def test_comments_survive_without_text(self):
        self.assertEqual(self.con.execute("select count(*) from comments where text is null").fetchone()[0], self.con.execute("select count(*) from comments").fetchone()[0])

    def test_underperformers_are_the_bottom_quarter_and_no_verdicts_exist(self):
        rows = insights.video_rows(self.con)
        by = {r["video_id"]: r for r in rows}
        self.assertEqual({k for k, r in by.items() if r["under"]}, {"v00", "v01", "v02", "v03"})
        for r in rows:
            self.assertNotIn("bucket", r)                      # lift and sentiment are reported side by side, never merged

    def test_metrics(self):
        m = insights.metrics(self.con)
        self.assertEqual(m["totals"]["videos"], 12)
        self.assertAlmostEqual(m["outperformer_rate"], 3 / 12, places=2)
        self.assertEqual([x["rel_lift"] for x in m["highest_lift"]][:3], [round(8 / 1.3, 1), round(5 / 1.3, 1), round(3 / 1.3, 1)])
        top = m["highest_lift"][0]
        self.assertEqual(top["product_comments"], 20)
        self.assertAlmostEqual(top["pos"], 0.75, places=2)     # 15 of 20 positive
        self.assertEqual(m["highest_lift"][2]["product_comments"], 4)    # too few to judge: reported as a count, not hidden


class HostedChat(unittest.TestCase):
    def test_limits_per_visitor_and_per_day(self):
        import importlib, sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "api"))
        chat = importlib.import_module("chat")
        chat.HITS.clear(); chat.DAY.update(d="", n=0)
        results = [chat.allowed("1.1.1.1")[0] for _ in range(chat.PER_VISITOR_HOUR + 1)]
        self.assertEqual(results, [True] * chat.PER_VISITOR_HOUR + [False])
        self.assertTrue(chat.allowed("2.2.2.2")[0])                    # another visitor is unaffected
        chat.HITS.clear(); chat.DAY.update(n=chat.GLOBAL_DAY)
        self.assertFalse(chat.allowed("3.3.3.3")[0])                   # global daily budget


class ChangesAndWatchlist(unittest.TestCase):
    def test_first_run_has_no_changes(self):
        self.assertIsNone(insights.changes(dict(topics={}), None))

    def test_new_topic_and_growth_are_reported(self):
        prev = dict(as_of="2026-09-27", videos=["a"], comments=100, sentiment=dict(pos=0.4, neg=0.3), topics={"p01": dict(name="X", n=50, pos=0.4, neg=0.3)})
        snap = dict(videos=["a", "b"], comments=180, sentiment=dict(pos=0.41, neg=0.28),
                    topics={"p01": dict(name="X", n=90, pos=0.4, neg=0.3), "p02": dict(name="Y", n=40, pos=0.5, neg=0.2)})
        ch = insights.changes(snap, prev)
        self.assertEqual((ch["new_videos"], ch["new_comments"]), (1, 80))
        self.assertEqual([t["id"] for t in ch["new_topics"]], ["p02"])
        self.assertEqual(ch["moved"][0]["d_n"], 40)

    def test_watchlist_flags_gaining_and_net_negative_only(self):
        m = dict(topics=[dict(id="a", name="A", n=200, pos=0.2, neg=0.5, recent=10, trend=1.0), dict(id="b", name="B", n=100, pos=0.4, neg=0.3, recent=30, trend=2.0),
                         dict(id="c", name="C", n=300, pos=0.4, neg=0.3, recent=10, trend=1.0)])
        self.assertEqual([w["id"] for w in insights.watchlist(m)], ["a", "b"])


class Alerts(unittest.TestCase):
    def snap(self, neg, n=400, themes=None, total=1000, out=None):
        return dict(as_of="2026-10-04", topics={"p04": dict(name="Price Complaints")}, recent=dict(n=n, pos=0.4, neg=neg, by_topic=themes or {}, total=total),
                    prior=dict(n=n, pos=0.4, neg=0.30, by_topic={}, total=total), outperformers=out or [])

    def test_sentiment_shift_needs_five_points_and_enough_comments(self):
        self.assertEqual([a["kind"] for a in insights.alerts(self.snap(0.36), None)], ["sentiment"])
        self.assertEqual(insights.alerts(self.snap(0.33), None), [])
        self.assertEqual(insights.alerts(self.snap(0.40, n=100), None), [])

    def test_topic_spike(self):
        s = self.snap(0.30, themes={"p04": 80})
        s["prior"]["by_topic"] = {"p04": 40}
        self.assertEqual([a["kind"] for a in insights.alerts(s, None)], ["topic"])

    def test_new_outperformers_vs_previous_snapshot(self):
        out = insights.alerts(self.snap(0.30, out=["a", "b", "c"]), {"outperformers": ["a"]})
        self.assertEqual(out[0]["ids"], ["b", "c"])
        self.assertEqual(insights.alerts(self.snap(0.30, out=["a"]), {"outperformers": ["a"]}), [])


if __name__ == "__main__":
    unittest.main()
