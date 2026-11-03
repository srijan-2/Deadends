# Architecture (target, Phases 2-6)

## Data flow
```
Claude Code session
   | hook events (stdin JSON)                      no LLM, no network, fail open
   v
deadends hook <event>  -->  redact -->  events table  -->  infer problems/attempts  -->  ledger (SQLite, WAL)
   |                                                              |
   | (only on a failure whose fingerprint matches history)        |
   v                                                              v
additionalContext (<= 600 chars)                    deadends serve (127.0.0.1, read-only)
back into Claude's context                          /api/*  ->  stats page + route graph (static UI)
```
Two outputs only: a tiny injected hint (rare) and a local dashboard (on demand). Everything else is storage.

## Schema additions (migration to `user_version = 2`)
Existing: `problems`, `attempts` (with `occurrences`), `lookups`, `attempts_fts`. New:

```sql
meta(key TEXT PRIMARY KEY, value TEXT)            -- fingerprint_version, created_with, ...
sessions(
  id TEXT PRIMARY KEY,                            -- Claude Code session_id
  project TEXT NOT NULL, cwd TEXT,
  started_at TEXT NOT NULL, ended_at TEXT,
  prompts INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, recalls INTEGER DEFAULT 0)
events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,                           -- order inside the session
  ts TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('prompt','action','failure','recall','resolved','stop')),
  tool TEXT,                                      -- Bash | Edit | Write | ...
  summary TEXT NOT NULL,                          -- redacted, <= 200 chars (command, file, prompt head)
  exit_code INTEGER,
  fp_strict TEXT, fp_loose TEXT,
  attempt_id INTEGER REFERENCES attempts(id),
  problem_id INTEGER REFERENCES problems(id),
  UNIQUE(session_id, seq))
recalls(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, session_id TEXT, project TEXT,
  attempt_ids TEXT, level TEXT, chars INTEGER, est_tokens INTEGER,
  followed_known_fix INTEGER)                     -- filled later by heuristic, nullable
CREATE INDEX idx_events_session ON events(session_id, seq);
CREATE INDEX idx_events_fp ON events(fp_strict);
```
Rules: no raw tool output is stored (only a redacted <= 200-char summary and, for failures, the fingerprinted
error text capped at 2 KB). `PRAGMA journal_mode=WAL`, `busy_timeout=200`. One transaction per hook event.
Replace the ad-hoc `_migrate()` with `PRAGMA user_version` steps (v1 = Phase 1.1 DB, v2 = this).

## Inferring problems and attempts without an LLM
All heuristics, deterministic, testable with fixtures.
1. **Action** = a `PostToolUse` for `Bash`, `Edit`, `Write`, `MultiEdit`. Summary = normalized command or file path.
2. **Failure** = a Bash action whose exit code is non-zero (field name verified in Phase 2 step 0). Parse/fingerprint the error text, then
   open a *problem* for `(session, loose fingerprint)` if none is open, and an *attempt* whose approach label is
   the failing action plus the edits since the previous failure/prompt (e.g. `edit app/db.py; run pytest -x`).
3. **New attempt vs retry**: after a failure, if the next failing action is the same normalized command with no intervening
   Edit/Write, it is a **retry** (merge, `occurrences += 1`). If edits happened in between, or the command changed, it is a **new attempt**.
4. **Resolution**: the same normalized command (or its prefix, e.g. same test target) later exits 0 -> mark the problem resolved, the
   attempt that preceded success `worked`, earlier ones `failed`. Auto-fill `fix` with the edits/commands between last failure and
   success (summary only), `confidence=low`, `source=hook`.
5. **Root cause is never invented.** It stays empty until a human or the optional skill (Phase 6) writes it.
6. Unresolved problems are closed as `abandoned` at `SessionEnd`; they still count as dead ends, labeled unresolved.
7. Edge cases to cover in tests: parallel/chained commands (`a && b`), commands that exit non-zero on purpose (`grep` no match,
   `diff`), `set -e` scripts, flaky tests (same command fails then passes with no edits -> resolved, `flaky=true`), interrupted commands.

## Route (derived at read time, not stored)
`route.build_session_route(session_id)` and `build_problem_route(problem_id)` read `events` and return
`{nodes:[...], edges:[...], lanes:[...]}` as plain dicts (see `docs/UI_SPEC.md` for the node/edge schema).
Compression: collapse consecutive successful actions into one `steps` node ("5 steps"); always keep prompts, failures, recalls,
resolutions and the action immediately before each failure. A 500-event session must still give < 60 nodes.

## Module layout (additions)
```
deadends/
  hooks/__init__.py       dispatcher: read stdin, route by event, fail-open wrapper, JSON-only stdout
  hooks/events.py         event -> row mapping, failure detection, problem/attempt inference
  hooks/recall.py         match + build the capped additionalContext string
  route.py                route building and compression (pure functions, no I/O besides db reads)
  server.py               ThreadingHTTPServer, read-only JSON API, static file serving
  ui/                     index.html, app.js, style.css (+ vendor/ only if a graph lib is adopted)
  install.py              install / uninstall / doctor (settings.json merge, backups)
  config.py               env + ~/.deadends/config.json (store_prompts, caps, retention_days)
```
CLI additions: `hook <event>`, `install`, `uninstall`, `doctor`, `serve`, `prune`, `stats --days N`, `digest`.

## Cross-cutting
* **Project key**: reuse `detect_project(cwd)` from the hook payload's `cwd`, not the process cwd.
* **Concurrency**: several Claude sessions can write at once; WAL + busy timeout; on lock timeout drop the event and log, never block.
* **Retention**: `events` older than 90 days are pruned (`deadends prune`, also opportunistic at `SessionEnd`). `attempts`/`problems` are kept.
* **Windows/macOS/Linux**: use `sys.executable` in installed hook commands; avoid shell-specific syntax.
* **Versioning**: `meta.fingerprint_version` is compared at startup; mismatch -> `doctor` warns and `rehash` is offered.
