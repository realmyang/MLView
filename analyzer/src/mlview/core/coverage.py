"""Coverage diagnostics: say when the analysis was blind (COVERAGE).

MLView's worst failure mode is that it cannot distinguish *"I checked and it is
fine"* from *"I could not check"*. Two measured instances of one defect get a
voice here, both `Diagnostic.kind` values added by CONTRACTS amendment 11.18:

* **`untagged_dataflow`** - a leakage-family rule reached a `fit` / `split`
  site whose key argument carries **no `ValueTag` at all**, which is what
  happens the moment the value arrives as a function parameter. The rule is
  silent by design (that silence is what keeps precision at 100%), but silence
  and "no leak here" must not look the same.
* **`single_file_analysis`** - one file of a larger package was analyzed. On
  `samples/vision_pipeline/train.py` that is a **57% loss**, measured: 3
  findings against the 7 the same file yields inside its directory, because
  MLV301 / MLV302 / MLV401 / MLV501 need `model.py` and `data.py`.

Neither changes a rule's gate, so the demo's 15 issues and both clean corpora
are untouched; they only make the analyzer's blind spots visible.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

from .graph import Diagnostic

__all__ = ["COVERAGE_KINDS", "UntaggedNotes", "single_file_diagnostic"]

#: The kinds this module emits. The summary emitter gives them their own block.
COVERAGE_KINDS = ("untagged_dataflow", "single_file_analysis")

#: How many sites one `untagged_dataflow` message names before it counts.
_NAMED_SITES = 3
#: How many sibling modules one `single_file_analysis` message names.
_NAMED_SIBLINGS = 4
#: Ceiling on the sibling walk, so the check stays cheap on a huge package.
#: Past it the message says "at least N" rather than overclaiming a total.
_SIBLING_CAP = 1000


# ---------------------------------------------------------------------------
# untagged_dataflow
# ---------------------------------------------------------------------------
class UntaggedNotes:
    """Accumulates untraced-value sites into one diagnostic per scope.

    One diagnostic per `(file, scope)` rather than per site: a helper called in
    a loop would otherwise produce a diagnostic per iteration, and the rule
    codes that gave up on the same scope belong on one row - the shape
    `framework_suppressed` already uses.
    """

    def __init__(self, diagnostics: List[Diagnostic]):
        self.diagnostics = diagnostics
        self._by_scope: Dict[Tuple[str, str], Diagnostic] = {}
        self._sites: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
        self._codes: Dict[Tuple[str, str], List[str]] = {}

    def note(self, code: str, file: str, line: int, scope: str,
             variable: Optional[str], reason: str) -> Diagnostic:
        """Record that `code` could not check `variable` at `file:line`."""
        key = (file or "", scope or "")
        name = variable or "the value"
        sites = self._sites.setdefault(key, [])
        if (name, line) not in sites:
            sites.append((name, line))
        codes = self._codes.setdefault(key, [])
        if code and code not in codes:
            codes.append(code)
        diagnostic = self._by_scope.get(key)
        if diagnostic is None:
            diagnostic = Diagnostic(kind="untagged_dataflow", message="",
                                    file=file or None, line=line or None,
                                    scope=scope or None)
            self._by_scope[key] = diagnostic
            self.diagnostics.append(diagnostic)
        diagnostic.line = min(line for _n, line in sites) or None
        diagnostic.codes = sorted(codes)
        diagnostic.count = len(sites)
        diagnostic.message = _untagged_message(scope, sites, sorted(codes), reason)
        return diagnostic


def _untagged_message(scope: str, sites: Sequence[Tuple[str, int]],
                      codes: Sequence[str], reason: str) -> str:
    named = ", ".join("`%s` (line %d)" % (name, line)
                      for name, line in sorted(sites, key=lambda s: (s[1], s[0]))
                      [:_NAMED_SITES])
    more = ("" if len(sites) <= _NAMED_SITES
            else " and %d more" % (len(sites) - _NAMED_SITES))
    return ("%s stayed silent in %s: %s%s carr%s no dataflow tag (%s), so leakage "
            "through %s is neither confirmed nor ruled out - a gap in coverage, "
            "not a clean result."
            % (", ".join(codes) or "A leakage rule", scope or "this scope",
               named, more, "ies" if len(sites) == 1 else "y", reason,
               "it" if len(sites) == 1 else "them"))


# ---------------------------------------------------------------------------
# single_file_analysis
# ---------------------------------------------------------------------------
def _package_root(abs_file: str) -> str:
    """The nearest ancestor that is *not* itself inside a package."""
    directory = os.path.dirname(abs_file)
    while os.path.isfile(os.path.join(directory, "__init__.py")):
        parent = os.path.dirname(directory)
        if not parent or parent == directory:
            break
        directory = parent
    return directory


def single_file_diagnostic(found, workspace, cross_file_codes: Sequence[str],
                           include: Sequence[str] = (),
                           exclude: Sequence[str] = ()) -> Optional[Diagnostic]:
    """The `single_file_analysis` note, or None when the run was not one file.

    Fires only when all three hold: exactly one module was analyzed, sibling
    Python modules exist beside it, and the analyzed module **imports** at
    least one of them. The import is what turns "you asked about one file" into
    "the answer you got is incomplete": a standalone script with no siblings in
    scope loses nothing, and saying otherwise would be crying wolf.
    """
    from ..ingest.discover import discover      # local: cyclic at import time

    if len(found.files) != 1:
        return None
    relpath = found.files[0]
    module = workspace.modules.get(relpath) if workspace is not None else None
    if module is None:
        return None
    abs_file = found.abspath(relpath)
    package_root = _package_root(abs_file)
    # Bounded: this runs on every single-file analysis, including the VS Code
    # extension's analyze-on-save, and a monorepo package can be enormous.
    siblings = discover([package_root], include=include, exclude=exclude,
                        max_files=_SIBLING_CAP)
    others = sorted(name for name in siblings.files
                    if siblings.abspath(name) != abs_file)
    if not others:
        return None
    at_least = "at least " if siblings.file_cap_hit else ""

    dotted = {os.path.splitext(name)[0].replace("/", ".") for name in others}
    dotted |= {name.rsplit("/", 1)[-1][:-3] for name in others if name.endswith(".py")}
    dotted.discard("")
    imported = sorted(
        name for name in (getattr(module, "imports", ()) or ())
        if name in dotted or any(d.endswith("." + name) or d == name for d in dotted))
    if not imported:
        return None

    named = ", ".join(others[:_NAMED_SIBLINGS])
    if len(others) > _NAMED_SIBLINGS:
        named += " and %d more" % (len(others) - _NAMED_SIBLINGS)
    codes = sorted(cross_file_codes)
    return Diagnostic(
        kind="single_file_analysis",
        message="Only %s was analyzed: %s%d sibling module(s) in the same package "
                "were not (%s), and %s imports %d of them. Rules that need "
                "cross-file evidence (%s) cannot see those definitions, so a "
                "clean result here is not a clean result for the package - "
                "analyze the directory to widen."
                % (relpath, at_least, len(others), named, relpath, len(imported),
                   ", ".join(codes) or "none registered"),
        file=relpath, codes=codes or None, count=len(others))
