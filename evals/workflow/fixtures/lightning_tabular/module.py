"""The LightningModule. The framework owns the loop; the absence rules must
stay off this file entirely.

Planted defect: `forward` returns a softmax and `training_step` feeds it to
`F.cross_entropy`, which log-softmaxes again.
"""
from __future__ import annotations

import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F


class ChurnClassifier(pl.LightningModule):
    def __init__(self, features: int = 5, classes: int = 2, lr: float = 1e-3) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.encoder = nn.Sequential(
            nn.Linear(features, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Dropout(0.3),
        )
        self.head = nn.Linear(64, classes)
        self.lr = lr

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.softmax(self.head(self.encoder(x)), dim=1)

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss)
        return loss

    def validation_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        self.log_dict({"val_loss": loss})
        return loss

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=self.lr)
