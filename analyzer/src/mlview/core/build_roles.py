"""Which roles the graph draws, and which it deliberately does not.

Two frozensets and one label table, read by `core/build_ops.py` and
`core/build_edges.py` and re-exported from `core/build.py`, where they were
defined before the builder was split. They are data, not policy: the policy
that reads them is one `if` in each of the two passes, and keeping the data in
its own module is what lets both passes import it without importing each other.
"""

from __future__ import annotations

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

_LOOP_BACK_LABEL = {"batch": "next batch", "epoch": "next epoch", "fold": "next fold",
                    "other": "next iteration"}
