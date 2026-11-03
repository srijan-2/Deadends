"""Error logging for hook entrypoints. Never raises, never touches stdout."""
from __future__ import annotations

import os
from datetime import datetime, timezone

_MAX_BYTES = 256 * 1024


def log_path() -> str:
    return os.environ.get("DEADENDS_HOOK_LOG") or os.path.join(os.path.expanduser("~"), ".deadends", "hook.log")


def log_error(context: str, exc: BaseException) -> None:
    """Append one entry to the hook log, rotating it at _MAX_BYTES. Swallows all errors."""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > _MAX_BYTES:
            os.replace(path, path + ".old")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = "%s [%s] %s: %s\n" % (ts, context, type(exc).__name__, exc)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
