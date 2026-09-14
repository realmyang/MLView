"""Hop 3 - the training loop, in the layered layout a monorepo actually has.

ROB-14. `--relevance ml` is the default and `--relevance-hops` defaults to 2,
so this module - three import hops from the only file in the package that
names the framework - is "read but not analyzed". The `diagnostics` do say so,
in a `config_warning` that names the file. Nothing the reader looks at first
repeats it:

    Stages
      train         2 nodes
    verdict:  No findings: no rule fired on this workspace. MLView also
              reported 1 coverage gap(s) (untagged_dataflow), so this is not a
              clean bill of health.

Those two `train` nodes are `Adam()` and `make_optimizer()`. The batch loop
below, `loss.backward()` and `opt.step()` are not in the graph at all, and
neither is the `train()` unit - so the diagram, which is the product, shows a
pipeline with no training loop in it and says nothing about the omission where
it is shown. `--relevance-hops 4`, or `--relevance all`, restores all five
nodes and the MLV601 finding.

The verdict line already knows how to qualify itself: it appends the
`untagged_dataflow` coverage gap. The set-aside is the gap it does not append.

NB. `core/relevance.py` seeds by byte scan, so this docstring must not contain
the name of a framework - naming one here would make this file a seed and the
fixture would stop reproducing.
"""
from ..engine.assembly import assemble


def train(dataset, epochs=2):
    model, opt, crit, loader = assemble(dataset)
    for _ in range(epochs):
        for xb, yb in loader:
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model
