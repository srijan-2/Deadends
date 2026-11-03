"""SQLite ledger: problems, attempts, and lookup events.

Design notes
* One global database (``~/.deadends/ledger.db`` or ``$DEADENDS_DB``); every row is
  tagged with a project key so matches from the same repo rank first, while errors
  seen in *other* repos are still surfaced.
* All free text is redacted before it is stored.
* Full-text search uses FTS5 when available and falls back to LIKE.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .fingerprint import Fingerprint, fingerprint
from .redact import redact

OUTCOMES = ("failed", "worked", "partial")
CONFIDENCES = ("low", "medium", "high")

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  UNIQUE(project, title)
);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id INTEGER REFERENCES problems(id),
  project TEXT NOT NULL,
  approach TEXT NOT NULL,
  why TEXT,
  outcome TEXT NOT NULL CHECK(outcome IN ('failed','worked','partial')),
  error_redacted TEXT,
  error_kind TEXT,
  error_type TEXT,
  error_message TEXT,
  frames TEXT,
  fp_strict TEXT,
  fp_loose TEXT,
  root_cause TEXT,
  fix TEXT,
  confidence TEXT CHECK(confidence IS NULL OR confidence IN ('low','medium','high')),
  versions TEXT,
  evidence TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  occurrences INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_strict ON attempts(fp_strict);
CREATE INDEX IF NOT EXISTS idx_attempts_loose ON attempts(fp_loose);
CREATE INDEX IF NOT EXISTS idx_attempts_project ON attempts(project);
CREATE TABLE IF NOT EXISTS lookups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  project TEXT NOT NULL,
  fp_strict TEXT,
  fp_loose TEXT,
  level TEXT NOT NULL,
  matched_ids TEXT,
  had_fix INTEGER NOT NULL DEFAULT 0
);
"""

_TEXT_FIELDS = ("approach", "why", "root_cause", "fix")


