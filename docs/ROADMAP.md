# Roadmap

Tick boxes as work lands. Each phase ends with: tests green, eval 100%, docs updated, a commit, and a short demo you can run.
Do phases in order; do not start a phase before the previous one's acceptance criteria pass.

## Done
- [x] Phase 1: ledger, fingerprinting (strict/loose), redaction, CLI, samples + eval
- [x] Phase 1.1: merge repeated attempts (`occurrences`), migration for the first DB

## Phase 2: automatic capture (hooks)  `docs/HOOKS_SPEC.md`, `docs/ARCHITECTURE.md`
- [ ] 2.0 Re-read the current hooks docs; add `hook-probe`; record real payloads; answer the checklist in HOOKS_SPEC; save redacted fixtures to `tests/fixtures/hooks/`
- [ ] 2.1 Migration to `user_version = 2`: `meta`, `sessions`, `events`, `recalls`, indexes, WAL, busy timeout; test against a v1 DB
- [ ] 2.2 `config.py`: env + `~/.deadends/config.json` (store_prompts, caps, retention, loop cost)
- [ ] 2.3 `deadends hook <event>` dispatcher: fail open, JSON-only stdout, `hook.log`, lazy imports
- [ ] 2.4 Recording: sessions, prompts (per privacy mode), actions
- [ ] 2.5 Failure detection (exclusions per spec) and problem/attempt inference (retry vs new attempt, resolution)
- [ ] 2.6 `install` / `uninstall` / `doctor` (backup, merge, idempotent, live self-test)

**Acceptance:** a scripted 3-step session replayed from fixtures yields the expected events, 1 problem, 2 attempts, `resolved`; hook p95 < 100 ms on a 10k-attempt DB;
every fuzz input (garbage JSON, empty stdin, locked DB) exits 0 with empty stdout; install -> uninstall leaves the user's settings byte-identical apart from our entries;
one real Claude Code session verified manually with `doctor` green.

## Phase 3: recall + token budget  `docs/TOKEN_BUDGET.md`
- [ ] 3.1 `hooks/recall.py`: match, rank, build capped string, snapshot-tested wording
- [ ] 3.2 Dedupe per fingerprint per session, 3-per-session cap, `recalls` rows + `recall` events
- [ ] 3.3 `SessionStart` digest (<= 800 chars) behind `DEADENDS_SESSION_DIGEST`
- [ ] 3.4 Heuristic `followed_known_fix` (next action repeats the listed failed approach or not)
- [ ] 3.5 Budget test suite (worst-case data) and a `deadends budget` command that prints current overhead estimates

**Acceptance:** all budget tests pass; a known failing error in a new session produces exactly one hint <= 600 chars; no output when nothing matches;
the manual end-to-end check in HOOKS_SPEC passes.

## Phase 4: dashboard backend  `docs/UI_SPEC.md`
- [ ] 4.1 `route.py`: session and problem routes, compression (500 events -> < 60 nodes)
- [ ] 4.2 Metrics queries in `db.py` (overview, timeline, families, problems, sessions)
- [ ] 4.3 `server.py` + all API endpoints, Host check, read-only DB, security headers
- [ ] 4.4 `stats --days`, `serve` CLI wiring, package data for `ui/`

**Acceptance:** every endpoint has a test; metrics match hand-computed numbers on a fixture ledger; wheel contains `ui/` files.

## Phase 5: dashboard UI
- [ ] 5.1 App shell, theme (light/dark), routing, empty states
- [ ] 5.2 Overview: tiles, activity chart, top families, open problems (estimates labeled)
- [ ] 5.3 Sessions + Problems tables
- [ ] 5.4 Route graph: layout, node/edge types, pan/zoom/fit, side panel
- [ ] 5.5 Replay, filters, outline view, keyboard + aria
- [ ] 5.6 Responsive pass (390px), reduced motion, no external requests

**Acceptance:** works offline; keyboard-only usable; 500-event session renders under 1 s; screenshots of each screen saved to `docs/img/` for the README.

## Phase 6: polish and packaging
- [ ] 6.1 `FINGERPRINT_VERSION` + `rehash` migration + `doctor` check
- [ ] 6.2 `prune` and retention; `wipe` command with confirmation
- [ ] 6.3 `digest` / improved `export` (<= 40 lines) for the user's own CLAUDE.md
- [ ] 6.4 Environment awareness: hash of lockfiles/requirements, flag old dead ends as "revalidate" after a version change
- [ ] 6.5 Optional skill `/deadend-note` to add a root cause to the latest problem (tiny, on demand)
- [ ] 6.6 Claude Code plugin packaging (verify the current plugin format in the docs first)
- [ ] 6.7 Optional: global "error families map" graph (vendored, pinned lib)

## Phase 7 (stretch, only if time allows)
- [ ] Optional team mode: thin FastAPI + Postgres sync service (mirrors a typical Python backend stack) with per-user auth, off by default

## Application demo checklist (Loom)
1. Problem in one sentence: AI assistants repeat approaches that already failed.
2. Show `install`, then a real vibe-coding session where something fails twice.
3. Show the injected hint on a repeat, and its size (token budget).
4. Open the dashboard: tiles (with the estimate labels), then the route graph with replay.
5. Decisions and trade-offs: stdlib-only, fail-open hooks, no LLM in the hot path, redaction, honest metrics.
6. Numbers: fingerprint eval (pairs), repeat-failure rate and relevance from your own dogfood, hook p95 latency.
