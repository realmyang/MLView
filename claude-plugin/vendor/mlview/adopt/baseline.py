"""The baseline ratchet (CI-ADOPT part b).

A realistic 50-file repo starts at 111 findings, so `--fail-on high` exits 2
forever and the only way to adopt MLView is never to gate on it. The ratchet
is the fix: record what is there today, gate on what arrives tomorrow.

    mlview baseline write [PATHS] [--out .mlview/baseline.json]
    mlview issues . --baseline .mlview/baseline.json --fail-on high

**The match key is `(code, symbol, snippetHash)`**, where `snippetHash` is the
SHA-1 of the whitespace-normalised primary snippet. Deliberately **not** the
file or the line:

* not the line, because a baseline that dies on an unrelated edit above the
  finding is a baseline nobody keeps;
* not the file, because a moved or renamed module is the same finding, and
  `git diff -M` already teaches the change attribution the same lesson.

The cost is stated rather than hidden: two textually identical findings of the
same rule in two files share one key. **Matching is therefore counted, not
keyed alone** - a key recorded `n` times baselines the first `n` findings that
carry it, in document order, and the `n+1`th is reported. Copying a bad
training loop into a second function does not arrive pre-forgiven, which is
precisely what a ratchet is for. An entry is *marked*, never deleted:
`--show-suppressed` still shows every one, with `baselined: true` on it.

**Unmatched entries are reported.** A baseline that has silently stopped
matching is a gate that has silently stopped gating, so `N baseline entries no
longer match` is a `config_warning` on every run.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.graph import Diagnostic, MLGraph

__all__ = ["BASELINE_VERSION", "DEFAULT_BASELINE_PATH", "snippet_hash",
           "issue_key", "build_baseline", "write_baseline", "load_baseline",
           "apply_baseline"]

#: Format version of the baseline document itself.
BASELINE_VERSION = 1
DEFAULT_BASELINE_PATH = ".mlview/baseline.json"


def snippet_hash(snippet: Optional[str]) -> str:
    """SHA-1 (12 hex, the house width) of the whitespace-normalised snippet.

    Normalisation is `" ".join(text.split())`: indentation, trailing spaces and
    a reflowed line break all collapse, so a formatter run does not invalidate
    a baseline. A missing snippet hashes the empty string rather than falling
    back to something line-derived.
    """
    normalised = " ".join((snippet or "").split())
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:12]


def issue_key(code: str, symbol: str, digest: str) -> Tuple[str, str, str]:
    return (code or "", symbol or "", digest or "")


def _key_of(issue) -> Tuple[str, str, str]:
    loc = getattr(issue, "loc", None)
    return issue_key(getattr(issue, "code", ""), getattr(loc, "symbol", "") or "",
                     snippet_hash(getattr(loc, "snippet", "") or ""))


# ------------------------------------------------------------------ write
def build_baseline(graph: MLGraph) -> Dict[str, Any]:
    """The baseline document for `graph`, deterministic and diff-friendly.

    Carries **no timestamp and no version of the analyzer**: the file is
    committed, reviewed and re-generated, and a byte that changes for no
    reason is a byte somebody has to read. `file`, `line` and `title` are
    written for the human reviewing the pull request that adds it and are
    never matched on.
    """
    entries: List[Dict[str, Any]] = []
    for issue in graph.issues:
        if getattr(issue, "suppressed", False):
            continue                      # already invisible; not a ratchet entry
        loc = issue.loc
        entries.append({
            "code": issue.code,
            "symbol": getattr(loc, "symbol", "") or "",
            "snippetHash": snippet_hash(getattr(loc, "snippet", "") or ""),
            "file": getattr(loc, "file", ""),
            "line": getattr(loc, "line", 0),
            "title": issue.title,
        })
    entries.sort(key=lambda e: (e["code"], e["symbol"], e["snippetHash"],
                                e["file"], e["line"]))
    return {"version": BASELINE_VERSION, "tool": "mlview", "entries": entries}


def write_baseline(graph: MLGraph, path: str) -> str:
    """Write `build_baseline(graph)`; returns the absolute forward-slashed path."""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(build_baseline(graph), indent=2,
                                ensure_ascii=False) + "\n")
    return abs_path.replace("\\", "/")


# ------------------------------------------------------------------- read
def load_baseline(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """`(entries, error)`. A bad baseline is a `config_warning`, never an exit.

    A file that cannot be read, is not JSON, or was written by a newer format
    yields `([], reason)` - the run then reports every finding, which is the
    safe direction for a gate to fail in.
    """
    try:
        with open(path, encoding="utf-8-sig") as handle:
            doc = json.load(handle)
    except OSError as exc:
        return [], "cannot read %s: %s" % (path, exc)
    except ValueError as exc:
        return [], "%s is not valid JSON: %s" % (path, exc)
    if not isinstance(doc, dict):
        return [], "%s is not a baseline document" % path
    version = doc.get("version")
    if version != BASELINE_VERSION:
        return [], ("%s declares baseline version %r; this build writes version %d"
                    % (path, version, BASELINE_VERSION))
    raw = doc.get("entries")
    if not isinstance(raw, list):
        return [], "%s carries no entries[] array" % path
    entries = [e for e in raw if isinstance(e, dict) and e.get("code")]
    return entries, ""


def apply_baseline(graph: MLGraph, entries: Sequence[Dict[str, Any]],
                   path: str, load_error: str = "") -> List[Diagnostic]:
    """Mark baselined issues and report entries that no longer match."""
    if load_error:
        return [Diagnostic(
            kind="config_warning",
            message="baseline ignored: %s. Every finding is reported. Re-create "
                    "it with `mlview baseline write --out %s`." % (load_error, path))]

    by_key: Dict[Tuple[str, str, str], List[Any]] = {}
    for issue in graph.issues:
        by_key.setdefault(_key_of(issue), []).append(issue)

    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for entry in entries:
        key = issue_key(entry.get("code", ""), entry.get("symbol", "") or "",
                        entry.get("snippetHash", "") or "")
        grouped.setdefault(key, []).append(entry)

    unmatched: List[Dict[str, Any]] = []
    matched = 0
    for key, rows in grouped.items():
        hits = by_key.get(key, [])
        # Counted matching: `len(rows)` entries forgive `len(rows)` findings,
        # in document order. A duplicated finding beyond that count is new.
        for issue in hits[:len(rows)]:
            issue.baselined = True
            matched += 1
        if len(rows) > len(hits):
            unmatched.extend(rows[len(hits):])

    diagnostics: List[Diagnostic] = []
    if unmatched:
        named = ", ".join("%s at %s:%s" % (e.get("code", "?"), e.get("file", "?"),
                                           e.get("line", "?"))
                          for e in unmatched[:3])
        more = "" if len(unmatched) <= 3 else " (+%d more)" % (len(unmatched) - 3)
        diagnostics.append(Diagnostic(
            kind="config_warning",
            message="%d baseline entries no longer match: %s%s. They were fixed, "
                    "moved or reworded; re-run `mlview baseline write --out %s` "
                    "to tighten the ratchet." % (len(unmatched), named, more, path),
            count=len(unmatched)))
    if matched:
        diagnostics.append(Diagnostic(
            kind="config_warning",
            message="%d finding(s) matched %s and are marked baselined: still "
                    "emitted, excluded from the counts and from --fail-on. Use "
                    "--show-suppressed to list them." % (matched, path),
            count=matched))
    return diagnostics
