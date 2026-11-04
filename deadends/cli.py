"""Command line interface: ``deadends <command>`` or ``python -m deadends <command>``."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from typing import Any, Dict, List, Optional

from . import __version__
from .db import CONFIDENCES, OUTCOMES, Ledger, default_db_path
from .fingerprint import fingerprint
from .redact import redact


# ------------------------------------------------------------------- project key

def _git(args: List[str], cwd: Optional[str] = None) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def detect_project(cwd: Optional[str] = None) -> str:
    """Stable key for the current repo: git remote if any, else repo root, else cwd."""
    env = os.environ.get("DEADENDS_PROJECT")
    if env:
        return env
    remote = _git(["config", "--get", "remote.origin.url"], cwd)
    if remote:
        remote, _ = redact(remote)
        return re.sub(r"\.git$", "", remote)
    return _git(["rev-parse", "--show-toplevel"], cwd) or os.path.abspath(cwd or os.getcwd())


def project_label(key: str) -> str:
    return re.split(r"[/\\:]", key.rstrip("/\\"))[-1] or key


# --------------------------------------------------------------------- helpers

def _read_error(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "text", None):
        return args.text
    path = getattr(args, "file", None)
    if path:
        if path == "-":
            return sys.stdin.read()
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return None


def _kv(pairs: Optional[List[str]], flag: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("%s expects KEY=VALUE, got %r" % (flag, pair))
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _short(text: Optional[str], width: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "..."


def _fmt_attempt(a: Dict[str, Any], indent: str = "  ") -> str:
    seen = "  seen %dx" % a["occurrences"] if a.get("occurrences", 1) > 1 else ""
    lines = ["%s#%d [%s] %s  (%s)%s" % (indent, a["id"], a["outcome"], a["created_at"][:10], project_label(a["project"]), seen)]
    lines.append("%s  approach:   %s" % (indent, _short(a["approach"])))
    if a.get("problem"):
        lines.append("%s  problem:    %s" % (indent, _short(a["problem"])))
    if a.get("error_type"):
        lines.append("%s  error:      %s: %s" % (indent, a["error_type"], _short(a["error_message"], 80)))
    if a.get("root_cause"):
        conf = " (confidence: %s)" % a["confidence"] if a.get("confidence") else ""
        lines.append("%s  root cause: %s%s" % (indent, _short(a["root_cause"]), conf))
    if a.get("fix"):
        lines.append("%s  fix:        %s" % (indent, _short(a["fix"])))
    if a.get("versions"):
        lines.append("%s  versions:   %s" % (indent, ", ".join("%s=%s" % kv for kv in a["versions"].items())))
    return "\n".join(lines)


def _print(args: argparse.Namespace, human: str, data: Any) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(human)


# -------------------------------------------------------------------- commands

def cmd_init(args, ledger: Ledger) -> int:
    _print(args, "Ledger ready at %s (full-text search: %s)" % (ledger.path, "on" if ledger.fts else "off"),
           {"path": ledger.path, "fts": ledger.fts})
    return 0


def cmd_add(args, ledger: Ledger) -> int:
    project = args.project or detect_project()
    result = ledger.add_attempt(
        project=project,
        approach=args.approach,
        outcome=args.outcome,
        why=args.why,
        problem=args.problem,
        error_text=_read_error(args),
        root_cause=args.root_cause,
        fix=args.fix,
        confidence=args.confidence,
        versions=_kv(args.env, "--env"),
        evidence=_kv(args.evidence, "--evidence"),
        source=args.source,
    )
    if result.duplicate_of:
        lines = ["Already logged as #%d (now seen %d times) - updated it instead of adding a duplicate"
                 % (result.id, result.occurrences)]
    else:
        lines = ["Logged attempt #%d (%s) in %s" % (result.id, args.outcome, project_label(project))]
    if result.fp:
        lines.append("  error: %s: %s" % (result.fp.parsed.exc_type, _short(result.fp.parsed.message, 80)))
        lines.append("  fingerprint: strict=%s loose=%s" % (result.fp.strict, result.fp.loose))
        if result.seen_before and not result.duplicate_of:
            lines.append("  note: this exact error was logged %d time(s) before - run `deadends lookup`" % result.seen_before)
    if result.redacted:
        lines.append("  redacted before saving: %s" % ", ".join(result.redacted))
    _print(args, "\n".join(lines), {
        "id": result.id,
        "strict": result.fp.strict if result.fp else None,
        "loose": result.fp.loose if result.fp else None,
        "seen_before": result.seen_before,
        "duplicate_of": result.duplicate_of,
        "occurrences": result.occurrences,
        "redacted": result.redacted,
    })
    return 0


def cmd_lookup(args, ledger: Ledger) -> int:
    text = _read_error(args)
    if not text:
        raise SystemExit("lookup needs the error: use --text '...' or --file PATH (or '-' for stdin)")
    project = args.project or detect_project()
    res = ledger.find_matches(text, project=project, limit=args.limit, record=not args.no_record)
    data = {
        "level": res.level,
        "strict": res.fp.strict,
        "loose": res.fp.loose,
        "matches": res.matches,
        "resolutions": res.resolutions,
        "had_fix": res.had_fix,
    }
    p = res.fp.parsed
    lines = ["Error: %s: %s" % (p.exc_type, _short(p.message, 90))]
    if res.level == "none":
        lines.append("No prior record. This looks new - if you try an approach and it fails, log it with `deadends add`.")
    else:
        label = "same error" if res.level == "exact" else "similar error (same family, different details)"
        lines.append("Seen before: %s - %d prior attempt(s)" % (label, len(res.matches)))
        for m in res.matches:
            lines.append(_fmt_attempt(m))
        if res.resolutions:
            lines.append("What eventually worked for the same problem:")
            for r in res.resolutions:
                lines.append(_fmt_attempt(r))
        if not res.had_fix:
            lines.append("No fix recorded yet. Add one later with `deadends update <id> --fix '...'`.")
    _print(args, "\n".join(lines), data)
    return 0


def cmd_fingerprint(args, ledger: Optional[Ledger]) -> int:
    text = _read_error(args)
    if not text:
        raise SystemExit("fingerprint needs the error: use --text '...' or --file PATH (or '-' for stdin)")
    text, _ = redact(text)
    fp = fingerprint(text)
    _print(args, "\n".join([
        "kind:        %s" % fp.parsed.kind,
        "type:        %s" % fp.parsed.exc_type,
        "message:     %s" % _short(fp.parsed.message, 100),
        "top frames:  %s" % (", ".join(fp.parsed.frames) or "-"),
        "strict norm: %s" % fp.norm_strict,
        "loose norm:  %s" % fp.norm_loose,
        "strict fp:   %s" % fp.strict,
        "loose fp:    %s" % fp.loose,
    ]), {"kind": fp.parsed.kind, "type": fp.parsed.exc_type, "message": fp.parsed.message,
         "frames": fp.parsed.frames, "norm_strict": fp.norm_strict, "norm_loose": fp.norm_loose,
         "strict": fp.strict, "loose": fp.loose})
    return 0


def cmd_hook_probe(args, ledger: Optional[Ledger]) -> int:
    """Hook entrypoint: record a redacted copy of the raw stdin payload. Always exits 0, prints nothing."""
    from .hooks.log import log_error
    from .hooks.probe import run_hook_probe

    try:
        run_hook_probe(args.event, sys.stdin.read())
    except Exception as exc:  # fail open: a probe must never break the session
        log_error("hook-probe", exc)
    return 0


def cmd_hook_post_tool_use_failure(args, ledger: Optional[Ledger]) -> int:
    """Hook entrypoint: log a failed Bash command as an attempt. Always exits 0, prints nothing."""
    from .hooks.log import log_error

    try:
        data = json.loads(sys.stdin.read())
        if data.get("tool_name") != "Bash" or data.get("is_interrupt"):
            return 0
        command = (data.get("tool_input") or {}).get("command")
        if not command:
            return 0
        project = detect_project(data.get("cwd"))
        local = Ledger(args.db or default_db_path()) if ledger is None else ledger
        try:
            local.add_attempt(
                project=project,
                approach="ran: %s" % command,
                outcome="failed",
                error_text=data.get("error"),
                source="hook",
            )
        finally:
            if ledger is None:
                local.close()
    except Exception as exc:  # fail open: a hook must never break the session
        log_error("hook-post-tool-use-failure", exc)
    return 0


def cmd_search(args, ledger: Ledger) -> int:
    project = None if args.all_projects else (args.project or detect_project())
    rows = ledger.search(" ".join(args.query), project=project, limit=args.limit)
    human = "\n".join(_fmt_attempt(r) for r in rows) if rows else "No matches."
    _print(args, human, rows)
    return 0


def cmd_list(args, ledger: Ledger) -> int:
    project = None if args.all_projects else (args.project or detect_project())
    rows = ledger.list_attempts(project=project, outcome=args.outcome, limit=args.limit)
    human = "\n".join(_fmt_attempt(r) for r in rows) if rows else "Nothing logged yet for this project."
    _print(args, human, rows)
    return 0


def cmd_update(args, ledger: Ledger) -> int:
    ok = ledger.update_attempt(
        args.id, outcome=args.outcome, why=args.why, root_cause=args.root_cause, fix=args.fix,
        confidence=args.confidence,
    )
    if not ok:
        print("No attempt #%d, or nothing to change." % args.id, file=sys.stderr)
        return 1
    _print(args, "Updated attempt #%d." % args.id, ledger.get_attempt(args.id))
    return 0


def render_markdown(project: str, rows: List[Dict[str, Any]]) -> str:
    out = [
        "# Dead ends - %s" % project_label(project),
        "",
        "_Generated by deadends on %s. Approaches that already failed in this project. "
        "Treat each as 'failed in this setup' and re-check if library versions have changed._",
        "",
    ]
    out[2] = out[2] % date.today().isoformat()
    groups: Dict[str, List[Dict[str, Any]]] = {}
    worked: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        key = r.get("problem") or "Unsorted"
        (worked if r["outcome"] == "worked" else groups).setdefault(key, []).append(r)
    if not groups:
        out.append("_No failed approaches logged yet._")
    for title, items in groups.items():
        out.append("## %s" % title)
        for r in items:
            tag = "failed" if r["outcome"] == "failed" else "partly worked"
            seen = ", seen %d times" % r["occurrences"] if r.get("occurrences", 1) > 1 else ""
            out.append("- **%s** - %s (%s%s)" % (_short(r["approach"], 140), tag, r["created_at"][:10], seen))
            if r.get("error_type"):
                out.append("  - Error: `%s: %s`" % (r["error_type"], _short(r["error_message"], 100)))
            if r.get("root_cause"):
                conf = " (confidence: %s)" % r["confidence"] if r.get("confidence") else ""
                out.append("  - Why it failed: %s%s" % (_short(r["root_cause"], 160), conf))
            if r.get("fix"):
                out.append("  - Fix: %s" % _short(r["fix"], 160))
            if r.get("versions"):
                out.append("  - Versions: %s" % ", ".join("%s=%s" % kv for kv in r["versions"].items()))
        for w in worked.get(title, []):
            out.append("- What worked: **%s** (%s)" % (_short(w["approach"], 140), w["created_at"][:10]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def cmd_export(args, ledger: Ledger) -> int:
    project = args.project or detect_project()
    md = render_markdown(project, ledger.export_rows(project, limit=args.limit))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print("Wrote %s" % args.out)
    else:
        sys.stdout.write(md)
    return 0


def cmd_stats(args, ledger: Ledger) -> int:
    project = None if args.all_projects else (args.project or detect_project())
    s = ledger.stats(project)
    rate = "n/a" if s["hit_rate"] is None else "%d%%" % round(100 * s["hit_rate"])
    human = "\n".join([
        "Scope:               %s" % (project_label(project) if project else "all projects"),
        "Attempts logged:     %d  %s" % (s["attempts"], s["by_outcome"]),
        "Problems tracked:    %d" % s["problems"],
        "Lookups run:         %d" % s["lookups"],
        "  matched history:   %d (exact: %d) -> hit rate %s" % (s["lookup_hits"], s["lookup_exact_hits"], rate),
        "  with a known fix:  %d" % s["lookups_with_known_fix"],
    ])
    _print(args, human, s)
    return 0


# ---------------------------------------------------------------------- parser

def _add_error_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--text", "-t", help="error text")
    p.add_argument("--file", "-f", help="file containing the error ('-' reads stdin)")


def _add_common(p: argparse.ArgumentParser, project: bool = True) -> None:
    if project:
        p.add_argument("--project", help="project key (default: detected from git)")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deadends", description="A ledger of failed approaches for AI-assisted coding.")
    p.add_argument("--db", help="ledger path (default: $DEADENDS_DB or ~/.deadends/ledger.db)")
    p.add_argument("--version", action="version", version="deadends " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create the ledger and show where it lives")
    _add_common(s, project=False)
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add", help="log an attempt (usually a failed approach)")
    s.add_argument("--approach", "-a", required=True, help="what was tried")
    s.add_argument("--outcome", choices=OUTCOMES, default="failed")
    s.add_argument("--why", help="why this approach was suggested/chosen")
    s.add_argument("--problem", help="problem title this attempt belongs to")
    s.add_argument("--root-cause", help="why it failed")
    s.add_argument("--fix", help="what fixed it")
    s.add_argument("--confidence", choices=CONFIDENCES, help="how sure the root cause is")
    s.add_argument("--env", action="append", metavar="KEY=VALUE", help="library/runtime version (repeatable)")
    s.add_argument("--evidence", action="append", metavar="KEY=VALUE", help="command, commit, ... (repeatable)")
    s.add_argument("--source", default="manual", help="manual | hook | skill")
    _add_error_args(s)
    _add_common(s)
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("lookup", help="have I seen this error before?")
    _add_error_args(s)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--no-record", action="store_true", help="do not count this lookup in stats")
    _add_common(s)
    s.set_defaults(func=cmd_lookup)

    s = sub.add_parser("fingerprint", help="show how an error is parsed and fingerprinted (debugging aid)")
    _add_error_args(s)
    _add_common(s, project=False)
    s.set_defaults(func=cmd_fingerprint)

    s = sub.add_parser("search", help="full-text search across attempts")
    s.add_argument("query", nargs="+")
    s.add_argument("--all-projects", action="store_true")
    s.add_argument("--limit", type=int, default=20)
    _add_common(s)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("list", help="recent attempts")
    s.add_argument("--outcome", choices=OUTCOMES)
    s.add_argument("--all-projects", action="store_true")
    s.add_argument("--limit", type=int, default=20)
    _add_common(s)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("update", help="add a root cause / fix to an existing attempt")
    s.add_argument("id", type=int)
    s.add_argument("--outcome", choices=OUTCOMES)
    s.add_argument("--why")
    s.add_argument("--root-cause")
    s.add_argument("--fix")
    s.add_argument("--confidence", choices=CONFIDENCES)
    _add_common(s, project=False)
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("export", help="write a DEADENDS.md for this project")
    s.add_argument("--out", "-o", help="output file (default: stdout)")
    s.add_argument("--limit", type=int, default=50)
    _add_common(s)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("stats", help="counts and lookup hit rate")
    s.add_argument("--all-projects", action="store_true")
    _add_common(s)
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("hook-probe", help="hook entrypoint: record a redacted copy of the raw stdin payload (debugging aid)")
    s.add_argument("event", help="hook event name, e.g. PostToolUse")
    s.set_defaults(func=cmd_hook_probe)

    s = sub.add_parser("hook", help="hook entrypoints")
    hook_sub = s.add_subparsers(dest="hook_cmd", required=True)
    s2 = hook_sub.add_parser("post-tool-use-failure", help="hook entrypoint: log a failed Bash command")
    s2.set_defaults(func=cmd_hook_post_tool_use_failure)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "fingerprint":
            return cmd_fingerprint(args, None)
        if args.cmd == "hook-probe":
            return cmd_hook_probe(args, None)
        if args.cmd == "hook" and args.hook_cmd == "post-tool-use-failure":
            return cmd_hook_post_tool_use_failure(args, None)
        ledger = Ledger(args.db or default_db_path())
        try:
            return args.func(args, ledger)
        finally:
            ledger.close()
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except BrokenPipeError:
        # e.g. `deadends list | head`: the reader went away; exit quietly instead of a traceback
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
