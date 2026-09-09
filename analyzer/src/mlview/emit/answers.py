"""The Pipeline Answer Card (ROADMAP MLV-P1).

MLView's headline is answering four questions in ninety seconds. The
practitioner walkthrough measured **two of four** answered from the first
screen, both by the rail rather than the diagram, and **nothing in any host
stating the answers in words**. This module states them.

    answers = {
      "dataEntry":  {"sentence": ..., "nodeIds": [...], "locs": [...], "confidence": 0.95},
      "objective":  {...}, "evaluation": {...}, "verdict": {...},
    }

Four properties are the whole contract:

* **Deterministic and offline.** Composed from the finished document by
  dictionary lookups over an already-sorted `nodes[]`; no model, no network,
  no clock. The same graph produces the same four sentences in all three
  hosts, byte for byte.
* **An absence is stated as an absence.** "No evaluation stage was detected"
  is an answer. Printing nothing is not - that is the "cannot tell *I checked
  and it is fine* from *I could not check*" failure this whole round exists to
  end.
* **Nothing below `MIN_CONFIDENCE` is asserted as fact.** A node the analyzer
  is not sure about is dropped from the citation and counted: the sentence
  then says how many candidates were left out rather than quietly resting on
  them.
* **A ghost is never evidence.** Ghost nodes are the analyzer's marker for
  something it expected and did **not** find (`model.eval()` that is missing),
  so citing one as a located fact would invert its meaning. They are read only
  where the absence itself is the answer - the eval guard.

`answers` is a root-level **optional** key. `core/graph.MLGraph.to_dict()`
attaches it to every document it builds; the hand-authored
`contracts/graph.sample.json` does not carry one, and a projection carries
whatever its input carried, verbatim - answers are project-level truth, like
`stages[].present`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["compose", "render_block", "digest_answers", "FIELDS",
           "MIN_CONFIDENCE"]

#: Never assert a fact from a node the analyzer is less than this sure of.
MIN_CONFIDENCE = 0.6
FIELDS = ("dataEntry", "objective", "evaluation", "verdict")
_LABELS = {"dataEntry": "data", "objective": "objective",
           "evaluation": "evaluation", "verdict": "verdict"}
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
#: ANA-5a adds `unresolved_callee`: a call MLView could not read is exactly the
#: reason a verdict of "no findings" must not be read as a clean bill of health.
_COVERAGE_KINDS = ("untagged_dataflow", "single_file_analysis", "unresolved_callee")
_MAX_CITED = 3


# ------------------------------------------------------------------ helpers
def _nodes(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [n for n in (doc.get("nodes") or []) if isinstance(n, dict)]


def _confident(node: Dict[str, Any]) -> bool:
    value = node.get("confidence")
    return isinstance(value, (int, float)) and float(value) >= MIN_CONFIDENCE


def _pick(nodes: Iterable[Dict[str, Any]], **match) -> Tuple[List[Dict[str, Any]], int]:
    """`(confident matches, how many were dropped for low confidence)`.

    Ghosts are excluded here by construction: every caller that wants one asks
    for it explicitly through `_ghosts`.
    """
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for node in nodes:
        if node.get("ghost"):
            continue
        if any(node.get(key) != value for key, value in match.items()):
            continue
        if _confident(node):
            kept.append(node)
        else:
            dropped += 1
    return kept, dropped


def _ghosts(nodes: Iterable[Dict[str, Any]], predicate) -> List[Dict[str, Any]]:
    return [n for n in nodes if n.get("ghost") and predicate(n)]


def _loc(node: Dict[str, Any]) -> Dict[str, Any]:
    loc = node.get("loc") or {}
    return {"file": loc.get("file", ""), "line": int(loc.get("line") or 1)}


def _at(node: Dict[str, Any]) -> str:
    loc = node.get("loc") or {}
    return "%s:%s" % (loc.get("file", "?"), loc.get("line", "?"))


def _cite(node: Dict[str, Any], with_fqn: bool = False) -> str:
    label = node.get("label") or node.get("qualname") or "?"
    if with_fqn and node.get("fqn"):
        return "%s (%s) at %s" % (label, node["fqn"], _at(node))
    return "%s at %s" % (label, _at(node))


def _join(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "%s and %s" % (", ".join(parts[:-1]), parts[-1])


def _listing(nodes: Sequence[Dict[str, Any]], with_fqn: bool = False,
             limit: int = _MAX_CITED) -> str:
    shown = _join([_cite(n, with_fqn) for n in nodes[:limit]])
    if len(nodes) > limit:
        shown += " (+%d more)" % (len(nodes) - limit)
    return shown


def _dropped_clause(dropped: int) -> str:
    if not dropped:
        return ""
    return (" %d further candidate(s) were below the %.1f confidence floor and "
            "are not asserted." % (dropped, MIN_CONFIDENCE))


def _answer(sentence: str, cited: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """One answer. `confidence` is the **weakest** node it rests on, so the
    number cannot be inflated by a long list with one shaky member; with
    nothing cited it is 0.0 and the sentence says why in words."""
    nodes = list(cited)
    confidence = 0.0
    if nodes:
        confidence = min(float(n.get("confidence") or 0.0) for n in nodes)
    return {"sentence": sentence,
            "nodeIds": [n.get("id", "") for n in nodes],
            "locs": [_loc(n) for n in nodes],
            "confidence": round(confidence, 3)}


# ---------------------------------------------------------------- the four
def _data_entry(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    datasets, dropped = _pick(nodes, kind="dataset")
    loaders, dropped_loaders = _pick(nodes, kind="dataloader")
    splits, dropped_splits = _pick(nodes, kind="split")
    dropped += dropped_loaders + dropped_splits
    if not datasets and not loaders:
        return _answer(
            "No data entry was detected: nothing in this workspace builds a "
            "dataset or a loader, so MLView could not determine where the data "
            "comes from." + _dropped_clause(dropped), ())
    if datasets:
        sentence = "Data enters at %s" % _listing(datasets)
        if loaders:
            sentence += ", feeding %d loader(s)" % len(loaders)
    else:
        sentence = "Data enters through %d loader(s), %s" % (len(loaders),
                                                             _listing(loaders))
    if splits:
        sentence += "; the train/test boundary is set by %s." % _listing(splits, limit=2)
    else:
        sentence += ("; no split call was detected, so the train/test boundary "
                     "could not be determined.")
    cited = (datasets[:_MAX_CITED] or loaders[:_MAX_CITED]) + splits[:2]
    return _answer(sentence + _dropped_clause(dropped), cited)


def _objective(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    losses, dropped = _pick(nodes, kind="loss")
    optimizers, dropped_opt = _pick(nodes, kind="optimizer")
    dropped += dropped_opt
    # A *bound* node is the definition site (`criterion = nn.CrossEntropyLoss()`,
    # `optimizer = optim.Adam(...)`); the unbound ones are calls onto it
    # (`loss.backward()`, `optimizer.step()`). Answer with the definition.
    defined_losses = [n for n in losses if n.get("var")] or losses
    defined_opts = [n for n in optimizers if n.get("var")] or optimizers
    if not defined_losses:
        return _answer(
            "No loss function was detected: nothing in the objective stage and "
            "no backward() call, so MLView could not determine what this "
            "pipeline optimises." + _dropped_clause(dropped), ())
    sentence = "The objective is %s" % _listing(defined_losses, with_fqn=True, limit=2)
    if defined_opts:
        sentence += ", optimised by %s." % _listing(defined_opts, with_fqn=True, limit=2)
    else:
        sentence += ("; no optimizer was detected, so the update rule could not "
                     "be determined.")
    cited = defined_losses[:2] + defined_opts[:2]
    return _answer(sentence + _dropped_clause(dropped), cited)


def _is_guard(node: Dict[str, Any]) -> bool:
    fqn = node.get("fqn") or ""
    return fqn.endswith(".eval") or "no_grad" in fqn or "inference_mode" in fqn


def _evaluation(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    eval_nodes = [n for n in nodes if n.get("stage") == "eval"]
    loops, dropped = _pick(eval_nodes, kind="eval_loop")
    metrics, dropped_metrics = _pick(eval_nodes, kind="metric")
    dropped += dropped_metrics
    guards = [n for n in eval_nodes if not n.get("ghost") and _is_guard(n)
              and _confident(n)]
    missing = _ghosts(eval_nodes, _is_guard)
    if not loops and not metrics and not guards:
        return _answer(
            "No evaluation stage was detected: nothing computes a metric or "
            "runs the model in eval mode, so this pipeline's quality is not "
            "measured anywhere MLView can see." + _dropped_clause(dropped), ())
    if loops and metrics:
        sentence = ("Evaluation runs in %s, computing %s"
                    % (_listing(loops, limit=2), _listing(metrics, limit=2)))
    elif loops:
        sentence = "Evaluation runs in %s" % _listing(loops, limit=2)
    elif metrics:
        sentence = "Evaluation computes %s" % _listing(metrics, limit=2)
    else:
        sentence = ("Evaluation was not localised to a loop or a metric, and "
                    "only the eval-mode switch was found")
    # The guard clause is stated only where a guard - present or missing - was
    # actually found. A sklearn-only pipeline has no eval mode to guard, and
    # inventing the absence of one would be a finding MLView did not make.
    if guards:
        sentence += "; the eval path is guarded by %s." % _listing(guards, limit=2)
    elif missing:
        sentence += ("; the eval path is NOT guarded - no model.eval() or "
                     "torch.no_grad() covers %s." % _at(missing[0]))
    else:
        sentence += "."
    cited = loops[:2] + metrics[:2] + guards[:2]
    return _answer(sentence + _dropped_clause(dropped), cited)


def _verdict(doc: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id = {n.get("id"): n for n in nodes}
    issues = [i for i in (doc.get("issues") or []) if isinstance(i, dict)]
    live = [i for i in issues if not i.get("suppressed") and not i.get("baselined")]
    counts = {"high": 0, "medium": 0, "low": 0}
    for issue in live:
        counts[issue.get("severity", "low")] = counts.get(issue.get("severity", "low"), 0) + 1
    coverage = [d for d in (doc.get("diagnostics") or [])
                if isinstance(d, dict) and d.get("kind") in _COVERAGE_KINDS]
    caveat = ""
    if coverage:
        kinds = sorted({d.get("kind", "") for d in coverage})
        caveat = (" MLView also reported %d coverage gap(s) (%s), so this is not "
                  "a clean bill of health." % (len(coverage), ", ".join(kinds)))
    baselined = sum(1 for i in issues if i.get("baselined"))
    baselined_clause = (" %d further finding(s) are baselined." % baselined) if baselined else ""
    if not live:
        return _answer("No findings: no rule fired on this workspace." +
                       baselined_clause + caveat, ())

    def score(issue: Dict[str, Any]):
        rank = _SEVERITY_RANK.get(issue.get("severity", "low"), 0) + 1
        confidence = float(issue.get("confidence") or 0.0)
        loc = issue.get("loc") or {}
        return (-(rank * confidence), loc.get("file", ""), int(loc.get("line") or 0),
                issue.get("code", ""), issue.get("id", ""))

    top = sorted(live, key=score)[:3]
    named = _join(["%s (%s) at %s:%s" % (i.get("code", "?"), i.get("severity", "?"),
                                         (i.get("loc") or {}).get("file", "?"),
                                         (i.get("loc") or {}).get("line", "?"))
                   for i in top])
    sentence = ("%d finding(s): %d high / %d medium / %d low. Fix first: %s."
                % (len(live), counts.get("high", 0), counts.get("medium", 0),
                   counts.get("low", 0), named)) + baselined_clause + caveat
    cited: List[Dict[str, Any]] = []
    for issue in top:
        for node_id in issue.get("nodeIds") or []:
            node = by_id.get(node_id)
            if node is not None and not node.get("ghost"):
                cited.append(node)
                break
    answer = _answer(sentence, cited)
    # A verdict is a claim about the findings, not about the nodes they sit on,
    # so its confidence is the weakest finding it names - not the weakest node.
    answer["confidence"] = round(min(float(i.get("confidence") or 0.0) for i in top), 3)
    answer["locs"] = [{"file": (i.get("loc") or {}).get("file", ""),
                       "line": int((i.get("loc") or {}).get("line") or 1)}
                      for i in top]
    return answer


# ------------------------------------------------------------------- entry
def compose(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The four answers for a finished MLGraph document. Pure dict -> dict."""
    nodes = _nodes(doc)
    return {
        "dataEntry": _data_entry(nodes),
        "objective": _objective(nodes),
        "evaluation": _evaluation(nodes),
        "verdict": _verdict(doc, nodes),
    }


def render_block(answers: Optional[Dict[str, Any]], width: int = 96) -> List[str]:
    """The `Answers` block for `--format summary` / `text`, as lines.

    Wrapped deterministically at `width` with a hanging indent, so a CI log
    reads the four answers without horizontal scrolling and two runs of the
    same graph produce identical bytes.
    """
    if not isinstance(answers, dict):
        return []
    import textwrap

    lines = ["Answers"]
    for field in FIELDS:
        answer = answers.get(field)
        if not isinstance(answer, dict):
            continue
        head = "  %-11s " % (_LABELS[field] + ":")
        text = str(answer.get("sentence", ""))
        wrapped = textwrap.wrap(text, width=max(40, width - len(head))) or [""]
        lines.append(head + wrapped[0])
        for extra in wrapped[1:]:
            lines.append(" " * len(head) + extra)
    return lines


def digest_answers(answers: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """The four sentences alone - what the MCP digest can afford (~400 B)."""
    if not isinstance(answers, dict):
        return {}
    out: Dict[str, str] = {}
    for field in FIELDS:
        answer = answers.get(field)
        if isinstance(answer, dict) and answer.get("sentence"):
            out[field] = str(answer["sentence"])
    return out
