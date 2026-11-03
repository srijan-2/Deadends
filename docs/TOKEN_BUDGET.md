# Token budget

The tool exists to save tokens and loops. If it costs more context than it saves, it failed.
Estimate: 1 token ~ 4 characters (a constant in `config.py`; label every figure as an estimate).

## Where text can reach Claude's context
| channel | cap | when | default |
|---|---|---|---|
| Recall hint (`PostToolUse` additionalContext) | **600 chars (~150 tokens)**, max 2 matches | only on a failure that matches history | on |
| Per-session recall limit | **3 injections** | resets each session | `DEADENDS_MAX_RECALLS=3` |
| Same fingerprint twice in one session | **0** (inject once, then stay silent) | - | fixed |
| Session digest (`SessionStart` additionalContext) | **800 chars (~200 tokens)**, top 3 unresolved or recently-fixed dead ends for this project | only if there is something to say | on, `DEADENDS_SESSION_DIGEST=off` |
| `UserPromptSubmit` injection | **0** | never in v1 | - |
| Hook stdout other than the JSON above | **0** | never | fixed |
| CLI output the user pastes into chat | <= 25 lines by default, `--full` for more | - | compact |
| `deadends export` (for the user's own CLAUDE.md) | <= 40 lines, unresolved first, then recent fixes | - | compact |
| `templates/CLAUDE.snippet.md` | <= 8 lines | one-time paste | - |

Worst-case injected cost per session: 3 x 150 + 200 = **~650 tokens**. The dashboard shows the real overhead next to the benefit.

## Rules
1. **Silence is the default.** No match, no output. Do not announce that the tool is running.
2. **Match quality gates injection.** Exact match: inject. Similar match: inject only if a fix is recorded. Never inject unresolved noise from other repos
   unless the exact fingerprint matches.
3. **Rank, then cut.** Same-project first, known fix first, newest first. Drop the rest; never paginate into context.
4. **Telegraphic format.** One line per match: error head (<= 80 chars) -> failed approach (<= 80) -> what worked (<= 120) -> env (<= 30). No markdown, no emojis, no headers.
5. **Truncate with a pointer, not a dump**: end with `(deadends why <id>)` only if there is more; never print the full record.
6. **No LLM calls anywhere in the capture path.** Summaries are mechanical (command text, file paths, exit code). Root cause is human/skill-supplied and optional.
7. **Store small.** Event summary <= 200 chars, error text <= 2 KB, prompt head <= 300 chars (configurable). Fewer bytes read back means fewer tokens spent, and a faster hook.
8. **Don't make Claude re-read the world.** Never inject file contents, diffs or logs. Facts and pointers only.

## Metrics the dashboard must show about itself (honesty)
* Injected hints, injected chars, **estimated injected tokens** (sum of `recalls.est_tokens`).
* Recall relevance: share of recalls after which the next action was **not** a repeat of a listed failed approach (heuristic, labeled).
* **Repeats avoided (estimate)** = recalls with a known fix where the failed approach was not repeated.
* **Tokens saved (estimate)** = repeats avoided x `DEADENDS_LOOP_COST_TOKENS` (default 1500, user-adjustable, shown on the page with the formula).
  Always render as "~N (estimate)". Never present it as measured.
* Net = estimated saved - estimated injected. If net is negative, say so.

## Tests that enforce the budget
* Build worst-case data (huge error text, 50 matches, long approach strings, unicode) and assert `len(additionalContext) <= 600` and `<= 2 matches`.
* Same fingerprint twice in one session -> second call returns empty stdout.
* 4th recall in a session -> empty stdout.
* Session digest <= 800 chars with 100 stored problems.
* A snapshot test of the exact recall string for a known fixture, so wording changes are deliberate.
* Default CLI commands print <= 25 lines on a 500-attempt ledger.

## Guidance for the user's own sessions (goes in `templates/CLAUDE.snippet.md`)
Keep it to a handful of lines: what a `[deadends]` hint means, and "do not run deadends commands unless asked".
Every extra line in a user's CLAUDE.md is paid for on every turn of every session.
