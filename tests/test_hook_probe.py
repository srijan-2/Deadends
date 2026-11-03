import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from deadends.cli import main
from deadends.hooks.probe import probe_dir, run_hook_probe


class HookProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probe = os.path.join(self.tmp.name, "probe")
        self.env = mock.patch.dict(os.environ, {"DEADENDS_PROBE_DIR": self.probe})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_cli(self, *argv, stdin="", expect=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("sys.stdin", io.StringIO(stdin)):
            code = main(list(argv))
        self.assertEqual(code, expect, err.getvalue() or out.getvalue())
        self.assertEqual(out.getvalue(), "", "hook-probe must never print to stdout")
        return out.getvalue()

    def _files(self):
        return sorted(os.listdir(self.probe)) if os.path.isdir(self.probe) else []

    def test_writes_redacted_payload(self):
        payload = '{"session_id": "abc", "aws_key": "AKIAABCDEFGHIJKLMNOP"}'
        self.run_cli("hook-probe", "PostToolUse", stdin=payload)
        files = self._files()
        self.assertEqual(files, ["PostToolUse-1.json"])
        with open(os.path.join(self.probe, files[0]), encoding="utf-8") as fh:
            written = fh.read()
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", written)
        self.assertIn("REDACTED", written)
        self.assertIn('"session_id": "abc"', written)

    def test_malformed_json_does_not_crash(self):
        self.run_cli("hook-probe", "PreToolUse", stdin="not json at all {{{")
        self.assertEqual(self._files(), ["PreToolUse-1.json"])

    def test_empty_stdin_does_not_crash(self):
        self.run_cli("hook-probe", "SessionStart", stdin="")
        self.assertEqual(self._files(), ["SessionStart-1.json"])

    def test_numbering_does_not_collide(self):
        self.run_cli("hook-probe", "Stop", stdin="{}")
        self.run_cli("hook-probe", "Stop", stdin="{}")
        self.assertEqual(self._files(), ["Stop-1.json", "Stop-2.json"])

    def test_unwritable_probe_dir_fails_open(self):
        # point the probe dir at a path that can't be created (a file, not a directory)
        blocker = os.path.join(self.tmp.name, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        with mock.patch.dict(os.environ, {"DEADENDS_PROBE_DIR": os.path.join(blocker, "probe")}):
            self.run_cli("hook-probe", "PostToolUse", stdin="{}")

    def test_unsafe_event_name_is_sanitized(self):
        self.run_cli("hook-probe", "../../etc/passwd", stdin="{}")
        files = self._files()
        self.assertEqual(len(files), 1)
        self.assertTrue(all(c.isalnum() or c in "-_." for c in files[0]))

    def test_run_hook_probe_direct(self):
        run_hook_probe("Direct", '{"a": 1}')
        self.assertIn("Direct-1.json", self._files())
        self.assertEqual(probe_dir(), self.probe)


if __name__ == "__main__":
    unittest.main()
