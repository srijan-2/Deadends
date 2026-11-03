---
description: Run the unit tests and the fingerprint eval quietly and report only what matters
---
Run these two commands and report tersely:

1. `python3 -m unittest discover -s tests -t . -q 2>&1 | tail -15`
2. `python3 scripts/eval_fingerprints.py | tail -6`

Reply in at most 5 lines: test count and OK/FAILED, eval overall percentage, and for any failure the test name plus a one-line cause.
If something fails, do not edit anything yet. Ask whether I want you to fix it. $ARGUMENTS
