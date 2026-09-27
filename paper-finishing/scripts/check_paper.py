#!/usr/bin/env python3
"""Deterministic checks for the paper-finishing skill.

Usage:
    python check_paper.py MAIN.tex [--log MAIN.log] [--variant us|uk]
                                   [--todo-macros name1,name2] [--json]
                                   [--state finishing/ [--save]]

Follows \\input/\\include from MAIN.tex, reads the .bib files it names, and
prints findings grouped by the check IDs of ../CHECKS.md as [id] file:line.
Lines marked "hint" are heuristic: confirm them by reading the text.
The id is stable across runs (no line numbers in it). With --state, IDs listed
in finishing/dismissed.md are skipped and findings are compared against the
last saved run; --save writes finishing/state.json. Nothing else is written.
Standard library only.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_PER_CHECK = 60

TITLES = {
    "L1": "Build log",
    "L2": "Labels and references resolve",
    "L3": "Floats referenced",
    "L4": "Draft leftovers and TODOs",
    "L5": "Placeholders",
    "L6": "Non-breaking space before \\cite / \\ref",
    "L7": "Citation mechanics",
    "L8": "Quotes and dashes",
    "L9": "URLs",
    "L10": "No pasted Unicode",
    "S1": "Springer reference names",
    "T2": "Page count",
    "B1": "Shortened bibliography and citation keys",
    "B2": "Duplicate bib entries",
    "B3": "Bib entry completeness",
    "B4": "Preprints",
    "B5": "Bib title capitalization",
    "B6": "Citation order by year",
    "G2": "Spelling variant",
    "G3": "Hyphenation consistency",
    "G4": "Latin abbreviations",
    "G5": "Numbers and units",
    "G6": "Contractions and informal wording",
    "G7": "Sentence openings",
    "C1": "Sections filled",
    "C2": "Paper structure and roadmap paragraph",
    "C3": "Term capitalization consistency",
    "C4": "Abbreviations",
    "C5": "Duplicate footnotes and citations",
    "C6": "Citation integration",
    "F1": "Figure files",
}

# --------------------------------------------------------------------------
# Loading and masking
# --------------------------------------------------------------------------

INPUT_RE = re.compile(r"\\(input|include|subfile)\s*\{([^}]+)\}")
REF_CMDS = ("ref|eqref|pageref|autoref|cref|Cref|vref|Vref|nameref|"
            "cpageref|Cpageref|labelcref|subref")
REF_RE = re.compile(r"\\(" + REF_CMDS + r")\*?\{([^}]*)\}")
CITE_RE = re.compile(
    r"\\([a-zA-Z]*cite[a-zA-Z]*|nocite)\*?((?:\s*\[[^\]]*\]){0,2})\s*\{([^}]*)\}")
TEXTUAL_CITES = {"citet", "citeauthor", "citeyear", "citetitle", "textcite",
                 "Citet", "Citeauthor", "Textcite", "citealt", "citealp",
                 "nocite", "fullcite", "footcite", "supercite"}
TILDE_RE = re.compile(
    r"\\(cite|citep|parencite|autocite|ref|eqref|pageref|cref|Cref|autoref|"
    r"vref|Vref|nameref|cpageref)(?![a-zA-Z])")
LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
HEAD_RE = re.compile(
    r"\\(chapter|section|subsection|subsubsection|paragraph)(\*?)\s*"
    r"(?:\[[^\]]*\])?\s*\{")
LEVELS = {"chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3,
          "paragraph": 4}
FLOAT_ENVS = r"figure|table|algorithm|listing|wrapfigure|wraptable|sidewaysfigure|sidewaystable"
FLOAT_RE = re.compile(r"\\begin\{(" + FLOAT_ENVS + r")(\*?)\}(.*?)\\end\{\1\2\}", re.S)

ABBREV_BEFORE_DOT = re.compile(
    r"(?:\b(?:cf|al|Figs?|Sects?|Secs?|Eqs?|Chaps?|Refs?|pp?|vs|etc|resp|"
    r"approx|No|Nos|Vol|Def|Thm|Prop|Lem|Cor|Dr|Prof|ca|incl|w\.r\.t)|"
    r"e\.g|i\.e)\.$")


def blank(s: str) -> str:
    return re.sub(r"[^\n]", " ", s)


def comment_start(line: str) -> int:
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            return i
        i += 1
    return -1


def strip_comments(raw: str) -> str:
    out = []
    for line in raw.split("\n"):
        i = comment_start(line)
        out.append(line if i < 0 else line[:i] + " " * (len(line) - i))
    return "\n".join(out)


def match_brace(text: str, i: int) -> int:
    """Index of the brace closing the one at text[i], or len(text)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


PROSE_MASKS = [
    re.compile(
        r"\\begin\{(equation|align|gather|multline|eqnarray|displaymath|math|"
        r"flalign|alignat|verbatim|Verbatim|lstlisting|minted|tikzpicture|"
        r"algorithmic|tabular|tabularx|tabulary|longtable|comment|"
        r"thebibliography)(\*?)\}.*?\\end\{\1\2\}", re.S),
    re.compile(r"\$\$.*?\$\$", re.S),
    re.compile(r"(?<!\\)\\\[.*?\\\]", re.S),
    re.compile(r"(?<!\\)\\\(.*?\\\)", re.S),
    re.compile(r"(?<!\\)\$(?:\\.|[^\\$])+\$"),
    re.compile(r"\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?"),
    re.compile(
        r"\\(?:label|" + REF_CMDS + r"|[a-zA-Z]*cite[a-zA-Z]*|nocite|url|href|"
        r"includegraphics|input|include|bibliography|bibliographystyle|"
        r"addbibresource|graphicspath|usepackage|documentclass|hspace|vspace|"
        r"textcolor|color|colorbox|newcommand|renewcommand|setlength|"
        r"lstinputlisting|hypersetup|orcidID|email|thanks|lstset)\*?"
        r"(?:\s*\[[^\]]*\])*(?:\s*\{[^{}]*\})?"),
    re.compile(r"\\[a-zA-Z@]+\*?"),
    re.compile(r"\\[^a-zA-Z\n]"),
]


@dataclass
class Segment:
    flat_start: int
    file: Path
    file_start: int


class Doc:
    def __init__(self, main: Path):
        self.main = main.resolve()
        self.root = self.main.parent
        self.files: dict[Path, str] = {}
        self.line_starts: dict[Path, list[int]] = {}
        self.segments: list[Segment] = []
        self.missing_inputs: list[tuple[int, str]] = []
        self._raw: list[str] = []
        self._nc: list[str] = []
        self._len = 0
        self._flatten(self.main, frozenset())
        self.raw = "".join(self._raw)
        self.nc = "".join(self._nc)
        self._seg_starts = [s.flat_start for s in self.segments]
        m = re.search(r"\\begin\{document\}", self.nc)
        self.body_start = m.end() if m else 0
        m = re.search(r"\\end\{document\}", self.nc)
        self.body_end = m.start() if m else len(self.nc)
        self.preamble = self.nc[: self.body_start]
        t = (blank(self.nc[: self.body_start]) + self.nc[self.body_start: self.body_end]
             + blank(self.nc[self.body_end:]))
        for pat in PROSE_MASKS:
            t = pat.sub(lambda m: blank(m.group(0)), t)
        self.prose = t
        self.prose_nofloat = FLOAT_RE.sub(lambda m: blank(m.group(0)), t)
        m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", self.nc, re.S)
        self.abstract = (m.start(), m.end()) if m else None

    def _emit(self, path: Path, raw: str, nc: str, a: int, b: int) -> None:
        if a >= b:
            return
        self.segments.append(Segment(self._len, path, a))
        self._raw.append(raw[a:b])
        self._nc.append(nc[a:b])
        self._len += b - a

    def _resolve(self, name: str, current: Path) -> Path | None:
        name = name.strip()
        for base in (self.root, current.parent):
            for cand in (base / name, base / (name + ".tex")):
                if cand.is_file():
                    return cand.resolve()
        return None

    def _flatten(self, path: Path, stack: frozenset) -> None:
        raw = path.read_text(encoding="utf-8", errors="replace")
        self.files[path] = raw
        self.line_starts[path] = [0] + [m.end() for m in re.finditer("\n", raw)]
        nc = strip_comments(raw)
        pos = 0
        for m in INPUT_RE.finditer(nc):
            self._emit(path, raw, nc, pos, m.start())
            child = self._resolve(m.group(2), path)
            if child is None or child in stack or child == path:
                if child is None:
                    self.missing_inputs.append((self._len, m.group(2)))
                self._emit(path, raw, nc, m.start(), m.end())
            else:
                self._flatten(child, stack | {path})
            pos = m.end()
        self._emit(path, raw, nc, pos, len(raw))

    def where(self, off: int) -> str:
        i = max(bisect.bisect_right(self._seg_starts, off) - 1, 0)
        seg = self.segments[i]
        foff = seg.file_start + (off - seg.flat_start)
        line = bisect.bisect_right(self.line_starts[seg.file], foff)
        return f"{rel(seg.file, self.root)}:{line}"

    def in_body(self, off: int) -> bool:
        return self.body_start <= off < self.body_end

    def in_abstract(self, off: int) -> bool:
        return bool(self.abstract) and self.abstract[0] <= off < self.abstract[1]

    def uses_package(self, name: str) -> bool:
        return bool(re.search(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\b"
                              + re.escape(name) + r"\b[^}]*\}", self.preamble))


