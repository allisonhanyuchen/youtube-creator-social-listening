import unittest
from tests import helpers  # noqa: F401  (sets sys.path)
import explore


class ExploreHelpers(unittest.TestCase):
    def test_net_score_is_positive_minus_negative_in_points(self):
        self.assertEqual(explore.net([6, 2, 2]), 40)
        self.assertEqual(explore.net([1, 8, 1]), 0)
        self.assertIsNone(explore.net([0, 0, 0]))

    def rep(self):
        return dict(keyword="standing desk", totals=dict(videos=2, channels=2, views=2_000_000, comments=40, ps=[5, 3, 2], score=30),
                    videos=[], topics=[dict(name="Wobble", summary="People mention wobble at standing height", n=12, ps=[2, 3, 7], score=-42)],
                    summary=dict(headline="Mixed reception", bullets=["Lift is high on one video", "Wobble dominates the complaints"]),
                    _corpus=["my desk has a terrible wobble at the full standing height every single day"])

    def test_push_is_the_full_reports_summary_read_from_docs_when_there_are_no_local_insights(self):
        import json, os, tempfile
        from unittest import mock
        tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(tmp.name, "docs"))
        json.dump({"push": {"subject": "S", "email": "<p>full</p>", "slack": {"text": "x", "blocks": []}}}, open(os.path.join(tmp.name, "docs", "data.json"), "w"))
        with mock.patch.object(explore, "HERE", tmp.name):
            self.assertEqual(explore.push_bundle()["subject"], "S")
        tmp.cleanup()

    def test_estimate_scales_with_videos_and_comments_and_matches_a_measured_run(self):
        small, big = explore.estimate(20, 20), explore.estimate(200, 20)
        self.assertAlmostEqual(small["tokens_in"], 17_400, delta=1_500)              # a measured 20 x 20 run used about 17.4k input tokens
        self.assertGreater(big["yt_units"], small["yt_units"] * 5)
        self.assertGreater(big["usd"], small["usd"] * 5)
        self.assertEqual(explore.estimate(9999, 9999)["videos"], explore.CAP_VIDEOS)       # capped
        self.assertEqual(explore.clamp("abc", 200, 200), 200)

    def test_label_can_stop_on_a_budget_and_continue_where_it_left_off(self):
        from unittest import mock
        calls = []
        def fake(batch, kw):
            calls.append(len(batch)); return [{"l": "en", "t": "product", "s": "positive", "in": "none"}] * len(batch)
        texts = [f"c{i}" for i in range(60 * 9)]                                      # nine batches
        with mock.patch.object(explore, "label_batch", fake):
            part, finished = explore.label(texts, "x", budget=-1, workers=4)             # an exhausted budget stops after the first round
            self.assertFalse(finished); self.assertEqual(sum(1 for x in part if x), 4 * 60)
            done, finished = explore.label(texts, "x", part, budget=None, workers=4)
            self.assertTrue(finished); self.assertTrue(all(done))
        self.assertEqual(len(calls), 9)                                                  # nothing was labelled twice

    def test_the_push_step_is_named_for_the_full_report(self):
        self.assertIn("full report", dict(explore.STEPS)["push"])

    def test_public_sample_drops_text_that_copies_a_comment_and_never_keeps_the_corpus(self):
        rep = self.rep()
        rep["topics"][0]["summary"] = "my desk has a terrible wobble at the full standing height every single day"
        out = explore.sanitise_for_public(rep)
        self.assertEqual(out["topics"][0]["summary"], "")
        self.assertNotIn("_corpus", out)


if __name__ == "__main__":
    unittest.main()
