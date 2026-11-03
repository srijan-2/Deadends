"""`deadends hook-probe <event>`: record a redacted copy of a real hook payload.

Used once, manually, to verify real Claude Code hook payload shapes before any
handler is written against guessed field names. See docs/HOOKS_SPEC.md "Step 0".
"""
from __future__ import annotations

import os
import re
import sys

from ..redact import redact

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def probe_dir() -> str:
    return os.environ.get("DEADENDS_PROBE_DIR") or os.path.join(os.path.expanduser("~"), ".deadends", "probe")


def _safe_event(event: str) -> str:
    return _SAFE.sub("_", event) or "unknown"


def _next_index(dir_path: str, event: str) -> int:
    prefix = event + "-"
    max_n = 0
    try:
        for name in os.listdir(dir_path):
            if name.startswith(prefix) and name.endswith(".json"):
                mid = name[len(prefix):-len(".json")]
                if mid.isdigit():
                    max_n = max(max_n, int(mid))
    except OSError:
        pass
    return max_n + 1


def run_hook_probe(event: str, stdin_text: str) -> None:
    event = _safe_event(event)
    redacted_text, _ = redact(stdin_text)
    d = probe_dir()
    os.makedirs(d, exist_ok=True)
    n = _next_index(d, event)
    path = os.path.join(d, "%s-%d.json" % (event, n))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(redacted_text)


def main(event: str) -> None:
    run_hook_probe(event, sys.stdin.read())
