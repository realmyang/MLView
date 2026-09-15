# MLVIEW-EXPECT-NONE: MLV205
"""REC-02: a loss module that collects its per-term losses and returns their
sum must keep every graph - that return value IS what the caller differentiates.

`losses.append(term_loss.mean((1,)))` then `loss = sum(losses); return loss /
len(features)` is `diffusers/examples/research_projects/lpl/lpl_loss.py:180`,
and `.item()` there would stop training outright. The discriminator is that the
collected tensor is not itself back-propagated in this scope: when it is
(`losses.append(loss)` after `loss.backward()`), the list is a record of the
epoch and MLV205 still fires - that is `MLV205_bad.py`.
"""
import torch
import torch.nn as nn


class PerceptualLoss(nn.Module):
    """Sums a weighted per-layer distance; the caller back-propagates it."""

    def __init__(self, layers: int = 3):
        super().__init__()
        self.layers = layers
        self.distance = nn.L1Loss(reduction="none")

    def forward(self, features, targets):
        losses = []
        for index in range(self.layers):
            weight = 2 ** (-index)
            term_loss = self.distance(features, targets) * weight
            losses.append(term_loss.mean((1,)))
        loss = sum(losses)
        return loss / len(losses)
