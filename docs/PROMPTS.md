# Prompts for Claude Code (copy, paste, go)

Workflow per phase: `/clear` -> paste the phase prompt -> approve the plan -> let it build the first slice -> review -> commit -> next slice.
CLAUDE.md is loaded automatically, so these prompts stay short.

## Session starter (use at the start of any session)
```
Read CLAUDE.md, then the current phase in docs/ROADMAP.md and only the spec doc that phase names.
Tell me in <= 6 lines: the next unchecked item, the files you will touch, and the test you will write first. Do not write code yet.
```

## Phase 2
**2.0 probe**
```
Phase 2, item 2.0. First fetch the current Claude Code hooks documentation and list any differences from the "verified facts" in CLAUDE.md.
Then implement `deadends hook-probe <event>` exactly as in docs/HOOKS_SPEC.md (redacted raw stdin JSON to ~/.deadends/probe/, prints nothing, always exits 0) with tests.
Do NOT install it into my real settings. Give me the exact settings.json snippet and the steps to run one real session; I will run it and send you the payloads.
```
**2.0b after you have payloads** (paste the redacted JSON files or put them in `tests/fixtures/hooks/`)
```
Here are the real payloads in tests/fixtures/hooks/. Update the "must verify" checklist in docs/HOOKS_SPEC.md with the answers, correct CLAUDE.md if anything differed,
and tell me which assumptions in ARCHITECTURE.md changed. No handler code yet.
```
**2.1-2.2 storage + config**
```
Items 2.1 and 2.2: migration to user_version 2 (meta, sessions, events, recalls, indexes, WAL, busy timeout) and config.py.
Plan first (<= 10 lines). Test the migration against a database created by the Phase 1.1 code (build it in the test from the old schema). Keep db.py as the only place with SQL.
```
**2.3-2.5 hooks**
```
Items 2.3 to 2.5. Smallest slice first: dispatcher + recording of prompts and Bash actions from fixtures, with fail-open tests.
Then failure detection and problem/attempt inference per docs/ARCHITECTURE.md. Show me the plan, then do slice 1 only.
```
**2.6 install**
```
Item 2.6: install / uninstall / doctor per docs/HOOKS_SPEC.md. Verify the settings.json hook structure against the current docs and my existing ~/.claude/settings.json (read it, do not modify it in tests; use temp copies).
Install must back up, merge, be idempotent, and show a diff. Write a test that uninstall restores the original bytes apart from our entries.
```

## Phase 3
```
Phase 3. Implement recall per docs/TOKEN_BUDGET.md. Write the budget tests first (worst-case data, caps, dedupe, 3-per-session), then the code to satisfy them.
Snapshot-test the exact hint string. Show me the final hint for a realistic fixture before moving on.
```

## Phase 4
```
Phase 4. Implement route.py and the metrics queries from docs/UI_SPEC.md. Start with route.py using fixtures (linear, two failed attempts then fix, abandoned, 500 events).
Pure functions, no I/O besides db reads. Show me the JSON for the "two failed attempts then fix" fixture before building the server.
```

## Phase 5
```
Phase 5. Build the dashboard UI under deadends/ui/ per docs/UI_SPEC.md: vanilla JS + SVG, no CDN, no framework.
Order: shell and theme, Overview, tables, then the route graph, then replay/filters/outline. After the Overview and after the route graph, run `deadends serve` against a fixture ledger,
and tell me exactly what to open and what I should see so I can check it myself. Keep the layout algorithm a pure, tested function.
```

## When things go wrong
**Tests failing**
```
Run the tests quietly and show only failures. Diagnose the root cause before editing. Do not weaken or delete tests or samples to get green; if a test is wrong, explain why first.
```
**Hooks misbehave in my real session**
```
Read ~/.deadends/hook.log (tail only) and run `deadends doctor`. Tell me the likely cause in <= 5 lines and propose the smallest fix with a regression test using a fixture.
```
**Context getting big**
```
Summarize the current state in <= 10 lines (done, in progress, decisions, next step) and write it to docs/ROADMAP.md notes. I will /clear and continue from it.
```
**Before committing**
```
Run the definition-of-done checklist from CLAUDE.md. List anything not satisfied. Then suggest the commit message in the repo's `<area>: <what and why>` style.
```
