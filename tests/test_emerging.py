import unittest
from tests import helpers  # noqa: F401
import emerging

BATTERY = ["the battery drains so fast on this thing", "battery life looks terrible honestly", "worried about battery life with two screens", "will the battery last a full day",
           "battery drains overnight on mine", "battery capacity seems small for the size", "that battery is the real problem for me", "battery health after a year worries me"]
PENCIL = ["apple pencil support would be amazing here", "no pencil support is a dealbreaker for notes", "i want pencil support on the inner screen", "pencil support please apple",
          "drawing with the pencil support on this screen", "apple pencil would make this a tablet replacement", "the pencil support rumours were exciting", "pencil support or no deal for me"]


def rows(texts, day):
    return [dict(text=t, published=day, sentiment="neutral", themes=[]) for t in texts]


class Tokens(unittest.TestCase):
    def test_stopwords_removed_and_bigrams_added(self):
        t = emerging.tokens("The battery life is really bad")
        self.assertIn("battery", t)
        self.assertIn("battery life", t)
        self.assertNotIn("the", t)
        self.assertNotIn("really", t)

    def test_short_and_empty(self):
        self.assertEqual(emerging.tokens("a an of"), [])
        self.assertEqual(emerging.tokens(""), [])


class Clustering(unittest.TestCase):
    def test_two_clear_topics_are_separated(self):
        data = rows(BATTERY * 6 + PENCIL * 6, "2026-10-01")
        out = emerging.analyse(data, k=2, min_size=10, max_df=0.9)
        self.assertEqual(len(out), 2)
        for c in out:
            kinds = {("battery" in data[i]["text"]) for i in c["members"]}
            self.assertEqual(len(kinds), 1, "a cluster mixed both topics")
        self.assertTrue(any("battery" in " ".join(c["terms"]) for c in out))
        self.assertTrue(any("pencil" in " ".join(c["terms"]) for c in out))

    def test_deterministic(self):
        data = rows(BATTERY * 6 + PENCIL * 6, "2026-10-01")
        a = [c["members"] for c in emerging.analyse(data, k=2, min_size=10, max_df=0.9)]
        b = [c["members"] for c in emerging.analyse(data, k=2, min_size=10, max_df=0.9)]
        self.assertEqual(a, b)

    def test_recent_vs_prior_counts(self):
        data = rows(BATTERY * 3, "2026-10-04") + rows(BATTERY * 2, "2026-09-22") + rows(PENCIL * 6, "2026-09-01")
        out = {("battery" in " ".join(c["terms"])): c for c in emerging.analyse(data, k=2, min_size=5, max_df=0.9)}
        self.assertEqual((out[True]["recent"], out[True]["prior"]), (24, 16))
        self.assertEqual(out[False]["recent"], 0)

    def test_theme_alignment_and_no_theme_share(self):
        data = rows(BATTERY * 6, "2026-10-01")
        for i, r in enumerate(data):
            r["themes"] = ["software_usability"] if i % 2 == 0 else []
        c = emerging.analyse(data, k=1, min_size=10, max_df=0.9)[0]
        self.assertAlmostEqual(c["alignment"], 0.5, places=2)
        self.assertAlmostEqual(c["no_theme"], 0.5, places=2)
        self.assertEqual(c["dominant_theme"], "software_usability")


if __name__ == "__main__":
    unittest.main()
