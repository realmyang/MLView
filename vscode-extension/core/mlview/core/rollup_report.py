"""What `--max-nodes` did, and the one sentence that says so (CONTRACTS 11.46 D).

Split out of `core/rollup` when VIEW-R2 / REV5-02 turned the counters into a
**partition of the input document** rather than a tally of fold operations: the
arithmetic and the wording that reports it are one concern, and `rollup.py` is
the other one - the plan that decides what folds into what.

The invariant every field exists to hold up:

    folded + dropped + kept_originals == total

`folded` and `dropped` count **original** nodes, never a synthesized summary. A
summary is not a node anybody lost, and counting one made `Diagnostic.count`
over-report the moment the directory tier re-folded a file summary - which the
viewer then reads as `dropped = count - sum(rolledUp)` and renders as a banner
claiming a deletion the analyzer's own sentence, printed directly below it,
denied. PERF-04's headline promise is "folded, not deleted"; the number has to
say the same thing as the promise.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RollupReport"]


@dataclass
class RollupReport:
    """What the cap did, in the words the diagnostic uses (11.46 D)."""

    budget: int
    total: int = 0               # nodes in the document before the cap
    folded: int = 0              # originals represented by a surviving ancestor
    units_absorbing: int = 0     # units that absorbed their op children
    files_summarised: int = 0    # files that became one summary node
    dirs_summarised: int = 0     # directories that became one summary node
    dropped: int = 0             # originals with no representative at all
    kept: int = 0                # nodes in the emitted document
    kept_originals: int = 0      # of which were in the input document
    summaries_kept: int = 0      # of which the rollup synthesized
    lost_issues: int = 0
    edges_merged: int = 0        # parallel members removed by the merge
    edges_absorbed: int = 0      # both endpoints landed on one survivor
    edges_lost: int = 0          # an endpoint was dropped outright

    @property
    def rolled_up(self) -> bool:
        return self.folded > 0

    def message(self) -> str:
        """The `truncated` diagnostic. Must keep the two phrases 11.46 D pins:
        the word `budget`, and `<n> node(s) kept` for the document actually
        emitted.

        "%d of %d" is REV5-02: the three figures partition the input document,
        so a reader can add them up and get the number they started with. The
        old sentence said "54 node(s) rolled up ... 3 node(s) kept" of a
        54-node graph, which is not a possible state of the world.
        """
        if self.rolled_up:
            summarised = (" (%d of them synthesized by the rollup)" % self.summaries_kept
                          ) if self.summaries_kept else ""
            head = ("Graph cap (--max-nodes budget) %d reached: %d of %d node(s) "
                    "rolled up into their surviving ancestor (%d unit(s) absorbed "
                    "their operations, %d file(s) and %d director(ies) summarised), "
                    "%d node(s) dropped, %d node(s) kept%s."
                    % (self.budget, self.folded, self.total, self.units_absorbing,
                       self.files_summarised, self.dirs_summarised, self.dropped,
                       self.kept, summarised))
        else:
            head = ("Graph cap (--max-nodes budget) %d reached: nothing could be "
                    "rolled up, %d node(s) dropped, %d node(s) kept."
                    % (self.budget, self.dropped, self.kept))
        edges = ("%d parallel edge(s) merged into one carrying a weight, %d absorbed "
                 "into a rolled-up node, %d lost an endpoint."
                 % (self.edges_merged, self.edges_absorbed, self.edges_lost))
        tail = "Raise --max-nodes, or narrow the analyzed path, to see the rest."
        issues = ("%d finding(s) had no surviving node and went with them. "
                  % self.lost_issues) if self.lost_issues else ""
        return " ".join([head, edges, issues + tail])
