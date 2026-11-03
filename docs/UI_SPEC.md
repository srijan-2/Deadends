# Dashboard spec: stats page + route graph

Run with `deadends serve [--port 8765] [--open]`. Local only, read-only, no build step, works offline.

## Server (`deadends/server.py`)
* `http.server.ThreadingHTTPServer` bound to **127.0.0.1**; reject requests whose `Host` is not `127.0.0.1:<port>` / `localhost:<port>` (DNS-rebinding guard).
* `GET`/`HEAD` only; any other method -> 405. Responses: `Content-Type` explicit, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, strict CSP (`default-src 'self'`).
* Static files served from `deadends/ui/` (declare as package data in `pyproject.toml`; test that a built wheel contains them).
* The server opens the DB read-only (`file:...?mode=ro` URI) and never writes.
* Pagination (`limit` default 50, max 200) and `days` filters on every list endpoint. Bad params -> 400 JSON `{error}`.

## API (JSON; every response includes `generated_at`)
| endpoint | returns |
|---|---|
| `GET /api/projects` | projects with attempt/problem/session counts |
| `GET /api/overview?project=&days=30` | headline metrics (below) |
| `GET /api/timeline?project=&days=30` | per-day `{date, failures, recalls, resolved}` |
| `GET /api/families?project=&limit=10` | top error families: loose fp, example error, count, resolved share, last seen |
| `GET /api/problems?project=&status=&limit=` | problems with attempt counts, status, time to resolve |
| `GET /api/sessions?project=&limit=` | sessions: start, duration, prompts, failures, recalls, resolved/abandoned |
| `GET /api/session/<id>/route` | route graph for one session |
| `GET /api/problem/<id>/route` | route graph for one problem across sessions |
| `GET /api/attempt/<id>` | one attempt with redacted details |
| `GET /api/config` | effective config (store_prompts, caps, retention); read-only |

## Stats page: metrics and exact definitions
| tile | definition |
|---|---|
| Failures captured | `failure` events in range |
| Distinct problems | problems opened in range |
| Resolved rate | resolved problems / opened problems |
| Repeat-failure rate | failures whose strict fp was already in the ledger / all failures. **The headline number.** |
| Recalls injected | rows in `recalls` |
| Repeats avoided (est.) | recalls with a known fix not followed by a repeat of the listed approach (heuristic) |
| Injected tokens (est.) | sum of `recalls.est_tokens` + session digests |
| Tokens saved (est.) | repeats avoided x loop-cost constant, shown with its formula |
| Median time to resolve | first failure -> resolution, per problem |
| Open problems | unresolved/abandoned, with age |
| Top families | table from `/api/families` |
| Failures by ecosystem | `error_kind` bar chart |
| Activity | line chart from `/api/timeline` |
Every estimated metric carries an "(estimate)" label and an info popover showing the formula. Empty state: a friendly "No data yet. Install the hooks and run a session" with the `install` command.

Charts: hand-written SVG (small `chart.js`-free helpers: bars, line, sparkline). Follow the project's chart rules: one accent plus neutrals, labels on the chart,
no color-only encoding, light and dark themes via CSS variables, `prefers-reduced-motion` respected.

## Route graph (the signature feature)
Shows the path the work actually took: where the prompt led, which approaches failed, what was recalled, what finally worked.

### Node types (shape + icon + color, never color alone)
| type | shape | meaning | data |
|---|---|---|---|
| `prompt` | rounded rectangle | user prompt (redacted head, or "prompt hidden" if storage off) | ts, text |
| `steps` | small grey pill | N consecutive successful actions, collapsed (click to expand) | count, summaries |
| `attempt` | rectangle with a number badge | one distinct approach | approach, outcome, occurrences |
| `failure` | diamond, red | an error, with ecosystem badge | error type/head, fingerprint (short), exit code |
| `recall` | hexagon, blue | a hint deadends injected | matched attempt ids, chars |
| `resolved` | circle with check, green | problem resolved, with the fix summary | fix, time to resolve |
| `abandoned` | circle with dash, grey | problem left open at session end | - |

