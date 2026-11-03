"""Error parsing and fingerprinting.

Goal: two occurrences of "the same error" must hash to the same value even when
paths, line numbers, versions, ids and timestamps differ.

Two fingerprints are produced per error:

* ``strict`` - exception type + normalized message (quoted values kept). When the
  message is too short to tell errors apart (e.g. a bare ``NullPointerException``)
  the innermost stack frame is mixed in as well.
* ``loose``  - exception type + message with quoted values, ``{...}`` groups,
  ``pkg@version`` strings and fully-qualified class names blanked out. This groups
  an error *family* (``reading 'map'`` and ``reading 'filter'``).

A ``strict`` hit means "this exact error"; a ``loose`` hit means "similar error".
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# If the normalized message has fewer words than this, it can't distinguish
# errors on its own, so the innermost frame is added to the strict fingerprint.
MIN_INFORMATIVE_WORDS = 4
MAX_FRAMES = 3


@dataclass
class ParsedError:
    kind: str
    exc_type: str
    message: str
    frames: List[str] = field(default_factory=list)


@dataclass
class Fingerprint:
    strict: str
    loose: str
    parsed: ParsedError
    norm_strict: str
    norm_loose: str


# --------------------------------------------------------------------------- parsing

_PY_FRAME = re.compile(r'^\s*File "(?P<file>.*)", line (?P<line>\d+)(?:, in (?P<func>.+))?$')
_PY_EXC = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s?(?P<msg>.*))?$")


def _parse_python(lines: List[str]) -> Optional[ParsedError]:
    starts = [i for i, l in enumerate(lines) if l.startswith("Traceback (most recent call last)")]
    if not starts:
        return None
    frames: List[str] = []
    exc = None
    for line in lines[starts[-1] + 1 :]:  # last traceback = the exception that actually escaped
        m = _PY_FRAME.match(line)
        if m:
            frames.append((m.group("func") or "<module>").strip())
            continue
        if not line.strip() or line.startswith((" ", "\t")):
            continue  # source line / caret marker
        m = _PY_EXC.match(line)
        if m:
            exc = m
        break
    frames.reverse()  # innermost first
    return ParsedError(
        "python",
        exc.group("type") if exc else "Error",
        (exc.group("msg") or "") if exc else "",
        frames[:MAX_FRAMES],
    )


def _parse_spring(lines: List[str]) -> Optional[ParsedError]:
    if not any("APPLICATION FAILED TO START" in l for l in lines):
        return None
    for i, l in enumerate(lines):
        if l.strip() == "Description:":
            for nxt in lines[i + 1 :]:
                if nxt.strip():
                    return ParsedError("spring", "SpringStartupFailure", nxt.strip(), [])
    return ParsedError("spring", "SpringStartupFailure", "", [])


_MVN_ERR = re.compile(r"^\[ERROR\]\s+(?P<file>.+?\.java):\[\d+,\d+\]\s+(?P<msg>.+?)\s*$")
_MVN_SYMBOL = re.compile(r"^\[ERROR\]\s+symbol:\s*(?P<sym>.+?)\s*$")
_MVN_GOAL = re.compile(
    r"Failed to execute goal\s+(?P<goal>[\w.\-]+:[\w.\-]+):[\w.\-]+:[\w\-]+(?:\s+\([^)]*\))?"
    r"\s+on project\s+\S+:\s*(?P<reason>.*)$"
)


def _parse_maven(lines: List[str]) -> Optional[ParsedError]:
    if not any(l.startswith("[ERROR]") for l in lines):
        return None
    text = "\n".join(lines)
    if "COMPILATION ERROR" not in text and "Failed to execute goal" not in text:
        return None
    for i, l in enumerate(lines):
        m = _MVN_ERR.match(l)
        if m:
            msg = m.group("msg")
            for nxt in lines[i + 1 : i + 3]:
                s = _MVN_SYMBOL.match(nxt)
                if s:
                    msg = "%s; symbol: %s" % (msg, s.group("sym"))
                    break
            return ParsedError("maven", "MavenCompileError", msg, [])
    for l in lines:
        m = _MVN_GOAL.search(l)
        if m:
            return ParsedError("maven", "MavenGoalFailure", "%s: %s" % (m.group("goal"), m.group("reason")), [])
    return None


_NPM_CODE = re.compile(r"^npm (?:ERR!|error)\s+code\s+(?P<code>\S+)\s*$")
_NPM_LINE = re.compile(r"^npm (?:ERR!|error)\s?(?P<rest>.*)$")
_NPM_META = re.compile(r"^(syscall|path|errno|code|dest|A complete log)\b")


def _parse_npm(lines: List[str]) -> Optional[ParsedError]:
    for i, l in enumerate(lines):
        m = _NPM_CODE.match(l)
        if not m:
            continue
        message = ""
        for nxt in lines[i + 1 :]:
            n = _NPM_LINE.match(nxt)
            if not n:
                continue
            rest = n.group("rest").strip()
            if not rest or _NPM_META.match(rest):
                continue
            message = rest
            break
        return ParsedError("npm", m.group("code"), message, [])
    return None


_JAVA_HEAD = re.compile(
    r'^\s*(?:Exception in thread "[^"]*"\s+)?(?P<caused>Caused by:\s*)?'
    r"(?P<type>(?:[a-z_]\w*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable))(?::\s?(?P<msg>.*))?\s*$"
)
_JAVA_AT = re.compile(r"^\s*at\s+(?P<fn>[\w.$<>/@]+)\(")


def _parse_java(lines: List[str]) -> Optional[ParsedError]:
    heads = [(i, m) for i, l in enumerate(lines) for m in [_JAVA_HEAD.match(l)] if m]
    if not heads:
        return None
    caused = [h for h in heads if h[1].group("caused")]
    idx, m = caused[-1] if caused else heads[0]  # root cause beats the wrapper exception
    frames: List[str] = []
    skipped = 0
    for line in lines[idx + 1 :]:
        a = _JAVA_AT.match(line)
        if a:
            frames.append(a.group("fn").split("/")[-1])
            if len(frames) == MAX_FRAMES:
                break
        elif re.match(r"^\s*\.\.\.\s+\d+\s+(more|common)", line):
            continue
        elif not frames and skipped < 2:
            skipped += 1  # detail lines such as "Position: 15" can sit between header and frames
        else:
            break
    return ParsedError("java", m.group("type"), (m.group("msg") or "").strip(), frames)


_NODE_HEAD = re.compile(
    r"^\s*(?:Uncaught\s+)?(?:\(node:\d+\)\s+)?(?:UnhandledPromiseRejectionWarning:\s+)?"
    r"(?P<type>(?:[A-Za-z_$][\w$]*)?(?:Error|Exception))(?::\s?(?P<msg>.*))?\s*$"
)
_NODE_AT = re.compile(r"^\s*at\s+(?:async\s+)?(?P<fn>[^\s(]+)\s+(?:\[as [^\]]+\]\s+)?\(")


def _parse_node(lines: List[str]) -> Optional[ParsedError]:
    for i, l in enumerate(lines):
        m = _NODE_HEAD.match(l)
        if not m:
            continue
        frames: List[str] = []
        for line in lines[i + 1 : i + 41]:
            a = _NODE_AT.match(line)
            if a:
                frames.append(a.group("fn"))
                if len(frames) == MAX_FRAMES:
                    break
        return ParsedError("node", m.group("type"), (m.group("msg") or "").strip(), frames)
    return None


_GENERIC_KEY = re.compile(
    r"(?i)\b(error|exception|fatal|failed|failure|cannot|can't|unable|denied|refused|not found|no such|undefined)\b"
)


def _parse_generic(lines: List[str]) -> ParsedError:
    candidates = [l.strip() for l in lines if l.strip()]
    for l in candidates:
        if _GENERIC_KEY.search(l):
            return ParsedError("generic", "Error", l, [])
    return ParsedError("generic", "Error", candidates[0], [])


_PARSERS: List[Callable[[List[str]], Optional[ParsedError]]] = [
    _parse_python,
    _parse_spring,
    _parse_maven,
    _parse_npm,
    _parse_java,
    _parse_node,
]


def parse_error(text: str) -> ParsedError:
    clean = ANSI_RE.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = clean.split("\n")
    if not any(l.strip() for l in lines):
        return ParsedError("empty", "Error", "", [])
    for parser in _PARSERS:
        parsed = parser(lines)
        if parsed:
            return parsed
    return _parse_generic(lines)


# ----------------------------------------------------------------------- normalizing

_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s'\"<>)\]]+")
_WIN_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"<>():,\]]*")
_ROOT_PATH = re.compile(
    r"(?<![\w<>])/(?:home|Users|usr|var|opt|tmp|etc|app|srv|mnt|root|workspace|project|builds?|runner|nix|snap|Library|private)\b"
    r"(?:/[^\s'\"<>():,\]]*)?"
)
_EXT_PATH = re.compile(r"(?<![\w/.:<>@-])(?:[\w@.+\-~]+/)+[\w@.+\-~]+\.[A-Za-z0-9]{1,6}\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_HASH = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{8,}\b", re.I)
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_QUOTED = re.compile(r"""(?<!\w)(?:'[^'\n]{1,80}'|"[^"\n]{1,80}"|`[^`\n]{1,80}`)(?!\w)""")
_BRACES = re.compile(r"\{[^{}\n]*\}")
_PKGVER = re.compile(r"[\w.\-@/]+@[\^~<>=]*\d[\w.\-^~<>=*|]*")
_FQCN = re.compile(r"\b(?:[a-z_]\w*\.){2,}[A-Z][\w$]*")
_NUM = re.compile(r"\b\d+(?:\.\d+)*\b")
_WS = re.compile(r"\s+")


