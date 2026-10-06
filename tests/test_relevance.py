import unittest
from unittest import mock
from tests import helpers  # noqa: F401  (sets sys.path)
import relevance


class Relevance(unittest.TestCase):
    def test_off_topic_videos_are_found_and_moved_out_of_the_products_topic(self):
        items = [dict(id="a", title="iPhone Duo review", channel="X"), dict(id="b", title="Best case for iPhone Duo", channel="Y"), dict(id="c", title="Another Duo mouse", channel="Z")]
        reply = '{"results": [{"id": "a", "about": true}, {"id": "b", "about": false}, {"id": "c", "about": false}]}'
        with mock.patch.object(relevance, "claude", lambda *a, **k: reply):
            off = relevance.not_about(items, "Apple iPhone Duo")
        self.assertEqual(off, {"b", "c"})
        vids = [dict(id="a", topic="duo"), dict(id="b", topic="duo"), dict(id="c", topic="other")]
        self.assertEqual(relevance.apply(vids, off, "duo"), 1)                     # only "b" was in the topic, so only it moves
        self.assertEqual((vids[1]["topic"], vids[1]["topic_raw"], vids[1]["relevant"]), ("other", "duo", False))
        self.assertTrue(vids[0]["relevant"])

    def test_a_failed_check_keeps_the_videos(self):
        with mock.patch.object(relevance, "claude", lambda *a, **k: "not json"):
            self.assertEqual(relevance.not_about([dict(id="a", title="t", channel="c")], "x"), set())
