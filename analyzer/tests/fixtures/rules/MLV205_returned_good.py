# MLVIEW-EXPECT-NONE: MLV205
"""vision-05. The trap: a custom loss module that accumulates and RETURNS.

ISSUE_RULES MLV205 FP-note (a) suppresses the rule when `.backward()` is called
on the accumulator, and note (b) covers a list later `torch.stack`ed and
backwarded. Both were implemented by matching the accumulator's NAME inside the
same module, which never applies to the standard multi-part objective: the
`forward` accumulates, the caller back-propagates the returned value under
another name in another scope, and the graph has to stay alive until then.
"""
import torch
import torch.nn as nn


class DetectionLoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.classification = nn.BCEWithLogitsLoss(reduction="mean")
        self.regression = nn.SmoothL1Loss(reduction="mean")

    def forward(self, cls_logits, box_deltas, targets):
        total = cls_logits.new_zeros(())
        for index, target in enumerate(targets):
            one_hot = torch.zeros_like(cls_logits[index])
            total = total + self.classification(cls_logits[index], one_hot)
            total = total + self.regression(box_deltas[index], target)
        return total / max(len(targets), 1)


class StackedLoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.term = nn.SmoothL1Loss(reduction="mean")

    def forward(self, deltas, targets):
        parts = []
        for index, target in enumerate(targets):
            parts.append(self.term(deltas[index], target))
        return torch.stack(parts).sum()
