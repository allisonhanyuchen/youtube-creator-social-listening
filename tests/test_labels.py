import unittest
from tests import helpers  # noqa: F401  (sets sys.path)
import comments, textcluster


class ParseLabelLines(unittest.TestCase):
    def test_full_line(self):
        out = comments.parse_label_lines("3|e|P|-|n")
        self.assertEqual(out[3], {"l": "en", "t": "product", "s": "negative", "in": "none"})

    def test_other_language_creator_target(self):
        out = comments.parse_label_lines("4|o|C|+|b")
        self.assertEqual((out[4]["l"], out[4]["t"], out[4]["in"]), ("other", "video_or_creator", "buy"))

    def test_malformed_lines_are_skipped(self):
        out = comments.parse_label_lines("garbage\n1|e|P\nx|e|P|+|n\n2|e|P|0|n")
        self.assertEqual(list(out), [2])


class Trivial(unittest.TestCase):
    def test_no_signal(self):
        for t in ("😂😂😂", "first", "FIRST!", "4:20", "12:34 lol", "👍"):
            self.assertTrue(comments.trivial(t), t)

    def test_signal(self):
        for t in ("Price is insane for a phone with no Face ID", "The animation is so smooth", "Where is the telephoto lens"):
            self.assertFalse(comments.trivial(t), t)


class TextCluster(unittest.TestCase):
    TEXTS = (["the price is insane too expensive for a phone", "way too expensive price makes no sense", "price is crazy expensive for me"] * 14 +
             ["the camera under the display looks blurry", "under display camera quality is bad", "love the under display camera idea"] * 14)

    def test_two_obvious_topics_are_separated(self):
        _, cl = textcluster.clusters(self.TEXTS, k=2, min_size=10)
        self.assertEqual(len(cl), 2)
        self.assertTrue(any("expensive price" in c["terms"] for c in cl))

    def test_nearest_assigns_to_matching_topic_and_rejects_unrelated(self):
        vecs, cl = textcluster.clusters(self.TEXTS, k=2, min_size=10)
        centers = [c["center"] for c in cl]
        self.assertIsNotNone(textcluster.nearest(vecs[0], centers, 0.1))         # a member of the price cluster
        v2 = textcluster.tfidf([textcluster.tokens("zebra quantum lemonade")] + [textcluster.tokens(t) for t in self.TEXTS])[0]
        self.assertIsNone(textcluster.nearest(v2, centers, 0.1))


if __name__ == "__main__":
    unittest.main()
