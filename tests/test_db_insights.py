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

    def test_scale_improve_buckets(self):
        rows, med_net = insights.judged_videos(self.con)
        by = {r["video_id"]: r for r in rows}
        self.assertEqual(by["v11"]["bucket"], "scale")        # high lift + happy
        self.assertEqual(by["v10"]["bucket"], "improve")      # high lift + unhappy: fix before scaling
        self.assertEqual(by["v09"]["bucket"], "unverified")   # high lift, only 4 product-side comments
        for low in ("v00", "v01", "v02", "v03"):
            self.assertEqual(by[low]["bucket"], "improve", low)   # bottom quarter
        for mid in ("v05", "v06", "v07"):
            self.assertIsNone(by[mid]["bucket"], mid)
        self.assertAlmostEqual(med_net, 0.1, places=2)

    def test_metrics_counts(self):
        m = insights.metrics(self.con)
        self.assertEqual(m["scale_ready"], 1)
        self.assertEqual(m["improve_high_lift_unhappy_audience"], 1)
        self.assertEqual(m["outperformers_without_enough_comments"], 1)
        self.assertEqual(m["totals"]["videos"], 12)


class Tolerance(unittest.TestCase):
    def test_slightly_below_typical_still_counts_as_good(self):
        tmp = tempfile.TemporaryDirectory()
        comments = {i: MID for i in range(12)}
        comments[11] = (20, 6, 5)       # net +0.05: below typical +0.10 by 5 points exactly
        comments[10] = (20, 5, 7)       # net -0.10: clearly worse
        con = helpers.build(tmp.name, LIFTS, comments)
        by = {r["video_id"]: r for r in insights.judged_videos(con)[0]}
        self.assertEqual(by["v11"]["bucket"], "scale")
        self.assertEqual(by["v10"]["bucket"], "improve")
        con.close(); tmp.cleanup()


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
