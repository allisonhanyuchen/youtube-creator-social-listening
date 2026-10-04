import json, os, re, tempfile, unittest
from tests import helpers
import collect, common, report, state_io

SECRET_TEXT = "SECRET-COMMENT-TEXT-do-not-publish"


class StateHasNoText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data, self.state = os.path.join(self.tmp.name, "data"), os.path.join(self.tmp.name, "state")
        os.makedirs(self.data)
        common.DATA = state_io.DATA = self.data
        state_io.STATE = self.state
        w = lambda n, o: json.dump(o, open(os.path.join(self.data, n), "w"))
        w("videos.json", [dict(id="v1", title="T", desc="a description that must not be published", collab="affiliate", promo_type="organic", views=5)])
        w("creators.json", [dict(channel_id="c1", name="N")])
        w("channels_meta.json", {"c1": {"country": "US", "about": "x", "titles": []}})
        w("baselines.json", {"c1": [dict(p="2026-08-01", v=10, s=False, ip=False)]})
        w("comment_labels.json", {"k1": dict(lang="en", target="product", sentiment="positive", themes=[], intent="none", label_mode="fast")})
        w("comments_raw.json", {"v1": [dict(comment_id="k1", video_id="v1", text=SECRET_TEXT, likes=3, published="2026-09-10T00:00:00Z", source="relevance")]})

    def tearDown(self):
        self.tmp.cleanup(); common.DATA = state_io.DATA = helpers.ORIG_DATA; state_io.STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state')

    def test_saved_state_contains_no_comment_text_or_descriptions(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            state_io.save()
        blob = "".join(open(os.path.join(self.state, f)).read() for f in os.listdir(self.state))
        self.assertNotIn(SECRET_TEXT, blob)
        self.assertNotIn("must not be published", blob)
        v = json.load(open(os.path.join(self.state, "videos.json")))[0]
        self.assertEqual(v["desc"], "")
        for gone in ("collab", "promo_type"):
            self.assertNotIn(gone, v)

    def test_labels_keep_their_non_text_meta(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            state_io.save()
        l = json.load(open(os.path.join(self.state, "comment_labels.json")))["k1"]
        self.assertEqual((l["v"], l["p"], l["k"], l["s"]), ("v1", "2026-09-10", 3, "relevance"))

    def test_restore_seeds_an_empty_data_folder(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            state_io.save()
        for f in os.listdir(self.data): os.remove(os.path.join(self.data, f))
        state_io.restore()
        self.assertTrue(os.path.exists(os.path.join(self.data, "videos.json")))
        self.assertTrue(os.path.exists(os.path.join(self.data, "videos_raw.json")))


def fake_ins(headline="A headline"):
    size = lambda: dict(videos=10, outperformer_rate=0.3, pos=0.4, neg=0.3)
    return dict(as_of="2026-10-04", alerts=[dict(kind="topic", text="Price mentions are up")],
                narrative=dict(headline=headline, summary="Summary.", watch="Watch.", findings=[dict(title=f"F{i}", detail="d", action="a") for i in range(4)]),
                metrics=dict(totals=dict(videos=10, views=5_000_000, comments_en=1234), sentiment=dict(pos=0.4, neg=0.3), by_channel_size={k: size() for k in ("small (<250k)", "mid (250k-1M)", "large (1M+)")},
                             by_format=[dict(format="first_impressions", videos=12, outperformer_rate=0.4)], topics=[dict(id="p04", name="Price Complaints", summary="s", discovered=True, first_seen="2026-10-04", n=200, share=0.2, pos=0.2, neg=0.6, recent=40, trend=1.8)],
                             coverage=dict(videos=10, creators=8, with_sentiment=6, comments_en=1234, by_level={"small (<250k)": 4, "mid (250k-1M)": 3, "large (1M+)": 3}),
                             changes=dict(since="2026-09-27", new_videos=3, new_comments=120, new_topics=[dict(id="p21", name="Battery Life", n=40)], moved=[], sentiment_delta=dict(pos=0.01, neg=-0.02)),
                             watchlist=[dict(id="p04", name="Price Complaints", why="gaining")],
                             highest_lift=[dict(title="Good", url="https://y/1", creator="C", channel_size="small (<250k)", format="comparison", rel_lift=3.1, views=1000, product_comments=40, pos=0.6, neg=0.1),
                                           dict(title="Thin", url="https://y/2", creator="D", channel_size="mid (250k-1M)", format="first_impressions", rel_lift=9.0, views=5000, product_comments=3, pos=None, neg=None)]))


class EmailReport(unittest.TestCase):
    def test_renders_the_readout(self):
        html = report.build(fake_ins())
        for s in ("A headline", "Price mentions are up", "Highest-lift videos", "Price Complaints", "Battery Life", "Watchlist", "too few comments for sentiment", "60% positive"):
            self.assertIn(s, html)

    def test_no_traces_of_the_removed_paid_seeded_analysis(self):
        self.assertIsNone(re.search(r"(?i)paid|seeded|organic|sponsor", report.build(fake_ins())))

    def test_html_is_escaped(self):
        html = report.build(fake_ins(headline="<script>alert(1)</script>"))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class CollectHelpers(unittest.TestCase):
    def test_iso_duration(self):
        self.assertEqual(collect.iso_seconds("PT1M30S"), 90)
        self.assertEqual(collect.iso_seconds("PT1H2M3S"), 3723)
        self.assertEqual(collect.iso_seconds("PT45S"), 45)
        self.assertEqual(collect.iso_seconds(None), 0)

    def test_language_filter(self):
        v = lambda title, lang=None, ch="Chan": {"snippet": {"title": title, "channelTitle": ch, **({"defaultAudioLanguage": lang} if lang else {})}}
        self.assertTrue(collect.looks_english(v("iPhone Duo review", "en-US")))
        self.assertFalse(collect.looks_english(v("iPhone Duo review", "hi")))
        self.assertTrue(collect.looks_english(v("iPhone Duo review")))                       # no language field: judged from the text
        self.assertFalse(collect.looks_english(v("आईफोन डुओ रिव्यू", ch="टेक")))


class PublicDemoHasNoCommentText(unittest.TestCase):
    def test_scrub_removes_every_piece_of_comment_text(self):
        import build_dashboard
        data = dict(quotes=[[0, 1, 0, SECRET_TEXT, 5]],
                    videos=[dict(a=dict(tc=[[SECRET_TEXT, 0, [], 3]], ps=[1, 2, 3]))], words=dict(pos=[["good", 30]], neg=[]))
        out = build_dashboard.scrub_public(data)
        self.assertNotIn(SECRET_TEXT, json.dumps(out))
        self.assertTrue(out["public"])
        self.assertEqual(out["videos"][0]["a"]["ps"], [1, 2, 3])          # aggregates stay


class PublicSafety(unittest.TestCase):
    CORPUS_TEXTS = ["This is a completely ridiculous price for a phone with no telephoto lens at all",
                    "price for the iphone 18 pro is fine", "price for the iphone 18 pro is wild", "price for the iphone 18 pro makes no sense"]

    def test_distinctive_copy_is_flagged(self):
        import public_safety as safe
        corp = safe.corpus(self.CORPUS_TEXTS)
        self.assertTrue(safe.overlap("Someone called it a completely ridiculous price for a phone, again", corp))

    def test_paraphrase_and_common_phrases_pass(self):
        import public_safety as safe
        corp = safe.corpus(self.CORPUS_TEXTS)
        self.assertFalse(safe.overlap("Many people think the cost is far too high given the missing zoom camera", corp))
        self.assertFalse(safe.overlap("Opinions on the price for the iphone 18 pro are mixed", corp))      # an ordinary phrase many comments share

    def test_build_refuses_text_that_copies_a_comment(self):
        import build_dashboard, public_safety as safe
        data = {"summaries": {"topics": {"p04": {"positive": [], "negative": ["a completely ridiculous price for a phone with no telephoto lens"]}}}, "topics": []}
        tmp = tempfile.TemporaryDirectory()
        old = build_dashboard.HERE; build_dashboard.HERE = tmp.name          # no examples.json here
        try:
            with self.assertRaises(SystemExit):
                build_dashboard.attach_public_text(data, safe.corpus(self.CORPUS_TEXTS))
        finally:
            build_dashboard.HERE = old; tmp.cleanup()

    def test_build_accepts_a_paraphrase(self):
        import build_dashboard, public_safety as safe
        data = {"summaries": {"topics": {"p04": {"positive": [], "negative": ["Many people think the cost is far too high given the missing zoom camera"]}}}, "topics": [dict(name="Zoom lens", summary="People miss the telephoto camera")]}
        tmp = tempfile.TemporaryDirectory()
        old = build_dashboard.HERE; build_dashboard.HERE = tmp.name
        try:
            out = build_dashboard.attach_public_text(data, safe.corpus(self.CORPUS_TEXTS))
            self.assertEqual(out["examples"], [])
        finally:
            build_dashboard.HERE = old; tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
