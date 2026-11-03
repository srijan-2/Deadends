# deadends - project rules for Claude Code

## What this project is (read first)
`deadends` is a **backend-first, automatic ledger of failed approaches** for AI-assisted ("vibe") coding.
While a developer works in Claude Code, hooks capture prompts, tool calls and failures with **zero manual
steps and zero LLM tokens**, turn them into *attempts* and *problems*, remember what fixed them, and
**inject a tiny hint only when the same error shows up again**. A local dashboard shows stats and a
**route graph**: the path a session took (prompt -> attempt -> failure -> retry -> alternative -> fix).

North star, in priority order:
1. **Backend does the work.** The developer never types a command in the normal flow.
2. **Token-frugal.** The tool must cost the user almost no context. See `docs/TOKEN_BUDGET.md`. This beats features.
3. **Never harm the session.** Hooks fail open, are fast, and never block or crash Claude Code.
4. **Observable.** Stats page + route graph make the process visible (`docs/UI_SPEC.md`).
5. **Private.** Local only, redacted before storage, no network calls.

## Current state
* Phase 1 + 1.1 done: SQLite ledger, fingerprinting, redaction, CLI, merge-on-repeat, 53 tests, eval at 100%.
* Next: Phase 2 (hooks). Plan and acceptance criteria: `docs/ROADMAP.md`. Tick its checkboxes as you finish items.

## Read these before touching related code
| doc | when |
|---|---|
| `docs/ARCHITECTURE.md` | any schema, module or data-flow change |
| `docs/HOOKS_SPEC.md` | anything under hooks, install, doctor |
| `docs/TOKEN_BUDGET.md` | anything that prints, injects or returns text |
| `docs/UI_SPEC.md` | server, API, dashboard, route graph |
| `docs/PRIVACY.md` | anything that stores or displays captured text |
| `docs/DESIGN.md` | fingerprinting and matching trade-offs |
| `docs/TESTING.md` | how tests and samples are organized |

## Code map
| path | responsibility |
|---|---|
| `deadends/redact.py` | secret redaction. Everything persisted passes through it. |
| `deadends/fingerprint.py` | error parsing, normalization, strict/loose fingerprints |
| `deadends/db.py` | SQLite ledger, migrations, queries (all SQL lives here) |
| `deadends/cli.py` | argparse CLI, human + `--json` output |
| `scripts/eval_fingerprints.py`, `scripts/add_sample.py` | fingerprint regression eval and sample helper |
| `tests/` | unittest suite; `tests/samples/` real error samples + `manifest.json` |

Planned (see ARCHITECTURE): `deadends/hooks/` (event handlers), `deadends/route.py` (route building),
`deadends/server.py` + `deadends/ui/` (dashboard), `deadends/install.py` (install / uninstall / doctor).

## Commands
```bash
python3 -m unittest discover -s tests -t . -q 2>&1 | tail -15   # tests (quiet)
python3 scripts/eval_fingerprints.py | tail -6                   # must stay 100%
python3 -m deadends <command>                                    # run the CLI
DEADENDS_DB=/tmp/x.db DEADENDS_PROJECT=scratch python3 -m deadends ...   # isolated experiments
```
Never point experiments at the real ledger (`~/.deadends/ledger.db`). Use `DEADENDS_DB`.

## Non-negotiable rules
**Code**
* Python 3.9+ and **standard library only**. No new dependencies. (Vendored static JS for the UI is the only exception, see UI_SPEC.)
* `from __future__ import annotations`, type hints on public functions, small functions, no global mutable state.
* SQL only in `db.py`, always parameterized (never format user data into SQL).
* Library code never `print`s; only `cli.py` and hook entrypoints write to stdout/stderr.
* Migrations are additive and idempotent, tracked with `PRAGMA user_version`. Never drop or rewrite user data.
  Test every migration against a database created by the previous release.

**Safety / privacy**
* Everything entering the database goes through `redact()` first: prompts, commands, tool output, errors, free text.
* Prompt storage is configurable (`DEADENDS_STORE_PROMPTS=off|truncated|full`, default `truncated` = 300 chars, redacted).
* The dashboard server binds to `127.0.0.1` only, is read-only in v1, and validates the `Host` header.
* No network calls from the package, ever. No telemetry.

