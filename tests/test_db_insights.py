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


class Alerts(unittest.TestCase):
    def snap(self, neg, n=400, themes=None, total=1000, out=None):
        return dict(as_of="2026-10-04", recent=dict(n=n, pos=0.4, neg=neg, themes=themes or {}, total=total),
                    prior=dict(n=n, pos=0.4, neg=0.30, themes={}, total=total), outperformers=out or [])

    def test_sentiment_shift_needs_five_points_and_enough_comments(self):
        self.assertEqual([a["kind"] for a in insights.alerts(self.snap(0.36), None)], ["sentiment"])
        self.assertEqual(insights.alerts(self.snap(0.33), None), [])
        self.assertEqual(insights.alerts(self.snap(0.40, n=100), None), [])

    def test_theme_spike(self):
        s = self.snap(0.30, themes={"price_affordability": 80})
        s["prior"]["themes"] = {"price_affordability": 40}
        self.assertEqual([a["kind"] for a in insights.alerts(s, None)], ["theme"])

    def test_new_outperformers_vs_previous_snapshot(self):
        out = insights.alerts(self.snap(0.30, out=["a", "b", "c"]), {"outperformers": ["a"]})
        self.assertEqual(out[0]["ids"], ["b", "c"])
        self.assertEqual(insights.alerts(self.snap(0.30, out=["a"]), {"outperformers": ["a"]}), [])


if __name__ == "__main__":
    unittest.main()
