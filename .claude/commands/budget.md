---
description: Audit the code for token-budget and safety violations
---
Search the `deadends/` package (use grep, do not read whole files) and report violations of the rules in `CLAUDE.md` and `docs/TOKEN_BUDGET.md`:

1. `print(` outside `cli.py` and hook entrypoints.
2. Writes to the database (`INSERT`, `UPDATE`) whose text did not pass through `redact()`.
3. Any `additionalContext` construction without the length cap, or any hook path that can exit non-zero or print non-JSON.
4. Imports of third-party packages, or network libraries (`urllib.request`, `http.client`, `socket` clients, `requests`).
5. SQL built with string formatting from user data.

Reply as a short list of `path:line - problem` (max 15 lines). If everything is clean, say so in one line. Do not edit anything. $ARGUMENTS
