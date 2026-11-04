# Hooks spec

Goal: capture everything in the background, cost ~zero tokens, and never get in the way.
**Rule zero: facts about Claude Code hooks must come from the current docs and from recorded real payloads, not from this file.**
This file records what was verified at design time and what must be re-verified.

## Events we use
| event | what we do | injects context? |
|---|---|---|
| `SessionStart` | create/resume session row; optionally inject a tiny project digest | optional, <= 800 chars, default on, `DEADENDS_SESSION_DIGEST=off` to disable |
| `UserPromptSubmit` | record the prompt (redacted, truncated per `STORE_PROMPTS`) as a `prompt` event | no |
| `PostToolUse` (matcher `Bash`, `Edit`, `Write`, `MultiEdit`) | record an `action`; infer problem/attempt, look up history | **only on a match**, <= 600 chars |
| `PostToolUseFailure` (matcher `Bash`) | log the failed command as a `failed` attempt (`deadends hook post-tool-use-failure`) | no |
| `Stop` | check for resolution of open problems; mark `stop` | no |
| `SessionEnd` | close session, abandon open problems, opportunistic prune | no |

Optional later: `PreCompact` (snapshot open problems so they survive compaction), a dedicated failure event if one exists in the current docs.

## Step 0: probe real payloads before writing handlers
Ship `deadends hook-probe <event>`: writes the raw stdin JSON (after `redact()`) to `~/.deadends/probe/<event>-<n>.json` and prints nothing.
Install it for one real session, run a few commands (one succeeding, one failing, one with chained `&&`, an Edit, a prompt), then copy 1-2 payloads
per event into `tests/fixtures/hooks/` (redacted, no real paths or names). Answer and write down in this file:
- [ ] Bash `tool_response`: field holding the exit code? stdout and stderr separate or merged? any `interrupted` flag?
- [x] Does a failing Bash (non-zero exit) fire `PostToolUse` at all, or only a separate failure event? **Confirmed: a failing Bash fires a separate `PostToolUseFailure` event** (not `PostToolUse`), with `tool_name`, `tool_input` (`command`, `description`), `error` (starts `"Exit code N\n"` + traceback/output), `is_interrupt`, `duration_ms`, plus the common fields. See `tests/fixtures/hooks/post_tool_use_failure_modulenotfound.json`.
- [ ] `UserPromptSubmit`: name of the prompt field.
- [ ] `Stop` / `SessionEnd` / `SessionStart` fields (`source`, `reason`).
- [ ] Payload size for large outputs (is `tool_response` truncated by Claude Code?).
- [ ] Minimum Claude Code version for `additionalContext` on PostToolUse; how to read the version in `doctor`.
All later tests load these fixtures. No handler is written against guessed field names.

## Input (verified in docs, shapes to re-check)
JSON on stdin with at least `session_id`, `transcript_path`, `cwd`, `hook_event_name`; tool events add `tool_name`, `tool_input`, `tool_response`, `tool_use_id`.
Use `.get()` everywhere; an unknown or missing field means "skip this event", not "crash".

## Output contract
* Default: print nothing, exit 0.
* Injection: print exactly one JSON object, exit 0:
```json
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "<= 600 chars"}}
```
(`hookEventName` must match the event being answered: `PostToolUse`, `UserPromptSubmit` or `SessionStart`.)
* Never: exit 2, `decision: block`, `continue: false`, `stopReason`, or any non-JSON stdout.
* Errors: caught at the top level, appended to `~/.deadends/hook.log` (rotate at 256 KB), exit 0, empty stdout.

## Performance
* p95 under 100 ms per event, measured by a test on a warm DB with 10k attempts.
* Lazy imports (do not import `argparse`/`cli` in the hook path; the hook entry should import only `db`, `fingerprint`, `redact`, `config`).
* Fingerprint only on failures. Only look up history on failures. Recording an action is a single INSERT.
* Hooks are synchronous unless marked async. Recording-only events may be installed `async` if the docs confirm it; any event that can inject must stay synchronous.

## Install / uninstall / doctor
`deadends install [--scope user|project]`
* Reads the target settings file (`~/.claude/settings.json` or `.claude/settings.json`), **backs it up** to `settings.json.deadends.bak`, merges entries, never removes or reorders the user's other hooks.
* Idempotent: recognized by a marker in the command string (e.g. `deadends hook`); re-running updates in place.
* Hook command uses the absolute interpreter: `"<sys.executable> -m deadends hook post-tool-use"` so it works without PATH setup. Verify the exact JSON structure (event -> list of `{matcher, hooks:[{type:"command", command, timeout}]}`) against the current docs and a real settings file before coding it.
* Prints the diff it will apply and asks for confirmation unless `--yes`. Reminds the user to **restart Claude Code** (settings load at session start).

`deadends uninstall` removes only our entries. `deadends doctor` checks, one line each, with a clear fix hint:
Python version, DB path writable, schema version, fingerprint version, settings entries present and pointing at an existing interpreter,
Claude Code version supports `additionalContext`, last hook error from `hook.log`, last event time ("no events in 24h: hooks may not be running"), and a **live self-test** that pipes a fixture into each handler and checks stdout is empty-or-valid-JSON.

## Failure detection (Bash)
A failure is a Bash action with a non-zero exit code **and** a recognizable error text, with these exclusions (tested):
`grep`/`rg` exit 1 with no output, `diff` exit 1, `test`/`[` exit 1, commands the user interrupted, and exit 130/143.
Only the first 2 KB of stderr/stdout is parsed. Chained commands (`a && b`) are one action; the fingerprint comes from the output, not the command.

## Recall injection (what Claude sees)
Trigger: a failure whose **strict** fingerprint matches history (exact), or loose match (similar) **with a recorded fix**; otherwise silent.
Caps, dedupe and format are in `docs/TOKEN_BUDGET.md`. Template:
```
[deadends] Seen 2x in this repo: ModuleNotFoundError: No module named 'requests'.
Failed before: global pip install. Worked: activate .venv, then pip install requests. (python=3.12)
```
Wording rule: say "failed before in this setup", never "this approach is wrong".
The hook records the recall in `recalls` and as a `recall` event so the route graph can show it.

## Testing hooks without Claude Code
Same pattern as the docs: pipe a fixture into the entrypoint and inspect stdout/exit code.
```bash
cat tests/fixtures/hooks/post_tool_use_bash_fail.json | DEADENDS_DB=/tmp/x.db python3 -m deadends hook post-tool-use; echo "exit=$?"
```
Required tests: every fixture produces empty-or-valid-JSON stdout and exit 0; malformed JSON, empty stdin, unknown event and a locked DB all
fail open; injected `additionalContext` never exceeds the cap; a 3-step scripted session (prompt, failing Bash, edit, passing Bash) produces the expected
events, one problem, two attempts, and a `resolved` event.

## Manual end-to-end check (once per release)
1. `deadends install --scope user`, restart Claude Code.
2. In a scratch repo, make something fail, then fix it. Run `deadends serve` and confirm the session and route appear.
3. Cause the same error again in a new session: confirm exactly one `[deadends]` hint appears, and `deadends doctor` is all green.
