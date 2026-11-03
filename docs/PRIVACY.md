# Privacy and data handling

`deadends` records what happens in your coding sessions. That is sensitive, so the defaults are conservative and everything stays on your machine.

## What is stored (and where)
All data lives in one SQLite file: `~/.deadends/ledger.db` (override with `DEADENDS_DB`). Nothing is sent anywhere; the package makes no network calls.

| data | stored | limits |
|---|---|---|
| Prompts | redacted head only by default | `DEADENDS_STORE_PROMPTS=off` (nothing) / `truncated` (default, 300 chars) / `full` (redacted, opt-in) |
| Tool actions | redacted one-line summary (command or file path) | <= 200 chars; no file contents, no diffs |
| Failures | error text used for fingerprinting | <= 2 KB, redacted; no full tool output |
| Attempts / problems | approach label, outcome, optional root cause and fix, versions | redacted |
| Recalls | which hint was shown, size in chars | no hint text beyond what is derivable from attempts |

## Redaction
Every string passes `redact()` before it is written: cloud keys, GitHub/Slack/Anthropic/OpenAI tokens, JWTs, bearer headers, URL credentials, private keys, `password=...` style assignments.
Credentials inside a git remote URL are stripped from the project key. Redaction is a safety net, not a guarantee: internal hostnames, table names, customer names and
company package names are **not** detected. Use `STORE_PROMPTS=off` for client or confidential work.

## Controls
* `deadends wipe --project <key>` / `deadends wipe --all` (confirmation required) - Phase 6
* `deadends prune --days N` - events older than N days (default 90); attempts are kept
* `deadends uninstall` - removes the hooks; the ledger stays until you delete it
* Per-repo opt-out: an empty file `.deadends-ignore` in the repo root makes hooks record nothing for that project (implement in Phase 2)

## Dashboard
Binds to `127.0.0.1` only, read-only, no cookies, no external requests, strict CSP. Do not expose it through a tunnel or proxy.

## Sharing
Do not commit `ledger.db`. Do not publish screenshots or `DEADENDS.md` from client work without reading them first. Samples added to `tests/samples/` must be reviewed by hand.

## For client work (freelance)
Treat the ledger as client data: keep prompt storage off or truncated, keep it out of repos, and delete it when the engagement ends if your contract requires it.
