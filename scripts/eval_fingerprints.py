#!/usr/bin/env python3
"""Score the fingerprinter against tests/samples/manifest.json.

Every pair of sample files is checked against what the manifest says it should do:

  same group                      -> strict AND loose fingerprints must match
  different group, same family    -> strict must differ, loose must match
  different group, other family   -> strict AND loose must differ

Prints precision/recall-style numbers and every failing pair. Exit code 1 on any failure.
Usage: python scripts/eval_fingerprints.py [--verbose]
"""
from __future__ import annotations

import itertools
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deadends.fingerprint import fingerprint  # noqa: E402
from deadends.redact import redact  # noqa: E402

SAMPLES = os.path.join(ROOT, "tests", "samples")


def load():
    with open(os.path.join(SAMPLES, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    items = []
    for group in manifest["groups"]:
        for rel in group["files"]:
            with open(os.path.join(SAMPLES, rel), encoding="utf-8") as fh:
                text, _ = redact(fh.read())
            items.append({"file": rel, "group": group["id"], "family": group["family"], "fp": fingerprint(text)})
    return items


def evaluate(items):
    results = {"same_group": [0, 0], "same_family": [0, 0], "different": [0, 0]}
    failures = []
    for a, b in itertools.combinations(items, 2):
        if a["group"] == b["group"]:
            kind, ok = "same_group", a["fp"].strict == b["fp"].strict and a["fp"].loose == b["fp"].loose
        elif a["family"] == b["family"]:
            kind, ok = "same_family", a["fp"].strict != b["fp"].strict and a["fp"].loose == b["fp"].loose
        else:
            kind, ok = "different", a["fp"].strict != b["fp"].strict and a["fp"].loose != b["fp"].loose
        results[kind][1] += 1
        if ok:
            results[kind][0] += 1
        else:
            failures.append((kind, a["file"], b["file"]))
    return results, failures


def main() -> int:
    items = load()
    results, failures = evaluate(items)
    total_ok = sum(r[0] for r in results.values())
    total = sum(r[1] for r in results.values())
    print("samples: %d   groups: %d   pairs checked: %d" % (len(items), len({i["group"] for i in items}), total))
    labels = {
        "same_group": "same error, different environment -> should match",
        "same_family": "same family, different details    -> should be 'similar'",
        "different": "unrelated errors                    -> should not collide",
    }
    for key, (ok, n) in results.items():
        print("  %-52s %d/%d" % (labels[key], ok, n))
    print("overall: %d/%d (%.1f%%)" % (total_ok, total, 100.0 * total_ok / total if total else 0))
    for kind, fa, fb in failures:
        print("FAIL [%s] %s  <->  %s" % (kind, fa, fb))
        if "--verbose" in sys.argv:
            for f in (fa, fb):
                it = next(i for i in items if i["file"] == f)
                print("    %s: type=%s strict=%r" % (f, it["fp"].parsed.exc_type, it["fp"].norm_strict))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