def rel(p: Path, root: Path) -> str:
    try:
        return os.path.relpath(p, root).replace("\\", "/")
    except ValueError:
        return str(p)


def snippet(text: str, a: int, b: int, pad: int = 30) -> str:
    """The match plus whole words around it (about pad/7 on each side). Word-based, so a
    finding's context, and with it its ID, stays stable when nearby text changes length."""
    words = max(2, pad // 7)

    def sep(c: str) -> bool:  # "~" is a space in LaTeX; fixing L6 must not shift the context
        return c.isspace() or c == "~"

    s = a
    for _ in range(words):
        while s > 0 and sep(text[s - 1]):
            s -= 1
        while s > 0 and not sep(text[s - 1]):
            s -= 1
    e = b
    for _ in range(words):
        while e < len(text) and sep(text[e]):
            e += 1
        while e < len(text) and not sep(text[e]):
            e += 1
    return re.sub(r"\s+", " ", text[s:e]).strip()


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def fingerprint(check: str, where: str, msg: str) -> str:
    """Stable finding ID from check, file and the words of the message (with its context).
    Line numbers, counts, punctuation and LaTeX spacing are left out, so the ID survives
    edits elsewhere and small fixes next to the finding."""
    file = re.sub(r":\d+$", "", where)
    norm = " ".join(re.findall(r"[a-z]+", re.sub(r"[\w./-]+:\d+", "", msg).lower()))
    return hashlib.sha1(f"{check}|{file}|{norm}".encode("utf-8")).hexdigest()[:8]


@dataclass
class Finding:
    id: str
    check: str
    where: str
    msg: str
    hint: bool

    def line(self) -> str:
        return f"[{self.id}] {self.where}: {'hint: ' if self.hint else ''}{self.msg}"


class Report:
    def __init__(self) -> None:
        self.items: dict[str, list[Finding]] = defaultdict(list)
        self.infos: dict[str, list[str]] = defaultdict(list)
        self._seen: Counter = Counter()

    def add(self, check: str, where: str, msg: str, hint: bool = False) -> None:
        fid = fingerprint(check, where, msg)
        self._seen[fid] += 1
        if self._seen[fid] > 1:  # identical finding in the same file: number by order
            fid = hashlib.sha1(f"{fid}#{self._seen[fid]}".encode()).hexdigest()[:8]
        self.items[check].append(Finding(fid, check, where, msg, hint))

    def info(self, check: str, msg: str) -> None:
        self.infos[check].append(msg)

    def compare(self, state_dir: Path | None) -> "Result":
        """Drop dismissed findings and compare with the last saved run in state_dir."""
        dismissed: set[str] = set()
        previous: dict[str, dict] = {}
        if state_dir:
            dfile = state_dir / "dismissed.md"
            if dfile.is_file():
                for line in dfile.read_text(encoding="utf-8").split("\n"):
                    if m := re.match(r"\s*[-*]\s*`?([0-9a-f]{8})\b", line):
                        dismissed.add(m.group(1))
            sfile = state_dir / "state.json"
            if sfile.is_file():
                previous = json.loads(sfile.read_text(encoding="utf-8")).get("findings", {})
        res = Result()
        for check in TITLES:
            for f in self.items.get(check, []):
                if f.id in dismissed:
                    res.dismissed += 1
                    continue
                res.open.append(f)
                if previous and f.id not in previous:
                    res.new.add(f.id)
        ids = {f.id for f in res.open}
        res.resolved = {i: v for i, v in previous.items() if i not in ids and i not in dismissed}
        return res

    @staticmethod
    def save(state_dir: Path, res: "Result") -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        data = {"saved": datetime.now().isoformat(timespec="seconds"),
                "findings": {f.id: {"check": f.check, "where": f.where, "msg": f.msg}
                             for f in res.open}}
        (state_dir / "state.json").write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                              encoding="utf-8")

    def print(self, res: "Result") -> None:
        out = sys.stdout
        by_check: dict[str, list[Finding]] = defaultdict(list)
        for f in res.open:
            by_check[f.check].append(f)
        for check in TITLES:
            items, infos = by_check.get(check, []), self.infos.get(check, [])
            if not items and not infos:
                continue
            out.write(f"\n== {check} {TITLES[check]} ({len(items)}) ==\n")
            for line in infos:
                out.write(f"  info: {line}\n")
            for f in items[:MAX_PER_CHECK]:
                out.write(f"  {f.line()}{'  (new)' if f.id in res.new else ''}\n")
            if len(items) > MAX_PER_CHECK:
                out.write(f"  ... and {len(items) - MAX_PER_CHECK} more\n")
        if res.resolved:
            out.write(f"\n== Resolved since the last saved run ({len(res.resolved)}) ==\n")
            for i, v in res.resolved.items():
                out.write(f"  [{i}] {v['check']} {v['where']}: {v['msg']}\n")
        clean = [c for c in TITLES if c not in by_check and c not in self.infos]
        out.write(f"\n{len(res.open)} open findings ({len(res.new)} new), {len(res.resolved)} "
                  f"resolved, {res.dismissed} dismissed. No findings for: {', '.join(clean) or '-'}\n")

    def to_json(self, res: "Result") -> str:
        return json.dumps({
            "findings": [{"id": f.id, "check": f.check, "where": f.where, "msg": f.msg,
                          "hint": f.hint, "new": f.id in res.new} for f in res.open],
            "infos": self.infos, "resolved": res.resolved, "dismissed": res.dismissed,
        }, indent=1, ensure_ascii=False)


@dataclass
class Result:
    open: list = field(default_factory=list)
    new: set = field(default_factory=set)
    resolved: dict = field(default_factory=dict)
    dismissed: int = 0


# --------------------------------------------------------------------------
# Helpers for sentence position
# --------------------------------------------------------------------------

def prev_nonspace(text: str, i: int, stop: int) -> tuple[int, int]:
    """Index of the last non-whitespace char before i and the number of
    newlines skipped on the way."""
    j, nl = i - 1, 0
    while j >= stop and text[j].isspace():
        nl += text[j] == "\n"
        j -= 1
    return j, nl


SENTENCE_START_CMDS = re.compile(
    r"\\(?:chapter|section|subsection|subsubsection|paragraph|caption|footnote|"
    r"item|label|maketitle|begin|end|keywords|title|abstract)\*?"
    r"(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})?\s*\{?\s*$")


def is_sentence_start(text: str, i: int, stop: int) -> bool:
    j, nl = prev_nonspace(text, i, stop)
    if j < stop or nl >= 2:
        return True
    c = text[j]
    if c in ".!?":
        return not ABBREV_BEFORE_DOT.search(text[max(j - 12, 0): j + 1])
    return bool(SENTENCE_START_CMDS.search(text[max(j - 200, 0): j + 1]))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_log(log: Path | None, rep: Report) -> None:
    if not log or not log.is_file():
        rep.info("L1", "no .log found; build the paper and pass --log")
        return
    lines = log.read_text(encoding="utf-8", errors="replace").split("\n")
    joined, buf = [], ""
    for line in lines:  # TeX wraps log lines at 79 chars
        buf += line
        if len(line) != 79:
            joined.append(buf)
            buf = ""
    joined.append(buf)
    logname = log.name
    for k, line in enumerate(joined):
        if line.startswith("!"):
            rep.add("L1", logname, f"error: {line[:160]}")
        elif m := re.search(r"(Reference|Citation) `([^']*)' on page \S+ undefined", line):
            rep.add("L1", logname, f"undefined {m.group(1).lower()} '{m.group(2)}'")
        elif m := re.search(r"Label `([^']*)' multiply defined", line):
            rep.add("L1", logname, f"label '{m.group(1)}' multiply defined")
        elif m := re.search(r"Overfull \\[hv]box \((\d+(?:\.\d+)?)pt too \w+\)(.*)", line):
            if float(m.group(1)) >= 1.0:
                rep.add("L1", logname, f"overfull box {m.group(1)}pt{m.group(2)}")
        elif m := re.search(r"File `([^']*)' not found", line):
            rep.add("L1", logname, f"file not found: {m.group(1)}")
        elif m := re.search(r"Output written on (.*?) \((\d+) pages?", line):
            rep.info("T2", f"{m.group(1)}: {m.group(2)} pages (from log)")
        elif "Warning" in line and "undefined" in line and "There were" not in line:
            rep.add("L1", logname, line.strip()[:160])


