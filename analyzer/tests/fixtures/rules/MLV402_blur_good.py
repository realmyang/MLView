# MLVIEW-EXPECT-NONE: MLV402, MLV401
"""PUB-01. The trap: the producer is written one line AFTER the use.

`BCEBlurWithLogitsLoss` (yolov5 `utils/loss.py:26`, and every focal-loss
implementation written the same way) computes the loss from **raw logits**,
which is correct, and only then rebinds the local to build the blur factor:

    loss = self.loss_fcn(pred, true)     # correct - logits into a logits loss
    pred = torch.sigmoid(pred)           # AFTER the loss, for the blur factor

`ctx.binding_of` without `at=` answers with the scope's LAST store for a name,
so MLV402 read line 2 as the producer of line 1 and emitted high / 0.95 /
`certain` - with a message whose own line numbers ran backwards ("its input
comes from torch.sigmoid at m.py:17" for a use at m.py:16).
"""
import torch
import torch.nn as nn


class BCEBlurWithLogitsLoss(nn.Module):
    """Correct: raw logits reach the loss; the sigmoid only shapes the weight."""

    def __init__(self, alpha: float = 0.05) -> None:
        super().__init__()
        self.loss_fcn = nn.BCEWithLogitsLoss(reduction="none")
        self.alpha = alpha

    def forward(self, pred: torch.Tensor, true: torch.Tensor) -> torch.Tensor:
        loss = self.loss_fcn(pred, true)
        pred = torch.sigmoid(pred)              # the rebinding is below the use
        dx = pred - true
        alpha_factor = 1 - torch.exp((dx - 1) / (self.alpha + 1e-4))
        return (loss * alpha_factor).mean()


class SoftmaxAfterLoss(nn.Module):
    """The MLV401 half of the same shape: probabilities built for reporting."""

    def __init__(self) -> None:
        super().__init__()
        self.criterion = nn.CrossEntropyLoss()
        self.head = nn.Linear(16, 4)

    def forward(self, features: torch.Tensor, targets: torch.Tensor):
        logits = self.head(features)
        loss = self.criterion(logits, targets)
        logits = torch.softmax(logits, dim=1)   # reporting only, after the loss
        return loss, logits