### Edge types
`next` (solid arrow, time order), `retry` (curved loop on the same attempt, shows `xN`), `branch` (dashed, a new attempt after a failure),
`recalled` (dotted blue, recall -> the attempt it referenced), `resolved-by` (thick green into the resolution).

### Layout (vanilla JS, no library, ~300 lines)
* X axis = event order (compressed), Y = lanes. Lane 0 is the "main route". Each new attempt for a problem opens the next lane below, branching from the failure that triggered it.
* Resolution merges lanes back into lane 0 with a `resolved-by` edge.
* Positioning: `x = index * 140`, `y = lane * 90`; edges as cubic Bezier paths; the whole thing is one `<svg>` with a viewBox, pan with drag, zoom with wheel/buttons, "fit to screen" button.
* Cap rendering at ~120 nodes; beyond that, force collapse and show "Showing 118 of 640 events".
* Route data schema (from `route.py`): `{"nodes":[{"id","type","label","ts","lane","x_index","data":{}}],"edges":[{"from","to","type","label"}],"lanes":[{"id","title"}],"stats":{"events":N,"shown":N}}`.

### Interactions
* Hover: tooltip with the label and time. Click: side panel with redacted details (approach, error head, fix, versions, fingerprint, link to the attempt).
* **Replay**: play/pause/step through the route in order (nodes light up one by one); speed control; respects reduced-motion (steps without animation).
* Filters: by problem, by node type, "failures only".
* Keyboard: Tab through nodes, Enter opens details, arrow keys move to next/previous node, Esc closes the panel. Nodes have `role="button"` and `aria-label`.
* A text **outline view** toggle (same route as an indented list) for accessibility and for copying into notes.

### Screens
1. **Overview**: filters (project, range) + tiles + activity chart + top families + open problems.
2. **Sessions**: table; click a row -> Route.
3. **Route**: graph + side panel + replay bar.
4. **Problems**: table; click -> problem route (spans sessions).
5. **Settings (read-only)**: effective config and privacy mode; shows the CLI commands for wipe/prune.

Wireframe of the route view:
```
 session 7f3a  .  my-app  .  42 min  .  3 failures  .  resolved            [Replay >] [Fit] [Outline]
 ------------------------------------------------------------------------------------------------------
 lane 0  [prompt]-->[5 steps]-->(failure TypeError)-->[hex recall]----------------------->(v resolved)
 lane 1                     \--> [attempt 1: patch utils]--x-->|retry x2                        ^
 lane 2                              \--------------> [attempt 2: pin lib 2.31]-----------------+
 ------------------------------------------------------------------------------------------------------
 side panel: Attempt 2 - "pin lib 2.31" - worked - env: requests=2.31 - fp 9eed63...
```

## Graph library decision
* **v1: no library.** The route is a near-linear timeline with a few branches; hand-rolled SVG keeps the stdlib-only, offline, tiny promise and is easy to test (layout is a pure function over route data).
* **Phase 6 (optional): "Error families map"**, a global force-directed graph (families <-> projects <-> fixes). That one benefits from a library. If adopted, vendor a **pinned** build (Cytoscape.js or d3-force)
  under `deadends/ui/vendor/` with its license file and a note in the README; never load from a CDN. It is the only permitted exception to "no dependencies".
* If "Graphify" was meant as a specific tool the project should integrate with, decide that explicitly before Phase 5; nothing in this spec depends on it.

## Tests
* `route.py`: fixtures for a linear session, a session with 2 failed attempts then a fix, an abandoned problem, a 500-event session (must compress under 60 nodes), and an empty session.
* Layout function: pure, tested for lane assignment and no overlapping node boxes.
* Server: starts on an ephemeral port in a thread; test every endpoint, a bad `Host`, a non-GET method, `limit` bounds, and that no write is possible (read-only DB).
* A smoke test that `index.html` references only local assets (no `http://`/`https://` URLs).
* Manual: open in light and dark mode, 1280px and 390px widths, keyboard-only pass, reduced-motion on.