def check_refs(doc: Doc, rep: Report) -> tuple[dict, dict]:
    labels: dict[str, list[int]] = defaultdict(list)
    for m in LABEL_RE.finditer(doc.nc):
        labels[m.group(1).strip()].append(m.start())
    for m in re.finditer(r"\\(?:begin\{lstlisting\}|lstinputlisting)\s*\[([^\]]*)\]", doc.nc):
        if lm := re.search(r"label\s*=\s*\{?([^,}\]]+)", m.group(1)):
            labels[lm.group(1).strip()].append(m.start())
    refs: dict[str, list[int]] = defaultdict(list)
    for m in REF_RE.finditer(doc.nc):
        if not doc.in_body(m.start()):
            continue
        for key in m.group(2).split(","):
            key = key.strip()
            if key and "#" not in key:
                refs[key].append(m.start())
    for key, offs in labels.items():
        if len(offs) > 1:
            rep.add("L2", doc.where(offs[1]), f"label '{key}' defined {len(offs)} times "
                    f"(first at {doc.where(offs[0])})")
    for key, offs in refs.items():
        if key not in labels:
            rep.add("L2", doc.where(offs[0]), f"reference to undefined label '{key}'")
    for off, name in doc.missing_inputs:
        rep.add("L2", doc.where(off), f"\\input file not found: {name}")
    return labels, refs


def check_floats(doc: Doc, labels: dict, refs: dict, rep: Report) -> None:
    for m in FLOAT_RE.finditer(doc.nc):
        if not doc.in_body(m.start()):
            continue
        env = m.group(1) + m.group(2)
        flabels = LABEL_RE.findall(m.group(3))
        if not flabels:
            rep.add("L3", doc.where(m.start()), f"{env} has no \\label and cannot be referenced")
            continue
        for key in flabels:
            key = key.strip()
            if key not in refs:
                rep.add("L3", doc.where(m.start()), f"{env} '{key}' is never referenced")
            elif min(refs[key]) > m.start():
                rep.add("L3", doc.where(m.start()),
                        f"{env} '{key}' appears in the source before its first reference "
                        f"({doc.where(min(refs[key]))}); check its position in the PDF", hint=True)


NOTE_CMDS = ["todo", "missingfigure", "fxnote", "fxwarning", "fxerror", "fxfatal",
             "fixme", "FIXME", "TODO", "hl", "sout", "st", "colorbox", "marginpar"]


def check_leftovers(doc: Doc, todo_macros: list[str], rep: Report) -> None:
    pre = doc.preamble
    # Author note macros defined in the preamble, e.g. \newcommand{\till}[1]{\textcolor{red}{#1}}
    detected = set(todo_macros)
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?([^\n]*)", pre):
        if re.search(r"\\(?:todo|textcolor|color|hl|marginpar|fxnote|colorbox|sout)\b", m.group(2)):
            detected.add(m.group(1))
    for m in re.finditer(r"\\def\s*\\([A-Za-z@]+)([^\n]*)", pre):
        if re.search(r"\\(?:todo|textcolor|color|hl|marginpar)\b", m.group(2)):
            detected.add(m.group(1))
    if detected - set(todo_macros):
        rep.info("L4", "note macros detected in preamble: "
                 + ", ".join("\\" + n for n in sorted(detected - set(todo_macros))))
    cmds = sorted(set(NOTE_CMDS) | detected, key=len, reverse=True)
    pats = [
        (re.compile(r"\\(" + "|".join(map(re.escape, cmds)) + r")(?![a-zA-Z@])"), "note/markup command"),
        (re.compile(r"\b(TODO|FIXME|TBD|TBA|XXX+)\b"), "marker"),
        (re.compile(r"\?\?+"), "marker"),
        (re.compile(r"\\(?:textcolor|color)\s*\{(red|blue|magenta|orange|violet|purple|cyan|green)\}"),
         "colored text"),
    ]
    body = doc.nc
    for pat, what in pats:
        for m in pat.finditer(body):
            if doc.in_body(m.start()):
                rep.add("L4", doc.where(m.start()), f"{what}: {snippet(body, m.start(), m.end())}")
    # Markers only inside comments (not rendered, but still leftovers)
    for m in re.finditer(r"\b(TODO|FIXME|TBD)\b", doc.raw):
        if doc.in_body(m.start()) and doc.nc[m.start()] == " ":
            rep.add("L4", doc.where(m.start()), f"{m.group(1)} in a comment", hint=True)
    # Preamble state
    dc = re.search(r"\\documentclass\s*\[([^\]]*)\]", pre)
    if dc and re.search(r"\b(draft|showframe)\b", dc.group(1)):
        rep.add("L4", doc.where(dc.start()), f"\\documentclass options contain '{dc.group(1)}'")
    for pkg in ("showframe", "lineno", "todonotes", "fixme", "changes"):
        if m := re.search(r"\\usepackage\s*(\[[^\]]*\])?\s*\{" + pkg + r"\}", pre):
            if pkg in ("todonotes", "fixme", "changes") and m.group(1) and re.search(
                    r"disable|final", m.group(1)):
                continue
            rep.add("L4", doc.where(m.start()), f"package '{pkg}' still active", hint=pkg == "lineno")
    # Commented-out text blocks in the body
    lines = doc.raw[doc.body_start: doc.body_end].split("\n")
    off = doc.body_start
    run_start, run_words = None, 0
    for line in lines:
        is_comment = line.strip().startswith("%")
        if is_comment:
            if run_start is None:
                run_start, run_words = off, 0
            run_words += len(re.findall(r"[A-Za-z]{3,}", line))
        else:
            if run_start is not None and run_words >= 15:
                rep.add("L4", doc.where(run_start), f"commented-out text block (~{run_words} words)",
                        hint=True)
            run_start = None
        off += len(line) + 1


def check_placeholders(doc: Doc, bib: list, rep: Report) -> None:
    pats = [
        r"\\(?:url|href)\s*\{\s*\}",
        r"\\(?:url|href)\s*\{[^}]*(?:example\.(?:com|org)|TODO|xxx|placeholder|\.\.\.|<[^>]*>)[^}]*\}",
        r"\\[a-zA-Z]*cite[a-zA-Z]*\s*\{\s*\}",
        r"\\[a-zA-Z]*cite[a-zA-Z]*\s*\{[^}]*(?:\?|TODO|todo|xxx|XXX|placeholder|citation)[^}]*\}",
        r"\[\s*(?:\?|cite|ref|citation|url|link)\s*\]",
        r"\(\s*\?\s*\)",
        r"(?i:citation needed|lorem ipsum)",
        r"\b(?:CITE|CITATION|LINK)\b",
        r"<\s*(?:url|link|cite|ref)\s*>",
    ]
    for p in pats:
        for m in re.finditer(p, doc.nc):
            if doc.in_body(m.start()):
                rep.add("L5", doc.where(m.start()), f"placeholder: {snippet(doc.nc, m.start(), m.end())}")
    for e in bib:
        for name, value in e.fields.items():
            if re.search(r"\bTODO\b|\bxxx\b|placeholder|example\.com", value, re.I):
                rep.add("L5", e.where, f"bib entry '{e.key}' field '{name}' looks like a placeholder")


def check_tilde_and_cites(doc: Doc, rep: Report) -> None:
    t = doc.nc
    for m in TILDE_RE.finditer(t):
        i = m.start()
        if not doc.in_body(i) or not t[i - 1].isspace():
            continue
        j, nl = prev_nonspace(t, i, doc.body_start)
        if j < doc.body_start or nl >= 2 or t[j] in "{[(&~/-":
            continue
        head = t[max(j - 80, 0): j + 1]
        if re.search(r"\\[a-zA-Z@]+\*?$|\\\\$|\\[a-zA-Z]*cite[a-zA-Z]*\{[^}]*\}$", head):
            continue  # after a command, or a second citation (reported by L7)
        if t[j] in ".,;:" and not ABBREV_BEFORE_DOT.search(t[max(j - 12, 0): j + 1]):
            continue  # reported as punctuation issue below
        if is_sentence_start(t, i, doc.body_start):
            continue
        word = re.search(r"(\S+)$", t[max(j - 20, 0): j + 1]).group(1)
        rep.add("L6", doc.where(i), f"'{word} \\{m.group(1)}' -> '{word}~\\{m.group(1)}': "
                f"{snippet(t, i, m.end(), 14)}")
    for m in CITE_RE.finditer(t):
        cmd = m.group(1)
        if cmd in TEXTUAL_CITES or not doc.in_body(m.start()):
            continue
        j, nl = prev_nonspace(t, m.start(), doc.body_start)
        after = t[m.end(): m.end() + 40]
        nxt = after.lstrip()[:1]
        if nl < 2 and j >= doc.body_start and t[j] in ".,;:" and not ABBREV_BEFORE_DOT.search(
                t[max(j - 12, 0): j + 1]):
            if nxt.islower():
                rep.add("C6", doc.where(m.start()),
                        f"citation used as sentence part: {snippet(t, m.start(), m.end())}")
            else:
                rep.add("L7", doc.where(m.start()),
                        f"citation after '{t[j]}'; place it before the punctuation: "
                        f"{snippet(t, m.start(), m.end())}")
        elif (nl >= 2 or j < doc.body_start) and nxt.islower():
            rep.add("C6", doc.where(m.start()),
                    f"paragraph starts with a citation: {snippet(t, m.start(), m.end())}")
    for m in re.finditer(r"\\(cite|citep|parencite|autocite)\{[^}]*\}(?:[\s~,;]|and)*\\\1\{", t):
        if doc.in_body(m.start()):
            rep.add("L7", doc.where(m.start()),
                    f"consecutive citations; merge into one \\{m.group(1)}{{a,b}}: "
                    f"{snippet(t, m.start(), m.end(), 5)}")
    for m in re.finditer(r"\b(?:[Ii]n|[Bb]y|[Ss]ee|[Oo]f|[Ff]rom)(?:\s+|~)\\(?:cite|citep)\{", t):
        if doc.in_body(m.start()):
            rep.add("C6", doc.where(m.start()),
                    f"citation used as a noun: {snippet(t, m.start(), m.end())}", hint=True)


