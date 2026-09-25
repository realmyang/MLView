#!/usr/bin/env python3
"""Shared records, hashing, Git and path primitives for MLView's evaluation tools (stdlib only).

This is the one module that the decision tooling (tools/workflow_decisions.py) and the pilot
tooling (tools/workflow_pilot.py) share. It only parses, hashes, compares, reads pinned bytes and
writes files exclusively or atomically. It never interprets target code, never runs a model and
never writes a human decision, reviewer name, verdict, essential flag, policy value or approval.

Import it as ``eval_records`` with ``tools/`` on ``sys.path`` (the dispatcher in workflow_eval.py
and the tests arrange this), so every tool sees the same ``Problem`` and ``Record`` classes.

The grammar of every human-authored file (Campaign 2 specification, section 1.3):

* UTF-8; a leading BOM is stripped; CRLF, CR and LF all end a line; trailing spaces are ignored;
  ``Record.sha256`` is taken over the raw bytes.
* Blank lines and lines whose first non-space character is ``>`` are ignored (tool-written notes).
* The first remaining line is the title (``# Reference decisions: pilot-nanogpt``). It selects the
  schema, that is the header keys, the section kinds and each section's keys.
* Lines before the first ``##`` are header fields. ``## <Kind>`` or ``## <Kind> <id>`` starts a
  section. A section whose schema entry has a ``pattern`` (the development adjudication's
  ``## dev-gan / codex``) uses its normalised heading as its kind. Any other line that starts with
  ``#`` is an error. When it names a known section (``### Fact x``, ``##Fact x``, ``# Fact f02``)
  that section still starts there, and the lines after it belong to it. When it looks like a
  heading of an unknown section (two or more ``#``, or one ``#`` before a section kind or its plural
  and nothing else or one word that could be an ID of that kind, such as ``# Facts f02``) the
  following lines are skipped until the next valid heading, so they are never attributed to the
  previous section, and the error says so. Any other ``#`` line is a comment written in the wrong
  form: it is reported under the enclosing section, which keeps its fields. That covers prose
  (``# reviewed on the train``, ``# added the randint detail``), one ``#`` before a reference item
  kind and a word without a digit (``# Fact checked``, ``# Defects none``; every ledger and added
  item ID has a digit), and one ``#`` before a kind that takes no ID and one word (``# Scenario
  checked``, ``# Task done``). An unknown ``## `` heading also skips the lines after it, and its
  error says so.
* Every other line is ``Key: value``. Fixed keys are matched case-insensitively and stored under
  their canonical spelling. In a section with free keys (item IDs, artifact pointers, dated
  lines) the key ends at the first ``:`` that is followed by a space or the end of the line, so a
  pointer such as ``node:load-batches: pending`` keeps ``node:load-batches`` as its key; such a
  line can be re-joined as ``f"{key}: {value}"``. An empty value means "not supplied".
* A line indented by two or more spaces (or a tab) continues the previous value, joined with one
  space.
* A section whose schema allows it holds one fenced block (```` ```text ```` ... ```` ``` ````),
  captured line by line with trailing spaces removed and lines joined by ``\\n``.
* Unknown sections, unknown keys, repeated keys or sections, fences where none is allowed and any
  other line are errors that name the line and the section. A line without a key after a stored
  value (usually a wrapped sentence, even when a blank or ``>`` line comes between) gets the hint to
  indent it by two spaces.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Mapping, NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "skills" / "mlview" / "scripts" / "artifact.py"
TASKS_REL = "evals/workflow/tasks.json"
CANDIDATES_REL = "evals/workflow/reference-candidates"
EVAL_REL = "evals/workflow"

ERROR, TODO, NOTE = "ERROR", "TODO", "NOTE"
LEVELS = (ERROR, TODO, NOTE)

# The helper names the evaluation tools rely on (Campaign 2 specification, section 8.3 item 5).
HELPER_NAMES = ("_strip_bom", "_lines", "_parse_notebook", "_parse", "_rfc3339", "validate", "is_owned_path")

PILOT_TARGET_KEYS = (
    "structurallyValid", "exactAnchors", "supportedClaimPrecision", "essentialFactRecall",
    "knownUnresolvedQualified", "highSeverityFalseAccusations",
)
RATE_TARGET_KEYS = PILOT_TARGET_KEYS[:5]
REFERENCE_STATUSES = ("needs-human-review", "frozen")
TASK_SPLITS = ("development", "heldout")
MANIFEST_REQUIRED = ("version", "hosts", "repetitions", "pilotTargets", "tasks")
MANIFEST_KEYS = frozenset(MANIFEST_REQUIRED + ("pilotFreeze",))
PILOT_FREEZE_KEYS = frozenset({"campaign", "freeze", "referenceRevision"})

# Files a host reads as instructions from the workspace or any parent directory (J2).
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md",
                     ".github/copilot-instructions.md")

NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
SHA1_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
OBJECT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}", re.ASCII)
REVISION_RE = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
RUN_ID_RE = re.compile(r"(?P<task>[a-z0-9][a-z0-9-]*):(?P<host>[a-z0-9][a-z0-9-]*):(?:baseline:)?(?P<repeat>[1-9][0-9]*)",
                       re.ASCII)
RUN_DIR_RE = re.compile(r"[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*\.(?:baseline\.)?[1-9][0-9]*", re.ASCII)
ANCHOR_RE = re.compile(r"(?P<file>[^;:#]+?)(?:#cell(?P<cell>\d+))?:(?P<line>\d+)(?:-(?P<end>\d+))?")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
# Absolute machine paths that must never enter committed outputs (section 8.8 invariant 6): the
# common home and temporary roots and a drive letter followed by either slash (C:\ or C:/).
MACHINE_PATH_RE = re.compile(r"/Users/|/home/|/private/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_FREE_KEY_END = re.compile(r":(?=\s|$)")
# An unknown key that looks like a mistyped key (a few plain words) rather than a wrapped sentence.
_KEY_LIKE = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?: [A-Za-z0-9][A-Za-z0-9-]*){0,5}")
_CONTINUE_HINT = 'To continue the previous line, indent it by two spaces; put ">" in front of notes only.'
_REASON_SEPARATOR = re.compile("\\s(?:\u2014|\u2013|--)(?:\\s|$)")
SEPARATOR_HINT = 'write the reason after " -- " (two hyphens) or " \u2014 "; a single "-" is not a separator.'
_GLUED_SEPARATOR = re.compile("\u2014|--")
_SPARSE_FORBIDDEN = ("!", "?", "[", "\\", "**")
_GIT_ISOLATION = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                  "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")


# --------------------------------------------------------------------------------------------
# Records


class Problem(NamedTuple):
    """One finding in a human-authored file; ``str()`` gives ``path:line: LEVEL section: message``."""

    path: str
    line: int
    level: str
    section: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.level:<5} {self.section}: {self.message}"


@dataclass
class Field:
    """A ``Key: value`` line. ``key`` is the canonical spelling (fixed keys) or the key as written."""

    key: str
    value: str
    line: int


@dataclass
class Section:
    """The header (kind ``header``) or one ``## <Kind> [<id>]`` section.

    ``fields`` maps each key to its first line and ``lines`` keeps the same fields in file order.
    ``fence`` is the captured fenced block (``None`` when the section has none) and ``fence_line``
    the line of its opening fence.
    """

    kind: str
    ident: str | None
    line: int
    fields: dict[str, Field]
    lines: list[Field]
    fence: str | None
    fence_line: int | None = None

    @property
    def label(self) -> str:
        return self.kind if self.ident is None else f"{self.kind} {self.ident}"

    def field(self, key: str) -> Field | None:
        """The field for ``key``: an exact key first, then a case-insensitive match."""
        found = self.fields.get(key)
        if found is not None:
            return found
        folded = key.casefold()
        return next((item for name, item in self.fields.items() if name.casefold() == folded), None)

    def value(self, key: str, default: str | None = None) -> str | None:
        found = self.field(key)
        return default if found is None else found.value


@dataclass
class Record:
    """A parsed file. ``title`` is the title text as written (without ``# ``); ``kind`` is the
    canonical title kind (``Reference decisions``) and ``ident`` the text after its colon."""

    path: str
    sha256: str
    title: str
    header: Section
    sections: list[Section]
    kind: str = ""
    ident: str | None = None

    def section(self, kind: str, ident: str | None = None) -> Section | None:
        return next((s for s in self.sections if s.kind == kind and s.ident == ident), None)

    def find(self, kind: str) -> list[Section]:
        return [s for s in self.sections if s.kind == kind]


@dataclass(frozen=True)
class SectionSpec:
    """One section kind. ``keys`` is the canonical key set, or ``None`` for free keys. With a
    ``pattern`` the heading must match it and becomes the kind; ``kind`` is then only the hint
    shown in messages (for example ``<task> / <host>``)."""

    kind: str
    keys: tuple[str, ...] | None = None
    ident: bool = False
    fence: bool = False
    pattern: str | None = None
    numbered: bool = False  # every ID of this kind contains a digit (the reference items: f01, h01, d01...)


@dataclass(frozen=True)
class RecordSchema:
    """The fixed shape of one file type, selected by the title ``# <title>[: <id>]``."""

    title: str
    ident: bool
    header: tuple[str, ...]
    sections: tuple[SectionSpec, ...] = ()


_REVIEWER_HEADER = ("Reviewer", "Date", "Transcribed by")
_TASK = SectionSpec("Task", ("Review",))
_REFERENCE_SECTIONS = (
    SectionSpec("Scenario", ("Decision", "Description", "Entrypoints", "Arguments", "Reason")),
    SectionSpec("Fact", ("Decision", "Wording", "Basis", "Essential", "Anchors", "Reason"), ident=True, numbered=True),
    SectionSpec("Unknown", ("Decision", "Wording", "Runs must state", "Reason"), ident=True, numbered=True),
    SectionSpec("Non-defect", ("Decision", "Wording", "Reason"), ident=True, numbered=True),
    SectionSpec("Added fact", ("Wording", "Basis", "Essential", "Anchors", "Reason"), ident=True, numbered=True),
    SectionSpec("Added unknown", ("Wording", "Runs must state", "Reason"), ident=True, numbered=True),
    SectionSpec("Defect", ("Wording", "Severity", "Anchors", "Counter-evidence", "Reason"), ident=True, numbered=True),
)

# Every human-authored file type of Campaign 2 (sections 1.4-1.8, 2, 4.3, 4.4 and 4.6). Keys are
# the casefolded title kinds. Tools may pass their own mapping to parse_record(schemas=...).
SCHEMAS: dict[str, RecordSchema] = {schema.title.casefold(): schema for schema in (
    RecordSchema("Reference decisions", True, ("Candidate",) + _REVIEWER_HEADER,
                 _REFERENCE_SECTIONS + (SectionSpec("Disagreements"), _TASK)),
    RecordSchema("Second review", True, ("Candidate",) + _REVIEWER_HEADER, _REFERENCE_SECTIONS + (_TASK,)),
    RecordSchema("Pilot run policy", False, _REVIEWER_HEADER, (
        SectionSpec("Host", ("Model", "Reasoning", "Invocation"), ident=True),
        SectionSpec("Environment", ("Helper Python",)),
        SectionSpec("Budget", ("Active minutes", "Repair rounds", "Infrastructure retries")),
        SectionSpec("Scoring", ("Qualified claims", "Per-host targets")),
        SectionSpec("Conditions", ("Baseline sessions", "Development adjudication before Stage 1")),
        SectionSpec("Targets", ("Decision",)),
        SectionSpec("Skill prompt", ("Decision",), fence=True),
        SectionSpec("No-skill prompt", ("Decision",), fence=True),
        SectionSpec("Privacy", ("Publication",)),
        _TASK,
    )),
    RecordSchema("Development adjudication", False, _REVIEWER_HEADER, (
        SectionSpec("<task> / <host>", pattern=r"[A-Za-z0-9][A-Za-z0-9._-]* / [A-Za-z0-9][A-Za-z0-9._-]*"),
        SectionSpec("Baselines"),
        _TASK,
    )),
    RecordSchema("Session", True, (
        "Status", "Failure", "Prompt sent", "Started", "Ended", "Active minutes", "Approval wait minutes", "Repair rounds",
        "Host version", "Extension version", "Model", "Reasoning", "Resolved model", "Invocation",
        "Helper Python", "Usage", "Transcript", "UI log", "Prior attempts", "MLView available to host",
    ), (SectionSpec("Deviations"),)),
    RecordSchema("Run review", True, ("Run", "Artifact", "Transcript", "Reference") + _REVIEWER_HEADER, (
        SectionSpec("Claims"),
        SectionSpec("Severity"),
        SectionSpec("Essential facts"),
        SectionSpec("Known unresolved"),
        SectionSpec("Usability", ("dataOrigin", "updatedParametersAndFitState", "losses", "evaluationBoundaries",
                                  "outputs", "uncertainty", "task")),
        SectionSpec("Reference defects"),
        SectionSpec("False accusations"),
        _TASK,
    )),
    RecordSchema("Invalidation", True, _REVIEWER_HEADER + ("Scope", "Reason")),
)}


def split_title(title: str, schemas: Mapping[str, RecordSchema] | None = None) -> tuple[RecordSchema, str | None]:
    """The schema and identifier of a title text such as ``Reference decisions: pilot-nanogpt``."""
    registry = SCHEMAS if schemas is None else schemas
    kind_text, colon, ident_text = title.partition(":")
    schema = registry.get(" ".join(kind_text.split()).casefold())
    if schema is None:
        known = ", ".join(f'"# {s.title}{": <id>" if s.ident else ""}"' for s in registry.values())
        raise ValueError(f"the first line must be the title the tool wrote. Known titles: {known}.")
    ident = ident_text.strip() if colon else None
    expected = f'"# {schema.title}{": <id>" if schema.ident else ""}"'
    if schema.ident and (not ident or len(ident.split()) != 1):
        raise ValueError(f"the title must read {expected}, with a one-word ID.")
    if not schema.ident and colon:
        raise ValueError(f"the title must read {expected}.")
    return schema, ident


class _Sink:
    """Swallows continuation lines after a line that was reported and not stored."""

    value = ""


_SINK = _Sink()


_ID_LIKE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_NOT_READ = ' The lines after it, up to the next "## " heading, were not read.'


def _heading_like(schema: RecordSchema, line: str, text: str) -> bool:
    """Whether a ``#`` line that names no known section was meant as a heading rather than as a
    comment: two or more ``#`` (``### My notes``), one ``#`` before a section kind or its plural
    alone (``# Facts``), or one ``#`` before a section kind (or its plural) and one word that could be
    an ID of that kind (``# Facts demo-f02``: the kind takes an ID, and a reference item ID has a
    digit). Any other ``#`` line is a comment, such as ``# added the randint detail``, ``# Task done``
    or ``# Scenario checked`` (Task and Scenario take no ID) and ``# Defects none`` (no digit)."""
    if line.startswith("##"):
        return True
    words = text.casefold().split()
    for spec in schema.sections:
        if spec.pattern is not None:
            continue
        kind = spec.kind.casefold().split()
        size = len(kind)
        forms = (kind, kind[:-1] + [kind[-1] + "s"])
        if not any(words[:size] == form for form in forms) or len(words) > size + 1:
            continue
        if len(words) == size:
            return True
        word = words[size]
        if spec.ident and _ID_LIKE.fullmatch(word) and (not spec.numbered or any(char.isdigit() for char in word)):
            return True
    return False


def _match_heading(schema: RecordSchema, heading: str) -> tuple[SectionSpec | None, str | None, str | None]:
    """(spec, ident, error) for a normalised ``##`` heading."""
    folded = heading.casefold()
    found: tuple[int, SectionSpec, str | None] | None = None
    error = None
    for spec in schema.sections:
        if spec.pattern is not None:
            if re.fullmatch(spec.pattern, heading, re.IGNORECASE) and found is None:
                found = (0, spec, None)
            continue
        kind = spec.kind.casefold()
        if folded == kind:
            if spec.ident:
                error = f'section "## {heading}" needs an ID: write "## {spec.kind} <id>".'
                continue
            candidate = (len(kind), spec, None)
        elif folded.startswith(kind + " "):
            rest = heading[len(kind):].strip()
            if not spec.ident:
                error = f'section "## {spec.kind}" takes no ID: write "## {spec.kind}".'
                continue
            if len(rest.split()) != 1:
                error = f'section IDs are one word: "## {heading}".'
                continue
            candidate = (len(kind), spec, rest)
        else:
            continue
        if found is None or candidate[0] > found[0]:
            found = candidate
    if found is not None:
        return found[1], found[2], None
    if error is None:
        if schema.sections:
            names = ", ".join(s.kind + (" <id>" if s.ident else "") for s in schema.sections)
            error = f'unknown section "## {heading}". Sections: {names}.'
        else:
            error = f'unknown section "## {heading}". This file has no sections.'
    return None, None, error


def parse_record(raw: bytes, display_path: str, *,
                 schemas: Mapping[str, RecordSchema] | None = None) -> tuple[Record | None, list[Problem]]:
    """Parse one human-authored file with the shared grammar (see the module docstring).

    Returns ``(None, problems)`` when the file cannot be decoded or has no known title, otherwise
    the record and every grammar problem in line order. Semantic rules (what must be filled, which
    values are allowed) belong to the checker that owns the file type.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("parse_record needs the file's bytes")
    raw = bytes(raw)
    problems: list[Problem] = []

    def report(line: int, section: str, message: str) -> None:
        problems.append(Problem(display_path, line, ERROR, section, message))

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = len(_LINE_BREAK.split(raw[:exc.start].decode("utf-8")))
        report(line, "header", "the file is not valid UTF-8; save it as UTF-8.")
        return None, problems
    if text.startswith("\ufeff"):
        text = text[1:]
    registry = SCHEMAS if schemas is None else schemas

    schema: RecordSchema | None = None
    record: Record | None = None
    current: Section | None = None
    where = "header"  # the label of the current section, also while an unknown or repeated one is skipped
    current_keys: dict[str, str] | None = None
    current_fence = False
    seen: dict[tuple[str, str | None], Section] = {}
    last: Field | _Sink | None = None
    fence: tuple[int, list[str], Section | None, str] | None = None

    for number, raw_line in enumerate(_LINE_BREAK.split(text), 1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if fence is not None:
            if stripped == "```":
                start, captured, target, _where = fence
                if target is not None:
                    target.fence, target.fence_line = "\n".join(captured), start
                fence = None
            else:
                fence[1].append(line)
            continue
        if not stripped or stripped.startswith(">"):
            continue
        if record is None:
            if not line.startswith("# "):
                report(number, "header", "the first line must be the title the tool wrote, for example "
                                         '"# Reference decisions: <task>".')
                return None, problems
            title = line[2:].strip()
            try:
                schema, ident = split_title(title, registry)
            except ValueError as exc:
                report(number, "header", str(exc))
                return None, problems
            header = Section("header", None, number, {}, [], None)
            record = Record(display_path, sha256_bytes(raw), title, header, [], schema.title, ident)
            current, current_keys, current_fence = header, _key_map(schema.header), False
            continue
        assert schema is not None
        label = where
        if stripped.startswith("```"):
            target = None
            if current is not None:
                info = stripped[3:].strip()
                if not current_fence:
                    report(number, label, "a fenced block (```) is not allowed here; only the run-policy prompt "
                                          "sections take one.")
                elif current.fence is not None:
                    report(number, label, f"this section already has a fenced block (line {current.fence_line}); "
                                          "keep one.")
                else:
                    if info and info.casefold() != "text":
                        report(number, label, 'write the opening fence as "```text".')
                    target = current
            fence, last = (number, [], target, label), None
            continue
        heading = None
        if line == "##" or line.startswith("## "):
            heading = " ".join(line[2:].split())
        elif line.startswith("#"):
            # A mistyped heading ("### Fact x", "##Fact x", "# Fact x"): an error either way. When it
            # names a known section, that section starts here so its fields stay with it.
            attempt = " ".join(line.lstrip("#").split())
            known, _ident, _error = _match_heading(schema, attempt) if attempt else (None, None, None)
            # A reference item kind and a word that is not an item ID (every ledger and added item ID
            # has a digit) never starts that item: after one "#" ("# Fact checked", "# Defect
            # confirmed") it is a comment, after two or more ("### Fact checked") an unknown heading.
            no_id = known is not None and known.numbered and _ident is not None \
                and not any(char.isdigit() for char in _ident)
            worded = no_id and not line.startswith("##")
            if no_id:
                known = None
            if known is None and (worded or not _heading_like(schema, line, attempt)):
                # A "#" comment ("# reviewed on the train", "#1 priority"): an error, but the section
                # and the fields around it are kept, and the problem names the enclosing section.
                report(number, label, f'"{stripped[:40]}" is not "Key: value". Put ">" in front of notes; "#" '
                                      "does not start a comment.")
                last = _SINK
                continue
            last = None
            if known is None:
                where = attempt or "#"
                report(number, where, f'"{stripped[:40]}" is not a section heading. Write section headings as '
                                      '"## <Kind> <id>" (two # and a space); put ">" in front of notes.' + _NOT_READ)
                current = None
                continue
            report(number, attempt, f'"{stripped[:40]}" is not a section heading; write "## {attempt}" (two # and a '
                                    "space).")
            heading = attempt
        if heading is not None:
            spec, ident, error = _match_heading(schema, heading)
            last = None
            if spec is None:
                where = heading or "##"
                report(number, where, (error or "unknown section") + _NOT_READ)
                current = None
                continue
            kind = " ".join(heading.split()).casefold() if spec.pattern is not None else spec.kind
            section = Section(kind, ident, number, {}, [], None)
            where = section.label
            if (kind, ident) in seen:
                report(number, section.label,
                       f"this section appears twice (first on line {seen[(kind, ident)].line}). Keep one.")
                current = None
                continue
            seen[(kind, ident)] = section
            record.sections.append(section)
            current, current_keys, current_fence = section, _key_map(spec.keys), spec.fence
            continue
        if current is None:
            continue
        if last is not None and (line.startswith("  ") or line.startswith("\t")):
            if isinstance(last, Field):
                last.value = f"{last.value} {stripped}".strip()
            continue
        # A line after a stored value (blank and ">" lines between do not count) that is not
        # "Key: value" is usually a wrapped sentence; an indented line would still continue it.
        wrapped = isinstance(last, Field)
        if current_keys is None:
            end = _FREE_KEY_END.search(stripped)
            split_at = end.start() if end else stripped.find(":")
        else:
            split_at = stripped.find(":")
        key = stripped[:split_at].strip() if split_at > 0 else ""
        if not key:
            hint = _CONTINUE_HINT if wrapped else 'Put ">" in front of notes.'
            report(number, label, f'"{stripped[:40]}" is not "Key: value". {hint}')
            last = _SINK
            continue
        value = stripped[split_at + 1:].strip()
        if current_keys is not None:
            canonical = current_keys.get(" ".join(key.split()).casefold())
            if canonical is None:
                allowed = ", ".join(sorted(current_keys.values(), key=str.casefold))
                hint = f" {_CONTINUE_HINT}" if wrapped and not _KEY_LIKE.fullmatch(key) else ""
                report(number, label, f'unknown field "{key}". Allowed here: {allowed}.{hint}')
                last = _SINK
                continue
            key = canonical
        if key in current.fields:
            report(number, label, f'"{stripped[:split_at].strip()}" appears twice (first on line '
                                  f'{current.fields[key].line}). Keep one.')
            last = _SINK
            continue
        item = Field(key, value, number)
        current.fields[key] = item
        current.lines.append(item)
        last = item

    if fence is not None:
        start, _captured, _target, fence_label = fence
        report(start, fence_label, "this fenced block is never closed; add a line with ``` after it.")
    if record is None:
        report(1, "header", "the file is empty; restore it from the template.")
        return None, problems
    problems.sort(key=lambda problem: problem.line)
    return record, problems


def _key_map(keys: Sequence[str] | None) -> dict[str, str] | None:
    return None if keys is None else {" ".join(key.split()).casefold(): key for key in keys}


def split_list(value: str) -> list[str]:
    """Items of a ``;``-separated value; a lone ``none`` (any case) or an empty value is an empty list."""
    if value.strip().casefold() == "none":
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_anchor(text: str) -> tuple[str, int | None, int, int]:
    """``path:LINE``, ``path:LINE-END`` or ``path#cellN:LINE-END`` -> (path, cell, line, endLine).

    Cells are zero-based and lines one-based, as in the helper; a notebook (.ipynb) needs a cell and
    any other file must not have one. Raises ValueError with a message for the reviewer.
    """
    part = text.strip()
    match = ANCHOR_RE.fullmatch(part)
    if not match:
        raise ValueError(f'"{part}" is not an anchor. Write path:LINE or path:LINE-END; notebooks '
                         'path#cellN:LINE-END; separate several with ";".')
    path = match["file"].strip()
    problem = _path_problem(path)
    if problem:
        raise ValueError(f'"{part}": the path {problem}.')
    line = int(match["line"])
    end = int(match["end"]) if match["end"] is not None else line
    cell = int(match["cell"]) if match["cell"] is not None else None
    if line < 1:
        raise ValueError(f'"{part}": lines start at 1.')
    if end < line:
        raise ValueError(f'"{part}": the end line is before the start line.')
    notebook = PurePosixPath(path).suffix.lower() == ".ipynb"
    if notebook and cell is None:
        raise ValueError(f'"{part}": a notebook anchor needs a zero-based cell, like {path}#cell0:{line}.')
    if cell is not None and not notebook:
        raise ValueError(f'"{part}": only notebooks (.ipynb) take #cellN.')
    return path, cell, line, end


def format_anchor(path: str, cell: int | None, line: int, end: int) -> str:
    """The locator written for an anchor (``train.py:48-49``, ``nb.ipynb#cell3:2``)."""
    where = f"{path}#cell{cell}" if cell is not None else path
    return f"{where}:{line}" if line == end else f"{where}:{line}-{end}"


def parse_verdict(value: str, vocab: set[str]) -> tuple[str, list[str], str | None]:
    """``<word> [pointer ...] [\u2014 reason]`` -> (verdict, pointers, reason).

    The verdict is matched case-insensitively and returned as spelled in ``vocab``. The reason
    follows the first `` \u2014 `` (also ``--`` or an en dash) and is ``None`` when absent or empty.
    """
    text = value.strip()
    separator = _REASON_SEPARATOR.search(text)
    head, reason = (text[:separator.start()], text[separator.end():].strip() or None) if separator else (text, None)
    words = head.split()
    allowed = {item.casefold(): item for item in vocab}
    choices = ", ".join(sorted(vocab))
    if not words:
        raise ValueError(f"the verdict is empty; write one of: {choices}.")
    verdict = allowed.get(words[0].casefold())
    if verdict is None:
        glued = _GLUED_SEPARATOR.search(words[0])
        hint = (' Put a space on both sides of the " -- " (or " \u2014 ") that starts the reason.' if glued else "")
        raise ValueError(f'"{words[0]}" is not one of: {choices}.{hint}')
    if "-" in words[1:]:
        raise ValueError(SEPARATOR_HINT[0].upper() + SEPARATOR_HINT[1:])
    return verdict, words[1:], reason


def lone_hyphen(words: list[str]) -> bool:
    """True when a single "-" stands where the reason separator was meant."""
    return "-" in words


# --------------------------------------------------------------------------------------------
# Hashes and pinned Git bytes


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_oid(data: bytes) -> str:
    """The SHA-1 Git blob object ID of ``data`` (the corpus repositories use SHA-1 object names)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _GIT_ISOLATION}
    env.update({"GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    return env


def _git(repo: Path, *args: str) -> bytes:
    """Run a read-only git command in ``repo``. Lazy fetches are disabled (GIT_NO_LAZY_FETCH, and
    ``protocol.allow=never`` for Git versions older than 2.44), so a missing object is an error."""
    command = ["git", "-c", "protocol.allow=never", "-C", str(repo), *args]
    try:
        result = subprocess.run(command, capture_output=True, env=_git_env(), check=False)
    except OSError as exc:
        raise ValueError(f"cannot run git: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip() or f"exit status {result.returncode}"
        raise ValueError(f"git {args[0]} failed in {repo}: {detail}")
    return result.stdout


_TREES: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}


def pinned_tree(repo: Path, commit: str) -> dict[str, str]:
    """``{path: blob OID}`` for every blob of ``commit`` (``git ls-tree -r``; symbolic links are
    listed with their link blob, submodules are omitted). Reads trees only, never blobs."""
    if not isinstance(commit, str) or not SHA1_RE.fullmatch(commit):
        raise ValueError(f"a pinned commit is a full 40-hex SHA-1, not {commit!r}")
    key = (str(Path(repo).resolve()), commit)
    if key not in _TREES:
        output = _git(Path(repo), "ls-tree", "-r", "-z", "--full-tree", f"{commit}^{{commit}}")
        entries = []
        for entry in output.split(b"\0"):
            if not entry:
                continue
            meta, _tab, raw_path = entry.partition(b"\t")
            mode, kind, oid = meta.decode("ascii").split(" ")
            if kind != "blob":
                continue
            if not SHA1_RE.fullmatch(oid):
                raise ValueError(f"{repo} does not use SHA-1 object names ({oid})")
            try:
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{repo} has a path that is not UTF-8: {raw_path!r}") from exc
            entries.append((path, oid))
        _TREES[key] = tuple(entries)
    return dict(_TREES[key])


def pinned_bytes(repo: Path, commit: str, path: str, *, tree: Mapping[str, str] | None = None) -> bytes:
    """The worktree bytes of ``path``, required to be materialised and equal to the blob pinned at
    ``commit`` (compared by computing the blob OID of the bytes, so no object is read). Pass
    ``tree`` (from pinned_tree) to avoid listing the tree again. Raises ValueError."""
    problem = _path_problem(path)
    if problem:
        raise ValueError(f"{path!r}: the path {problem}")
    listing = pinned_tree(repo, commit) if tree is None else tree
    oid = listing.get(path)
    if oid is None:
        raise ValueError(f"{path} is not in the pinned tree of {Path(repo).name} at {commit[:12]}")
    try:
        data = confined_file(Path(repo), path).read_bytes()
    except (ValueError, OSError) as exc:
        raise ValueError(f"{path} is not materialised in {Path(repo).name}: {exc}") from exc
    if git_blob_oid(data) != oid:
        raise ValueError(f"{path} in {Path(repo).name} differs from the pinned blob {oid[:12]}; the checkout was modified")
    return data


def git_show(root: Path, commit: str, path: str) -> bytes:
    """The exact bytes of ``path`` at ``commit`` in the repository at ``root`` (a blob read with
    ``git cat-file blob``: no pager, text conversion or line-ending filter; lazy fetch disabled)."""
    if not isinstance(commit, str) or not OBJECT_RE.fullmatch(commit):
        raise ValueError(f"a commit is a full hexadecimal object name, not {commit!r}")
    problem = _path_problem(path)
    if problem:
        raise ValueError(f"{path!r}: the path {problem}")
    return _git(Path(root), "cat-file", "blob", f"{commit}:{path}")


REGULAR_MODES = ("100644", "100755")


@dataclass
class PathHistory:
    """Every version one path ever had in the history reachable from HEAD.

    ``versions`` maps each distinct object ID to the oldest commit (topological order) whose diff
    records the path with that object; ``removals`` lists the commits whose diff removes the path;
    ``modes`` maps an object ID to its Git mode when that version is not a regular file (a gitlink
    ``160000``, whose ID names a commit, or a symbolic link ``120000``). Merges are diffed against
    every parent (``git log --full-history -m``), so a version added, replaced or removed inside a
    merge, or on a branch merged later, is listed too. Counting distinct objects rather than commits
    keeps an ordinary merge of a branch that added the file (which records the same blob twice) at
    one version."""

    versions: dict[str, str]
    removals: list[str]
    modes: dict[str, str] = field(default_factory=dict)

    @property
    def irregular(self) -> list[tuple[str, str, str]]:
        """(object ID, oldest commit, mode) of every version that is not a regular file."""
        return [(oid, self.versions[oid], mode) for oid, mode in self.modes.items() if oid in self.versions]

    @property
    def committed(self) -> bool:
        return bool(self.versions or self.removals)

    @property
    def first(self) -> tuple[str, str] | None:
        """(blob, commit) of the oldest version, or None."""
        return next(iter(self.versions.items()), None)


def history_limit(repo: Path) -> str | None:
    """Why the Git history of ``repo`` may be incomplete (a shallow or a partial clone, whose missing
    commits or objects are never fetched here), or None."""
    repo = Path(repo)
    try:
        shallow = _git(repo, "rev-parse", "--is-shallow-repository").decode("utf-8").strip() == "true"
    except ValueError:
        shallow = False
    if shallow:
        return "this is a shallow clone (git fetch --unshallow gives the full history)"
    try:
        config = _git(repo, "config", "--get-regexp", r"^(remote\..*\.promisor|extensions\.partialclone)$")
    except ValueError:  # git config exits 1 when no key matches
        config = b""
    for line in config.decode("utf-8", "replace").splitlines():
        key, _space, value = line.partition(" ")
        value = value.strip().casefold()
        if (key.endswith(".promisor") and value in ("true", "yes", "on", "1")) or \
                (key == "extensions.partialclone" and value):
            return "this is a partial clone, whose missing objects are not fetched here (clone without --filter)"
    return None


# The user's Git configuration must not change what a history query lists: log.follow would turn a
# copy or rename into a line naming another path, log.diffMerges=combined|dense-combined|off would
# replace or drop the per-parent diffs of merges, and log.showRoot=false would hide the root
# commit's additions. Older Git versions ignore the keys they do not know.
_HISTORY_CONFIG = ("-c", "log.follow=false", "-c", "log.diffMerges=separate", "-c", "log.showRoot=true",
                   "-c", "log.showSignature=false", "-c", "diff.renames=false", "-c", "core.quotePath=true")


def _raw_history(repo: Path, rel: str, tip: str = "HEAD") -> list[tuple[str, list[str], list[str]]]:
    """``(commit, fields, paths)`` of every ``--raw`` line of ``git log`` for the pathspec ``rel``
    in the history reachable from ``tip`` (HEAD, or a full commit ID), oldest first (merges diffed
    against every parent). Raises ValueError when Git cannot read the history or prints a line in a
    form this parser does not know (a combined merge diff, or a copy or rename), so a caller reports
    "not verified" instead of silently missing a version."""
    problem = _path_problem(rel)
    if problem:
        raise ValueError(f"{rel!r}: the path {problem}")
    if tip != "HEAD" and not (isinstance(tip, str) and OBJECT_RE.fullmatch(tip)):
        raise ValueError(f"a history tip is HEAD or a full hexadecimal object name, not {tip!r}")
    output = _git(Path(repo), *_HISTORY_CONFIG, "log", "--full-history", "-m", "--no-renames", "--no-abbrev",
                  "--no-color", "--topo-order", "--reverse", "--format=%x01%H", "--raw", tip, "--",
                  f":(literal){rel}")
    lines: list[tuple[str, list[str], list[str]]] = []
    commit = None
    for line in output.decode("utf-8", "replace").splitlines():
        if line.startswith("\x01"):
            commit = line[1:].strip()
            continue
        if not line.startswith(":"):
            continue
        meta, _tab, rest = line.partition("\t")
        fields = meta.split()
        paths = rest.split("\t") if rest else []
        if commit is None or meta.startswith("::") or len(fields) != 5 or len(paths) != 1 \
                or fields[4][:1] not in ("A", "M", "D", "T"):
            raise ValueError(f"git log printed a history line of {rel} in an unexpected form: {line[:120]!r}")
        lines.append((commit, fields, paths))
    return lines


def path_history(repo: Path, rel: str, tip: str = "HEAD") -> PathHistory:
    """The :class:`PathHistory` of ``rel`` in the repository at ``repo``, in the history reachable
    from ``tip`` (HEAD by default). Raises ValueError when Git cannot read the history (for example
    an object missing from a partial clone)."""
    versions: dict[str, str] = {}
    removals: list[str] = []
    modes: dict[str, str] = {}
    for commit, fields, paths in _raw_history(repo, rel, tip):
        if paths[0] != rel:
            continue
        blob, mode = fields[3], fields[1]
        if not blob.strip("0"):
            removals.append(commit)
            continue
        if blob not in versions:
            versions[blob] = commit
        if mode not in REGULAR_MODES:
            modes.setdefault(blob, mode)
    return PathHistory(versions, removals, modes)


def version_hashes(repo: Path, rel: str, tip: str) -> dict[str, str]:
    """``{sha256: commit}`` of every regular-file version ``rel`` had in the history reachable from
    the commit ``tip`` (merges included; each version with the oldest commit that recorded it). A
    version of a file at any commit of that history is listed, because every such version is the
    one some commit of the history recorded. Raises ValueError when Git cannot read the history or
    a version's bytes."""
    found: dict[str, str] = {}
    history = path_history(repo, rel, tip)
    for oid, commit in history.versions.items():
        if oid in history.modes:
            continue  # a gitlink or a symbolic link is not a version of a file
        found.setdefault(sha256_bytes(_git(Path(repo), "cat-file", "blob", oid)), commit)
    return found


def committed_paths(repo: Path, rel: str) -> dict[str, str]:
    """``{path: oldest commit}`` of every path under the directory ``rel`` that the history reachable
    from HEAD ever recorded (merges diffed against every parent, removals included). Raises
    ValueError when Git cannot read the history."""
    found: dict[str, str] = {}
    for commit, _fields, paths in _raw_history(repo, rel):
        if paths[0].startswith(rel.rstrip("/") + "/"):
            found.setdefault(paths[0], commit)
    return found


# --------------------------------------------------------------------------------------------
# Helper semantics


_DEFAULT_HELPER: types.ModuleType | None = None


def load_helper(source: bytes | None = None) -> types.ModuleType:
    """A fresh module of the skill helper: skills/mlview/scripts/artifact.py, or the given bytes
    (for example the frozen helper read with git_show). The module is not registered in
    sys.modules and its ``main`` does not run."""
    if source is None:
        data, filename = HELPER_PATH.read_bytes(), str(HELPER_PATH)
    else:
        data = bytes(source)
        filename = f"<artifact.py sha256:{sha256_bytes(data)[:12]}>"
    module = types.ModuleType(f"_mlview_helper_{sha256_bytes(data)[:16]}")
    module.__file__ = filename
    exec(compile(data, filename, "exec", dont_inherit=True), module.__dict__)
    missing = [name for name in HELPER_NAMES if not callable(getattr(module, name, None))]
    if missing:
        raise ValueError(f"{filename} is not the MLView helper (missing {', '.join(missing)})")
    return module


def _helper(helper: types.ModuleType | None) -> types.ModuleType:
    global _DEFAULT_HELPER
    if helper is not None:
        return helper
    if _DEFAULT_HELPER is None:
        _DEFAULT_HELPER = load_helper()
    return _DEFAULT_HELPER


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def source_lines(data: bytes, cell: int | None, helper: types.ModuleType | None = None) -> list[str]:
    """The lines the helper compares quotes against: UTF-8, BOM stripped (``_strip_bom``), a
    notebook cell's joined source (``_parse_notebook``), split by ``_lines`` (a final newline
    leaves a trailing empty element). Raises ValueError where the helper would refuse the source."""
    module = _helper(helper)
    limit = getattr(module, "MAX_SOURCE", None)
    if isinstance(limit, int) and len(data) > limit:
        raise ValueError(f"the source exceeds {limit} bytes")
    try:
        text = module._strip_bom(bytes(data).decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError("the source is not UTF-8") from None
    if cell is None:
        return module._lines(text)
    if not _is_int(cell) or cell < 0:
        raise ValueError("a notebook cell is a zero-based integer index")
    notebook = module._parse_notebook(text)
    try:
        if notebook is None:
            raise ValueError
        source = notebook["cells"][cell]["source"]
        text = "".join(source) if isinstance(source, list) else source
        if not isinstance(text, str):
            raise TypeError
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError(f"cell {cell} does not identify valid notebook source") from None
    return module._lines(text)


def human_line_count(lines: list[str]) -> int:
    """The line count a person sees: a trailing empty element (after a final newline) is dropped."""
    return len(lines) - 1 if lines and lines[-1] == "" else len(lines)


def excerpt(lines: list[str], line: int, end: int) -> str:
    """The helper's excerpt of lines ``line``..``end`` (inclusive) joined by LF; ValueError when the
    range is one the helper refuses (``range``)."""
    if not _is_int(line) or not _is_int(end) or line < 1 or end < line or end > len(lines):
        raise ValueError(f"lines {line}-{end} are out of range; the source has {human_line_count(lines)} lines")
    return "\n".join(lines[line - 1:end])


def quote_matches(quote: object, lines: list[str], line: int, end: int,
                  helper: types.ModuleType | None = None) -> bool:
    """The helper's quote comparison: exact, except that a line-1 quote may include or omit a BOM."""
    try:
        expected = excerpt(lines, line, end)
    except ValueError:
        return False
    if not isinstance(quote, str):
        return False
    if line == 1:
        strip = _helper(helper)._strip_bom
        return strip(quote) == strip(expected)
    return quote == expected


def is_rfc3339(value: str, helper: types.ModuleType | None = None) -> bool:
    """The helper's strict RFC 3339 date-time profile (``_rfc3339``)."""
    return isinstance(value, str) and bool(_helper(helper)._rfc3339(value))


def safe_streams() -> None:
    """Let stdout and stderr write any text: a character their encoding lacks (a Windows code page for a
    redirect, a pipe or Git Bash without UTF-8 mode) becomes a backslash escape instead of an error."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except (AttributeError, OSError, TypeError, ValueError):
                pass


def rfc3339_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------------
# Sparse patterns, required paths and the task manifest


def validate_sparse_patterns(p: Sequence[str]) -> None:
    """Accept only the non-cone subset sparse_covers implements; raise ValueError otherwise."""
    if isinstance(p, (str, bytes)) or not isinstance(p, Sequence):
        raise ValueError("sparse patterns must be a list of strings")
    for pattern in p:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"unsupported sparse pattern {pattern!r}: patterns are non-empty strings")
        if pattern != pattern.strip() or pattern.startswith("#"):
            raise ValueError(f"unsupported sparse pattern {pattern!r}: no surrounding spaces or comments")
        bad = [token for token in _SPARSE_FORBIDDEN if token in pattern]
        if bad:
            raise ValueError(f"unsupported sparse pattern {pattern!r}: {' '.join(bad)} is not supported")
        if pattern.endswith("/"):
            raise ValueError(f"unsupported sparse pattern {pattern!r}: no trailing /")
        parts = (pattern[1:] if pattern.startswith("/") else pattern).split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"unsupported sparse pattern {pattern!r}: empty, . or .. component")


def sparse_covers(patterns: Sequence[str], path: str) -> bool:
    """Whether Git's non-cone sparse checkout with ``patterns`` materialises ``path``.

    A pattern with a leading or inner ``/`` is anchored at the root and matched component by
    component with ``fnmatchcase`` (so ``*`` never crosses ``/``; validate_sparse_patterns leaves
    ``*`` as the only wildcard); matching a leading run of components covers the subtree. A pattern without ``/`` matches any single component. An empty list is a full
    checkout. Matching is case-sensitive, as with ``core.ignorecase=false``.
    """
    validate_sparse_patterns(patterns)
    problem = _path_problem(path)
    if problem:
        raise ValueError(f"{path!r}: the path {problem}")
    if not patterns:
        return True
    parts = path.split("/")
    for pattern in patterns:
        if "/" in pattern:
            comps = (pattern[1:] if pattern.startswith("/") else pattern).split("/")
            if len(parts) >= len(comps) and all(fnmatchcase(part, comp) for part, comp in zip(parts, comps)):
                return True
        elif any(fnmatchcase(part, pattern) for part in parts):
            return True
    return False


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{path} does not exist") from None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def required_paths(task_id: str, root: Path = ROOT) -> list[str]:
    """Every repository path a task needs, sorted: its tasks.json ``entrypoints``; for a held-out
    task also the candidate ledger's scenario entrypoints and anchor files, and after a freeze the
    frozen reference's ``sourceFiles``. Scenario arguments are never parsed."""
    if not isinstance(task_id, str) or not NAME_RE.fullmatch(task_id):
        raise ValueError(f"not a task ID: {task_id!r}")
    root = Path(root)
    manifest = _read_json(root / TASKS_REL)
    tasks = manifest.get("tasks") if isinstance(manifest, dict) else None
    task = next((t for t in tasks or [] if isinstance(t, dict) and t.get("id") == task_id), None)
    if task is None:
        raise ValueError(f"unknown task {task_id!r}")
    paths = set(_strings(task.get("entrypoints"), f"{task_id} entrypoints"))
    if task.get("split") == "heldout":
        ledger = _read_json(root / CANDIDATES_REL / f"{task_id}.json")
        if not isinstance(ledger, dict) or not isinstance(ledger.get("scenario"), dict):
            raise ValueError(f"{task_id}: the candidate ledger has no scenario")
        paths.update(_strings(ledger["scenario"].get("entrypoints"), f"{task_id} scenario entrypoints"))
        for fact in ledger.get("facts") or []:
            for anchor in (fact.get("anchors") or []) if isinstance(fact, dict) else []:
                paths.update(_strings([anchor.get("file") if isinstance(anchor, dict) else None], f"{task_id} anchors"))
        freeze = manifest.get("pilotFreeze")
        if freeze is not None:
            pointer = freeze.get("freeze") if isinstance(freeze, dict) else None
            if not isinstance(pointer, str) or _path_problem(pointer):
                raise ValueError("tasks.json pilotFreeze.freeze is not a relative path")
            reference = (root / EVAL_REL / pointer).parent / "reference" / f"{task_id}.json"
            frozen = _read_json(reference)
            sources = frozen.get("sourceFiles") if isinstance(frozen, dict) else None
            if not isinstance(sources, dict):
                raise ValueError(f"{reference} has no sourceFiles")
            paths.update(_strings(list(sources), f"{task_id} frozen sourceFiles"))
    for path in paths:
        problem = _path_problem(path)
        if problem:
            raise ValueError(f"{task_id}: required path {path!r} {problem}")
    return sorted(paths)


def _strings(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{what} must be a list of non-empty strings")
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_task_manifest(manifest: dict) -> list[str]:
    """Problems with tasks.json (empty when it is usable): the fixed six ``pilotTargets`` keys, task
    identity fields and the ``referenceStatus`` state machine. Before a freeze every task is
    ``needs-human-review`` and there is no ``pilotFreeze``; after it every held-out task is
    ``frozen``, development tasks stay ``needs-human-review`` and ``pilotFreeze`` names the freeze."""
    if not isinstance(manifest, dict):
        return ["tasks.json must be a JSON object"]
    problems: list[str] = []
    unknown = sorted(set(manifest) - MANIFEST_KEYS)
    if unknown:
        problems.append(f"unknown top-level key(s): {', '.join(unknown)}")
    missing = [key for key in MANIFEST_REQUIRED if key not in manifest]
    if missing:
        problems.append(f"missing top-level key(s): {', '.join(missing)}")
    if "version" in manifest and (not _is_int(manifest["version"]) or manifest["version"] != 1):
        problems.append("version must be 1")
    hosts = manifest.get("hosts")
    if "hosts" in manifest and (not isinstance(hosts, list) or not hosts
                                or not all(isinstance(h, str) and NAME_RE.fullmatch(h) for h in hosts)
                                or len(set(hosts)) != len(hosts)):
        problems.append("hosts must be a non-empty list of unique lowercase host names")
    repetitions = manifest.get("repetitions")
    if "repetitions" in manifest and (not _is_int(repetitions) or repetitions < 1):
        problems.append("repetitions must be a positive integer")
    targets = manifest.get("pilotTargets")
    if "pilotTargets" in manifest:
        if not isinstance(targets, dict):
            problems.append("pilotTargets must be an object")
        else:
            absent = [key for key in PILOT_TARGET_KEYS if key not in targets]
            extra = sorted(set(targets) - set(PILOT_TARGET_KEYS))
            if absent or extra:
                detail = "; ".join(part for part in (
                    f"missing {', '.join(absent)}" if absent else "",
                    f"unexpected {', '.join(extra)}" if extra else "") if part)
                problems.append(f"pilotTargets must have exactly the keys {', '.join(PILOT_TARGET_KEYS)} ({detail})")
            for key in RATE_TARGET_KEYS:
                if key in targets and not (_is_number(targets[key]) and 0 <= targets[key] <= 1):
                    problems.append(f"pilotTargets.{key} must be a number from 0 to 1")
            count = targets.get("highSeverityFalseAccusations")
            if "highSeverityFalseAccusations" in targets and (not _is_int(count) or count < 0):
                problems.append("pilotTargets.highSeverityFalseAccusations must be a non-negative integer")
    tasks = manifest.get("tasks")
    valid_tasks: list[dict] = []
    if "tasks" in manifest:
        if not isinstance(tasks, list) or not tasks:
            problems.append("tasks must be a non-empty list")
            tasks = []
        seen: set[str] = set()
        for index, task in enumerate(tasks):
            where = f"tasks[{index}]"
            if not isinstance(task, dict):
                problems.append(f"{where} must be an object")
                continue
            task_id = task.get("id")
            if not isinstance(task_id, str) or not NAME_RE.fullmatch(task_id) or task_id in seen:
                problems.append(f"{where}: id must be a unique lowercase task ID")
            else:
                seen.add(task_id)
                where = task_id
            if task.get("split") not in TASK_SPLITS:
                problems.append(f"{where}: split must be one of {', '.join(TASK_SPLITS)}")
            for key in ("repository", "prompt"):
                if not isinstance(task.get(key), str) or not task[key].strip():
                    problems.append(f"{where}: {key} must be a non-empty string")
            entrypoints = task.get("entrypoints")
            if (not isinstance(entrypoints, list) or not entrypoints
                    or not all(isinstance(p, str) and not _path_problem(p) for p in entrypoints)):
                problems.append(f"{where}: entrypoints must be a non-empty list of relative paths")
            if task.get("referenceStatus") not in REFERENCE_STATUSES:
                problems.append(f"{where}: referenceStatus must be one of {', '.join(REFERENCE_STATUSES)}")
            if task.get("split") == "heldout":
                if not isinstance(task.get("commit"), str) or not SHA1_RE.fullmatch(task["commit"]):
                    problems.append(f"{where}: a held-out task needs a full 40-hex commit")
                if not isinstance(task.get("url"), str) or not task["url"].strip():
                    problems.append(f"{where}: a held-out task needs a url")
            valid_tasks.append(task)
    if "pilotFreeze" not in manifest:
        for task in valid_tasks:
            if task.get("referenceStatus") == "frozen":
                problems.append(f"{task.get('id')}: referenceStatus is frozen but tasks.json has no pilotFreeze; "
                                "only a freeze sets it")
        return problems
    freeze = manifest["pilotFreeze"]
    campaign = None
    if not isinstance(freeze, dict) or set(freeze) != PILOT_FREEZE_KEYS:
        problems.append(f"pilotFreeze must have exactly the keys {', '.join(sorted(PILOT_FREEZE_KEYS))}")
    else:
        campaign = freeze.get("campaign")
        if not isinstance(campaign, str) or not NAME_RE.fullmatch(campaign):
            problems.append("pilotFreeze.campaign must be a lowercase campaign name such as pilot-01")
            campaign = None
        elif freeze.get("freeze") != f"pilot/{campaign}/freeze.json":
            problems.append(f"pilotFreeze.freeze must be pilot/{campaign}/freeze.json")
        if not isinstance(freeze.get("referenceRevision"), str) or not REVISION_RE.fullmatch(freeze["referenceRevision"]):
            problems.append('pilotFreeze.referenceRevision must be "sha256:" followed by 64 hex digits')
    frozen_by = f"the freeze of {campaign}" if campaign else "the freeze"
    if not any(task.get("split") == "heldout" for task in valid_tasks):
        problems.append("pilotFreeze needs at least one held-out task")
    for task in valid_tasks:
        status = task.get("referenceStatus")
        if task.get("split") == "heldout" and status != "frozen":
            problems.append(f"{task.get('id')}: a held-out task must be frozen after {frozen_by} (is {status})")
        if task.get("split") == "development" and status != "needs-human-review":
            problems.append(f"{task.get('id')}: a development task stays needs-human-review (is {status})")
    return problems


# --------------------------------------------------------------------------------------------
# Paths and files


def _path_problem(rel: object) -> str | None:
    """Why ``rel`` is not a plain relative POSIX path inside its root, or None."""
    if not isinstance(rel, str) or not rel:
        return "must be a non-empty relative path"
    if "\0" in rel:
        return "must not contain NUL"
    if "\\" in rel:
        return "must use / as the separator"
    if rel.startswith("/") or DRIVE_RE.match(rel):
        return "must be relative, not absolute"
    if ":" in rel:
        return "must not contain ':'"
    if any(part in {"", ".", ".."} for part in rel.split("/")):
        return "must stay inside its root (no empty, . or .. components)"
    return None


# Windows reparse tags of symbolic links and junctions (the stat constants exist only on Windows).
_LINK_REPARSE_TAGS = (getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
                      getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003))


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in _LINK_REPARSE_TAGS


def confined_file(root: Path, rel: str) -> Path:
    """``root/rel`` when ``rel`` is a relative POSIX path without ``..``, no component below
    ``root`` is a symbolic link (or junction) and the target is a regular file; else ValueError."""
    problem = _path_problem(rel)
    if problem:
        raise ValueError(f"{rel!r} {problem}")
    current = Path(root)
    info = None
    for part in rel.split("/"):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise ValueError(f"{rel} does not exist") from None
        except OSError as exc:
            raise ValueError(f"{rel} cannot be read: {exc.strerror or exc}") from None
        if _is_link(info):
            raise ValueError(f"{rel} passes through a symbolic link")
    if info is None or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{rel} is not a regular file")
    return current


def outside_repositories(path: Path, mlview_root: Path = ROOT) -> list[str]:
    """Why ``path`` cannot hold pilot workspaces and evidence (empty when it can): it is inside the
    MLView checkout, inside a Git work tree, or it or a parent directory holds a file a host reads
    as instructions (CLAUDE.md, CLAUDE.local.md, AGENTS.md, AGENTS.override.md,
    .github/copilot-instructions.md). ``path`` need not exist yet."""
    reasons: list[str] = []
    given = Path(path).expanduser()
    target = given.resolve()
    root = Path(mlview_root).resolve()
    if target == root or root in target.parents:
        reasons.append(f"{target} is inside the MLView checkout {root}")
    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    work_tree = next((d for d in (existing, *existing.parents) if os.path.lexists(d / ".git")), None)
    if work_tree is not None:
        reasons.append(f"{target} is inside the Git work tree {work_tree}")
    else:
        env = _git_env()
        env["GIT_DISCOVERY_ACROSS_FILESYSTEM"] = "1"
        try:
            result = subprocess.run(["git", "-C", str(existing), "rev-parse", "--is-inside-work-tree"],
                                    capture_output=True, env=env, check=False)
        except OSError:
            result = None
        if result is not None and result.returncode == 0:
            where = "work tree" if result.stdout.strip() == b"true" else "repository directory"
            reasons.append(f"{target} is inside a Git {where} (git rev-parse --is-inside-work-tree succeeds)")
    directories: list[Path] = []
    # The real (resolved) path and the logical one, lexically normalised: "<checkout>/../pilot" has the
    # checkout's parent as its parent, never the checkout itself.
    for start in (target, Path(os.path.abspath(given))):
        for directory in (start, *start.parents):
            if directory not in directories:
                directories.append(directory)
    for directory in directories:
        for name in INSTRUCTION_FILES:
            if os.path.lexists(directory / name):
                reasons.append(f"{directory / name} would be read by a host as instructions")
    return reasons


def canonical_json(value: object) -> bytes:
    """Canonical JSON bytes: sorted keys, two-space indent, UTF-8, one trailing newline, no NaN."""
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def write_exclusive(path: Path, data: bytes) -> None:
    """Create ``path`` with ``data``; FileExistsError if it exists. A failed write leaves no file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def write_atomic(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically (temporary file in the same directory, then
    os.replace), keeping an existing file's permissions. A symbolic link is refused."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"{path} is a symbolic link; refusing to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mask = os.umask(0)
        os.umask(mask)
        mode = 0o666 & ~mask
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    if os.name != "nt":
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        except OSError:
            pass
        finally:
            os.close(directory)


def run_dir_name(run_id: str) -> str:
    """The directory name of a pilot run ID (``pilot-nanogpt:codex:1`` -> ``pilot-nanogpt.codex.1``);
    Windows forbids ``:`` in file names (N8)."""
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"not a pilot run ID: {run_id!r} (expected <task>:<host>:<n> or <task>:<host>:baseline:<n>)")
    return run_id.replace(":", ".")


def run_id_from_dir(name: str) -> str:
    """The pilot run ID of a run directory name; the inverse of run_dir_name."""
    if not isinstance(name, str) or not RUN_DIR_RE.fullmatch(name):
        raise ValueError(f"not a pilot run directory: {name!r} (expected <task>.<host>.<n> or <task>.<host>.baseline.<n>)")
    return name.replace(".", ":")
