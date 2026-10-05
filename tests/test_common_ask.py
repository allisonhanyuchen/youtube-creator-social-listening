import os, sqlite3, tempfile, unittest
from tests import helpers  # noqa: F401
import ask, common


class ParseJson(unittest.TestCase):
    def test_ignores_text_around_json(self):
        self.assertEqual(common.parse_json('Sure! {"a": 1} hope that helps'), {"a": 1})

    def test_tolerates_raw_newline_inside_string(self):
        self.assertEqual(common.parse_json('{"a": "line1\nline2"}'), {"a": "line1\nline2"})

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            common.parse_json("no braces here")


class Secret(unittest.TestCase):
    def test_env_beats_file_and_missing_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "env"); open(f, "w").write("MY_TEST_KEY=from-file\n")
            old = common.ENV_FILE; common.ENV_FILE = f
            try:
                self.assertEqual(common.secret("MY_TEST_KEY"), "from-file")
                os.environ["MY_TEST_KEY"] = "from-env"
                self.assertEqual(common.secret("MY_TEST_KEY"), "from-env")
                del os.environ["MY_TEST_KEY"]
                self.assertIsNone(common.secret("NOT_THERE", required=False))
                with self.assertRaises(SystemExit):
                    common.secret("NOT_THERE")
            finally:
                common.ENV_FILE = old
                os.environ.pop("MY_TEST_KEY", None)


class ReadOnlySql(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ask.DB = os.path.join(self.tmp.name, "t.db")
        con = sqlite3.connect(ask.DB); con.execute("create table t(a int)"); con.executemany("insert into t values (?)", [(i,) for i in range(100)]); con.commit(); con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_select_and_with_are_allowed(self):
        cols, rows = ask.run_sql("select a from t where a < 3 order by a")
        self.assertEqual(cols, ["a"]); self.assertEqual(rows, [[0], [1], [2]])
        self.assertEqual(ask.run_sql("with x as (select 5 as b) select b from x")[1], [[5]])

    def test_row_cap(self):
        self.assertEqual(len(ask.run_sql("select a from t")[1]), ask.MAX_ROWS)

    def test_anything_that_writes_is_rejected(self):
        for bad in ("delete from t", "drop table t", "insert into t values (1)", "update t set a=1", "pragma table_info(t)",
                    "select 1; select 2", "with x as (select 1) insert into t select * from x", "attach database 'x' as y", "create table z(a int)"):
            with self.assertRaises(ValueError, msg=bad):
                ask.run_sql(bad)
        self.assertEqual(ask.run_sql("select count(*) from t")[1], [[100]])      # data untouched

    def test_connection_is_read_only_even_if_the_filter_were_bypassed(self):
        con = sqlite3.connect(f"file:{ask.DB}?mode=ro", uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("insert into t values (1)")


if __name__ == "__main__":
    unittest.main()


class SlackLinks(unittest.TestCase):
    def test_slack_link_text_is_escaped(self):
        import notify
        self.assertEqual(notify.slack_text("A <b> & c|d"), "A &lt;b&gt; &amp; c/d")