def check_quotes_dashes(doc: Doc, rep: Report) -> None:
    p = doc.prose
    for m in re.finditer(r'"[^"\n]{0,80}"?', p):
        rep.add("L8", doc.where(m.start()), f"straight double quotes; use ``...'': "
                f"{snippet(p, m.start(), m.end(), 10)}")
    for m in re.finditer(r"(?<![\w.$\\-])(\d+)\s*-\s*(\d+)(?![\w-]|\.\d)", p):
        rep.add("L8", doc.where(m.start()), f"range with hyphen '{m.group(0)}'; use '--'")
    for m in re.finditer(r"(?<=\w)[ \t]+-[ \t]+(?=\w)", p):
        rep.add("L8", doc.where(m.start()), f"spaced hyphen used as dash: {snippet(p, m.start(), m.end())}")
    em = len(re.findall(r"---", p))
    en_spaced = len(re.findall(r"(?<=\w)\s--\s(?=\w)", p))
    if em and en_spaced:
        rep.add("L8", "-", f"mixed dash styles: {em}x '---' and {en_spaced}x spaced ' -- '", hint=True)


UNICODE_MAP = {
    "—": "---", "–": "--", "‒": "--", "‐": "-", "‑": "-",
    "−": "$-$", "“": "``", "”": "''", "„": ",,", "‘": "`",
    "’": "'", "«": "\\guillemotleft{}", "»": "\\guillemotright{}",
    "…": "\\ldots{}", " ": "~", " ": "\\,", " ": "\\,", " ": " ",
    " ": " ", "​": "(delete)", "‌": "(delete)", "‍": "(delete)",
    "⁠": "(delete)", "﻿": "(delete)", "­": "(delete)",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "×": "$\\times$", "±": "$\\pm$", "≤": "$\\leq$", "≥": "$\\geq$",
    "≠": "$\\neq$", "≈": "$\\approx$", "→": "$\\rightarrow$",
    "←": "$\\leftarrow$", "⇒": "$\\Rightarrow$", "↔": "$\\leftrightarrow$",
    "°": "$^\\circ$", "µ": "$\\mu$", "μ": "$\\mu$", "·": "$\\cdot$",
    "•": "\\textbullet{}", "ß": "{\\ss}", "ø": "{\\o}", "Ø": "{\\O}",
    "æ": "{\\ae}", "Æ": "{\\AE}", "ł": "{\\l}", "Ł": "{\\L}",
    "©": "\\copyright{}", "®": "\\textregistered{}", "™": "\\texttrademark{}",
    "§": "\\S{}", "€": "\\euro{}", "′": "$'$", "∞": "$\\infty$",
}
ACCENTS = {"̀": "`", "́": "'", "̂": "^", "̈": '"', "̃": "~",
           "̧": "c", "̌": "v", "̊": "r", "̄": "=", "̆": "u",
           "̋": "H", "̨": "k"}


def unicode_replacement(ch: str) -> str | None:
    if ch in UNICODE_MAP:
        return UNICODE_MAP[ch]
    base, *marks = unicodedata.normalize("NFD", ch)
    if marks and base.isascii() and len(marks) == 1 and marks[0] in ACCENTS:
        acc = ACCENTS[marks[0]]
        base = {"i": "\\i", "j": "\\j"}.get(base, base)
        return f"{{\\{acc}{base}}}" if acc in "`'^\"~=" else f"\\{acc}{{{base}}}"
    return None


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F
            or 0x1F1E6 <= o <= 0x1F1FF)


def unicode_finding(ch: str) -> str:
    name = unicodedata.name(ch, f"U+{ord(ch):04X}")
    if is_emoji(ch):
        return f"emoji/pictograph {name}; remove"
    repl = unicode_replacement(ch)
    if repl:
        return f"Unicode {name} -> {repl}"
    return f"Unicode {name} (U+{ord(ch):04X}); replace with a LaTeX command or remove"


def check_unicode(doc: Doc, bibs: list[Path], rep: Report) -> None:
    """Every non-ASCII character outside comments, in the sources and the used .bib files."""
    counts: Counter = Counter()
    for m in re.finditer(r"[^\x00-\x7f]", doc.nc):
        counts[m.group(0)] += 1
        rep.add("L10", doc.where(m.start()), f"{unicode_finding(m.group(0))}: "
                f"{snippet(doc.nc, m.start(), m.end(), 20)}")
    for b in bibs:
        text = b.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.split("\n"), 1):
            for ch in dict.fromkeys(re.findall(r"[^\x00-\x7f]", line)):
                counts[ch] += 1
                rep.add("L10", f"{rel(b, doc.root)}:{i}", unicode_finding(ch))
    if counts:
        rep.info("L10", "characters: " + ", ".join(
            f"{unicodedata.name(c, hex(ord(c)))} ({n}x)" for c, n in counts.most_common()))


def footnotes(doc: Doc) -> list[tuple[int, str]]:
    out = []
    for m in re.finditer(r"\\footnote(?:text)?\s*(?:\[[^\]]*\])?\s*\{", doc.nc):
        if doc.in_body(m.start()):
            end = match_brace(doc.nc, m.end() - 1)
            out.append((m.start(), doc.nc[m.end(): end]))
    return out


def check_urls(doc: Doc, rep: Report) -> None:
    for m in re.finditer(r"https?://\S+|\bwww\.\S+", doc.prose):
        rep.add("L9", doc.where(m.start()), f"bare URL; wrap in \\url{{}}: {m.group(0)[:60]}")
    for off, text in footnotes(doc):
        if re.search(r"\\(?:url|href)\b", text) and not re.search(
                r"accessed|last visited|retrieved|last access|visited on", text, re.I):
            flat = re.sub(r"\s+", " ", text)
            rep.add("L9", doc.where(off), f"footnote URL without access date: {flat[:80]}")


SPRINGER_RE = re.compile(
    r"(?<![A-Za-z\\])(Figures?|Figs?\.|Sections?|Sects?\.|Secs?\.|Equations?|Eqs?\.|"
    r"Chapters?|Chaps?\.|Tables?|Tabs?\.)(?=(?:~|\s)*(?:\\(?:ref|eqref|subref)(?![a-zA-Z])|\(?\d))",
    re.I)
SPRINGER_FORMS = {  # stem -> (singular full, plural full, singular abbr, plural abbr)
    "fig": ("Figure", "Figures", "Fig.", "Figs."),
    "sec": ("Section", "Sections", "Sect.", "Sects."),
    "equ": ("Equation", "Equations", "Eq.", "Eqs."),
    "eq.": ("Equation", "Equations", "Eq.", "Eqs."),
    "eqs": ("Equation", "Equations", "Eq.", "Eqs."),
    "cha": ("Chapter", "Chapters", "Chap.", "Chaps."),
    "tab": ("Table", "Tables", "Table", "Tables"),
}


