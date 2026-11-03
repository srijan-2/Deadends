"""Secret redaction.

Everything that enters the ledger passes through ``redact`` first, so a pasted
stack trace or command line never leaves a token on disk. This is a safety net,
not a guarantee: patterns catch well-known secret formats and ``key=value``
assignments, nothing more.
"""
from __future__ import annotations

import re
from typing import List, Tuple

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)

# (kind, compiled regex). Matched text is replaced wholesale with [REDACTED:kind].
_TOKEN_PATTERNS = [
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    ),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("notion_token", re.compile(r"\b(?:secret|ntn)_[A-Za-z0-9]{30,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
]

_BEARER = re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9._\-~+/]{16,}=*")
_URL_CREDS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z0-9_\-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|auth)[a-z0-9_\-]*)"
    r"(\s*[=:]\s*)(['\"]?)([^\s'\"&,;]{4,})(\3)"
)


def _looks_secret(value: str, quoted: bool) -> bool:
    """Decide whether the value of a ``password=...`` style assignment is a secret.

    Quoted values are always redacted. Unquoted ones must look like a credential
    (long, with a digit or symbol) so that prose such as ``invalid token: expired``
    survives intact and the error stays searchable.
    """
    if quoted:
        return True
    if len(value) < 8:
        return False
    return any(c.isdigit() for c in value) or any(not c.isalnum() for c in value)


def redact(text: str) -> Tuple[str, List[str]]:
    """Return ``(redacted_text, sorted_unique_kinds)``."""
    if not text:
        return text, []
    found: set = set()

    def _sub_const(kind: str):
        def _inner(_m):
            found.add(kind)
            return "[REDACTED:%s]" % kind

        return _inner

    text = _PRIVATE_KEY.sub(_sub_const("private_key"), text)
    for kind, rx in _TOKEN_PATTERNS:
        text = rx.sub(_sub_const(kind), text)

    def _bearer(m):
        found.add("bearer")
        return "%s%s[REDACTED:bearer]" % (m.group(1), m.group(2))

    text = _BEARER.sub(_bearer, text)

    def _url(m):
        found.add("url_credentials")
        return "%s[REDACTED:credentials]@" % m.group(1)

    text = _URL_CREDS.sub(_url, text)

    def _assign(m):
        name, sep, quote, value, _q = m.groups()
        if value.startswith("[REDACTED"):
            return m.group(0)
        if not _looks_secret(value, bool(quote)):
            return m.group(0)
        found.add("secret_assignment")
        return "%s%s%s[REDACTED:secret]%s" % (name, sep, quote, quote)

    text = _ASSIGNMENT.sub(_assign, text)
    return text, sorted(found)
