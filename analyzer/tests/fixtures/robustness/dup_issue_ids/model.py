"""ROB-03 (single file): the same attribute is assigned a plain submodule list
twice in one `__init__`. MLV702 fires on both lines; the two findings share
`(code, file, qualname, symbol)`, which is the whole issue-id recipe.

A second assignment to the same attribute is redundant, not illegal: it is
what a copy-paste inside a long `__init__` looks like.
"""
import torch
import torch.nn as nn


class Net(nn.Module):
    def __init__(self, width: int = 32, depth: int = 3):
        super().__init__()
        self.blocks = [nn.Linear(width, width) for _ in range(depth)]
        self.blocks = [nn.Linear(width, width) for _ in range(depth)]
        self.head = nn.Linear(width, 3)

    def forward(self, x):
        for layer in self.blocks:
            x = torch.relu(layer(x))
        return self.head(x)