def check_springer(doc: Doc, rep: Report) -> None:
    t = doc.nc
    for m in SPRINGER_RE.finditer(t):
        if not doc.in_body(m.start()):
            continue
        word = m.group(1)
        forms = SPRINGER_FORMS.get(word[:3].lower())
        if not forms:
            continue
        plural = word.lower().rstrip(".").endswith("s")
        start = is_sentence_start(t, m.start(), doc.body_start)
        expected = forms[1 if plural else 0] if start else forms[3 if plural else 2]
        if word != expected:
            pos = "sentence start" if start else "inside a sentence"
            rep.add("S1", doc.where(m.start()), f"'{word}' -> '{expected}' ({pos}): "
                    f"{snippet(t, m.start(), m.end())}")
    if doc.uses_package("cleveref"):
        wanted = {"figure": ("Fig.", "Figs."), "section": ("Sect.", "Sects."),
                  "equation": ("Eq.", "Eqs."), "table": ("Table", "Tables")}
        if re.search(r"\\chapter\b", doc.nc):
            wanted["chapter"] = ("Chap.", "Chaps.")
        defined = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(
            r"\\crefname\s*\{(\w+)\}\s*\{([^}]*)\}\s*\{([^}]*)\}", doc.preamble)}
        for env, forms in wanted.items():
            if defined.get(env) != forms:
                rep.add("S1", "preamble", f"cleveref: set \\crefname{{{env}}}{{{forms[0]}}}"
                        f"{{{forms[1]}}} (found {defined.get(env)})")
        for m in re.finditer(r"\\(cref|Cref)(?![a-zA-Z])", t):
            if not doc.in_body(m.start()):
                continue
            start = is_sentence_start(t, m.start(), doc.body_start)
            if start and m.group(1) == "cref":
                rep.add("S1", doc.where(m.start()), "\\cref at sentence start -> \\Cref")
            elif not start and m.group(1) == "Cref":
                rep.add("S1", doc.where(m.start()), "\\Cref inside a sentence -> \\cref")
    for m in re.finditer(r"\\autoref(?![a-zA-Z])", t):
        if doc.in_body(m.start()):
            rep.add("S1", doc.where(m.start()),
                    "\\autoref prints full names ('Figure'); check it matches the Springer form",
                    hint=True)


# ---------------------------------------------------------------- bibliography

@dataclass
class BibEntry:
    type: str
    key: str
    fields: dict[str, str]
    where: str


def parse_bib_value(s: str, i: int) -> tuple[str, int]:
    parts = []
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        c = s[i]
        if c == "{":
            end = match_brace(s, i)
            parts.append(s[i + 1: end])
            i = end + 1
        elif c == '"':
            j = i + 1
            depth = 0
            while j < n and not (s[j] == '"' and depth == 0 and s[j - 1] != "\\"):
                depth += (s[j] == "{") - (s[j] == "}")
                j += 1
            parts.append(s[i + 1: j])
            i = j + 1
        else:
            m = re.compile(r"[^\s,#}]+").match(s, i)
            if not m:
                break
            parts.append(m.group(0))
            i = m.end()
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


def parse_bib(path: Path, root: Path) -> list[BibEntry]:
    text = path.read_text(encoding="utf-8", errors="replace")
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    entries = []
    pos = 0
    head = re.compile(r"@\s*(\w+)\s*\{")
    field_re = re.compile(r"\s*,?\s*([\w:.-]+)\s*=\s*")
    while m := head.search(text, pos):
        end = match_brace(text, m.end() - 1)
        typ = m.group(1).lower()
        pos = end + 1
        if typ in ("comment", "preamble", "string"):
            continue
        body = text[m.end(): end]
        key, _, rest = body.partition(",")
        fields: dict[str, str] = {}
        i = 0
        while fm := field_re.match(rest, i):
            value, i = parse_bib_value(rest, fm.end())
            fields[fm.group(1).lower()] = value.strip()
        line = bisect.bisect_right(line_starts, m.start())
        entries.append(BibEntry(typ, key.strip(), fields, f"{rel(path, root)}:{line}"))
    return entries


