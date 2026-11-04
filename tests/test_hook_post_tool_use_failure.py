import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from deadends.cli import main
from deadends.db import Ledger

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "hooks", "post_tool_use_failure_modulenotfound.json"
)


class HookPostToolUseFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "ledger.db")
        with open(FIXTURE, encoding="utf-8") as fh:
            self.payload = fh.read()

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, stdin, expect=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("sys.stdin", io.StringIO(stdin)):
            code = main(["--db", self.db, "hook", "post-tool-use-failure"])
        self.assertEqual(code, expect, err.getvalue() or out.getvalue())
        self.assertEqual(out.getvalue(), "", "hook must never print to stdout")
        return out.getvalue()

    def attempts(self):
        ledger = Ledger(self.db)
        try:
            return ledger.list_attempts(project="/home/user/project")
        finally:
            ledger.close()

    def test_logs_a_failed_attempt(self):
        self.run_hook(self.payload)
        rows = self.attempts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "failed")
        self.assertEqual(rows[0]["source"], "hook")
        self.assertIn("python3 -c", rows[0]["approach"])
        self.assertIn("ModuleNotFoundError", rows[0]["error_redacted"])

    def test_is_interrupt_is_skipped(self):
        data = json.loads(self.payload)
        data["is_interrupt"] = True
        self.run_hook(json.dumps(data))
        self.assertEqual(self.attempts(), [])

    def test_non_bash_tool_is_skipped(self):
        data = json.loads(self.payload)
        data["tool_name"] = "Edit"
        self.run_hook(json.dumps(data))
        self.assertEqual(self.attempts(), [])

    def test_malformed_json_fails_open(self):
        self.run_hook("not json at all {{{")
        self.assertEqual(self.attempts(), [])

    def test_duplicate_failures_merge(self):
        self.run_hook(self.payload)
        self.run_hook(self.payload)
        rows = self.attempts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["occurrences"], 2)


if __name__ == "__main__":
    unittest.main()
