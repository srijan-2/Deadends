# deadends

A local ledger of **failed approaches**. When an AI assistant suggests approach A and it errors,
`deadends` records it - with a normalized error fingerprint, the root cause, the fix, and library
versions - so the next time the same error shows up (today, next week, in another repo) you see
what was already tried instead of looping.

Python 3.9+, standard library only, one SQLite file. Nothing leaves your machine.

> Status: **Phase 1** - the ledger, fingerprinting, redaction and CLI. Hooks (auto-capture),
> error-time recall inside Claude Code, the `/deadend` skill and spaced review come next.

## Quick start

```bash
# from the project folder (no install needed)
python -m deadends init

# an approach failed: log it
python -m deadends add -a "Use requests without a venv" --problem "deps" \
    --env python=3.12 -f error.txt          # or:  -t "ModuleNotFoundError: ..."

# new error? have I seen it before?
python -m deadends lookup -f error.txt      # pipe: some_cmd 2>&1 | python -m deadends lookup -f -

# later, record what actually fixed it
python -m deadends update 1 --root-cause "wrong interpreter" --fix "use .venv/bin/python" --confidence medium

python -m deadends search venv              # full-text search
python -m deadends export -o DEADENDS.md    # dead-ends list for this repo (paste into CLAUDE.md)
python -m deadends stats                    # attempts, lookups, hit rate
```

Optional: `pip install .` gives you a plain `deadends` command.

## Commands

| command | what it does |
|---|---|
| `init` | create the ledger, show its path |
| `add` | log an attempt (`--outcome failed\|worked\|partial`, `--problem`, `--root-cause`, `--fix`, `--env k=v`, `--evidence k=v`) |
| `lookup` | find prior attempts for an error: **exact** (same error) or **similar** (same family) |
| `update ID` | add a root cause / fix / outcome later |
| `search` / `list` | find or browse attempts (current project by default, `--all-projects`) |
| `export` | write a markdown dead-ends list for the current project |
| `stats` | counts and lookup hit rate |
| `fingerprint` | show how an error is parsed and normalized (debugging aid) |

Add `--json` to any command for machine-readable output (used by the hooks in Phase 2).

## How matching works

Errors are parsed per ecosystem (Python tracebacks, Node, Java/Spring incl. `Caused by`,
Spring startup failures, npm, Maven, generic), then normalized: paths, line numbers, versions,
ids, timestamps, hashes and IPs are stripped. Two fingerprints are stored:

* **strict** - exception type + normalized message -> "this exact error"
* **loose** - quoted values blanked out -> "same family" (`reading 'map'` ~ `reading 'filter'`)

See [docs/DESIGN.md](docs/DESIGN.md) for the trade-offs, and [docs/TESTING.md](docs/TESTING.md)
for how to test and keep improving it.

## Safety

Everything is passed through a redactor before it is written (cloud keys, GitHub/Slack/Anthropic/
OpenAI tokens, JWTs, bearer headers, URL credentials, private keys, `password=...` assignments).
Credentials embedded in a git remote URL are stripped from the project key. Redaction is a safety
net, not a guarantee - don't paste secrets on purpose.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v
python scripts/eval_fingerprints.py
```