def normalize_message(message: str, loose: bool = False) -> str:
    s = message or ""
    for rx, repl in (
        (_TS, "<ts>"),
        (_UUID, "<uuid>"),
        (_URL, "<url>"),
        (_WIN_PATH, "<path>"),
        (_ROOT_PATH, "<path>"),
        (_EXT_PATH, "<path>"),
        (_HEX, "<hex>"),
        (_HASH, "<hash>"),
        (_IP, "<ip>"),
    ):
        s = rx.sub(repl, s)
    if loose:
        for rx, repl in ((_QUOTED, "<s>"), (_BRACES, "{<s>}"), (_PKGVER, "<pkg>"), (_FQCN, "<class>")):
            s = rx.sub(repl, s)
    s = _NUM.sub("<n>", s)
    return _WS.sub(" ", s).strip().lower()


def _norm_frame(frame: str) -> str:
    return re.sub(r"\d+", "N", frame.split("/")[-1])


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def fingerprint(text: str) -> Fingerprint:
    parsed = parse_error(text)
    norm_strict = normalize_message(parsed.message, loose=False)
    norm_loose = normalize_message(parsed.message, loose=True)
    strict_parts = [parsed.exc_type, norm_strict]
    if len(norm_strict.split()) < MIN_INFORMATIVE_WORDS and parsed.frames:
        strict_parts.append(_norm_frame(parsed.frames[0]))
    return Fingerprint(
        strict=_digest("|".join(strict_parts)),
        loose=_digest("%s|%s" % (parsed.exc_type, norm_loose)),
        parsed=parsed,
        norm_strict=norm_strict,
        norm_loose=norm_loose,
    )
