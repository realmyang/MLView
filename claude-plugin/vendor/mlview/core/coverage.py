"""Coverage diagnostics: say when the analysis was blind (COVERAGE).

MLView's worst failure mode is that it cannot distinguish *"I checked and it is
fine"* from *"I could not check"*. Two measured instances of one defect get a
voice here, both `Diagnostic.kind` values added by CONTRACTS amendment 11.18:

* **`untagged_dataflow`** - a `fit` / `fit_transform` / `split` / `DataLoader`
  site whose key argument carries **no `ValueTag` at all**, which is what
  happens the moment the value arrives as a function parameter. The rules are
  silent by design (that silence is what keeps precision at 100%), but silence
  and "no leak here" must not look the same.
* **`single_file_analysis`** - a strict subset of the Python in a package was
  analyzed. On `samples/vision_pipeline/train.py` that is a **57% loss**,
  measured: 3 findings against the 7 the same file yields inside its directory,
  because MLV301 / MLV302 / MLV401 / MLV501 need `model.py` and `data.py`.

Neither changes a rule's gate, so the demo's 15 issues and both clean corpora
are untouched; they only make the analyzer's blind spots visible.

`untagged_dataflow` used to be reachable **only** from MLV101 and MLV102
(TB-10): those two gates were its only callers, so an untraced `SPLIT`,
`LOADER` or `FIT` site outside the leakage pair was silent, and its silence was
indistinguishable from a clean file. `note_untraced_sites` now sweeps the call
index once, after the rules, so the coverage claim no longer depends on which
rules happened to run.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

from .graph import Diagnostic

__all__ = ["COVERAGE_KINDS", "UNTRACED_ROLES", "UntaggedNotes",
           "note_untraced_sites", "note_unconfirmed_train_loops",
           "single_file_diagnostic", "framework_filter_diagnostic"]

#: The kinds this module emits. The summary emitter gives them their own block.
COVERAGE_KINDS = ("untagged_dataflow", "single_file_analysis", "framework_filter")

#: Roles the post-rule sweep declares a coverage gap for (TB-10).
#:
#: `FORWARD` and `DATASET` are deliberately **not** here, and that exclusion is
#: measured rather than assumed: on `samples/vision_pipeline`,
#: `samples/vision_pipeline_clean` and `analyzer/tests/clean` those two roles
#: account for 29 of the 29 untagged sites, and every one of them is the
#: universal `def forward(self, x): x = layer(x)` shape or a `Dataset(path)`
#: constructor. Reporting them would put a coverage note on every correct
#: `nn.Module` in the corpus - crying wolf, and a direct contradiction of the
#: roadmap's own negative ("both clean corpora are unchanged"). The four roles
#: below produce **zero** notes on those three corpora today, so a note here is
#: information rather than noise.
UNTRACED_ROLES = ("FIT", "FIT_TRANSFORM", "SPLIT", "LOADER")

#: Method names that are a fit site by any reading, swept even when the callee
#: resolved to nothing. `def fit_model(model, X, y): model.fit(X, y)` is the
#: measured case: `model` is a bare parameter, so `model.fit` answers to no FQN
#: and the call never reaches the role index at all - the blindest site in the
#: file was the one the role sweep could not see. Also zero on the three
#: shipped corpora.
_UNRESOLVED_FIT_METHODS = frozenset({"fit", "fit_transform", "fit_predict",
                                     "partial_fit"})

#: How many sites one `untagged_dataflow` message names before it counts.
_NAMED_SITES = 3
#: How many sibling modules one `single_file_analysis` message names.
_NAMED_SIBLINGS = 4
#: Ceiling on the sibling walk, so the check stays cheap on a huge package.
#: Past it the message says "at least N" rather than overclaiming a total.
_SIBLING_CAP = 1000
#: How many rule codes one `framework_filter` message names before it counts.
_NAMED_FILTERED = 6


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
            % (", ".join(codes) or "MLView", scope or "this scope",
               named, more, "ies" if len(sites) == 1 else "y", reason,
               "it" if len(sites) == 1 else "them"))


def untraced_reason(call, name: Optional[str], ref) -> str:
    """Why the analyzer has no tag for this value - the honest short answer.

    Shared by the rule-level `ctx.untraced` callers and by the post-rule sweep,
    so the two never explain the same blind spot two different ways.
    """
    scope = getattr(call, "scope", None)
    function = getattr(call, "function", None)
    if name and function is not None and name in (getattr(function, "params", ()) or ()):
        return "it arrives as a parameter of %s" % function.qualname
    if ref is None:
        return "it is not bound to any value the analyzer could follow"
    if scope is not None and scope.is_dynamic:
        return "%s is a dynamic scope" % scope.qualname
    return "its producer resolved to nothing the knowledge tables recognise"


def note_untraced_sites(ctx) -> None:
    """Declare a coverage gap at every untagged FIT / SPLIT / LOADER site.

    Runs once, after the rules, over the call index the rules already share.
    A site a rule already declared is folded into that rule's note by
    `UntaggedNotes` (the `(name, line)` pair de-duplicates), so a scope that
    MLV101 spoke for keeps MLV101's codes and its count; a scope no rule
    reached gains a note that would previously not have existed at all.
    """
    from ..rules.helpers import arg_ref     # local: rules import this module

    def declare(call) -> None:
        name, ref = arg_ref(ctx, call, 0)
        if not name:
            return                          # a literal / inline call, not a value
        if ref is not None and ref.tags:
            return                          # traced; the rules could check it
        ctx.untraced(call, name, untraced_reason(call, name, ref))

    for role in UNTRACED_ROLES:
        for call in ctx.calls_with_role(role):
            declare(call)
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            if (call.method or "") not in _UNRESOLVED_FIT_METHODS:
                continue
            if call.canonical_fqns or call.fqn:
                continue                    # resolved: the role sweep saw it
            declare(call)


# ---------------------------------------------------------------------------
# an unconfirmed training loop
# ---------------------------------------------------------------------------
def note_unconfirmed_train_loops(ctx) -> None:
    """A `backward()` + optimizer `step()` pair in a loop nothing confirmed.

    MLV201 / MLV202 / MLV203 all require a **batch loop** - the innermost `for`
    over a `LOADER`-tagged value. A full-batch loop, `for epoch in range(20):`
    over tensors already in memory, is the shape a tabular script and a
    notebook write, and it produced zero findings *and zero diagnostics*: a
    missing `zero_grad` there accumulates gradients across every epoch, and the
    miss was silent, which is the one thing the standing acceptance criterion
    forbids. The pair itself is strong evidence of a training iteration, so the
    honest move is to say the loop was not confirmed rather than to guess at
    its cadence and spend precision on it.
    """
    from ..rules.helpers import loop_chain     # local: rules import this module

    steps: Dict[int, List] = {}
    for call in ctx.calls_with_role("OPT_STEP"):
        if call.loop is not None:
            steps.setdefault(id(call.loop), []).append(call)
    for call in ctx.calls_with_role("BACKWARD"):
        loop = call.loop
        if loop is None:
            continue
        if any(link.kind == "batch" for link in loop_chain(loop)):
            continue                        # a confirmed loop; the rules judged it
        if id(loop) not in steps:
            continue
        ctx.diagnostics.append(Diagnostic(
            kind="untagged_dataflow",
            message="the loop at %s:%d contains backward() (line %d) and an "
                    "optimizer step, but the value it iterates%s carries no "
                    "LOADER tag, so MLView "
                    "could not confirm it as a training loop: MLV201 / MLV202 / "
                    "MLV203 did not judge it, and their silence here is a gap in "
                    "coverage rather than a clean result."
                    % (loop.loc.file, loop.loc.line, call.loc.line,
                       (" (`%s`)" % loop.iter_text) if loop.iter_text else ""),
            file=loop.loc.file, line=loop.loc.line,
            scope=loop.scope.qualname if loop.scope is not None else None,
            codes=["MLV201", "MLV202", "MLV203"]))


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
    """The `single_file_analysis` note, or None when nothing was left out.

    Fires when all three hold: the analyzed set is a **strict subset** of the
    Python discoverable under the owning package root, and at least one of the
    analyzed modules **imports** one of the modules that were left out. The
    import is what turns "you asked about part of a package" into "the answer
    you got is incomplete": a standalone script with no siblings in scope loses
    nothing, and saying otherwise would be crying wolf.

    TB-11: it used to fire only for `len(found.files) == 1`, which is a
    narrowing of the stated trigger and misses exactly the shape the VS Code
    `mlview.currentFileAnalysisScope: "package"` setting produces - `pkg/sub`
    analyzed while the rest of `pkg` is never seen.
    """
    from ..ingest.discover import discover      # local: cyclic at import time

    if not found.files or workspace is None:
        return None
    analyzed = [name for name in found.files if name in workspace.modules]
    if not analyzed:
        return None
    package_root = _package_root(found.abspath(analyzed[0]))
    if (len(analyzed) > 1 and package_root == found.root
            and len(found.files) >= found.total_found and not found.file_cap_hit):
        # Everything discoverable under the analyzed root was analyzed, and the
        # root is not itself inside a package: nothing was left out, and a
        # second `discover` of the same tree on every multi-file run is a cost
        # the perf gate should not have to pay to learn that.
        return None
    # Bounded: this runs on every narrowed analysis, including the VS Code
    # extension's analyze-on-save, and a monorepo package can be enormous.
    siblings = discover([package_root], include=include, exclude=exclude,
                        max_files=_SIBLING_CAP)
    # TB-15: both halves of the message are rendered against `package_root`, so
    # the analyzed module and its siblings are named on one path base. They used
    # to mix "train.py" with "pkg/sub/model.py" for the same directory.
    mine = {found.abspath(name) for name in analyzed}
    shown = sorted(name for name in siblings.files if siblings.abspath(name) in mine)
    others = sorted(name for name in siblings.files
                    if siblings.abspath(name) not in mine)
    if not others:
        return None
    if not shown:                              # outside the walk (cap, excludes)
        shown = list(analyzed)
    at_least = "at least " if siblings.file_cap_hit else ""

    dotted = {os.path.splitext(name)[0].replace("/", ".") for name in others}
    dotted |= {name.rsplit("/", 1)[-1][:-3] for name in others if name.endswith(".py")}
    dotted.discard("")
    imports = set()
    for name in analyzed:
        imports |= set(getattr(workspace.modules[name], "imports", ()) or ())
    imported = sorted(
        name for name in imports
        if name in dotted or any(d == name or d.endswith("." + name)
                                 or d.startswith(name + ".") for d in dotted))
    if not imported:
        return None

    named = ", ".join(others[:_NAMED_SIBLINGS])
    if len(others) > _NAMED_SIBLINGS:
        named += " and %d more" % (len(others) - _NAMED_SIBLINGS)
    codes = sorted(cross_file_codes)
    if len(shown) == 1:
        head = "Only %s was analyzed" % shown[0]
        subject = shown[0]
    else:
        head = "Only %d of %s%d modules in this package were analyzed" % (
            len(shown), at_least, len(shown) + len(others))
        subject = "they"
    return Diagnostic(
        kind="single_file_analysis",
        message="%s: %s%d sibling module(s) in the same package "
                "were not (%s), and %s import%s %d of them. Rules that need "
                "cross-file evidence (%s) cannot see those definitions, so a "
                "clean result here is not a clean result for the package - "
                "analyze the directory to widen."
                % (head, at_least, len(others), named, subject,
                   "s" if len(shown) == 1 else "", len(imported),
                   ", ".join(codes) or "none registered"),
        file=analyzed[0], codes=codes or None, count=len(others))


# ---------------------------------------------------------------------------
# framework_filter
# ---------------------------------------------------------------------------
def framework_filter_diagnostic(framework: str,
                                skipped: Sequence[str]) -> Optional[Diagnostic]:
    """The `framework_filter` note, or None when `--framework` cost nothing.

    C8. `--framework torch` is documented as *"restrict framework extractors"*,
    and what it actually does is narrow the **rule set**: `registry._applies`
    drops every rule that does not declare that framework, including rules that
    the detected frameworks would have run. A user who passes it therefore reads
    a shorter finding list with nothing in the document saying why - the same
    silent narrowing `single_file_analysis` exists to make loud, and the reason
    the MCP host renders a coverage block rather than a bare count.

    `skipped` is the codes that would have run under `--framework auto` on this
    workspace and did not. An empty list is not a caveat: a filter that matched
    every applicable rule narrowed nothing, and saying otherwise would be crying
    wolf on the one flag a CI job is most likely to pass.
    """
    if not framework or framework == "auto":
        return None
    codes = sorted({code for code in skipped if code})
    if not codes:
        return None
    named = ", ".join(codes[:_NAMED_FILTERED])
    if len(codes) > _NAMED_FILTERED:
        named += " and %d more" % (len(codes) - _NAMED_FILTERED)
    return Diagnostic(
        kind="framework_filter",
        message="--framework %s narrowed the rule set: %d rule(s) that the "
                "detected frameworks would have run did not (%s). A clean "
                "result here is a clean result for %s alone - drop --framework "
                "(or pass auto) to judge the whole workspace."
                % (framework, len(codes), named, framework),
        codes=codes, count=len(codes))
