# deadends

A local ledger of **failed approaches**, captured automatically while you code.

When an AI assistant suggests approach A and it errors, `deadends` records it in the
background - the failing command, a normalized error fingerprint, and (once you add it) the
root cause, the fix, and the library versions involved. The next time the same error shows up
- today, next week, in another repo - you see what was already tried instead of looping on it
again.

Python 3.9+, standard library only, one SQLite file. Nothing leaves your machine.

## Automatic capture, zero commands

Wire up one hook and `deadends` logs every failed shell command on its own - no `deadends add`
needed for the common case:

```bash
$ python3 inventory.py
Traceback (most recent call last):
  ...
KeyError: 'oranges'
```

Nothing was typed by hand, but it's already in the ledger:

```bash
$ python -m deadends lookup -t "KeyError: 'oranges'"
Error: KeyError: 'oranges'
Seen before: similar error (same family, different details) - 1 prior attempt(s)
  #1 [failed] 2026-11-04  (deadends-test-project)
    approach:   ran: python3 inventory.py
    error:      KeyError: 'oranges'
No fix recorded yet. Add one later with `deadends update <id> --fix '...'`.
```

That capture (the `Ran: python3 inventory.py` attempt above) came from a `PostToolUseFailure`
hook in Claude Code, not from a manual `add`. See [Set up automatic capture](#set-up-automatic-capture-claude-code)
below.

> Status: ledger, fingerprinting, redaction, CLI, and automatic capture of failed Bash commands
> via a Claude Code hook are done and tested. Broader session capture (prompts, edits, retries),
> error-time recall injected back into Claude's context, and a stats/route-graph dashboard are
> planned next - see [docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start (manual use, works without any hook)

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

## Set up automatic capture (Claude Code)

Add a `PostToolUseFailure` hook, matched to `Bash`, to your project's
`.claude/settings.local.json`:

```json
{
  "hooks": {
    "PostToolUseFailure": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "cd /absolute/path/to/deadends && /usr/bin/python3 -m deadends hook post-tool-use-failure",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Replace the two absolute paths with your own (`cd $(pwd)` for this repo, and `command -v python3`
for your interpreter). Open a **new** Claude Code session on the target project (hooks only load
at session start) and run `/hooks` to confirm `PostToolUseFailure` shows "1 hook".

What it does: on every failed `Bash` tool call, the hook reads the command and error text Claude
Code reports, skips anything that isn't a real failure (user-interrupted commands, non-Bash
tools), and calls the same `add_attempt()` the CLI uses - redacted, deduplicated by
`(project, approach, exact error)` just like a manual `add`. It never blocks or slows down the
agent: any internal error is logged to `~/.deadends/hook.log` and the hook still exits 0 with
empty output, so a bug in deadends can never break a Claude Code session.

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
| `hook post-tool-use-failure` | hook entrypoint: auto-log a failed Bash command (see above) |
| `hook-probe` | hook entrypoint: record a redacted raw payload for debugging a hook's input shape |

Add `--json` to any command for machine-readable output.

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
net, not a guarantee - don't paste secrets on purpose. See [docs/PRIVACY.md](docs/PRIVACY.md) for
what the hook stores and how to control it.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v
python scripts/eval_fingerprints.py
```