def default_db_path() -> str:
    return os.environ.get("DEADENDS_DB") or os.path.join(os.path.expanduser("~"), ".deadends", "ledger.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AddResult:
    id: int
    fp: Optional[Fingerprint]
    redacted: List[str]
    seen_before: int = 0
    duplicate_of: Optional[int] = None
    occurrences: int = 1


@dataclass
class LookupResult:
    fp: Fingerprint
    level: str  # exact | similar | none
    matches: List[Dict[str, Any]] = field(default_factory=list)
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    had_fix: bool = False


class Ledger:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.fts = self._ensure_fts()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(attempts)")}
        if "occurrences" not in cols:
            self.conn.execute("ALTER TABLE attempts ADD COLUMN occurrences INTEGER NOT NULL DEFAULT 1")
            self.conn.commit()

    def _reindex_fts(self, attempt_id: int) -> None:
        if not self.fts:
            return
        row = self.conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        self.conn.execute("DELETE FROM attempts_fts WHERE rowid=?", (attempt_id,))
        self.conn.execute(
            "INSERT INTO attempts_fts(rowid, approach, why, root_cause, fix, error_message) VALUES(?,?,?,?,?,?)",
            (attempt_id, row["approach"], row["why"] or "", row["root_cause"] or "", row["fix"] or "", row["error_message"] or ""),
        )

    def close(self) -> None:
        self.conn.close()

    def _ensure_fts(self) -> bool:
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS attempts_fts USING "
                "fts5(approach, why, root_cause, fix, error_message)"
            )
            return True
        except sqlite3.OperationalError:
            return False

    # ------------------------------------------------------------------ writes

    def ensure_problem(self, project: str, title: str) -> int:
        title, _ = redact(title.strip())
        row = self.conn.execute(
            "SELECT id FROM problems WHERE project=? AND title=?", (project, title)
        ).fetchone()
        if row:
            return int(row["id"])
        cur = self.conn.execute(
            "INSERT INTO problems(project, title, created_at) VALUES(?,?,?)", (project, title, _now())
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_attempt(
        self,
        *,
        project: str,
        approach: str,
        outcome: str = "failed",
        why: Optional[str] = None,
        problem: Optional[str] = None,
        error_text: Optional[str] = None,
        root_cause: Optional[str] = None,
        fix: Optional[str] = None,
        confidence: Optional[str] = None,
        versions: Optional[Dict[str, str]] = None,
        evidence: Optional[Dict[str, str]] = None,
        source: str = "manual",
    ) -> AddResult:
        if outcome not in OUTCOMES:
            raise ValueError("outcome must be one of %s" % (OUTCOMES,))
        if confidence is not None and confidence not in CONFIDENCES:
            raise ValueError("confidence must be one of %s" % (CONFIDENCES,))
        if not approach or not approach.strip():
            raise ValueError("approach is required")

        kinds: set = set()

        def clean(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            text, found = redact(value)
            kinds.update(found)
            return text

        approach_c, why_c, root_c, fix_c = (clean(v) for v in (approach, why, root_cause, fix))
        err_c = clean(error_text) if error_text and error_text.strip() else None
        versions_c = {k: clean(str(v)) for k, v in (versions or {}).items()}
        evidence_c = {k: clean(str(v)) for k, v in (evidence or {}).items()}

        fp: Optional[Fingerprint] = fingerprint(err_c) if err_c else None
        problem_id = self.ensure_problem(project, problem) if problem else None

        seen_before = 0
        if fp:
            seen_before = self.conn.execute(
                "SELECT COUNT(*) FROM attempts WHERE fp_strict=?", (fp.strict,)
            ).fetchone()[0]

        # Same project + same approach (ignoring case/spacing) + same exact error = the same attempt.
        # Merge instead of duplicating, so hooks that log repeatedly don't flood the ledger.
        norm_approach = " ".join(approach_c.split()).casefold()
        dup = None
        for row in self.conn.execute(
            "SELECT * FROM attempts WHERE project=? AND fp_strict IS ?", (project, fp.strict if fp else None)
        ):
            if " ".join(row["approach"].split()).casefold() == norm_approach:
                dup = row
                break
        if dup is not None:
            sets, vals = ["occurrences = occurrences + 1"], []
            for col, val in (("why", why_c), ("root_cause", root_c), ("fix", fix_c), ("confidence", confidence)):
                if val is not None:
                    sets.append("%s=?" % col)
                    vals.append(val)
            if versions_c:
                sets.append("versions=?")
                vals.append(json.dumps(versions_c))
            if evidence_c:
                sets.append("evidence=?")
                vals.append(json.dumps(evidence_c))
            if outcome != dup["outcome"]:
                sets.append("outcome=?")
                vals.append(outcome)
            if problem_id and not dup["problem_id"]:
                sets.append("problem_id=?")
                vals.append(problem_id)
            self.conn.execute("UPDATE attempts SET %s WHERE id=?" % ", ".join(sets), vals + [dup["id"]])
            self._reindex_fts(dup["id"])
            self.conn.commit()
            return AddResult(dup["id"], fp, sorted(kinds), seen_before, dup["id"], dup["occurrences"] + 1)

        cur = self.conn.execute(
            """INSERT INTO attempts(problem_id, project, approach, why, outcome, error_redacted,
                 error_kind, error_type, error_message, frames, fp_strict, fp_loose, root_cause, fix,
                 confidence, versions, evidence, source, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                problem_id,
                project,
                approach_c,
                why_c,
                outcome,
                err_c,
                fp.parsed.kind if fp else None,
                fp.parsed.exc_type if fp else None,
                fp.parsed.message if fp else None,
                json.dumps(fp.parsed.frames) if fp else None,
                fp.strict if fp else None,
                fp.loose if fp else None,
                root_c,
                fix_c,
                confidence,
                json.dumps(versions_c) if versions_c else None,
                json.dumps(evidence_c) if evidence_c else None,
                source,
                _now(),
            ),
        )
        attempt_id = int(cur.lastrowid)
        if self.fts:
            self.conn.execute(
                "INSERT INTO attempts_fts(rowid, approach, why, root_cause, fix, error_message) VALUES(?,?,?,?,?,?)",
                (attempt_id, approach_c, why_c or "", root_c or "", fix_c or "", fp.parsed.message if fp else ""),
            )
        self.conn.commit()
        return AddResult(attempt_id, fp, sorted(kinds), seen_before)

    def update_attempt(self, attempt_id: int, **changes: Optional[str]) -> bool:
        allowed = {"outcome", "why", "root_cause", "fix", "confidence"}
        sets, values = [], []
        for key, value in changes.items():
            if value is None:
                continue
            if key not in allowed:
                raise ValueError("cannot update %s" % key)
            if key == "outcome" and value not in OUTCOMES:
                raise ValueError("outcome must be one of %s" % (OUTCOMES,))
            if key == "confidence" and value not in CONFIDENCES:
                raise ValueError("confidence must be one of %s" % (CONFIDENCES,))
            if key in _TEXT_FIELDS:
                value, _ = redact(value)
            sets.append("%s=?" % key)
            values.append(value)
        if not sets:
            return False
        cur = self.conn.execute("UPDATE attempts SET %s WHERE id=?" % ", ".join(sets), values + [attempt_id])
        if cur.rowcount:
            self._reindex_fts(attempt_id)
        self.conn.commit()
        return bool(cur.rowcount)

    # ------------------------------------------------------------------- reads

    def _attempt_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("versions", "evidence", "frames"):
            d[key] = json.loads(d[key]) if d.get(key) else ({} if key != "frames" else [])
        if d.get("problem_id"):
            p = self.conn.execute("SELECT title FROM problems WHERE id=?", (d["problem_id"],)).fetchone()
            d["problem"] = p["title"] if p else None
        else:
            d["problem"] = None
        return d

    def get_attempt(self, attempt_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        return self._attempt_dict(row) if row else None

    def find_matches(
        self, error_text: str, project: Optional[str] = None, limit: int = 10, record: bool = True
    ) -> LookupResult:
        text, _ = redact(error_text)
        fp = fingerprint(text)
        level, rows = "none", []
        rows = self.conn.execute("SELECT * FROM attempts WHERE fp_strict=?", (fp.strict,)).fetchall()
        if rows:
            level = "exact"
        else:
            rows = self.conn.execute("SELECT * FROM attempts WHERE fp_loose=?", (fp.loose,)).fetchall()
            if rows:
                level = "similar"
        matches = [self._attempt_dict(r) for r in rows]
        # newest first, then a stable sort so same-project and known-fix matches rank on top
        matches.sort(key=lambda m: m["created_at"], reverse=True)
        matches.sort(key=lambda m: (m["project"] != project, not (m["fix"] or m["outcome"] == "worked")))
        matches = matches[:limit]

        resolutions: List[Dict[str, Any]] = []
        seen_ids = {m["id"] for m in matches}
        for pid in {m["problem_id"] for m in matches if m["problem_id"]}:
            for r in self.conn.execute(
                "SELECT * FROM attempts WHERE problem_id=? AND outcome='worked' ORDER BY created_at DESC", (pid,)
            ):
                if r["id"] not in seen_ids:
                    resolutions.append(self._attempt_dict(r))
        had_fix = any(m["fix"] or m["outcome"] == "worked" for m in matches) or bool(resolutions)

        if record:
            self.conn.execute(
                "INSERT INTO lookups(ts, project, fp_strict, fp_loose, level, matched_ids, had_fix) VALUES(?,?,?,?,?,?,?)",
                (_now(), project or "", fp.strict, fp.loose, level, json.dumps([m["id"] for m in matches]), int(had_fix)),
            )
            self.conn.commit()
        return LookupResult(fp, level, matches, resolutions, had_fix)

    def search(self, query: str, project: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        tokens = [t for t in query.replace('"', " ").split() if t]
        if not tokens:
            return []
        rows: List[sqlite3.Row] = []
        if self.fts:
            expr = " ".join('"%s"' % t for t in tokens)
            try:
                rows = self.conn.execute(
                    "SELECT a.* FROM attempts a JOIN attempts_fts f ON f.rowid=a.id "
                    "WHERE attempts_fts MATCH ? ORDER BY rank LIMIT ?",
                    (expr, limit * 3),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            clause = " AND ".join(
                "(approach LIKE ? OR why LIKE ? OR root_cause LIKE ? OR fix LIKE ? OR error_message LIKE ?)"
                for _ in tokens
            )
            params: List[Any] = []
            for t in tokens:
                params.extend(["%" + t + "%"] * 5)
            rows = self.conn.execute(
                "SELECT * FROM attempts WHERE %s ORDER BY created_at DESC LIMIT ?" % clause, params + [limit * 3]
            ).fetchall()
        out = [self._attempt_dict(r) for r in rows]
        if project:
            out.sort(key=lambda m: m["project"] != project)
        return out[:limit]

    def list_attempts(
        self, project: Optional[str] = None, outcome: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM attempts WHERE 1=1", []
        if project:
            sql += " AND project=?"
            params.append(project)
        if outcome:
            sql += " AND outcome=?"
            params.append(outcome)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [self._attempt_dict(r) for r in self.conn.execute(sql, params)]

    def export_rows(self, project: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM attempts WHERE project=? ORDER BY created_at DESC, id DESC LIMIT ?", (project, limit)
        ).fetchall()
        return [self._attempt_dict(r) for r in rows]

    def stats(self, project: Optional[str] = None) -> Dict[str, Any]:
        where, params = ("WHERE project=?", [project]) if project else ("", [])
        by_outcome = {
            r["outcome"]: r["n"]
            for r in self.conn.execute("SELECT outcome, COUNT(*) AS n FROM attempts %s GROUP BY outcome" % where, params)
        }
        lookups_total = self.conn.execute("SELECT COUNT(*) FROM lookups %s" % where, params).fetchone()[0]
        hits = self.conn.execute(
            "SELECT COUNT(*) FROM lookups %s %s level IN ('exact','similar')" % (where, "AND" if where else "WHERE"), params
        ).fetchone()[0]
        exact = self.conn.execute(
            "SELECT COUNT(*) FROM lookups %s %s level='exact'" % (where, "AND" if where else "WHERE"), params
        ).fetchone()[0]
        fixes = self.conn.execute(
            "SELECT COUNT(*) FROM lookups %s %s had_fix=1" % (where, "AND" if where else "WHERE"), params
        ).fetchone()[0]
        return {
            "attempts": sum(by_outcome.values()),
            "by_outcome": by_outcome,
            "problems": self.conn.execute("SELECT COUNT(*) FROM problems %s" % where, params).fetchone()[0],
            "projects": self.conn.execute("SELECT COUNT(DISTINCT project) FROM attempts").fetchone()[0],
            "lookups": lookups_total,
            "lookup_hits": hits,
            "lookup_exact_hits": exact,
            "lookups_with_known_fix": fixes,
            "hit_rate": (hits / lookups_total) if lookups_total else None,
            "fts": self.fts,
        }
