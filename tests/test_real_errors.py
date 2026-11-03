"""Fingerprint genuine errors produced by real interpreters, not hand-written samples.

The same failing program is run from two different directories (different absolute
paths, different file names, different line numbers) and must fingerprint identically.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from deadends.fingerprint import fingerprint

PROGRAMS = {
    "keyerror": 'def get_user(d):\n    return d["user_id"]\n\nget_user({})\n',
    "import": "import definitely_not_a_real_module_xyz\n",
    "zerodiv": "def ratio(a, b):\n    return a / b\n\nratio(1, 0)\n",
    "attr": "class A:\n    pass\n\nA().missing_attribute\n",
}


def run_python(code, name, padding_lines):
    with tempfile.TemporaryDirectory() as tmp:
        sub = os.path.join(tmp, "dir_%s" % name)
        os.makedirs(sub)
        path = os.path.join(sub, "prog_%s.py" % name)
        with open(path, "w") as fh:
            fh.write("# pad\n" * padding_lines + code)
        proc = subprocess.run([sys.executable, path], capture_output=True, text=True)
        return proc.stderr


class RealPythonTracebacks(unittest.TestCase):
    def test_same_program_different_location_matches(self):
        for label, code in PROGRAMS.items():
            a = run_python(code, "one", 0)
            b = run_python(code, "two_longer_name", 17)
            self.assertIn("Traceback", a, label)
            fa, fb = fingerprint(a), fingerprint(b)
            self.assertEqual(fa.strict, fb.strict, "%s: %r vs %r" % (label, fa.norm_strict, fb.norm_strict))
            self.assertEqual(fa.loose, fb.loose, label)

    def test_different_programs_do_not_collide(self):
        prints = {label: fingerprint(run_python(code, "x", 0)) for label, code in PROGRAMS.items()}
        self.assertEqual(len({p.strict for p in prints.values()}), len(PROGRAMS))
        self.assertEqual(len({p.loose for p in prints.values()}), len(PROGRAMS))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RealNodeErrors(unittest.TestCase):
    def run_node(self, code, name, padding):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "n_%s" % name)
            os.makedirs(sub)
            path = os.path.join(sub, "prog_%s.js" % name)
            with open(path, "w") as fh:
                fh.write("// pad\n" * padding + code)
            return subprocess.run(["node", path], capture_output=True, text=True).stderr

    def test_node_same_error_different_location_matches(self):
        code = "function renderList(items) { return items.map(x => x); }\nrenderList(undefined);\n"
        a, b = self.run_node(code, "a", 0), self.run_node(code, "bbbb", 9)
        self.assertEqual(fingerprint(a).strict, fingerprint(b).strict)
        self.assertEqual(fingerprint(a).parsed.exc_type, "TypeError")


if __name__ == "__main__":
    unittest.main()
