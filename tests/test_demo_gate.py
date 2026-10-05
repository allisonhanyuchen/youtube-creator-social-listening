import os, unittest
from unittest import mock
from tests import helpers  # noqa: F401  (sets sys.path)
import demo_gate as gate


class DemoGate(unittest.TestCase):
    def setUp(self):
        gate.FAILS.clear(); gate.RUNS.update(d="", n=0, refresh=0.0)

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


if __name__ == "__main__":
    unittest.main()