def bib_files(doc: Doc) -> list[Path]:
    out = []
    for m in re.finditer(r"\\bibliography\s*\{([^}]+)\}", doc.nc):
        for name in m.group(1).split(","):
            name = name.strip()
            p = doc.root / (name if name.endswith(".bib") else name + ".bib")
            out.append(p)
    for m in re.finditer(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", doc.nc):
        out.append(doc.root / m.group(1).strip())
    return out


REQUIRED = {
    "article": [("author",), ("title",), ("journal", "journaltitle"), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "conference": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "incollection": [("author",), ("title",), ("booktitle",), ("publisher",), ("year", "date")],
    "book": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "phdthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "mastersthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "techreport": [("author",), ("title",), ("institution",), ("year", "date")],
    "misc": [("author", "organization", "editor"), ("title",), ("year", "date", "urldate")],
    "online": [("author", "organization", "editor"), ("title",), ("url",), ("urldate",)],
}
PREPRINT_RE = re.compile(r"arxiv|\bcorr\b|biorxiv|medrxiv|ssrn|techrxiv|openreview|preprint|"
                         r"abs/\d{4}\.\d{4,5}", re.I)


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def unprotected_caps(title: str) -> list[str]:
    title = title.strip()
    if title.startswith("{") and match_brace(title, 0) == len(title) - 1:
        return []
    words, depth, cur, protected = [], 0, "", False
    for c in title + " ":
        if c == "{":
            depth += 1
            protected = True
        elif c == "}":
            depth -= 1
        elif c.isspace() and depth == 0:
            if cur and not protected:
                words.append(cur)
            cur, protected = "", False
        else:
            cur += c
    out = []
    for w in words:
        core = re.sub(r"^[^\w]+|[^\w]+$", "", w)
        if len(core) > 1 and any(ch.isupper() for ch in core[1:]) and "\\" not in core:
            out.append(core)
    return out


def needed_keys(cited: dict, by_key: dict) -> set[str]:
    """Cited keys plus the crossref targets they pull in (JabRef's AUX export does the same)."""
    keys = set(cited)
    todo = list(keys)
    while todo:
        e = by_key.get(todo.pop())
        ref = e.fields.get("crossref", "").strip() if e else ""
        if ref and ref not in keys:
            keys.add(ref)
            todo.append(ref)
    return keys


def check_short_bib(doc: Doc, cited: dict, by_key: dict, bibs: list[Path], missing: list,
                    rep: Report) -> None:
    """The paper must use a shortened .bib built by JabRef from the .aux file (Tools > New
    sublibrary based on AUX file), holding exactly the cited entries, not the full library."""
    if re.search(r"\\nocite\s*\{\s*\*\s*\}", doc.nc):
        rep.add("B1", "-", "\\nocite{*} pulls in the whole .bib; remove it and use the shortened .bib")
    needed = needed_keys(cited, by_key)
    extra = [k for k in by_key if k not in needed]
    names = ", ".join(rel(b, doc.root) for b in bibs)
    if extra and len(extra) >= len(needed):
        rep.add("B1", names, f"BLOCKING: the paper uses the full library ({len(by_key)} entries, "
                f"{len(needed)} needed), not a shortened .bib; create one with JabRef from the "
                f".aux file and point \\bibliography to it")
    elif extra:
        rep.add("B1", names, f"shortened .bib is stale: {len(extra)} entries are no longer cited "
                f"({', '.join(extra[:15])}{' ...' if len(extra) > 15 else ''}); regenerate it "
                f"from the current .aux")
    if missing and not extra:
        rep.add("B1", names, f"shortened .bib is stale: {len(missing)} cited keys are missing; "
                f"regenerate it from the current .aux")
    # Other .bib files near the paper: a shortened version that exists but is not used
    used = {b.resolve() for b in bibs}
    for cand in sorted(set(doc.root.glob("*.bib")) | set(doc.root.glob("*/*.bib"))):
        if cand.resolve() in used:
            continue
        try:
            keys = {e.key for e in parse_bib(cand, doc.root)}
        except OSError:
            continue
        if keys and needed <= keys and len(keys) < len(by_key):
            rep.add("B1", rel(cand, doc.root), f"contains all {len(needed)} needed entries "
                    f"({len(keys)} total) but is not used; is this the shortened .bib?")
        else:
            rep.info("B1", f"other .bib file {rel(cand, doc.root)}: {len(keys)} entries, "
                           f"{len(needed & keys)} of {len(needed)} needed")


def entry_year(key: str, by_key: dict, depth: int = 0) -> int | None:
    e = by_key.get(key)
    if not e:
        return None
    if m := re.search(r"\d{4}", e.fields.get("year", "") or e.fields.get("date", "")):
        return int(m.group(0))
    parent = e.fields.get("crossref", "").strip()
    return entry_year(parent, by_key, depth + 1) if parent and depth < 3 else None


def check_cite_order(doc: Doc, by_key: dict, rep: Report) -> None:
    """Keys inside one citation command are ordered by publication year, earliest first.
    Keys with the same year keep their relative order."""
    for m in CITE_RE.finditer(doc.nc):
        if m.group(1) == "nocite" or not doc.in_body(m.start()):
            continue
        keys = [k.strip() for k in m.group(3).split(",") if k.strip()]
        if len(keys) < 2 or any(k not in by_key for k in keys):
            continue  # unknown keys are reported by B1
        years = [entry_year(k, by_key) for k in keys]
        if None in years:
            nokey = keys[years.index(None)]
            rep.add("B6", doc.where(m.start()), f"cannot order \\{m.group(1)}{{{','.join(keys)}}}: "
                    f"'{nokey}' has no year")
            continue
        ordered = [k for _, k in sorted(zip(years, keys), key=lambda t: t[0])]
        if ordered != keys:
            shown = ", ".join(f"{k} ({y})" for k, y in zip(keys, years))
            rep.add("B6", doc.where(m.start()), f"citations not ordered by year: {shown} -> "
                    f"\\{m.group(1)}{{{','.join(ordered)}}}")


def check_bib(doc: Doc, cited: dict, rep: Report, entries: list[BibEntry],
              bibs: list[Path]) -> None:
    by_key = {}
    for e in entries:
        if e.key in by_key:
            rep.add("B2", e.where, f"key '{e.key}' defined twice (also {by_key[e.key].where})")
        by_key[e.key] = e
    missing = [k for k in cited if k not in by_key]
    for key in missing:
        rep.add("B1", doc.where(cited[key][0]), f"cited key '{key}' not found in any .bib file")
    check_short_bib(doc, cited, by_key, bibs, missing, rep)
    check_cite_order(doc, by_key, rep)
    used = [by_key[k] for k in cited if k in by_key]
    groups: dict[str, list[BibEntry]] = defaultdict(list)
    for e in used:
        if t := norm_title(e.fields.get("title", "")):
            groups["t:" + t].append(e)
        if doi := e.fields.get("doi", "").lower().strip():
            groups["d:" + doi].append(e)
    seen = set()
    for g in groups.values():
        keys = tuple(sorted({e.key for e in g}))
        if len(keys) > 1 and keys not in seen:
            seen.add(keys)
            rep.add("B2", g[0].where, f"same paper under several keys: {', '.join(keys)}")
    for e in used:
        f = e.fields
        if "crossref" in f:
            continue
        for alts in REQUIRED.get(e.type, []):
            if not any(f.get(a) for a in alts):
                rep.add("B3", e.where, f"'{e.key}' (@{e.type}) lacks {'/'.join(alts)}")
        if e.type in ("article", "inproceedings", "incollection", "conference") and not (
                f.get("pages") or f.get("doi")):
            rep.add("B3", e.where, f"'{e.key}' has neither pages nor doi", hint=True)
        if any(PREPRINT_RE.search(v) for k, v in f.items() if k not in ("abstract", "file")):
            rep.add("B4", e.where, f"preprint '{e.key}' ({f.get('year', '?')}): "
                    f"{re.sub(r'[{}]', '', f.get('title', ''))[:90]}")
        caps = unprotected_caps(f.get("title", ""))
        if caps:
            rep.add("B5", e.where, f"'{e.key}' title: protect {', '.join(caps)} with braces")


# ---------------------------------------------------------------- language

US_UK = [  # (American, British) full-word patterns
    (r"behavior(s|al|ally)?", r"behaviour(s|al|ally)?"),
    (r"color(s|ed|ing|ful|less)?", r"colour(s|ed|ing|ful|less)?"),
    (r"favor(s|ed|ing|able|ite|ites)?", r"favour(s|ed|ing|able|ite|ites)?"),
    (r"labor(s|ed|ing)?", r"labour(s|ed|ing)?"),
    (r"neighbor(s|ing|hood|hoods)?", r"neighbour(s|ing|hood|hoods)?"),
    (r"honor(s|ed|ing|able)?", r"honour(s|ed|ing|able)?"),
    (r"center(s|ed|ing)?", r"centre(s|d)?"), (r"fiber(s)?", r"fibre(s)?"),
    (r"model(ed|ing|er|ers)", r"modell(ed|ing|er|ers)"), (r"label(ed|ing)", r"labell(ed|ing)"),
    (r"travel(ed|ing|er|ers)", r"travell(ed|ing|er|ers)"),
    (r"signal(ed|ing)", r"signall(ed|ing)"), (r"cancel(ed|ing)", r"cancell(ed|ing)"),
    (r"catalog(s)?", r"catalogue(s)?"), (r"defense(s)?", r"defence(s)?"),
    (r"offense(s)?", r"offence(s)?"), (r"gray(s|ish)?", r"grey(s|ish)?"),
    (r"fulfill(s|ment)?", r"fulfil(s|ment)?"), (r"judgment(s)?", r"judgement(s)?"),
    (r"acknowledgment(s)?", r"acknowledgement(s)?"), (r"artifact(s)?", r"artefact(s)?"),
    (r"toward", r"towards"), (r"afterward", r"afterwards"), (r"aluminum", r"aluminium"),
]
ISE_ONLY = set("""advertise advise apprise appraise arise braise chastise circumcise comprise
compromise concise demise despise devise disguise enterprise excise exercise expertise franchise
improvise incise merchandise noise otherwise paradise poise praise precise imprecise premise
promise raise revise rise sunrise supervise surmise surprise televise treatise wise likewise
clockwise counterclockwise anticlockwise cruise bruise guise reprise valise anise porpoise
tortoise turquoise mortise prise chemise cerise""".split())
IZE_ONLY = set("size seize prize capsize maize resize downsize oversize upsize baize assize "
               "outsize undersize midsize".split())
SAME_IN_BOTH = {"analyses", "crises", "paralyses", "catalyses"}  # plural nouns


def fixed_spelling(base: str, words: set[str]) -> bool:
    # Long entries also match as suffix ("unsupervise"); short ones only exactly,
    # since e.g. "rise" would swallow "categorise".
    return base in words or any(base.endswith(w) for w in words if len(w) >= 7)


def uk_form(word: str) -> str | None:
    """Return 'us'/'uk' for words whose spelling marks the variant."""
    w = word.lower()
    for us, uk in US_UK:
        if re.fullmatch(uk, w):
            return "uk"
        if re.fullmatch(us, w):
            return "us"
    m = re.fullmatch(r"([a-z]+)([iy])([sz])(e|es|ed|ing|er|ers|ation|ations|ational)", w)
    if m and w not in SAME_IN_BOTH:
        stem = m.group(1) + m.group(2)
        if (fixed_spelling(stem + "se", ISE_ONLY) or fixed_spelling(stem + "ze", IZE_ONLY)
                or len(m.group(1)) < 2):
            return None
        return "uk" if m.group(3) == "s" else "us"
    return None


def check_language(doc: Doc, variant: str | None, rep: Report) -> None:
    p = doc.prose
    body = p[doc.body_start: doc.body_end]
    # G2 spelling variant
    occ: dict[str, list[tuple[int, str]]] = {"us": [], "uk": []}
    for m in re.finditer(r"[A-Za-z]+", p):
        if v := uk_form(m.group(0)):
            occ[v].append((m.start(), m.group(0)))
    n_us, n_uk = len(occ["us"]), len(occ["uk"])
    rep.info("G2", f"American spellings: {n_us}, British spellings: {n_uk}")
    target = variant or ("us" if n_us >= n_uk else "uk")
    other = "uk" if target == "us" else "us"
    for off, w in occ[other]:
        rep.add("G2", doc.where(off), f"'{w}' is {'British' if other == 'uk' else 'American'} "
                f"spelling (paper: {'American' if target == 'us' else 'British'})")
    # G3 hyphenation
    lower = re.sub(r"\s+", " ", body.lower())
    seen = set()
    for m in re.finditer(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b", p):
        h = m.group(0).lower()
        if h in seen:
            continue
        seen.add(h)
        n_h = len(re.findall(r"\b" + re.escape(h) + r"\b", lower))
        closed = h.replace("-", "")
        spaced = h.replace("-", " ")
        n_c = len(re.findall(r"\b" + re.escape(closed) + r"\b", lower))
        n_s = len(re.findall(r"(?<!-)\b" + re.escape(spaced) + r"\b(?!-)", lower))
        if n_c:
            rep.add("G3", doc.where(m.start()), f"'{h}' ({n_h}x) vs '{closed}' ({n_c}x)")
        if n_s:
            rep.add("G3", doc.where(m.start()), f"'{h}' ({n_h}x) vs '{spaced}' ({n_s}x); "
                    f"fine if noun vs. adjective", hint=True)
    # G4 Latin abbreviations
    for m in re.finditer(r"\b(e\.g|i\.e)\.(?!,)", p):
        if variant != "uk":
            rep.add("G4", doc.where(m.start()), f"'{m.group(0)}' without comma -> '{m.group(0)},'")
    for m in re.finditer(r"\b(?:eg|ie)\.|\b(?:e\.g|i\.e)(?![.\w])|\bet al\b(?!\.)|\betal\.|"
                         r"\bcf\b(?!\.)|\bvs\b(?!\.)", p):
        rep.add("G4", doc.where(m.start()), f"malformed abbreviation '{m.group(0)}'")
    if variant == "uk":
        with_c = len(re.findall(r"\b(?:e\.g|i\.e)\.,", p))
        without = len(re.findall(r"\b(?:e\.g|i\.e)\.(?!,)", p))
        if with_c and without:
            rep.add("G4", "-", f"e.g./i.e. with comma {with_c}x, without {without}x; unify")
    # G5 numbers and units
    for m in re.finditer(r"(?<![\w.,$\\/-])([0-9])(?=[ ~]+[a-z]{3,})", p):
        before = p[max(m.start() - 15, 0): m.start()]
        if re.search(r"[A-Z][a-z]*\.?[ ~]*$", before):
            continue
        rep.add("G5", doc.where(m.start()), f"digit in prose, spell out numbers below ten: "
                f"{snippet(p, m.start(), m.end(), 20)}", hint=True)
    for m in re.finditer(r"\b\d+(?:\.\d+)?(ms|ns|us|km|kg|Hz|kHz|MHz|GHz|GB|MB|KB|kB|TB|px|cm|mm|"
                         r"min|fps|dB|km/h|m/s)\b", p):
        rep.add("G5", doc.where(m.start()), f"no space between value and unit: '{m.group(0)}'")
    # G6 contractions and informal wording
    for m in re.finditer(r"\b(?:do|does|did|is|are|was|were|ca|could|wo|would|should|has|have|had)"
                         r"n['\u2019]t\b|\b(?:it|that|there|let|what|here|who)['\u2019]s\b|"
                         r"\b(?:we|they|you)['\u2019](?:re|ve|ll|d)\b", p, re.I):
        rep.add("G6", doc.where(m.start()), f"contraction '{m.group(0)}': "
                f"{snippet(p, m.start(), m.end(), 20)}")
    for m in re.finditer(r"\b(?:a lot of|lots of|pretty much|basically|totally|huge|awesome|"
                         r"okay|stuff|gonna|tons of)\b", p, re.I):
        rep.add("G6", doc.where(m.start()), f"informal wording '{m.group(0)}'", hint=True)
    # G7 sentence openings with digits or symbols
    for m in re.finditer(r"(?:[.!?][ \t]+|\n[ \t]*\n[ \t]*)(\d|\$)", doc.nc):
        i = m.start(1)
        if doc.in_body(i) and not ABBREV_BEFORE_DOT.search(doc.nc[max(m.start() - 12, 0): m.start() + 1]):
            if doc.prose[i] != " " or doc.nc[i] == "$":
                rep.add("G7", doc.where(i), f"sentence starts with a digit or symbol: "
                        f"{snippet(doc.nc, i, i + 1, 25)}", hint=True)


# ---------------------------------------------------------------- content

def headings(doc: Doc) -> list[dict]:
    out = []
    for m in HEAD_RE.finditer(doc.nc):
        if not doc.in_body(m.start()):
            continue
        end = match_brace(doc.nc, m.end() - 1)
        title = re.sub(r"\s+", " ", doc.nc[m.end(): end]).strip()
        lab = re.match(r"\s*\\label\{([^}]*)\}", doc.nc[end + 1: end + 200])
        out.append({"cmd": m.group(1), "star": m.group(2), "level": LEVELS[m.group(1)],
                    "title": title, "start": m.start(), "end": end + 1,
                    "label": lab.group(1).strip() if lab else None})
    return out


def check_sections(doc: Doc, refs: dict, rep: Report) -> None:
    hs = headings(doc)
    stop = doc.body_end
    for pat in (r"\\bibliography\s*\{", r"\\printbibliography", r"\\begin\{thebibliography\}"):
        if m := re.search(pat, doc.nc[doc.body_start:]):
            stop = min(stop, doc.body_start + m.start())
    appendix = re.search(r"\\appendix\b", doc.nc[doc.body_start:])
    for k, h in enumerate(hs):
        nxt = hs[k + 1] if k + 1 < len(hs) else None
        end = nxt["start"] if nxt else stop
        words = len(re.findall(r"[A-Za-z]{2,}", doc.prose_nofloat[h["end"]: end]))
        h["words"] = words
        deeper = nxt is not None and nxt["level"] > h["level"]
        if words == 0 and not deeper:
            rep.add("C1", doc.where(h["start"]), f"\\{h['cmd']}{{{h['title']}}} is empty")
        elif words < 40 and not deeper and h["level"] < 4:
            rep.add("C1", doc.where(h["start"]), f"\\{h['cmd']}{{{h['title']}}} has only "
                    f"{words} words", hint=True)
    for h in hs:
        if h["level"] <= 2:
            ind = "  " * h["level"]
            rep.info("C2", f"{ind}{h['title']} [{h['label'] or 'no label'}] "
                     f"{doc.where(h['start'])}, {h.get('words', 0)} words")
    if appendix:
        rep.info("C2", f"\\appendix at {doc.where(doc.body_start + appendix.start())}")
    # Roadmap paragraph
    rm = re.search(r"(?:remainder|rest) of (?:this|the) (?:paper|article|work|chapter)|"
                   r"(?:paper|article|work) is (?:structured|organi[sz]ed) as follows|"
                   r"structure of (?:this|the) (?:paper|article)", doc.prose, re.I)
    if not rm:
        rep.info("C2", "no roadmap paragraph ('remainder of this paper ...') found")
        return
    t = doc.nc
    a = t.rfind("\n\n", doc.body_start, rm.start()) + 1
    b = t.find("\n\n", rm.end())
    b = b if b != -1 else doc.body_end
    para = t[a:b]
    rep.info("C2", f"roadmap paragraph at {doc.where(rm.start())}")
    sec_labels = {h["label"]: h for h in hs if h["label"]}
    mentioned = []
    for m in REF_RE.finditer(para):
        for key in m.group(2).split(","):
            key = key.strip()
            if key in sec_labels:
                mentioned.append(sec_labels[key])
            else:
                rep.add("C2", doc.where(a + m.start()),
                        f"roadmap references '{key}', which is not a section label")
    starts = [h["start"] for h in mentioned]
    if starts != sorted(starts):
        rep.add("C2", doc.where(rm.start()), "roadmap mentions sections out of document order: "
                + ", ".join(h["title"] for h in mentioned), hint=True)
    if re.search(r"\b(?:Sect(?:ion)?s?\.?)[ ~]+\d", para):
        rep.add("C2", doc.where(rm.start()), "roadmap uses literal section numbers; use \\ref")
    top = min((h["level"] for h in hs), default=1)
    after = [h for h in hs if h["level"] == top and h["start"] > rm.start() and not h["star"]
             and not (appendix and h["start"] > doc.body_start + appendix.start())]
    missing = [h["title"] for h in after if h not in mentioned]
    if missing:
        rep.add("C2", doc.where(rm.start()), "sections after the roadmap not referenced in it: "
                + "; ".join(missing), hint=True)


REF_NOUNS = {"Figure", "Figures", "Section", "Sections", "Table", "Tables", "Equation",
             "Equations", "Chapter", "Chapters", "Appendix", "Definition", "Theorem", "Lemma",
             "Algorithm", "Listing", "Example", "Corollary", "Proposition", "Remark"}


def check_capitalization(doc: Doc, defs: dict, rep: Report) -> None:
    p = doc.prose
    # Title-case text that is fine: headings, the title, and abbreviation long forms.
    spans = [(h["start"], h["end"]) for h in headings(doc)]
    if m := re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", doc.nc):
        spans.append((m.start(), match_brace(doc.nc, m.end() - 1)))
    longform_words = [(off - 150, off, set(lf.split())) for ds in defs.values() for off, lf in ds]
    lower_words = Counter(w for w in re.findall(r"\b[a-z][a-z-]{3,}\b", p))
    cap_mid: dict[str, list[int]] = defaultdict(list)
    variants: dict[str, Counter] = defaultdict(Counter)
    for m in re.finditer(r"\b[A-Za-z][A-Za-z-]{3,}\b", p):
        w, o = m.group(0), m.start()
        if any(a <= o < b for a, b in spans):
            continue
        variants[w.lower()][w] += 1
        if w in REF_NOUNS or any(a <= o < b and w in ws for a, b, ws in longform_words):
            continue
        if w[0].isupper() and w[1:].islower():
            j, nl = prev_nonspace(p, m.start(), doc.body_start)
            if nl < 2 and j >= doc.body_start and (p[j].isalnum() or p[j] == ","):
                cap_mid[w].append(m.start())
    for w, offs in cap_mid.items():
        n_low = lower_words.get(w.lower(), 0)
        if n_low:
            rep.add("C3", doc.where(offs[0]), f"'{w}' capitalized mid-sentence {len(offs)}x, "
                    f"'{w.lower()}' {n_low}x; use one form", hint=True)
    for low, c in variants.items():
        inner = {v for v in c if any(ch.isupper() for ch in v[1:])}
        if inner and len(c) > 1:
            rep.add("C3", "-", "spelling variants: " + ", ".join(f"{v} ({n}x)" for v, n in c.items()),
                    hint=True)


STOPWORDS = {"of", "and", "the", "for", "in", "on", "to", "a", "an", "with", "by", "at", "from"}


def abbrev_defs(doc: Doc) -> dict[str, list[tuple[int, str]]]:
    """Plain-text definitions 'Long Form (LF)': acronym -> [(offset of '(', long form)]."""
    p = doc.prose
    defs: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for m in re.finditer(r"\(\s*([A-Z][A-Za-z0-9-]*?)(s?)\s*\)", p):
        acr = m.group(1)
        n_up = sum(ch.isupper() for ch in acr)
        if n_up < 2:
            continue
        words = re.findall(r"[A-Za-z][\w-]*", p[max(m.start() - 200, 0): m.start()])
        if "\n\n" in p[max(m.start() - 200, 0): m.start()]:
            para = p[max(m.start() - 200, 0): m.start()].split("\n\n")[-1]
            words = re.findall(r"[A-Za-z][\w-]*", para)
        count, phrase = 0, []
        for w in reversed(words):
            phrase.insert(0, w)
            if w.lower() in STOPWORDS:
                continue
            count += len(w.split("-"))
            if count >= n_up:
                break
        if count < n_up or not phrase or phrase[0][0].lower() != acr[0].lower():
            continue
        defs[acr].append((m.start(), " ".join(phrase)))
    return defs


def check_abbreviations(doc: Doc, defs: dict, rep: Report) -> None:
    pkg = next((p for p in ("acronym", "acro", "glossaries-extra", "glossaries")
                if doc.uses_package(p)), None)
    if pkg:
        rep.info("C4", f"'{pkg}' package in use; only plain-text definitions are checked here")
    p = doc.prose
    def_spans = {off for ds in defs.values() for off, _ in ds}
    for acr, ds in defs.items():
        body_ds = [d for d in ds if not doc.in_abstract(d[0])]
        uses = [m.start() for m in re.finditer(r"\b" + re.escape(acr) + r"s?\b", p)
                if not any(abs(m.start() - s) < len(acr) + 4 for s in def_spans)]
        body_uses = [u for u in uses if not doc.in_abstract(u)]
        if len(body_ds) > 1:
            rep.add("C4", doc.where(body_ds[1][0]), f"'{acr}' defined {len(body_ds)} times "
                    f"(first at {doc.where(body_ds[0][0])}); keep only the first")
        if not body_ds and body_uses:
            rep.add("C4", doc.where(body_uses[0]), f"'{acr}' is defined only in the abstract; "
                    f"define it again at its first use in the body")
            continue
        if not body_ds:
            continue
        first_def, longform = body_ds[0]
        early = [u for u in body_uses if u < first_def]
        if early:
            rep.add("C4", doc.where(early[0]), f"'{acr}' used before its definition at "
                    f"{doc.where(first_def)}")
        later = [u for u in body_uses if u > first_def]
        if len(later) == 0:
            rep.add("C4", doc.where(first_def), f"'{acr}' is defined but never used afterwards")
        elif len(later) == 1:
            rep.add("C4", doc.where(first_def), f"'{acr}' is used only once after its definition",
                    hint=True)
        lf = r"\b" + r"[\s~-]+".join(re.escape(w) for w in re.split(r"[\s-]+", longform)) + r"\b"
        for m in re.finditer(lf, p, re.I):
            if m.start() > first_def + 1 and not doc.in_abstract(m.start()) and not re.match(
                    r"\s*\(", p[m.end(): m.end() + 3]):
                rep.add("C4", doc.where(m.start()), f"long form '{m.group(0)}' written out after "
                        f"'{acr}' was defined; use '{acr}'")
    # Undefined acronym-like tokens
    tokens = Counter()
    first = {}
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*)(?:s)?\b", p):
        tok = m.group(1)
        if tok.endswith("s") and sum(ch.isupper() for ch in tok[:-1]) >= 2:
            tok = tok[:-1]
        if tok in defs or re.search(r"[a-z]{2,}", tok) or re.fullmatch(r"[IVXLC]+", tok):
            continue
        if not doc.in_body(m.start()):
            continue
        tokens[tok] += 1
        first.setdefault(tok, m.start())
    for tok, n in tokens.most_common():
        rep.add("C4", doc.where(first[tok]), f"'{tok}' ({n}x) is never defined", hint=True)


def check_duplicates(doc: Doc, rep: Report) -> None:
    fns = footnotes(doc)
    seen: dict[str, int] = {}
    url_seen: dict[str, int] = {}
    for off, text in fns:
        norm = re.sub(r"\s+", " ", text).strip().lower()
        if norm in seen:
            rep.add("C5", doc.where(off), f"duplicate footnote (same as {doc.where(seen[norm])})")
        else:
            seen[norm] = off
        for u in re.findall(r"\\(?:url|href)\s*\{([^}]*)\}", text):
            u = u.strip().rstrip("/")
            if u in url_seen and url_seen[u] != off:
                rep.add("C5", doc.where(off), f"URL {u} already in footnote at {doc.where(url_seen[u])}")
            url_seen.setdefault(u, off)
    body = doc.nc[doc.body_start: doc.body_end]
    pos = doc.body_start
    for para in re.split(r"(\n[ \t]*\n)", body):
        keys = Counter()
        for m in CITE_RE.finditer(para):
            if m.group(1) != "nocite":
                keys.update(k.strip() for k in m.group(3).split(",") if k.strip())
        for k, n in keys.items():
            if n > 1:
                rep.add("C5", doc.where(pos), f"'{k}' cited {n}x in one paragraph; check for "
                        f"repeated support of the same claim", hint=True)
        pos += len(para)


def check_figures(doc: Doc, rep: Report) -> None:
    gpaths = [doc.root]
    if m := re.search(r"\\graphicspath\s*\{((?:\s*\{[^}]*\})+)\s*\}", doc.nc):
        gpaths += [doc.root / d for d in re.findall(r"\{([^}]*)\}", m.group(1))]
    exts = ["", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"]
    for m in re.finditer(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", doc.nc):
        if not doc.in_body(m.start()):
            continue
        name = m.group(1).strip()
        found = next((g / (name + e) for g in gpaths for e in exts
                      if (g / (name + e)).is_file()), None)
        if not found:
            rep.add("F1", doc.where(m.start()), f"graphics file not found: {name}")
            continue
        rep.info("F1", f"{rel(found, doc.root)}")
        if found.suffix.lower() in (".png", ".jpg", ".jpeg"):
            rep.add("F1", doc.where(m.start()), f"raster image {rel(found, doc.root)}; prefer vector "
                    f"graphics for plots and diagrams", hint=True)


def pdf_pages(pdf: Path) -> int | None:
    try:
        data = pdf.read_bytes()
    except OSError:
        return None
    counts = [int(c) for c in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
    return max(counts) if counts else None


# --------------------------------------------------------------------------

def run(main: Path, log: Path | None = None, variant: str | None = None,
        todo_macros: list[str] | None = None) -> Report:
    """Run every check on the paper rooted at main and return the report."""
    doc = Doc(main)
    rep = Report()
    check_log(log or main.with_suffix(".log"), rep)
    pdf = main.with_suffix(".pdf")
    if (n := pdf_pages(pdf)) is not None:
        rep.info("T2", f"{pdf.name}: {n} pages (from PDF)")

    cited: dict[str, list[int]] = defaultdict(list)
    for m in CITE_RE.finditer(doc.nc):
        for key in m.group(3).split(","):
            key = key.strip()
            if key and key != "*" and "#" not in key:
                cited[key].append(m.start())
    entries: list[BibEntry] = []
    for bf in bib_files(doc):
        if bf.is_file():
            entries += parse_bib(bf, doc.root)
        else:
            rep.add("B1", "-", f".bib file not found: {rel(bf, doc.root)}")

    labels, refs = check_refs(doc, rep)
    check_floats(doc, labels, refs, rep)
    check_leftovers(doc, list(todo_macros or []), rep)
    check_placeholders(doc, [e for e in entries if e.key in cited], rep)
    check_tilde_and_cites(doc, rep)
    check_quotes_dashes(doc, rep)
    check_urls(doc, rep)
    check_unicode(doc, [b for b in bib_files(doc) if b.is_file()], rep)
    check_springer(doc, rep)
    check_bib(doc, cited, rep, entries, [b for b in bib_files(doc) if b.is_file()])
    check_language(doc, variant, rep)
    check_sections(doc, refs, rep)
    defs = abbrev_defs(doc)
    check_capitalization(doc, defs, rep)
    check_abbreviations(doc, defs, rep)
    check_duplicates(doc, rep)
    check_figures(doc, rep)
    if doc.abstract:
        words = len(re.findall(r"[A-Za-z]{2,}", doc.prose[doc.abstract[0]: doc.abstract[1]]))
        rep.info("T2", f"abstract: ~{words} words")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("main", type=Path)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--variant", choices=["us", "uk"])
    ap.add_argument("--todo-macros", default="", help="comma-separated extra note macro names")
    ap.add_argument("--state", type=Path, help="finishing/ directory: skips IDs listed in "
                    "dismissed.md and compares against state.json of the last saved run")
    ap.add_argument("--save", action="store_true", help="write this run to STATE/state.json")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.main.is_file():
        print(f"not found: {args.main}", file=sys.stderr)
        return 2
    rep = run(args.main, args.log, args.variant, [t for t in args.todo_macros.split(",") if t])
    res = rep.compare(args.state)
    if args.json:
        print(rep.to_json(res))
    else:
        rep.print(res)
    if args.state and args.save:
        Report.save(args.state, res)
        if not args.json:
            print(f"State saved to {args.state / 'state.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
