"""IP-01: the only path from the split to this loader is a CONSTRUCTOR hop.

`self.rows` carries no tag in `--dataflow local`, so the finding below exists
only in `ip` - which makes it the cleanest possible probe for "a cross-object
finding is de-rated and names the hop it travelled".

Never executed: MLView analyses this file statically.
"""
from torch.utils.data import DataLoader


class Holder:
    def __init__(self, rows, labels):
        self.rows = rows
        self.labels = labels

    def build(self):
        anything = DataLoader(self.rows, batch_size=32, shuffle=True)
        return anything
