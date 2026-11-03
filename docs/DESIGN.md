# Design notes

## Why a ledger of dead ends
PRs record what shipped, not the three approaches that failed first. In AI-assisted coding the model
re-suggests a failed approach because it has no memory of the failure. The ledger is that memory.

## Decisions and trade-offs

| decision | why | cost |
|---|---|---|
| Standard library only | zero-install, nothing to break, easy to audit | no fancy fuzzy matching |
| SQLite, one global file | local-first, queryable, FTS5 search, cross-project recall | single-user for now |
| Fingerprint = parsed type + normalized message | stable across machines, paths and line numbers | numbers are collapsed (see below) |
| Two fingerprints (strict / loose) | "same error" and "same family" are different answers; saying which keeps results honest | two columns to maintain |
| Frames only mixed in for short messages | a bare `NullPointerException` carries no information; long messages already do | pasting only the last line of a short-message error may miss |
| Redact before storing, not after | a secret never touches disk | regex redaction can miss exotic formats |
| Same-project matches rank first, other repos still shown | the same error in another repo is still useful | may show noise on very generic errors |
| Log an attempt only when the approach changed (Phase 2 rule) | typos and missing env vars would flood the ledger | needs a confirmation step |

## Known limitations (tested and documented, not hidden)

* **Numbers are normalized.** `ECONNREFUSED 127.0.0.1:5432` and `:3306` fingerprint the same
  (`test_known_limitation_ports_are_collapsed`). Keeping numbers would make every line number and
  version a new "error".
* **Frameless short errors.** `KeyError: 'id'` as a bare last line will not match the same error
  pasted with its traceback, because short messages use the innermost frame.
* **Curated accuracy is not field accuracy.** `scripts/eval_fingerprints.py` scores the fingerprinter
  against hand-picked samples, so it is a regression guard. The real quality number is the lookup
  hit rate and relevance from using the tool on real projects (see docs/TESTING.md).
* **Root causes are claims, not facts.** Entries carry a `--confidence` so a guess is labelled a guess.
* **A failure is true for a version, not forever.** Versions are stored with each attempt;
  automatic "revalidate after upgrade" arrives in a later phase.
