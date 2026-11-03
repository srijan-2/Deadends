import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from deadends.cli import main, render_markdown

ERR = "ModuleNotFoundError: No module named 'requests'"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "ledger.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, expect=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.db] + list(argv))
        self.assertEqual(code, expect, err.getvalue() or out.getvalue())
        return out.getvalue()

    def test_full_workflow(self):
        self.assertIn("Ledger ready", self.run_cli("init"))
        added = json.loads(self.run_cli("add", "--project", "demo", "-a", "pip install globally", "--problem", "deps",
                                        "--env", "python=3.12", "-t", ERR, "--json"))
        self.assertIsNotNone(added["strict"])
        text = self.run_cli("lookup", "--project", "demo", "-t", ERR)
        self.assertIn("same error", text)
        self.assertIn("pip install globally", text)
        self.run_cli("update", str(added["id"]), "--root-cause", "wrong interpreter", "--fix", "use the venv python")
        data = json.loads(self.run_cli("lookup", "--project", "demo", "-t", ERR, "--json"))
        self.assertEqual(data["level"], "exact")
        self.assertTrue(data["had_fix"])
        stats = json.loads(self.run_cli("stats", "--project", "demo", "--json"))
        self.assertEqual((stats["attempts"], stats["lookups"], stats["lookup_hits"]), (1, 2, 2))
        self.assertIn("venv", self.run_cli("search", "--project", "demo", "venv"))

    def test_adding_the_same_attempt_twice_merges(self):
        first = self.run_cli("add", "--project", "demo", "-a", "same thing", "-t", ERR)
        second = self.run_cli("add", "--project", "demo", "-a", "same thing", "-t", ERR, "--fix", "pip install it")
        self.assertIn("Logged attempt #1", first)
        self.assertIn("Already logged as #1 (now seen 2 times)", second)
        self.assertEqual(json.loads(self.run_cli("stats", "--project", "demo", "--json"))["attempts"], 1)
        self.assertIn("seen 2 times", self.run_cli("export", "--project", "demo"))

    def test_lookup_no_record_does_not_touch_stats(self):
        self.run_cli("add", "--project", "demo", "-a", "x", "-t", ERR)
        self.run_cli("lookup", "--project", "demo", "-t", ERR, "--no-record")
        self.assertEqual(json.loads(self.run_cli("stats", "--project", "demo", "--json"))["lookups"], 0)

    def test_error_from_file(self):
        path = os.path.join(self.tmp.name, "err.txt")
        with open(path, "w") as fh:
            fh.write("Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\n" + ERR + "\n")
        self.run_cli("add", "--project", "demo", "-a", "from file", "-f", path)
        self.assertIn("same error", self.run_cli("lookup", "--project", "demo", "-t", ERR))

    def test_fingerprint_command_needs_no_ledger(self):
        out = self.run_cli("fingerprint", "-t", ERR)
        self.assertIn("ModuleNotFoundError", out)
        self.assertFalse(os.path.exists(self.db))

    def test_unknown_error_says_so(self):
        self.assertIn("No prior record", self.run_cli("lookup", "--project", "demo", "-t", "KeyError: 'zzz'"))

    def test_export_markdown_file(self):
        self.run_cli("add", "--project", "demo", "-a", "monkeypatch client", "--problem", "http", "-t", ERR,
                     "--root-cause", "private API changed", "--confidence", "medium", "--env", "requests=2.31")
        self.run_cli("add", "--project", "demo", "-a", "use httpx instead", "--problem", "http", "--outcome", "worked")
        out = os.path.join(self.tmp.name, "DEADENDS.md")
        self.run_cli("export", "--project", "demo", "-o", out)
        with open(out, encoding="utf-8") as fh:
            md = fh.read()
        for needle in ("# Dead ends - demo", "## http", "monkeypatch client", "private API changed",
                       "requests=2.31", "What worked: **use httpx instead**"):
            self.assertIn(needle, md)

    def test_export_empty_project(self):
        self.assertIn("No failed approaches", render_markdown("demo", []))

    def test_bad_input_is_reported_not_crashed(self):
        with self.assertRaises(SystemExit):
            self.run_cli("lookup", "--project", "demo")
        with self.assertRaises(SystemExit):
            self.run_cli("add", "-a", "x", "--env", "novalue")
        self.run_cli("update", "999", "--fix", "nothing", expect=1)

    def test_secrets_are_redacted_and_reported(self):
        out = self.run_cli("add", "--project", "demo", "-a", "use token", "-t",
                           "auth failed TOKEN=abc123def456ghi")
        self.assertIn("redacted before saving", out)


if __name__ == "__main__":
    unittest.main()


class ProjectDetectionTests(unittest.TestCase):
    def test_git_remote_is_used_and_credentials_are_stripped(self):
        import subprocess
        from deadends.cli import detect_project, project_label

        old = os.environ.pop("DEADENDS_PROJECT", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "init", "-q", tmp], check=True)
                subprocess.run(["git", "-C", tmp, "remote", "add", "origin",
                                "https://octocat:s3cretToken99@github.com/acme/shop.git"], check=True)
                key = detect_project(tmp)
                self.assertNotIn("s3cretToken99", key)
                self.assertNotIn("octocat", key)
                self.assertTrue(key.endswith("github.com/acme/shop"), key)
                self.assertEqual(project_label(key), "shop")

                bare = tempfile.mkdtemp()
                try:
                    subprocess.run(["git", "init", "-q", bare], check=True)
                    self.assertEqual(os.path.realpath(detect_project(bare)), os.path.realpath(bare))
                finally:
                    shutil.rmtree(bare)
        finally:
            if old is not None:
                os.environ["DEADENDS_PROJECT"] = old

    def test_env_override(self):
        from deadends.cli import detect_project

        os.environ["DEADENDS_PROJECT"] = "my-key"
        try:
            self.assertEqual(detect_project(), "my-key")
        finally:
            del os.environ["DEADENDS_PROJECT"]


class PipeTests(unittest.TestCase):
    def test_piping_into_head_does_not_traceback(self):
        import subprocess
        import sys as _sys

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run(
            "%s -m deadends fingerprint -t \"Error: boom failed badly\" | head -1" % _sys.executable,
            shell=True, cwd=root, capture_output=True, text=True,
        )
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("BrokenPipe", proc.stderr)
