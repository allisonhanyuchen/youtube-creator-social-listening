import unittest
from tests import helpers  # noqa: F401  (sets sys.path)
import comments, price_sub


class ParseLabelLines(unittest.TestCase):
    def test_full_line(self):
        out = comments.parse_label_lines("3|e|P|-|3,10|n")
        self.assertEqual(out[3], {"l": "en", "t": "product", "s": "negative", "th": ["price_affordability", "software_usability"], "in": "none"})

    def test_other_language_creator_target_no_themes(self):
        out = comments.parse_label_lines("4|o|C|+|-|b")
        self.assertEqual(out[4]["l"], "other")
        self.assertEqual(out[4]["t"], "video_or_creator")
        self.assertEqual(out[4]["th"], [])
        self.assertEqual(out[4]["in"], "buy")

    def test_malformed_lines_are_skipped(self):
        out = comments.parse_label_lines("garbage\n1|e|P\nx|e|P|+|-|n\n2|e|P|0|-|n")
        self.assertEqual(list(out), [2])

    def test_theme_numbers_outside_taxonomy_are_dropped(self):
        out = comments.parse_label_lines("1|e|P|+|99,2,0|n")
        self.assertEqual(out[1]["th"], ["fold_animation_ui"])


class Trivial(unittest.TestCase):
    def test_no_signal(self):
        for t in ("😂😂😂", "first", "FIRST!", "4:20", "12:34 lol", "👍"):
            self.assertTrue(comments.trivial(t), t)

    def test_signal(self):
        for t in ("Price is insane for a phone with no Face ID", "The animation is so smooth", "Where is the telephoto lens"):
            self.assertFalse(comments.trivial(t), t)


class PriceSub(unittest.TestCase):
    def test_parse_and_bounds(self):
        out = price_sub.parse_lines("0|1\n1|9\n2|12\n3|0\nnope")
        self.assertEqual(out, {0: "regional_price_gap", 1: "general"})

    def test_taxonomy_has_a_catch_all(self):
        self.assertIn("general", price_sub.SUBS)


if __name__ == "__main__":
    unittest.main()