**Hooks (see HOOKS_SPEC)**
* **Fail open:** wrap every hook in try/except, always exit 0, log errors to `~/.deadends/hook.log`, never raise to Claude Code.
* Never exit with code 2 or return `decision: block`. This tool must not block or redirect the agent.
* Stdout from a hook is either empty or exactly one valid JSON object. Nothing else, ever.
* **No LLM calls and no network in hooks.** Latency budget: p95 under 100 ms. Lazy-import, short SQLite busy timeout.
* Never read whole transcripts. If the transcript is needed at all, read the tail only.

**Tokens (see TOKEN_BUDGET)**
* Inject context only on a real match, once per fingerprint per session, within the hard caps in TOKEN_BUDGET.
* Default CLI output is compact. Long output is opt-in (`--full`).
* Anything new that can reach Claude's context needs a budget test.

**Fingerprinting**
* Changing normalization changes stored fingerprints. If you change it: update samples + eval, bump
  `FINGERPRINT_VERSION`, and ship a `rehash` migration. Never ship a silent change.
* Do not delete or rewrite samples in `tests/samples/` to make tests pass. Fix the code, or split the group in `manifest.json`.

## Hooks: verified facts vs. things to verify
Verified in the Claude Code hooks docs: hooks are configured in `~/.claude/settings.json`, `.claude/settings.json`
or `.claude/settings.local.json`; they get JSON on stdin (`session_id`, `transcript_path`, `cwd`, `hook_event_name`,
`tool_name`, `tool_input`, `tool_response`, `tool_use_id`); `PostToolUse`, `UserPromptSubmit` and `SessionStart` can
return `hookSpecificOutput.additionalContext`; hooks run synchronously unless made async; `matcher` filters by tool name only;
settings load at session start (restart after changing hooks); the field is `tool_response`, not `tool_result`.
`additionalContext` on PostToolUse needs a recent Claude Code (one source says v2.1.9+), so `doctor` must check the version.

**Verify empirically, do not assume** (Phase 2 step 0): the exact Bash `tool_response` shape (exit-code field name, stdout/stderr vs
combined output); whether a non-zero Bash exit fires `PostToolUse` or a separate failure event; the `UserPromptSubmit` prompt field name;
the current list of event names. Fetch the current docs AND record real payloads before writing handlers.

## How to work (token-friendly workflow)
1. Read only what the task needs: the phase section in ROADMAP + the one spec doc it names. Use grep/targeted reads, not whole-repo dumps.
2. For anything non-trivial, **propose a plan in <= 10 lines and wait for approval** before writing code.
3. Build the **smallest vertical slice** first, with its test, then widen.
4. Run tests quietly (`-q | tail`). Show me only failures and the final summary.
5. Never paste whole files or large outputs back to me; reference `path:line`.
6. When a phase is done: tick `docs/ROADMAP.md`, update `README.md`/docs if behavior changed, then stop and summarize in <= 8 lines.
7. Suggest `/clear` between phases to keep context small.

## Definition of done (every task)
- [ ] Tests added/updated and passing (`unittest` + eval at 100%)
- [ ] No new dependency, no unredacted persistence, no stdout noise from hooks
- [ ] Token-budget implications checked (if anything reaches Claude's context)
- [ ] Migration tested against a previous-release DB (if schema changed)
- [ ] ROADMAP checkbox ticked, docs touched if behavior changed
- [ ] Commit message: `<area>: <what and why>` (e.g. `hooks: detect failing bash via exit code`)

## Glossary
* **event** - one thing that happened in a session (prompt, tool call, failure, stop). Stored in `events`.
* **attempt** - one distinct approach tried for a problem, outcome failed/partial/worked. Identical retries merge (`occurrences`).
* **problem** - a failure being worked on; groups attempts until resolved.
* **family** - errors sharing a loose fingerprint ("same kind of error").
* **route** - the ordered graph of a session or problem: prompts, attempts, errors, recalls, resolution.
* **recall** - a hint injected into Claude's context because a fingerprint matched history.

## Do not
* Add features that need an LLM in the hot path, a daemon that must keep running, or a cloud service.
* Auto-edit the user's source files or their `CLAUDE.md`. Hooks observe and (rarely) inject context.
* Store secrets, full tool outputs, or full prompts by default.
* Claim metrics the data cannot support. "Tokens saved" is an **estimate** and must be labeled as one.
* Expand scope beyond the current phase without asking.
