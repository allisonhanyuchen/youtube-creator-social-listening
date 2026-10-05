import os, unittest
from unittest import mock
from tests import helpers  # noqa: F401  (sets sys.path)
import demo_gate as gate


class DemoGate(unittest.TestCase):
    def setUp(self):
        gate.FAILS.clear(); gate.RUNS.update(d="", n=0, units=0, refresh=0.0)

    def test_only_the_right_code_passes_and_the_code_is_never_defaulted(self):
        with mock.patch.dict(os.environ, {"DEMO_CODE": "s3cret"}):
            self.assertTrue(gate.check_code("s3cret", "1.1.1.1")[0])
            self.assertFalse(gate.check_code("S3cret", "1.1.1.1")[0])
            self.assertFalse(gate.check_code("", "1.1.1.1")[0])
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(gate.configured())
            self.assertFalse(gate.check_code("", "2.2.2.2")[0])          # nothing configured: nothing unlocks, not even an empty code

    def test_five_misses_lock_a_visitor_out_even_for_the_right_code(self):
        with mock.patch.dict(os.environ, {"DEMO_CODE": "s3cret"}):
            for _ in range(gate.MAX_FAILS): gate.check_code("nope", "3.3.3.3")
            ok, why = gate.check_code("s3cret", "3.3.3.3")
            self.assertFalse(ok); self.assertIn("Too many", why)
            self.assertTrue(gate.check_code("s3cret", "4.4.4.4")[0])      # someone else is unaffected

    def test_daily_run_budget_and_refresh_cooldown(self):
        for _ in range(gate.MAX_RUNS_PER_DAY): self.assertTrue(gate.allow_run()[0])
        self.assertFalse(gate.allow_run()[0])
        self.assertTrue(gate.allow_refresh()[0])
        self.assertFalse(gate.allow_refresh()[0])

    def test_youtube_quota_budget_limits_big_runs(self):
        self.assertTrue(gate.allow_run(1300)[0])
        self.assertTrue(gate.allow_run(1300)[0])
        ok, why = gate.allow_run(1300)                       # a third 200-video run would pass 3,000 units
        self.assertFalse(ok); self.assertIn("quota units", why)
        self.assertTrue(gate.allow_run(100)[0])              # a small run still fits

    def test_same_site_only(self):
        self.assertTrue(gate.same_site({"Origin": "https://x.vercel.app", "Host": "x.vercel.app"}))
        self.assertFalse(gate.same_site({"Origin": "https://evil.example", "Host": "x.vercel.app"}))


class StageMap(unittest.TestCase):
    def test_every_pipeline_step_belongs_to_exactly_one_stage_or_push(self):
        import run_weekly as rw
        staged = [n for names in rw.STAGES.values() for n in names]
        self.assertEqual(sorted(staged), sorted(n for n, _ in rw.STEPS))
        self.assertEqual(len(staged), len(set(staged)))

    def test_daily_pass_skips_the_slow_steps(self):
        import run_weekly as rw
        names = [n for sg in ("refresh", "analyse", "report") for n, _ in rw.stage_steps(sg, "daily", True)]
        for slow in rw.DAILY_SKIP: self.assertNotIn(slow, names)
        self.assertEqual([n for n, _ in rw.stage_steps("push", "daily", False)], [])          # --no-send


class SavedInput(unittest.TestCase):
    CUR = {"name": "iPhone Duo", "brand": "Apple", "keywords": ["iPhone Duo review"], "top_videos": 50, "comments_per_video": 60, "competitors": {"Samsung": "samsung"}, "pricing": {"input_per_m": 3, "output_per_m": 15}, "demo": True}

    def test_same_product_keeps_everything_else_and_only_changes_the_sizes(self):
        import inputs
        new, fresh = inputs.merge_input(self.CUR, "iPhone Duo hands on, iPhone Duo worth it", 200, 20)
        self.assertFalse(fresh)
        self.assertEqual((new["brand"], new["competitors"], new["top_videos"], new["comments_per_video"]), ("Apple", {"Samsung": "samsung"}, 200, 20))
        self.assertEqual(new["keywords"], ["iPhone Duo hands on", "iPhone Duo worth it"])

    def test_new_product_starts_fresh_and_keeps_only_deployment_settings(self):
        import inputs
        from datetime import date
        new, fresh = inputs.merge_input(self.CUR, "Galaxy Z Fold 8 review\nGalaxy Z Fold 8 vs Pixel Fold", 999, 0, today=date(2026, 10, 5))
        self.assertTrue(fresh)
        self.assertEqual((new["name"], new["brand"], new["competitors"], new["topic"]), ("Galaxy Z Fold 8", "", {}, "main"))
        self.assertEqual((new["top_videos"], new["comments_per_video"]), (200, 1))                    # capped and floored
        self.assertEqual((new["pricing"], new["demo"]), (self.CUR["pricing"], True))
        self.assertIn("galaxy", new["topic_regex"]); self.assertNotIn("review", new["topic_regex"])
        self.assertEqual(new["launch"], "2026-09-05")

    def test_empty_keywords_are_rejected(self):
        import inputs
        with self.assertRaises(ValueError): inputs.merge_input(self.CUR, " , ", 50, 20)


class RunUsage(unittest.TestCase):
    def test_usage_is_summed_across_steps_and_priced(self):
        import json, tempfile
        import run_weekly as rw
        tmp = tempfile.mkdtemp()
        old = rw.USAGE_LOG; rw.USAGE_LOG = os.path.join(tmp, "u.jsonl")
        try:
            with open(rw.USAGE_LOG, "w") as f:
                f.write(json.dumps(dict(step="a", claude_in=100_000, claude_out=20_000, calls=3, yt_units=900)) + "\n" + json.dumps(dict(step="b", claude_in=2_000, claude_out=500, calls=1, yt_units=700)) + "\n")
            u = rw.run_usage()
        finally:
            rw.USAGE_LOG = old
        self.assertEqual((u["claude_in"], u["claude_out"], u["yt_units"]), (102_000, 20_500, 1_600))
        self.assertAlmostEqual(u["usd"], 0.613, places=3)           # 3 dollars per million in, 15 per million out


if __name__ == "__main__":
    unittest.main()
