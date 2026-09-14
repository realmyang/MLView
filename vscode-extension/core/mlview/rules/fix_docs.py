"""H5 - what each opted-in rule's page must say about its structured fix.

Data, not logic: `analyzer/tools/gen_rule_docs.py` renders this into the
**Structured fix** section of `docs/rules/<CODE>.md`, which is the page both
hosts deep-link to from a finding.

Every entry states **both** halves. "Offered when" alone would leave a reader
who sees an empty lightbulb with no way to tell "MLView thinks this code is
fine" from "MLView could not compute an edit here" - which is the failure mode
`docs/ROADMAP.md` (f) asks every analyzer change to close. `rules/fixes.py`
enforces the conditions; this says them in words.

It lives beside `fixes.py` rather than inside it so that the module that edits
somebody's source stays a module about editing source.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = ["FIX_DOCS", "FIX_CODES", "MECHANICAL", "NEEDS_REVIEW"]

#: `mechanical` - one keyword at one call site; a host may mark it isPreferred.
MECHANICAL = "mechanical"
#: `needs-review` - it inserts a statement, so it can always be the thing the
#: author left out on purpose. Never isPreferred.
NEEDS_REVIEW = "needs-review"

FIX_DOCS: Dict[str, Dict[str, str]] = {
    "MLV111": {
        "safety": MECHANICAL,
        "title": "Set shuffle=False on this evaluation DataLoader",
        "offered": "the `shuffle=` keyword is the literal `True` at the call site - "
                   "the edit replaces that one literal and nothing else, so a trailing "
                   "comment on the same line survives it.",
        "withheld": "`shuffle=` is a variable or an expression rather than a literal, "
                    "so what the edit would have to say about it is not statically "
                    "known.",
    },
    "MLV201": {
        "safety": NEEDS_REVIEW,
        "title": "Zero the gradients at the top of the batch loop",
        "offered": "the optimizer is a plain dotted name, the `.step()` that proves the "
                   "finding is inside this loop's own body, and the optimizer is in "
                   "scope there - constructed above the insertion point in the same "
                   "suite, or arriving as a parameter of the edited function, which is "
                   "bound before the body runs at any line. The call is inserted as the "
                   "first statement of the loop body, at the body's own indentation.",
        "withheld": "the optimizer is an expression (`opts[0].step()`), the step lives "
                    "in a followed callee rather than in the loop, or the loop body "
                    "starts on the `for` line itself. It is `needs-review` in every "
                    "case: gradient accumulation is a missing `zero_grad()` that the "
                    "author meant, and no static analysis tells the two apart from the "
                    "modulo guard alone.",
    },
    "MLV301": {
        "safety": NEEDS_REVIEW,
        "title": "Switch the model to eval mode before this region",
        "offered": "the model is a plain dotted name bound above the region. "
                   "`model.eval()` is inserted immediately above the loop (or as the "
                   "first statement of the evaluation function), at that statement's "
                   "own indentation - inside a `with torch.no_grad():` block when that "
                   "is where the loop is.",
        "withheld": "the model is an expression, or it is constructed lower down the "
                    "same suite the edit would be inserted into. It is `needs-review` "
                    "because the edit cannot also "
                    "restore `model.train()`: where that belongs is a question about "
                    "the caller.",
    },
    "MLV302": {
        "safety": NEEDS_REVIEW,
        "title": "Decorate the evaluation function with @torch.no_grad()",
        "offered": "the region is inside a function that contains no `backward()`, "
                   "`optimizer.step()` or `zero_grad()` anywhere, and the module binds "
                   "the name `torch`. The decorator is inserted directly above the "
                   "`def`.",
        "withheld": "the region is at module level, the function also trains, or the "
                    "file imported symbols from torch without binding `torch` itself. "
                    "The `with torch.no_grad():` wrap the hint names is never built: "
                    "wrapping a suite means re-indenting every line inside it, and a "
                    "triple-quoted string in that suite would silently change value.",
    },
    "MLV602": {
        "safety": MECHANICAL,
        "title": "Add the reproducibility keyword to this split",
        "offered": "the call takes no `**kwargs` forward, so the keyword is provably "
                   "absent. It is appended after the last existing argument, which "
                   "leaves a trailing comment or a closing paren on its own line "
                   "untouched.",
        "withheld": "the finding did not reach the `likely` bucket - an unseeded split "
                    "in a workspace that seeds globally is `possible`, and prose is the "
                    "right answer there - or the torch spelling was needed and the "
                    "module does not bind `torch` (adding the import is a second edit "
                    "this feature deliberately will not make).",
    },
}

#: Every rule that may attach an edit. Read by the tests and by the doc
#: generator; a rule not listed here can never produce one.
FIX_CODES: Tuple[str, ...] = tuple(sorted(FIX_DOCS))
