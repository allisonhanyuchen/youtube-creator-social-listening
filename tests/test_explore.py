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
                    videos=[dict(url="https://y/1", title="Desk review", channel="A", lift=3.2, views=1_500_000, ps=[3, 1, 1]), dict(url="https://y/2", title="Other", channel="B", lift=None, views=500_000, ps=[2, 2, 1])],
                    topics=[dict(name="Wobble", summary="People mention wobble at standing height", n=12, ps=[2, 3, 7], score=-42)],
                    summary=dict(headline="Mixed reception", bullets=["Lift is high on one video", "Wobble dominates the complaints"]),
                    _corpus=["my desk has a terrible wobble at the full standing height every single day"])

    def test_slack_payload_has_headline_topics_and_top_video(self):
        p = explore.slack_payload(self.rep())
        text = " ".join(b["text"]["text"] for b in p["blocks"] if b["type"] == "section")
        for s in ("Mixed reception", "Wobble", "Desk review"):
            self.assertIn(s, text)

    def test_email_is_styled_and_leads_with_the_score(self):
        html = explore.email_html(self.rep())
        for s in ("standing desk on YouTube", "Mixed reception", "Wobble", "Desk review", "sentiment score", "+30"):
            self.assertIn(s, html)
        self.assertIn("background:#2f8f5b", html)                       # the coloured sentiment bar, like the daily email

    def test_public_sample_drops_text_that_copies_a_comment_and_never_keeps_the_corpus(self):
        rep = self.rep()
        rep["topics"][0]["summary"] = "my desk has a terrible wobble at the full standing height every single day"
        out = explore.sanitise_for_public(rep)
        self.assertEqual(out["topics"][0]["summary"], "")
        self.assertNotIn("_corpus", out)


if __name__ == "__main__":
    unittest.main()
