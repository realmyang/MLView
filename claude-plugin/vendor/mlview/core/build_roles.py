"""Role sets and labels the graph builder treats specially.

Split out of `core/build.py` so the builder's three halves (`build_units`,
`build_ops`, `build_edges`) can share them without importing each other.
`core.build` re-exports `NOT_DRAWN_ROLES`, which is part of its public API.
"""

from __future__ import annotations

__all__ = ["TRANSPARENT_ROLES", "NOT_DRAWN_ROLES", "LOOP_BACK_LABEL"]


#: Roles whose call is not drawn as its own op - the value keeps flowing from
#: the receiver's node (a forward pass belongs to the model, `.item()` to the
#: loss, `.parameters()` to the model).
TRANSPARENT_ROLES = frozenset({"FORWARD", "TO_DEVICE", "ITEM", "DETACH",
                               "TO_NUMPY", "PARAMETERS", "FRAME_OP"})

#: FW-RECOG F9 - recognised so that no symbol is fabricated for them, and
#: deliberately absent from `K.OP_ROLES` so they mint no node: "five metric
#: cards per training step is noise, not recognition".
#:
#: F9 was written about **nodes**, and the edge site still ran. A call that
#: minted no node of its own was mapped onto its class's unit node, so
#: `self.log("train_loss", loss)` drew a `data` edge from the loss node into
#: the LightningModule - the diagram told the reader the loss flows into the
#: model, which is a false statement about dataflow; the loss is being logged.
#: `self.log_dict({...})` drew none, so the two logging calls were rendered
#: inconsistently as well. The exclusion belongs at both sites.
NOT_DRAWN_ROLES = frozenset({"LIGHTNING_LOG", "LIGHTNING_HPARAMS",
                             "LIGHTNING_CTL", "MODEL_SUMMARY", "TFDATA_CARD"})

#: The label on a loop unit's `back` control edge, by loop kind.
LOOP_BACK_LABEL = {"batch": "next batch", "epoch": "next epoch", "fold": "next fold",
                   "other": "next iteration"}
