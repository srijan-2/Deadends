#!/usr/bin/env python3
"""Turn a real error you hit into a permanent regression sample.

    python scripts/add_sample.py err.txt --lang python --group py-keyerror-user_id
    python scripts/add_sample.py err2.txt --lang node --group node-reading-map --family node-reading-undefined

* The text is passed through the redactor before it is saved.
* If --group already exists the file joins it (same error, new environment);
  otherwise a new group is created (--family defaults to the group id).
* The evaluation runs straight away, so you immediately see whether the new sample
  broke anything or exposed a fingerprinting weakness.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from deadends.redact import redact  # noqa: E402

SAMPLES = os.path.join(ROOT, "tests", "samples")
MANIFEST = os.path.join(SAMPLES, "manifest.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="file containing the raw error output ('-' for stdin)")
    ap.add_argument("--lang", required=True, help="folder under tests/samples (python, node, java, npm, maven, generic, ...)")
    ap.add_argument("--group", required=True, help="group id: files that are the SAME error")
    ap.add_argument("--family", help="family id: groups that are the same kind of error (default: group id)")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_\-]+", args.group) or not re.fullmatch(r"[A-Za-z0-9_\-]+", args.lang):
        ap.error("--lang and --group may only contain letters, digits, '_' and '-'")

    raw = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8", errors="replace").read()
    text, kinds = redact(raw)
    if not text.strip():
        ap.error("the error text is empty")

    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    group = next((g for g in manifest["groups"] if g["id"] == args.group), None)
    if group is None:
        group = {"id": args.group, "family": args.family or args.group, "files": []}
        manifest["groups"].append(group)
    elif args.family and args.family != group["family"]:
        ap.error("group %r already has family %r" % (args.group, group["family"]))

    folder = os.path.join(SAMPLES, args.lang)
    os.makedirs(folder, exist_ok=True)
    n = len(group["files"]) + 1
    while True:
        rel = "%s/%s_%d.txt" % (args.lang, args.group.replace("-", "_"), n)
        if not os.path.exists(os.path.join(SAMPLES, rel)):
            break
        n += 1
    with open(os.path.join(SAMPLES, rel), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    group["files"].append(rel)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print("Saved %s to group %r (family %r)%s" % (rel, group["id"], group["family"],
                                                 "; redacted: " + ", ".join(kinds) if kinds else ""))
    print("Running evaluation...\n")
    return subprocess.call([sys.executable, os.path.join(ROOT, "scripts", "eval_fingerprints.py"), "--verbose"])


if __name__ == "__main__":
    raise SystemExit(main())
