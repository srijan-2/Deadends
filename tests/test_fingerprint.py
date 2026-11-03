import json
import os
import unittest

from deadends.fingerprint import fingerprint, normalize_message, parse_error
from scripts import eval_fingerprints as ev

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def sample(rel):
    with open(os.path.join(SAMPLES, rel), encoding="utf-8") as fh:
        return fh.read()


class ManifestTests(unittest.TestCase):
    """Every pair of curated samples must behave as the manifest says."""

    def test_all_pairs(self):
        results, failures = ev.evaluate(ev.load())
        self.assertEqual(failures, [], "fingerprint regressions: %s" % failures)
        for kind, (ok, n) in results.items():
            self.assertGreater(n, 0, kind)
            self.assertEqual(ok, n, kind)

    def test_every_sample_is_in_the_manifest(self):
        with open(os.path.join(SAMPLES, "manifest.json"), encoding="utf-8") as fh:
            listed = {f for g in json.load(fh)["groups"] for f in g["files"]}
        on_disk = set()
        for root, _dirs, files in os.walk(SAMPLES):
            for name in files:
                if name.endswith(".txt"):
                    on_disk.add(os.path.relpath(os.path.join(root, name), SAMPLES).replace(os.sep, "/"))
        self.assertEqual(on_disk - listed, set(), "sample files missing from manifest.json")
        self.assertEqual(listed - on_disk, set(), "manifest lists files that do not exist")


class ParsingTests(unittest.TestCase):
    def test_python_uses_last_traceback_and_innermost_frame_first(self):
        p = parse_error(sample("python/connrefused_a.txt"))
        self.assertEqual(p.exc_type, "requests.exceptions.ConnectionError")
        self.assertEqual(p.frames[0], "send")

    def test_java_prefers_root_cause(self):
        p = parse_error(sample("java/spring_relation_orders_a.txt"))
        self.assertEqual(p.exc_type, "org.postgresql.util.PSQLException")
        self.assertTrue(p.frames[0].endswith("receiveErrorResponse"))

    def test_spring_startup_failure(self):
        p = parse_error(sample("java/spring_bean_orders_a.txt"))
        self.assertEqual(p.exc_type, "SpringStartupFailure")
        self.assertIn("OrderRepository", p.message)

    def test_npm_code_is_the_type(self):
        self.assertEqual(parse_error(sample("npm/eresolve_a.txt")).exc_type, "ERESOLVE")
        self.assertEqual(parse_error(sample("npm/eresolve_b.txt")).exc_type, "ERESOLVE")

    def test_maven_compile_error_includes_symbol(self):
        p = parse_error(sample("maven/cannot_find_symbol_foo_a.txt"))
        self.assertEqual(p.exc_type, "MavenCompileError")
        self.assertIn("class Foo", p.message)

    def test_generic_fallback_and_empty(self):
        self.assertEqual(parse_error("something went sideways: failed to frobnicate").kind, "generic")
        self.assertEqual(parse_error("").kind, "empty")
        self.assertEqual(parse_error("   \n\n").kind, "empty")


class NormalizationTests(unittest.TestCase):
    def test_noise_is_stripped(self):
        a = normalize_message("failed at 2024-05-01T10:22:11Z id 123e4567-e89b-12d3-a456-426614174000 addr 0x7f3c1c2b5d90 line 42")
        b = normalize_message("failed at 2025-11-30 08:01:55 id 00000000-0000-0000-0000-000000000000 addr 0x1a2b line 9000")
        self.assertEqual(a, b)

    def test_paths_normalized_but_api_routes_kept(self):
        self.assertEqual(
            normalize_message("cannot open /home/alice/app/config.yml"),
            normalize_message("cannot open C:\\Users\\bob\\app\\config.yml"),
        )
        self.assertNotEqual(normalize_message("GET /api/users failed"), normalize_message("GET /api/orders failed"))

    def test_apostrophes_are_not_quotes(self):
        self.assertEqual(normalize_message("can't find 'x'", loose=True), "can't find <s>")

    def test_ansi_codes_ignored(self):
        plain = fingerprint("Error: connect ECONNREFUSED 127.0.0.1:5432")
        colored = fingerprint("\x1b[31mError: connect ECONNREFUSED 127.0.0.1:5432\x1b[0m")
        self.assertEqual(plain.strict, colored.strict)


class BehaviourTests(unittest.TestCase):
    def test_last_line_alone_matches_full_traceback_when_message_is_informative(self):
        full = fingerprint(sample("python/modulenotfound_requests_a.txt"))
        last = fingerprint("ModuleNotFoundError: No module named 'requests'")
        self.assertEqual(full.strict, last.strict)

    def test_short_messages_use_the_frame_to_avoid_collisions(self):
        a = fingerprint("Traceback (most recent call last):\n  File \"a.py\", line 1, in load\nKeyError: 'id'\n")
        b = fingerprint("Traceback (most recent call last):\n  File \"a.py\", line 1, in save\nKeyError: 'id'\n")
        self.assertNotEqual(a.strict, b.strict)
        self.assertEqual(a.loose, b.loose)

    def test_different_exception_types_never_collide(self):
        self.assertNotEqual(
            fingerprint("ValueError: bad value 'x' for field").loose,
            fingerprint("TypeError: bad value 'x' for field").loose,
        )

    def test_known_limitation_ports_are_collapsed(self):
        # Documented trade-off: numbers are normalized, so postgres (5432) and mysql (3306)
        # connection refusals share a fingerprint. See docs/DESIGN.md.
        self.assertEqual(
            fingerprint("Error: connect ECONNREFUSED 127.0.0.1:5432").strict,
            fingerprint("Error: connect ECONNREFUSED 127.0.0.1:3306").strict,
        )


if __name__ == "__main__":
    unittest.main()
