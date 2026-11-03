import unittest

from deadends.db import Ledger

PY_REQUESTS = "ModuleNotFoundError: No module named 'requests'"
PY_NUMPY = "ModuleNotFoundError: No module named 'numpy'"


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.l = Ledger(":memory:")

    def tearDown(self):
        self.l.close()

    def add(self, **kw):
        base = dict(project="proj", approach="try something", error_text=PY_REQUESTS)
        base.update(kw)
        return self.l.add_attempt(**base)

    def test_exact_similar_none(self):
        self.add()
        self.assertEqual(self.l.find_matches(PY_REQUESTS, "proj").level, "exact")
        self.assertEqual(self.l.find_matches(PY_NUMPY, "proj").level, "similar")
        self.assertEqual(self.l.find_matches("KeyError: 'x'", "proj").level, "none")

    def test_same_project_ranks_first(self):
        self.add(project="other", approach="from other repo")
        mine = self.add(project="proj", approach="from this repo")
        res = self.l.find_matches(PY_REQUESTS, "proj")
        self.assertEqual(res.matches[0]["id"], mine.id)
        self.assertEqual(len(res.matches), 2)

    def test_known_fix_surfaces_even_from_sibling_attempt(self):
        self.add(problem="deps", approach="global pip install")
        self.add(problem="deps", approach="use a venv", outcome="worked", error_text=None)
        res = self.l.find_matches(PY_REQUESTS, "proj")
        self.assertTrue(res.had_fix)
        self.assertEqual([r["approach"] for r in res.resolutions], ["use a venv"])

    def test_update_adds_fix_and_is_searchable(self):
        a = self.add(approach="monkeypatch the client")
        self.assertFalse(self.l.find_matches(PY_REQUESTS, "proj", record=False).had_fix)
        self.assertTrue(self.l.update_attempt(a.id, fix="pin urllib3 below 2", confidence="high"))
        self.assertTrue(self.l.find_matches(PY_REQUESTS, "proj", record=False).had_fix)
        self.assertEqual([r["id"] for r in self.l.search("urllib3")], [a.id])

    def test_secrets_never_reach_the_database(self):
        secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        res = self.add(approach="clone with token %s" % secret, error_text="fatal: auth failed for %s" % secret,
                       root_cause="PASSWORD=hunter2hunter2 was wrong")
        self.assertIn("github_token", res.redacted)
        blob = " ".join(str(v) for v in self.l.get_attempt(res.id).values())
        self.assertNotIn(secret, blob)
        self.assertNotIn("hunter2hunter2", blob)

    def test_stats_and_hit_rate(self):
        self.add()
        self.l.find_matches(PY_REQUESTS, "proj")          # exact hit
        self.l.find_matches("KeyError: 'x'", "proj")       # miss
        self.l.find_matches(PY_NUMPY, "proj", record=False)  # not counted
        s = self.l.stats("proj")
        self.assertEqual((s["attempts"], s["lookups"], s["lookup_hits"], s["lookup_exact_hits"]), (1, 2, 1, 1))
        self.assertAlmostEqual(s["hit_rate"], 0.5)

    def test_seen_before_counts_exact_repeats(self):
        self.assertEqual(self.add().seen_before, 0)
        self.assertEqual(self.add().seen_before, 1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.add(outcome="exploded")
        with self.assertRaises(ValueError):
            self.add(approach="  ")
        with self.assertRaises(ValueError):
            self.add(confidence="certain")

    def test_search_falls_back_to_like_without_fts(self):
        a = self.add(approach="rewrite the retry loop")
        self.l.fts = False
        self.assertEqual([r["id"] for r in self.l.search("retry")], [a.id])
        self.assertEqual(self.l.search("   "), [])

    def test_search_survives_fts_special_characters(self):
        self.add(approach="use foo-bar (v2) AND baz")
        self.assertTrue(self.l.search('foo-bar (v2) "AND" baz'))

    def test_attempt_without_error_has_no_fingerprint(self):
        r = self.add(error_text=None)
        self.assertIsNone(r.fp)
        self.assertIsNone(self.l.get_attempt(r.id)["fp_strict"])


if __name__ == "__main__":
    unittest.main()
